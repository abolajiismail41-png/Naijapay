"""Deterministic pricing engine. Pure functions, integer kobo, Decimal rates, no floats."""
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum

from app.core.money import Money
from app.modules.services.errors import PricingBlockedError


class Method(StrEnum):
    PERCENT_MARKUP = "PERCENT_MARKUP"
    FIXED_MARKUP = "FIXED_MARKUP"
    CUSTOM_PRICE = "CUSTOM_PRICE"
    FACE_VALUE = "FACE_VALUE"   # customer pays the product value (+ fee); margin is the provider discount


@dataclass(frozen=True)
class RuleParams:
    method: str
    markup_bps: int | None = None
    markup_kobo: int | None = None
    custom_price_kobo: int | None = None
    fee_kobo: int = 0
    discount_bps: int = 0
    discount_kobo: int = 0
    referral_bps: int = 0
    cap_at_face: bool = False
    allow_subsidy: bool = False
    rounding_kobo: int = 1       # customer price is rounded UP to a multiple of this (100 = whole naira)


@dataclass(frozen=True)
class PriceBreakdown:
    cost: Money
    markup: Money
    fee: Money
    list_price: Money                      # cost + markup + fee, before discount
    discount: Money
    customer_price: Money                  # what the customer is charged
    referral_commission: Money
    processing_cost: Money
    gross_profit_before_discount: Money    # list price - cost
    gross_profit: Money                    # customer price - cost
    net_contribution: Money                # gross profit - referral - processing
    margin_pct: Decimal                    # gross profit / customer price, 2dp
    capped: bool
    below_cost: bool


def _bps(amount: Money, bps: int) -> Money:
    return amount.percent(Decimal(bps) / 100)


def compute(cost: Money, params: RuleParams, *, face: Money | None = None, referral_applicable: bool = False,
            processing_cost: Money = Money(0), enforce: bool = True) -> PriceBreakdown:
    if not cost.is_positive():
        raise ValueError("provider cost must be positive")
    if params.method == Method.CUSTOM_PRICE and params.custom_price_kobo is not None:
        markup = Money(params.custom_price_kobo) - cost
    elif params.method == Method.PERCENT_MARKUP and params.markup_bps is not None:
        markup = _bps(cost, params.markup_bps)
    elif params.method == Method.FACE_VALUE and face is not None:
        markup = face - cost
    elif params.method == Method.FIXED_MARKUP and params.markup_kobo is not None:
        markup = Money(params.markup_kobo)
    else:
        raise ValueError("pricing rule is incomplete for its method")
    fee = Money(params.fee_kobo)
    list_price = cost + markup + fee
    discount = min(Money(params.discount_kobo) + _bps(list_price, params.discount_bps), list_price)
    price, capped = list_price - discount, False
    if params.rounding_kobo > 1 and price.kobo % params.rounding_kobo:
        rounded = Money(-(-price.kobo // params.rounding_kobo) * params.rounding_kobo)  # ceil: never erodes margin
        list_price, markup, price = list_price + (rounded - price), markup + (rounded - price), rounded
    if params.cap_at_face and face is not None and price > face:
        price, capped = face, True                      # explicit ceiling: never sell airtime above face value
        list_price = price + discount
        markup = list_price - cost - fee
    below_cost = price < cost
    if below_cost and enforce and not params.allow_subsidy:
        raise PricingBlockedError(cost=cost.kobo, price=price.kobo)
    profit_base = max(Money(0), price - cost)
    referral = _bps(profit_base, params.referral_bps) if referral_applicable else Money(0)
    gross = price - cost
    margin = (Decimal(gross.kobo) * 100 / Decimal(price.kobo)).quantize(Decimal("0.01"), ROUND_HALF_EVEN) \
        if price.kobo else Decimal("0.00")
    return PriceBreakdown(cost, markup, fee, list_price, discount, price, referral, processing_cost,
                          list_price - cost, gross, gross - referral - processing_cost, margin, capped, below_cost)


def compute_scaled(unit_cost: Money, params: RuleParams, *, quantity: int, face: Money | None = None,
                   referral_applicable: bool = False, enforce: bool = True) -> PriceBreakdown:
    """Price ONE unit exactly as `compute` does (rounding, caps, margin protection), then multiply every
    component by the quantity, so per-unit rules (e.g. a fixed markup) stay per unit."""
    u = compute(unit_cost, params, face=face, referral_applicable=referral_applicable, enforce=enforce)
    if quantity == 1:
        return u
    t = lambda m: m.times(quantity)  # noqa: E731
    return PriceBreakdown(t(u.cost), t(u.markup), t(u.fee), t(u.list_price), t(u.discount), t(u.customer_price),
                          t(u.referral_commission), t(u.processing_cost), t(u.gross_profit_before_discount),
                          t(u.gross_profit), t(u.net_contribution), u.margin_pct, u.capped, u.below_cost)
