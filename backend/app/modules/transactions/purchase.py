import hashlib
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ratelimit
from app.core.config import Settings
from app.core.errors import AppError, ConflictError, ForbiddenError
from app.core.ids import uuid7
from app.core.money import Money
from app.modules.audit import service as audit
from app.modules.ledger.interface import SystemAccount
from app.modules.providers.models import DataPlan, ProviderPrice
from app.modules.providers.prices import (
    NETWORKS, airtime_price, data_price, education_price, electricity_price, tv_price, expected_cost, is_fresh,
)
from app.modules.services import interface as pricing
from app.modules.services.models import PricingRule
from app.modules.services.pricing import PriceBreakdown
from app.modules.transactions.models import AirtimeOrder, DataOrder, EducationOrder, ElectricityOrder, TVOrder, Transaction
from app.modules.transactions.networks import check_network
from app.modules.transactions.state import TxnStatus, transition
from app.modules.users.models import User
from app.modules.wallet.service import WalletService

log = logging.getLogger(__name__)
PROVIDER = "inlomax"


@dataclass(frozen=True)
class MeterTarget:
    """A meter the customer has just had verified. Purchases can only target a verified meter."""

    disco_id: uuid.UUID
    disco_code: str
    disco_name: str
    provider_disco_code: str
    meter_type: str
    meter_number: str
    customer_name: str
    customer_address: str
    service_id: str
    min_kobo: int


@dataclass(frozen=True)
class TVTarget:
    product_id: uuid.UUID
    operator_code: str
    operator_name: str
    smartcard_number: str
    customer_name: str
    current_bouquet: str
    provider_service_id: str
    product_name: str


@dataclass(frozen=True)
class ProductTarget:
    product_id: uuid.UUID
    code: str
    name: str
    provider_service_id: str
    max_quantity: int


class InvalidEducationQuantityError(AppError):
    status_code, code = 422, "invalid_quantity"
    user_message = "Please check the quantity."


class InvalidElectricityAmountError(AppError):
    status_code, code = 422, "invalid_electricity_amount"
    user_message = "Please check the amount."


class InvalidAirtimeError(AppError):
    status_code, code = 422, "invalid_airtime_request"
    user_message = "Please check the network and amount."


class PlanUnavailableError(AppError):
    status_code, code = 404, "plan_unavailable"
    user_message = "This data plan is no longer available."


class PurchaseService:
    def __init__(self, db: AsyncSession, redis: Redis, settings: Settings) -> None:
        self.db, self.redis, self.settings = db, redis, settings

    # ---------- shared ----------
    def _fresh(self, row: ProviderPrice | None) -> ProviderPrice:
        if row is None or not is_fresh(row, self.settings.provider_cost_max_age_h):
            raise pricing.PricingUnavailableError(reason="no fresh provider cost")
        return row

    async def _price(self, category: str, scope_keys: list[str], cost: Money, face: Money | None,
                     audit_key: str, quantity: int = 1) -> tuple[PriceBreakdown, PricingRule]:
        try:
            return await pricing.price_for(self.db, category=category, provider_code=PROVIDER,
                                           scope_keys=scope_keys, cost=cost, face=face, quantity=quantity)
        except pricing.PricingBlockedError as exc:
            if await self.redis.set(f"pricing:blocked:{audit_key}", 1, ex=600, nx=True):
                audit.record(self.db, action="pricing.blocked", meta={**exc.context, "scope": audit_key})
                await self.db.commit()
            raise

    # ---------- quoting ----------
    async def quote_airtime(self, network: str, amount_kobo: int) -> tuple[PriceBreakdown, PricingRule, ProviderPrice]:
        s = self.settings
        if network not in NETWORKS or amount_kobo % 100 or not s.airtime_min_kobo <= amount_kobo <= s.airtime_max_kobo:
            raise InvalidAirtimeError(
                f"Airtime must be a whole-naira amount between NGN {Money(s.airtime_min_kobo).naira:,.0f} "
                f"and NGN {Money(s.airtime_max_kobo).naira:,.0f}.")
        row = self._fresh(await airtime_price(self.db, PROVIDER, network))
        face = Money(amount_kobo)
        b, rule = await self._price("AIRTIME", [network], expected_cost(row, face), face, network)
        return b, rule, row

    async def quote_data(self, plan_id: uuid.UUID) -> tuple[PriceBreakdown, PricingRule, ProviderPrice, DataPlan]:
        plan = await self.db.get(DataPlan, plan_id)
        if plan is None or not (plan.listed and plan.active):
            raise PlanUnavailableError()
        row = self._fresh(await data_price(self.db, PROVIDER, plan.provider_service_id))
        scopes = [f"PLAN:{plan.provider_service_id}", f"{plan.network}:{plan.data_type}", plan.network]
        b, rule = await self._price("DATA", scopes, expected_cost(row, Money(0)), None, f"PLAN:{plan.provider_service_id}")
        return b, rule, row, plan

    async def quote_education(self, t: ProductTarget, quantity: int) -> tuple[PriceBreakdown, PricingRule, ProviderPrice]:
        top = min(t.max_quantity, self.settings.education_max_quantity)
        if not 1 <= quantity <= top:
            raise InvalidEducationQuantityError(f"You can buy between 1 and {top} PINs at a time.")
        row = self._fresh(await education_price(self.db, PROVIDER, t.provider_service_id))
        b, rule = await self._price("EDUCATION", [f"PRODUCT:{t.provider_service_id}", t.code],
                                    expected_cost(row, Money(0)), None, t.code, quantity)
        return b, rule, row

    async def quote_tv(self, t: TVTarget) -> tuple[PriceBreakdown, PricingRule, ProviderPrice]:
        row = self._fresh(await tv_price(self.db, PROVIDER, t.provider_service_id))
        b, rule = await self._price("TV", [f"PLAN:{t.provider_service_id}", t.operator_code],
                                    expected_cost(row, Money(0)), None, f"TV:{t.provider_service_id}")
        return b, rule, row

    async def quote_electricity(self, t: MeterTarget, amount_kobo: int) -> tuple[PriceBreakdown, PricingRule, ProviderPrice]:
        s = self.settings
        lo = max(s.electricity_min_kobo, t.min_kobo)
        if amount_kobo % 100 or not lo <= amount_kobo <= s.electricity_max_kobo:
            raise InvalidElectricityAmountError(
                f"Enter a whole-naira amount between NGN {Money(lo).naira:,.0f} and NGN {Money(s.electricity_max_kobo).naira:,.0f}.")
        row = self._fresh(await electricity_price(self.db, PROVIDER, t.service_id))
        face = Money(amount_kobo)
        scope = f"{t.disco_code}:{t.meter_type}"
        b, rule = await self._price("ELECTRICITY", [scope, t.disco_code], expected_cost(row, face), face, scope)
        return b, rule, row

    # ---------- purchases ----------
    async def create_airtime(self, user: User, network: str, phone: str, amount_kobo: int, confirmed_price_kobo: int,
                             idempotency_key: str, pin_jti: str, pin_exp: int, confirm_network: bool = False) -> Transaction:
        req_hash = hashlib.sha256(f"airtime:{network}:{phone}:{amount_kobo}".encode()).hexdigest()
        if (existing := await self._existing(user, idempotency_key, req_hash)):
            return existing
        await ratelimit.hit(self.redis, f"rl:buy:{user.id}", 30, 3600)
        b, rule, row = await self.quote_airtime(network, amount_kobo)
        check_network(phone, network, confirm_network)
        return await self._create(
            user, "AIRTIME", req_hash, idempotency_key, b, rule, row, amount_kobo, confirmed_price_kobo,
            lambda tid: AirtimeOrder(transaction_id=tid, network=network, phone=phone),
            f"{network} airtime", pin_jti, pin_exp)

    async def create_data(self, user: User, plan_id: uuid.UUID, phone: str, confirmed_price_kobo: int,
                          idempotency_key: str, pin_jti: str, pin_exp: int, confirm_network: bool = False) -> Transaction:
        req_hash = hashlib.sha256(f"data:{plan_id}:{phone}".encode()).hexdigest()
        if (existing := await self._existing(user, idempotency_key, req_hash)):
            return existing
        await ratelimit.hit(self.redis, f"rl:buy:{user.id}", 30, 3600)
        b, rule, row, plan = await self.quote_data(plan_id)
        check_network(phone, plan.network, confirm_network)
        return await self._create(
            user, "DATA", req_hash, idempotency_key, b, rule, row, b.customer_price.kobo, confirmed_price_kobo,
            lambda tid: DataOrder(transaction_id=tid, network=plan.network, phone=phone,
                                  provider_service_id=plan.provider_service_id, plan_name=plan.name,
                                  data_type=plan.data_type, validity=plan.validity),
            f"{plan.network} {plan.name} data", pin_jti, pin_exp, provider_service_id=plan.provider_service_id)

    async def create_education(self, user: User, t: ProductTarget, quantity: int, confirmed_price_kobo: int,
                               idempotency_key: str, pin_jti: str, pin_exp: int) -> Transaction:
        req_hash = hashlib.sha256(f"education:{t.product_id}:{quantity}".encode()).hexdigest()
        if (existing := await self._existing(user, idempotency_key, req_hash)):
            return existing
        await ratelimit.hit(self.redis, f"rl:buy:{user.id}", 30, 3600)
        b, rule, row = await self.quote_education(t, quantity)
        return await self._create(
            user, "EDUCATION", req_hash, idempotency_key, b, rule, row, b.customer_price.kobo, confirmed_price_kobo,
            lambda tid: EducationOrder(transaction_id=tid, product_id=t.product_id, product_code=t.code,
                                       product_name=t.name, quantity=quantity),
            f"{t.name} x{quantity}", pin_jti, pin_exp, provider_service_id=t.provider_service_id)

    async def create_tv(self, user: User, t: TVTarget, confirmed_price_kobo: int,
                        idempotency_key: str, pin_jti: str, pin_exp: int) -> Transaction:
        req_hash = hashlib.sha256(
            f"tv:{t.product_id}:{t.smartcard_number}:{t.current_bouquet}".encode()).hexdigest()
        if (existing := await self._existing(user, idempotency_key, req_hash)):
            return existing
        await ratelimit.hit(self.redis, f"rl:buy:{user.id}", 30, 3600)
        b, rule, row = await self.quote_tv(t)
        return await self._create(
            user, "TV", req_hash, idempotency_key, b, rule, row, b.customer_price.kobo, confirmed_price_kobo,
            lambda tid: TVOrder(transaction_id=tid, product_id=t.product_id, operator_code=t.operator_code,
                                operator_name=t.operator_name, product_name=t.product_name,
                                smartcard_number=t.smartcard_number, customer_name=t.customer_name,
                                current_bouquet=t.current_bouquet),
            f"{t.operator_name} {t.product_name} TV subscription", pin_jti, pin_exp,
            provider_service_id=t.provider_service_id)

    async def create_electricity(self, user: User, t: MeterTarget, amount_kobo: int, confirmed_price_kobo: int,
                                 idempotency_key: str, pin_jti: str, pin_exp: int) -> Transaction:
        req_hash = hashlib.sha256(f"electricity:{t.disco_id}:{t.meter_type}:{t.meter_number}:{amount_kobo}".encode()).hexdigest()
        if (existing := await self._existing(user, idempotency_key, req_hash)):
            return existing
        await ratelimit.hit(self.redis, f"rl:buy:{user.id}", 30, 3600)
        b, rule, row = await self.quote_electricity(t, amount_kobo)
        return await self._create(
            user, "ELECTRICITY", req_hash, idempotency_key, b, rule, row, amount_kobo, confirmed_price_kobo,
            lambda tid: ElectricityOrder(transaction_id=tid, disco_id=t.disco_id, disco_code=t.disco_code,
                                         disco_name=t.disco_name, provider_disco_code=t.provider_disco_code,
                                         meter_type=t.meter_type, meter_number=t.meter_number,
                                         customer_name=t.customer_name, customer_address=t.customer_address),
            f"{t.disco_name} {t.meter_type.lower()} electricity", pin_jti, pin_exp, provider_service_id=t.service_id)

    async def _create(self, user: User, service_type: str, req_hash: str, key: str, b: PriceBreakdown, rule: PricingRule,
                      price_row: ProviderPrice, amount_kobo: int, confirmed_price_kobo: int,
                      make_order: Callable[[uuid.UUID], Any], description: str, pin_jti: str, pin_exp: int,
                      provider_service_id: str | None = None) -> Transaction:
        if b.customer_price.kobo != confirmed_price_kobo:
            raise pricing.PriceChangedError(f"The price is now NGN {b.customer_price.naira_str()}. "
                                            "Please review and confirm again.")
        ref, txn_id = f"txn_{uuid7().hex}", uuid7()
        inserted = (await self.db.execute(
            insert(Transaction).values(
                id=txn_id, reference=ref, user_id=user.id, service_type=service_type, status=TxnStatus.INITIATED.value,
                idempotency_key=key, request_hash=req_hash, amount_kobo=amount_kobo, price_kobo=b.customer_price.kobo,
                provider_code=PROVIDER, provider_service_id=provider_service_id or price_row.provider_service_id)
            .on_conflict_do_nothing(constraint="uq_transactions_user_idempotency").returning(Transaction.id))
        ).scalar_one_or_none()
        if inserted is None:  # a concurrent request with the same key won the race
            existing = await self._existing(user, key, req_hash)
            assert existing is not None
            return existing
        txn = await self.db.get(Transaction, txn_id)
        assert txn is not None
        self.db.add(make_order(txn_id))
        pricing.add_snapshot(self.db, transaction_id=txn_id, rule=rule, b=b, provider_code=PROVIDER,
                             cost_source=price_row.source)
        # Lock order everywhere: transaction row first, then wallet.
        hold = await WalletService(self.db).debit(
            user.id, b.customer_price, reference=f"hold:{ref}", kind="purchase.hold",
            destination=SystemAccount.PROVIDER_CLEARING, description=description, meta={"transaction": ref})
        txn.hold_journal_reference = hold.reference
        transition(self.db, txn, TxnStatus.PENDING, "funds held")
        ttl = max(1, pin_exp - int(datetime.now(UTC).timestamp()))
        if not await self.redis.set(f"pin:used:{pin_jti}", 1, ex=ttl, nx=True):  # step-up token is single-use
            raise ForbiddenError("Please confirm with your transaction PIN again.")
        audit.record(self.db, action="transaction.created", actor_user_id=user.id, resource_type="transaction",
                     resource_id=ref, meta={"service": service_type})
        await self.db.commit()
        return txn

    async def find_by_key(self, user: User, key: str) -> Transaction | None:
        return (await self.db.execute(select(Transaction).where(
            Transaction.user_id == user.id, Transaction.idempotency_key == key))).scalar_one_or_none()

    async def _existing(self, user: User, key: str, req_hash: str) -> Transaction | None:
        txn = (await self.db.execute(select(Transaction).where(
            Transaction.user_id == user.id, Transaction.idempotency_key == key))).scalar_one_or_none()
        if txn is None:
            return None
        if txn.request_hash != req_hash:
            raise ConflictError("This idempotency key was already used for a different purchase.")
        return txn
