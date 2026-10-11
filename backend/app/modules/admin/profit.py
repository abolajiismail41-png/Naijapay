from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.money import Money
from app.modules.ledger import interface as ledger
from app.modules.ledger.interface import SystemAccount


LAGOS = ZoneInfo("Africa/Lagos")

# Only whitelisted SQL fragments may be interpolated.
GROUPS = {
    "service": "t.service_type",
    "provider": "t.provider_code",
    "network": "COALESCE(a.network, d.network, 'n/a')",
    "disco": "COALESCE(e.disco_code, 'n/a')",
    "product": "COALESCE(ed.product_code, 'n/a')",
    "date": (
        "to_char("
        "timezone('Africa/Lagos', t.completed_at), "
        "'YYYY-MM-DD'"
        ")"
    ),
}

_SALES = """
SELECT {g} AS grp,
       count(*) AS n,
       COALESCE(sum(s.list_price_kobo), 0) AS revenue,
       COALESCE(sum(t.provider_cost_kobo), 0) AS cost,
       COALESCE(sum(s.discount_kobo), 0) AS discounts,
       COALESCE(sum(s.referral_commission_kobo), 0) AS referral,
       COALESCE(sum(t.price_kobo), 0) AS customer_paid
FROM transactions t
JOIN pricing_snapshots s
  ON s.transaction_id = t.id
LEFT JOIN airtime_orders a
  ON a.transaction_id = t.id
LEFT JOIN data_orders d
  ON d.transaction_id = t.id
LEFT JOIN electricity_orders e
  ON e.transaction_id = t.id
LEFT JOIN education_orders ed
  ON ed.transaction_id = t.id
WHERE t.status = 'SUCCESSFUL'
  AND t.completed_at >= :start
  AND t.completed_at < :end
GROUP BY grp
ORDER BY grp
"""


def period(
    start: date | None,
    end: date | None,
) -> tuple[datetime, datetime]:
    """Return a half-open reporting period in Africa/Lagos time."""
    d0 = start or datetime.now(LAGOS).date()
    d1 = (end or d0) + timedelta(days=1)

    return (
        datetime.combine(d0, time.min, LAGOS),
        datetime.combine(d1, time.min, LAGOS),
    )


def _as_kobo(value: Any) -> int:
    """Normalize a database monetary value to exact integer kobo."""
    if value is None:
        return 0

    if isinstance(value, bool):
        raise TypeError("Money amount cannot be a boolean")

    if isinstance(value, int):
        return value

    try:
        amount = Decimal(str(value))
    except Exception as exc:
        raise TypeError(
            f"Invalid monetary value: {value!r}"
        ) from exc

    if not amount.is_finite():
        raise ValueError(
            f"Money amount must be finite, got {value!r}"
        )

    if amount != amount.to_integral_value():
        raise ValueError(
            f"Money amount must be a whole number of kobo, "
            f"got {value!r}"
        )

    return int(amount)


def _pct(num: int, den: int) -> str:
    """Calculate a percentage using deterministic decimal arithmetic."""
    if not den:
        return "0.00"

    percentage = (
        Decimal(num) * Decimal(100) / Decimal(den)
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_EVEN,
    )

    return str(percentage)


def _money(k: Any) -> dict[str, Any]:
    """Serialize money without weakening Money's invariants."""
    money = Money(_as_kobo(k))

    return {
        "kobo": money.kobo,
        "naira": money.naira_str(),
    }


def _block(
    row: Any,
    reversal_loss: Any = 0,
) -> dict[str, Any]:
    """Build a profit-report block using integer kobo."""
    revenue = _as_kobo(row.revenue)
    cost = _as_kobo(row.cost)
    discounts = _as_kobo(row.discounts)
    referral = _as_kobo(row.referral)
    customer_paid = _as_kobo(row.customer_paid)
    reversal_loss_kobo = _as_kobo(reversal_loss)

    gross_profit = revenue - cost
    net_contribution = (
        gross_profit
        - discounts
        - referral
        - reversal_loss_kobo
    )

    return {
        "transactions": int(row.n),
        "transaction_volume": _money(revenue),
        "customer_paid": _money(customer_paid),
        "provider_cost": _money(cost),
        "gross_revenue": _money(revenue),
        "gross_profit": _money(gross_profit),
        "discounts": _money(discounts),
        "referral_commissions": _money(referral),
        "refunds_reversals_loss": _money(reversal_loss_kobo),
        "net_contribution": _money(net_contribution),
        "gross_margin_pct": _pct(gross_profit, revenue),
        "net_margin_pct": _pct(net_contribution, revenue),
    }


@dataclass(frozen=True)
class Check:
    name: str
    expected: int
    actual: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "check": self.name,
            "expected_kobo": self.expected,
            "actual_kobo": self.actual,
            "diff_kobo": self.actual - self.expected,
            "ok": self.expected == self.actual,
        }


async def profit_report(
    db: AsyncSession,
    start: date | None,
    end: date | None,
    group_by: str | None,
) -> dict[str, Any]:
    """Build the profit report for the requested Lagos-local date range."""
    if group_by is not None and group_by not in GROUPS:
        raise ValueError(
            f"Unsupported group_by value: {group_by!r}"
        )

    t0, t1 = period(start, end)
    args = {"start": t0, "end": t1}

    total = (
        await db.execute(
            text(_SALES.format(g="'all'")),
            args,
        )
    ).first()

    zero = type(
        "ZeroProfitRow",
        (),
        {
            "n": 0,
            "revenue": 0,
            "cost": 0,
            "discounts": 0,
            "referral": 0,
            "customer_paid": 0,
        },
    )()

    loss = (
        await db.execute(
            text(
                """
                SELECT COALESCE(sum(provider_cost_kobo), 0)
                FROM transactions
                WHERE status = 'REVERSED'
                  AND completed_at >= :start
                  AND completed_at < :end
                """
            ),
            args,
        )
    ).scalar_one()

    refunded = (
        await db.execute(
            text(
                """
                SELECT count(*),
                       COALESCE(sum(price_kobo), 0)
                FROM transactions
                WHERE status = 'REFUNDED'
                  AND completed_at >= :start
                  AND completed_at < :end
                """
            ),
            args,
        )
    ).one()

    fees = (
        await db.execute(
            text(
                """
                SELECT COALESCE(
                    SUM(
                        CASE e.direction
                            WHEN 'C' THEN e.amount_kobo
                            ELSE -e.amount_kobo
                        END
                    ),
                    0
                )
                FROM ledger_entries e
                JOIN ledger_accounts a
                  ON a.id = e.account_id
                WHERE a.code = :code
                  AND e.created_at >= :start
                  AND e.created_at < :end
                """
            ),
            {
                **args,
                "code": SystemAccount.FEES.value,
            },
        )
    ).scalar_one()

    out: dict[str, Any] = {
        "period": {
            "from": t0.date().isoformat(),
            "to": (t1 - timedelta(days=1)).date().isoformat(),
            "timezone": "Africa/Lagos",
        },
        "totals": _block(total or zero, _as_kobo(loss)),
        "not_in_profit": {
            "failed_and_refunded_transactions": int(refunded[0]),
            "failed_and_refunded_value": _money(
                _as_kobo(refunded[1])
            ),
        },
        "funding_fee_income": _money(_as_kobo(fees)),
        "payment_processing_cost": None,
        "payment_processing_cost_note": (
            "Not recorded until external Paystack "
            "settlement reconciliation is integrated."
        ),
    }

    if group_by is not None:
        rows = (
            await db.execute(
                text(_SALES.format(g=GROUPS[group_by])),
                args,
            )
        ).all()

        out["group_by"] = group_by
        out["groups"] = [
            {"key": row.grp, **_block(row)}
            for row in rows
        ]

    return out


async def ledger_checks(
    db: AsyncSession,
) -> list[dict[str, Any]]:
    """Check ledger invariants against business records."""

    async def one(sql: str) -> Any:
        return await db.execute(text(sql))

    wallets = (
        await one(
            """
            SELECT COALESCE(sum(balance_kobo), 0)
            FROM wallets
            """
        )
    ).scalar_one()

    held = (
        await one(
            """
            SELECT COALESCE(sum(price_kobo), 0)
            FROM transactions
            WHERE status IN ('PENDING', 'PROCESSING', 'UNKNOWN')
            """
        )
    ).scalar_one()

    sales = (
        await one(
            """
            SELECT COALESCE(
                sum(s.list_price_kobo - s.fee_kobo), 0
            )
            FROM transactions t
            JOIN pricing_snapshots s
              ON s.transaction_id = t.id
            WHERE t.status = 'SUCCESSFUL'
            """
        )
    ).scalar_one()

    svc_fees = (
        await one(
            """
            SELECT COALESCE(sum(s.fee_kobo), 0)
            FROM transactions t
            JOIN pricing_snapshots s
              ON s.transaction_id = t.id
            WHERE t.status = 'SUCCESSFUL'
            """
        )
    ).scalar_one()

    cost = (
        await one(
            """
            SELECT COALESCE(sum(provider_cost_kobo), 0)
            FROM transactions
            WHERE status = 'SUCCESSFUL'
            """
        )
    ).scalar_one()

    acct = {
        account: await ledger.system_account_id(db, account)
        for account in SystemAccount
    }

    async def net(account: SystemAccount) -> int:
        return await ledger.account_net_credit(db, acct[account])

    return [
        check.as_dict()
        for check in (
            Check(
                "customer wallets: ledger vs cached balances",
                _as_kobo(wallets),
                _as_kobo(await ledger.owned_accounts_net_credit(db)),
            ),
            Check(
                "held funds in provider clearing vs open transactions",
                _as_kobo(held),
                _as_kobo(await net(SystemAccount.PROVIDER_CLEARING)),
            ),
            Check(
                "sales revenue vs settled transactions",
                _as_kobo(sales),
                _as_kobo(await net(SystemAccount.REVENUE)),
            ),
            Check(
                "service fee income vs settled transactions",
                _as_kobo(svc_fees),
                _as_kobo(await net(SystemAccount.SERVICE_FEES)),
            ),
            Check(
                "provider cost expense vs settled transactions",
                _as_kobo(cost),
                -_as_kobo(await net(SystemAccount.PROVIDER_COST)),
            ),
            Check(
                "ledger trial balance",
                0,
                _as_kobo(await ledger.trial_balance_diff(db)),
            ),
        )
    ]