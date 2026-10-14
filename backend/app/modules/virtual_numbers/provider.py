"""SMS-Man API v2.0 provider adapter.

No automatic retries are performed. Phone-number purchases are non-idempotent,
so an interrupted purchase must be reconciled before it is retried.

Operation paths (relative to https://api.sms-man.com/control):
    get-balance, countries, applications, get-prices, limits,
    get-number, get-sms, set-status

Outcome-uncertainty rules (``SMSManError.uncertain``), only for operations that
spend money or change provider state:
    * read/write timeouts, read errors, and HTTP 5xx  -> uncertain
    * connect failures (request never left the machine) -> NOT uncertain
    * HTTP 4xx (404 wrong path, 401/403 auth, 429 rate limit, ...) -> NOT
      uncertain: the provider rejected the request before acting on it
"""
from __future__ import annotations

import asyncio
import logging
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import SecretStr

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.sms-man.com/control"
DEFAULT_TIMEOUT = httpx.Timeout(45.0, connect=15.0, read=30.0, write=10.0, pool=5.0)
# get-prices streams slowly (headers can take ~40s, then the body stalls), so it
# gets a much longer read window than the other operations.
PRICES_TIMEOUT = httpx.Timeout(150.0, connect=15.0, read=120.0, write=10.0, pool=5.0)
APPLICATIONS_TIMEOUT = httpx.Timeout(55.0, connect=15.0, read=40.0, write=10.0, pool=5.0)
ALLOWED_STATUSES = frozenset({"ready", "close", "reject", "used"})
ALLOWED_CURRENCIES = frozenset({"RUB", "USD", "EUR"})

# Provider operation paths. These are NOT the same as the section titles in
# the public docs ("Request a phone number" -> get-number, etc.).
OP_BALANCE = "get-balance"
OP_COUNTRIES = "countries"
OP_APPLICATIONS = "applications"
OP_PRICES = "get-prices"
OP_LIMITS = "limits"
OP_PURCHASE = "get-number"
OP_SMS = "get-sms"
OP_STATUS = "set-status"

# Transport failures worth one more try for READ-ONLY operations. SMS-Man
# regularly drops get-prices mid-body (RemoteProtocolError). Never used for
# purchase / set-status, which spend money or change state.
_RETRYABLE = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadError,
    httpx.RemoteProtocolError,
)
READ_RETRIES = 2
# Hard wall-clock cap for one logical get-prices call (all retries included).
# httpx's read timeout is per read, so a trickling body could otherwise run forever.
PRICES_DEADLINE_SECONDS = 200.0
_CATALOGUE_KEYS = ("applications", "services", "countries", "items", "results", "data")
_ALLOWED_HOST = "api.sms-man.com"
_ALLOWED_PATH = "/control"
_SECRET_RE = re.compile(r"(?i)(token|api[_-]?key)(\s*[=:]\s*)[^&\s,;]+")
_LONG_NUMBER_RE = re.compile(r"\b\d{8,16}\b")


class SMSManError(Exception):
    """Sanitized provider error with outcome-uncertainty metadata."""

    def __init__(self, message: str, *, uncertain: bool = False, code: str = "provider_error") -> None:
        super().__init__(message)
        self.uncertain = uncertain
        self.code = code


class SMSManProvider:
    """Asynchronous SMS-Man API client."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        api_key: SecretStr,
        base_url: str = DEFAULT_BASE_URL,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        *,
        allow_get_limits_fallback: bool = False,
        send_purchase_options: bool = False,
    ) -> None:
        if not isinstance(http, httpx.AsyncClient):
            raise TypeError("http must be an httpx.AsyncClient.")
        if not isinstance(api_key, SecretStr):
            raise TypeError("api_key must be a SecretStr.")
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError("SMS-Man base URL must not be empty.")
        normalized_url = base_url.strip().rstrip("/")
        try:
            parsed = urlparse(normalized_url)
            port = parsed.port
        except ValueError as exc:
            raise ValueError("Invalid SMS-Man base URL.") from exc
        if (
            parsed.scheme.lower() != "https"
            or (parsed.hostname or "").lower() != _ALLOWED_HOST
            or port not in (None, 443)
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path.rstrip("/") != _ALLOWED_PATH
        ):
            raise ValueError("base_url must be https://api.sms-man.com/control.")
        if not isinstance(timeout, httpx.Timeout):
            raise TypeError("timeout must be an httpx.Timeout.")
        secret = api_key.get_secret_value().strip()
        if not secret:
            raise ValueError("SMS-Man API key must not be empty.")
        if not isinstance(allow_get_limits_fallback, bool):
            raise TypeError("allow_get_limits_fallback must be bool.")
        self.http = http
        self.api_key = secret
        self.base_url = normalized_url
        self.timeout = timeout
        # Kept for call-site compatibility only. The 404 that used to trigger
        # this fallback was caused by a wrong path, and a GET would put the
        # token in the query string, so the fallback no longer exists.
        self.allow_get_limits_fallback = allow_get_limits_fallback
        # When False (default) purchase() sends only country_id and
        # application_id. maxPrice / currency / hasMultipleSms are optional in
        # the API and a mismatch (e.g. quote currency vs. maxPrice) can cause a
        # 400. Enable once the price currency is confirmed.
        self.send_purchase_options = bool(send_purchase_options)

    # ------------------------------------------------------------------ utils

    @staticmethod
    def _response_shape(data: Any) -> str:
        if isinstance(data, dict):
            return f"dict(count={len(data)}, keys={sorted(str(k)[:60] for k in data)[:20]})"
        if isinstance(data, list):
            first = type(data[0]).__name__ if data else "empty"
            return f"list(length={len(data)}, first_item_type={first})"
        return type(data).__name__

    @staticmethod
    def _sanitize_text(text: str) -> str:
        text = _SECRET_RE.sub(r"\1\2[REDACTED]", text[:200])
        return _LONG_NUMBER_RE.sub("[REDACTED_NUMBER]", text)

    @staticmethod
    def _provider_error_code(value: Any) -> str:
        if not isinstance(value, (str, int)) or isinstance(value, bool):
            return "provider_rejected_request"
        normalized = "".join(c for c in str(value) if c.isalnum() or c in "_-. ")[:80].strip()
        return normalized or "provider_rejected_request"

    @staticmethod
    def _error_fields(data: dict[str, Any]) -> dict[str, Any]:
        """Sanitized provider error details (never raw bodies)."""
        diagnostic: dict[str, Any] = {}
        code = data.get("error_code")
        if isinstance(code, (str, int)) and not isinstance(code, bool):
            diagnostic["error_code"] = SMSManProvider._provider_error_code(code)
        message = data.get("error_msg")
        if isinstance(message, str):
            diagnostic["error_msg"] = SMSManProvider._sanitize_text(message)
        elif isinstance(message, dict):
            # Providers sometimes echo submitted values; keep field names only.
            diagnostic["error_fields"] = sorted(str(k)[:40] for k in message)[:15]
        return diagnostic

    @staticmethod
    def _safe_error_diagnostic(response: httpx.Response) -> dict[str, Any]:
        diagnostic: dict[str, Any] = {
            "status": response.status_code,
            "content_type": response.headers.get("content-type", "")[:100],
            "body_length": len(response.content),
            # Short, sanitized preview so a bare 4xx is debuggable. Tokens and
            # long digit strings (phone numbers, IDs) are redacted.
            "body_preview": SMSManProvider._sanitize_text(response.text[:200]),
        }
        try:
            data = response.json()
        except ValueError:
            return diagnostic
        if isinstance(data, dict):
            diagnostic.update(SMSManProvider._error_fields(data))
        else:
            diagnostic["response_shape"] = SMSManProvider._response_shape(data)
        return diagnostic

    @staticmethod
    def _parse_integer(value: Any, *, name: str, minimum: int = 0) -> int:
        if isinstance(value, bool) or value is None:
            raise ValueError(f"{name} must be an integer.")
        if isinstance(value, int):
            result = value
        elif isinstance(value, str) and re.fullmatch(r"\s*\d+\s*", value):
            result = int(value.strip())
        else:
            raise ValueError(f"{name} must be an integer.")
        if result < minimum:
            raise ValueError(f"{name} must be at least {minimum}.")
        return result

    @staticmethod
    def _mapping_get(mapping: Any, key: Any, default: Any = None) -> Any:
        """Look up ``key`` in a dict whose keys may be ints or strings."""
        if not isinstance(mapping, dict):
            return default
        for candidate in (key, str(key)):
            try:
                if candidate in mapping:
                    return mapping[candidate]
            except TypeError:
                continue
        try:
            return mapping.get(int(key), default)
        except (TypeError, ValueError, OverflowError):
            return default

    @staticmethod
    def _require_list(data: Any, *, operation: str, code: str, message: str) -> list[dict[str, Any]]:
        if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
            logger.warning(
                "SMS-Man response shape mismatch: operation=%s expected=list_of_objects actual=%s",
                operation,
                SMSManProvider._response_shape(data),
            )
            raise SMSManError(message, code=code)
        return data

    @staticmethod
    def _unwrap_catalogue(data: Any, *, operation: str) -> list[dict[str, Any]]:
        current = data
        for _ in range(5):
            if isinstance(current, list):
                return SMSManProvider._require_list(
                    current,
                    operation=operation,
                    code=f"invalid_{operation}_response",
                    message=f"SMS-Man returned an invalid {operation} catalogue.",
                )
            if not isinstance(current, dict):
                break
            if current.get("success") is False:
                raise SMSManError(
                    f"SMS-Man rejected the {operation} catalogue request.",
                    code=SMSManProvider._provider_error_code(current.get("error_code")),
                )
            nested = next((current[k] for k in _CATALOGUE_KEYS if isinstance(current.get(k), (list, dict))), None)
            if nested is not None:
                current = nested
                continue
            if current and all(isinstance(v, dict) for v in current.values()):
                records = []
                for record_id, value in current.items():
                    record = dict(value)
                    record.setdefault("id", record_id)
                    records.append(record)
                return records
            break
        logger.warning(
            "SMS-Man catalogue shape unsupported: operation=%s shape=%s",
            operation,
            SMSManProvider._response_shape(data),
        )
        raise SMSManError(f"SMS-Man returned an invalid {operation} catalogue.", code=f"invalid_{operation}_response")

    @staticmethod
    def _catalogue_id(item: dict[str, Any]) -> int | None:
        try:
            return SMSManProvider._parse_integer(item.get("id"), name="id", minimum=0)
        except (TypeError, ValueError, OverflowError):
            return None

    # ------------------------------------------------------------- transport

    async def _request(
        self,
        operation: str,
        *,
        params: dict[str, Any] | None = None,
        timeout: httpx.Timeout | None = None,
        outcome_uncertain_on_failure: bool = False,
        retries: int = 0,
    ) -> Any:
        """Make one POST request. Retries transport failures only when
        ``retries`` > 0, which callers set for read-only operations.

        SMS-Man's endpoints bind action arguments (country_id, application_id,
        request_id, status, ...) from the URL query string only; the same
        values sent in a POST form body are ignored, which produced
        "Missing required parameters: application_id" (HTTP 400). So:
          * operation parameters go in the query string,
          * the token stays in the POST form body, never in the URL, so it
            cannot leak through access logs, proxies, or the httpx logger.
        """
        if not re.fullmatch(r"[a-zA-Z0-9-]+", operation or ""):
            raise ValueError("Invalid SMS-Man operation.")
        query: dict[str, Any] = {}
        for key, value in (params or {}).items():
            if not isinstance(key, str):
                raise ValueError("Provider parameter names must be strings.")
            if key.lower() in {"token", "api_key"}:
                raise ValueError("Authentication parameters cannot be overridden.")
            if value is not None:
                query[key] = value
        form = {"token": self.api_key}

        try:
            response = None
            for attempt in range(retries + 1):
                try:
                    response = await self.http.post(
                        f"{self.base_url}/{operation}",
                        params=query or None,
                        data=form,
                        timeout=timeout or self.timeout,
                    )
                    break
                except _RETRYABLE as exc:
                    if attempt >= retries:
                        raise
                    logger.warning(
                        "SMS-Man transient failure, retrying: operation=%s attempt=%d type=%s",
                        operation,
                        attempt + 1,
                        type(exc).__name__,
                    )
                    await asyncio.sleep(1.5 * (attempt + 1))
            assert response is not None
        except (httpx.ConnectTimeout, httpx.ConnectError) as exc:
            # The request never reached the provider, so nothing was bought.
            logger.warning("SMS-Man connect failure: operation=%s type=%s", operation, type(exc).__name__)
            raise SMSManError("Could not connect to SMS-Man.", uncertain=False, code="provider_network_error") from exc
        except httpx.TimeoutException as exc:
            logger.warning("SMS-Man timeout: operation=%s", operation)
            raise SMSManError(
                "The SMS-Man request timed out.", uncertain=outcome_uncertain_on_failure, code="provider_timeout"
            ) from exc
        except httpx.NetworkError as exc:
            logger.warning("SMS-Man network failure: operation=%s type=%s", operation, type(exc).__name__)
            raise SMSManError(
                "Could not connect to SMS-Man.", uncertain=outcome_uncertain_on_failure, code="provider_network_error"
            ) from exc
        except httpx.HTTPError as exc:
            logger.warning("SMS-Man HTTP client failure: operation=%s type=%s", operation, type(exc).__name__)
            raise SMSManError(
                "The SMS-Man request failed.", uncertain=outcome_uncertain_on_failure, code="provider_http_error"
            ) from exc

        status = response.status_code
        if response.is_error:
            logger.warning(
                "SMS-Man HTTP failure: operation=%s diagnostic=%s", operation, self._safe_error_diagnostic(response)
            )
            # Only 5xx can mean "processed, but the reply failed". Any 4xx
            # (including a 404 from a wrong path) was rejected up front.
            uncertain = outcome_uncertain_on_failure and status >= 500
            raise SMSManError(f"SMS-Man returned HTTP {status}.", uncertain=uncertain, code=f"provider_http_{status}")

        try:
            data = response.json()
        except ValueError as exc:
            logger.warning("SMS-Man returned non-JSON response: operation=%s status=%s", operation, status)
            raise SMSManError(
                "SMS-Man returned an invalid response.",
                uncertain=outcome_uncertain_on_failure,
                code="invalid_provider_response",
            ) from exc

        if isinstance(data, dict) and data.get("success") is False:
            diagnostic = self._error_fields(data)
            code = diagnostic.get("error_code", "provider_rejected_request")
            logger.warning("SMS-Man rejected request: operation=%s diagnostic=%s", operation, diagnostic)
            raise SMSManError("SMS-Man rejected the request.", code=code)

        logger.debug(
            "SMS-Man response received: operation=%s status=%s shape=%s", operation, status, self._response_shape(data)
        )
        return data

    # --------------------------------------------------------------- catalogs

    async def balance(self) -> Decimal:
        data = await self._request(OP_BALANCE, retries=READ_RETRIES)
        raw = data.get("balance") if isinstance(data, dict) else None
        try:
            if isinstance(raw, bool) or raw is None:
                raise InvalidOperation
            value = Decimal(str(raw))
            if not value.is_finite():
                raise InvalidOperation
            return value
        except (InvalidOperation, ValueError):
            logger.warning("SMS-Man balance response invalid: shape=%s", self._response_shape(data))
            raise SMSManError("SMS-Man returned an invalid balance.", code="invalid_balance_response") from None

    async def countries(self) -> list[dict[str, Any]]:
        items = self._unwrap_catalogue(await self._request(OP_COUNTRIES, retries=READ_RETRIES), operation="country")
        result, rejected = [], 0
        for item in items:
            country_id, title = self._catalogue_id(item), item.get("title")
            if country_id is None or not isinstance(title, str) or not title.strip():
                rejected += 1
                continue
            normalized = dict(item)
            normalized.update(id=country_id, title=title.strip())
            result.append(normalized)
        if not result:
            logger.warning("SMS-Man country catalogue invalid: total=%d rejected=%d", len(items), rejected)
            raise SMSManError("SMS-Man returned no valid countries.", code="empty_country_catalogue")
        logger.info("SMS-Man country catalogue validated: count=%d rejected=%d", len(result), rejected)
        return result

    async def services(self) -> list[dict[str, Any]]:
        items = self._unwrap_catalogue(
            await self._request(OP_APPLICATIONS, timeout=APPLICATIONS_TIMEOUT, retries=READ_RETRIES), operation="service"
        )
        result, rejected, field_samples = [], 0, []
        for item in items:
            service_id = self._catalogue_id(item)
            name = item.get("name", item.get("title"))
            if service_id is None or not isinstance(name, str) or not name.strip():
                rejected += 1
                if len(field_samples) < 3:
                    field_samples.append(sorted(str(k)[:60] for k in item)[:20])
                continue
            normalized = dict(item)
            normalized["id"], normalized["name"] = service_id, name.strip()
            code = normalized.get("code")
            if code is not None:
                normalized["code"] = (
                    str(code).strip() if isinstance(code, (str, int)) and not isinstance(code, bool) else None
                )
            result.append(normalized)
        if rejected:
            logger.warning(
                "SMS-Man service records rejected: total=%d rejected=%d valid=%d sample_field_sets=%s",
                len(items),
                rejected,
                len(result),
                field_samples,
            )
        if not result:
            raise SMSManError("SMS-Man returned no valid services.", code="empty_service_catalogue")
        logger.info("SMS-Man service catalogue validated: count=%d rejected=%d", len(result), rejected)
        return result

    # ----------------------------------------------------------------- prices

    @staticmethod
    def _is_quote(value: Any) -> bool:
        return isinstance(value, dict) and "cost" in value

    @classmethod
    def _normalize_prices(cls, data: dict[str, Any], country_id: int | None) -> dict[str, dict[str, Any]]:
        """Return prices as ``{country_id: {application_id: {cost, count}}}``.

        The docs describe that nested shape, but when ``country_id`` is given
        the live API returns a flat ``{application_id: {cost, count,
        application_id}}`` map instead. Both are normalized here.
        """
        sample = [v for _, v in zip(range(10), data.values())]
        flat = bool(sample) and all(cls._is_quote(v) for v in sample)
        if flat:
            if country_id is None:
                raise SMSManError(
                    "SMS-Man returned prices without country information.", code="invalid_price_response"
                )
            return {str(country_id): data}

        nested_ok = bool(sample) and all(
            isinstance(v, dict) and all(cls._is_quote(q) for _, q in zip(range(3), v.values())) for v in sample
        )
        if not nested_ok and data:
            logger.warning("SMS-Man price shape unsupported: shape=%s", cls._response_shape(data))
            raise SMSManError("SMS-Man returned an invalid price catalogue.", code="invalid_price_response")
        if country_id is None:
            return {str(k): v for k, v in data.items()}
        selected = cls._mapping_get(data, country_id)
        return {str(country_id): selected} if isinstance(selected, dict) else {}

    async def prices(self, country_id: int | None = None) -> dict[str, dict[str, Any]]:
        params: dict[str, Any] = {}
        if country_id is not None:
            country_id = self._parse_integer(country_id, name="country_id", minimum=0)
            params["country_id"] = country_id
        try:
            data = await asyncio.wait_for(
                self._request(OP_PRICES, params=params, timeout=PRICES_TIMEOUT, retries=READ_RETRIES),
                timeout=PRICES_DEADLINE_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            logger.warning("SMS-Man get-prices exceeded the %ss deadline", PRICES_DEADLINE_SECONDS)
            raise SMSManError("The SMS-Man price lookup timed out.", code="provider_timeout") from exc
        if not isinstance(data, dict):
            logger.warning("SMS-Man price response shape mismatch: actual=%s", self._response_shape(data))
            raise SMSManError("SMS-Man returned an invalid price catalogue.", code="invalid_price_response")
        normalized = self._normalize_prices(data, country_id)
        logger.info(
            "SMS-Man prices: requested_country=%s raw_count=%d normalized_countries=%d",
            "all" if country_id is None else country_id,
            len(data),
            len(normalized),
        )
        return normalized

    async def quote(self, country_id: int, application_id: int) -> dict[str, Any]:
        """Return ``{"cost": <str|number>, "count": int}`` for one country/app pair."""
        country_id = self._parse_integer(country_id, name="country_id", minimum=0)
        application_id = self._parse_integer(application_id, name="application_id", minimum=1)
        prices = await self.prices(country_id)
        entry = self._mapping_get(self._mapping_get(prices, country_id), application_id)
        if not self._is_quote(entry):
            raise SMSManError("No price is available for this service and country.", code="pricing_unavailable")
        try:
            count = self._parse_integer(entry.get("count", 0), name="count", minimum=0)
        except ValueError:
            count = 0
        return {"cost": entry["cost"], "count": count}

    # ----------------------------------------------------------------- limits

    async def limits(self, country_id: int | None = None, application_id: int | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if country_id is not None:
            params["country_id"] = self._parse_integer(country_id, name="country_id", minimum=0)
        if application_id is not None:
            params["application_id"] = self._parse_integer(application_id, name="application_id", minimum=1)
        data = await self._request(OP_LIMITS, params=params, retries=READ_RETRIES)
        return self._require_list(
            data, operation=OP_LIMITS, code="invalid_inventory_response", message="SMS-Man returned invalid availability data."
        )

    # --------------------------------------------------------------- purchase

    async def purchase(
        self, country_id: int, application_id: int, max_price: int | None = None, currency: str = "USD"
    ) -> dict[str, Any]:
        """Purchase once only; never automatically retry this operation.

        ``currency`` and ``max_price`` are validated but only sent to the
        provider when ``send_purchase_options`` is enabled.
        """
        country_id = self._parse_integer(country_id, name="country_id", minimum=0)
        application_id = self._parse_integer(application_id, name="application_id", minimum=1)
        if not isinstance(currency, str):
            raise ValueError("currency must be a string.")
        currency = currency.strip().upper()
        if currency not in ALLOWED_CURRENCIES:
            raise ValueError("currency must be RUB, USD or EUR.")
        params: dict[str, Any] = {
            "country_id": country_id,
            "application_id": application_id,
        }
        if self.send_purchase_options:
            params["currency"] = currency
            params["hasMultipleSms"] = "False"
            if max_price is not None:
                params["maxPrice"] = self._parse_integer(max_price, name="max_price", minimum=1)

        data = await self._request(OP_PURCHASE, params=params, outcome_uncertain_on_failure=True)
        if not isinstance(data, dict):
            logger.warning("SMS-Man purchase response invalid: shape=%s", self._response_shape(data))
            raise SMSManError(
                "SMS-Man returned an invalid purchase response.", uncertain=True, code="invalid_purchase_response"
            )
        # SMS-Man reports many purchase failures (no stock, low balance, bad
        # application) as HTTP 200 with an error_code/error_msg body and NO
        # "success": false flag. That is a definite rejection, not an unknown
        # outcome, so it must not be left for manual reconciliation.
        if data.get("error_code") not in (None, "") and data.get("request_id") in (None, ""):
            diagnostic = self._error_fields(data)
            logger.warning("SMS-Man purchase rejected: diagnostic=%s", diagnostic)
            raise SMSManError(
                "SMS-Man rejected the number purchase.",
                uncertain=False,
                code=diagnostic.get("error_code", "provider_rejected_request"),
            )
        try:
            request_id = self._parse_integer(data.get("request_id"), name="request_id", minimum=1)
        except (TypeError, ValueError, OverflowError):
            request_id = None
        number = data.get("number")
        if request_id is None or not isinstance(number, str) or not number.strip():
            logger.warning("SMS-Man purchase confirmation incomplete: shape=%s", self._response_shape(data))
            raise SMSManError(
                "SMS-Man did not confirm the phone number purchase.", uncertain=True, code="invalid_purchase_response"
            )
        normalized = dict(data)
        normalized["request_id"], normalized["number"] = request_id, number.strip()
        return normalized

    async def sms(self, request_id: int) -> dict[str, Any]:
        """Poll for the SMS. Adds ``status``: ``received`` or ``waiting``.

        A "wait_sms" reply is a normal pending state, not an error.
        """
        request_id = self._parse_integer(request_id, name="request_id", minimum=1)
        data = await self._request(OP_SMS, params={"request_id": request_id}, retries=READ_RETRIES)
        if not isinstance(data, dict):
            logger.warning("SMS-Man SMS response invalid: shape=%s", self._response_shape(data))
            raise SMSManError("SMS-Man returned an invalid SMS response.", code="invalid_sms_response")
        normalized = dict(data)
        code = normalized.get("sms_code")
        if code not in (None, ""):
            normalized["sms_code"] = str(code).strip()
            normalized["status"] = "received"
        elif normalized.get("error_code") in (None, "wait_sms"):
            normalized["status"] = "waiting"
        else:
            raise SMSManError(
                "SMS-Man could not deliver the SMS.",
                code=self._provider_error_code(normalized.get("error_code")),
            )
        return normalized

    async def change_status(self, request_id: int, status: str) -> dict[str, Any]:
        request_id = self._parse_integer(request_id, name="request_id", minimum=1)
        if not isinstance(status, str):
            raise ValueError("status must be a string.")
        status = status.strip().lower()
        if status not in ALLOWED_STATUSES:
            raise ValueError("status must be ready, close, reject or used.")
        data = await self._request(
            OP_STATUS, params={"request_id": request_id, "status": status}, outcome_uncertain_on_failure=True
        )
        if not isinstance(data, dict) or data.get("success") is not True:
            logger.warning("SMS-Man status change unconfirmed: status=%s", status)
            raise SMSManError("SMS-Man did not confirm the status change.", uncertain=True, code="status_change_unconfirmed")
        return data


def provider_cost_to_kobo(cost: Any, ngn_per_unit: Decimal) -> int:
    """Convert provider currency to NGN kobo using a trusted FX rate."""
    if not isinstance(ngn_per_unit, Decimal) or not ngn_per_unit.is_finite() or ngn_per_unit <= Decimal("0"):
        raise SMSManError("The provider conversion rate is invalid.", code="pricing_unavailable")
    try:
        if isinstance(cost, bool) or cost is None:
            raise InvalidOperation
        amount = Decimal(str(cost))
        if not amount.is_finite() or amount <= Decimal("0"):
            raise InvalidOperation
        kobo = amount * ngn_per_unit * Decimal("100")
        return int(kobo.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError, TypeError, OverflowError) as exc:
        raise SMSManError("The provider price is invalid.", code="invalid_price") from exc