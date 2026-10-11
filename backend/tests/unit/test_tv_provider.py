import httpx
import pytest

from app.core.money import Money
from app.modules.providers.base import Outcome, TVRequest
from app.modules.providers.inlomax import InlomaxProvider
from app.modules.providers.sandbox import SandboxBillProvider


@pytest.mark.asyncio
async def test_inlomax_validates_tv_smartcard_and_returns_customer() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/validatecable"
        assert request.headers["Authorization"] == "Token test-key"
        assert request.read() == b'{"serviceID":"1","iucNum":"7027914329"}'
        return httpx.Response(200, json={"status": "success", "data": {
            "customerName": "JOHN DOE", "currentBouquet": "GOtv Jolli"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = InlomaxProvider(client, "test-key", "https://provider.test/api")
        info = await provider.validate_smartcard("1", "7027914329")
    assert info.customer_name == "JOHN DOE"
    assert info.current_bouquet == "GOtv Jolli"
    assert info.smartcard_number == "7027914329"


@pytest.mark.asyncio
async def test_inlomax_tv_purchase_uses_request_id_and_maps_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/subcable"
        assert request.read() == b'{"serviceID":"95","iucNum":"7027914329","request-id":"txn_abc"}'
        return httpx.Response(200, json={"status": "success", "data": {
            "reference": "INL-123", "amount": 8500, "status": "success"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = InlomaxProvider(client, "test-key", "https://provider.test/api")
        result = await provider.purchase_tv(TVRequest("txn_abc", "95", "7027914329"))
    assert result.outcome is Outcome.SUCCESS
    assert result.provider_reference == "INL-123"
    assert result.amount_charged == Money.from_naira(8500)


@pytest.mark.asyncio
async def test_sandbox_tv_validation_and_purchase() -> None:
    provider = SandboxBillProvider()
    info = await provider.validate_smartcard("gotv", "7027914329")
    result = await provider.purchase_tv(TVRequest("txn_sandbox", "sandbox-gotv-jolli", "7027914329"))
    assert info.customer_name == "SANDBOX CUSTOMER"
    assert result.outcome is Outcome.SUCCESS
    assert provider.calls[0].smartcard_number == "7027914329"


@pytest.mark.asyncio
async def test_inlomax_tv_timeout_is_unknown_not_failed() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("provider timed out", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = InlomaxProvider(client, "test-key", "https://provider.test/api")
        result = await provider.purchase_tv(TVRequest("txn_abc", "95", "7027914329"))
    assert calls == 1
    assert result.outcome is Outcome.UNKNOWN
