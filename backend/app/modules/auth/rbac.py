from enum import StrEnum

from app.modules.users.models import Role


class Permission(StrEnum):
    USERS_READ = "users.read"
    USERS_MANAGE = "users.manage"
    TRANSACTIONS_READ = "transactions.read"
    TICKETS_MANAGE = "tickets.manage"
    REFUND_REQUEST = "refund.request"
    REFUND_APPROVE = "refund.approve"
    LEDGER_ADJUST = "ledger.adjust"
    PROVIDERS_MANAGE = "providers.manage"
    AUDIT_READ = "audit.read"
    FRAUD_REVIEW = "fraud.review"
    RECONCILIATION_RUN = "reconciliation.run"
    ROLES_ASSIGN = "roles.assign"
    TRANSACTIONS_RESOLVE = "transactions.resolve"
    PRICING_MANAGE = "pricing.manage"
    PRICING_SUBSIDY = "pricing.subsidy"          # may approve selling below provider cost
    FINANCE_PROFIT_READ = "finance.profit.read"  # provider costs, margins, profit: never exposed to users

P = Permission

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.USER: frozenset(),
    Role.SUPPORT: frozenset({P.USERS_READ, P.TRANSACTIONS_READ, P.TICKETS_MANAGE}),
    Role.FINANCE: frozenset({P.TRANSACTIONS_READ, P.REFUND_REQUEST, P.REFUND_APPROVE,
                             P.RECONCILIATION_RUN, P.TRANSACTIONS_RESOLVE, P.PRICING_MANAGE,
                             P.FINANCE_PROFIT_READ}),
    # ADMIN deliberately lacks refund approval and ledger adjustment.
    Role.ADMIN: frozenset({P.USERS_READ, P.USERS_MANAGE, P.TRANSACTIONS_READ, P.TICKETS_MANAGE, P.REFUND_REQUEST,
                           P.PROVIDERS_MANAGE, P.AUDIT_READ, P.FRAUD_REVIEW}),
    Role.SUPER_ADMIN: frozenset(Permission),
}


def has_permission(role: str, permission: Permission) -> bool:
    try:
        return permission in ROLE_PERMISSIONS[Role(role)]
    except (ValueError, KeyError):
        return False
