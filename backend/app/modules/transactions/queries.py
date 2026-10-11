from typing import Any

from sqlalchemy import Select, select

from app.modules.transactions.models import AirtimeOrder, DataOrder, EducationOrder, ElectricityOrder, TVOrder, Transaction


def with_orders() -> Select[Any]:
    """Transaction plus whichever service-specific order row it has (at most one is non-null)."""
    return (select(Transaction, AirtimeOrder, DataOrder, ElectricityOrder, EducationOrder, TVOrder)
            .outerjoin(AirtimeOrder, AirtimeOrder.transaction_id == Transaction.id)
            .outerjoin(DataOrder, DataOrder.transaction_id == Transaction.id)
            .outerjoin(ElectricityOrder, ElectricityOrder.transaction_id == Transaction.id)
            .outerjoin(EducationOrder, EducationOrder.transaction_id == Transaction.id)
            .outerjoin(TVOrder, TVOrder.transaction_id == Transaction.id))


def order_of(row: Any) -> Any:
    return row[1] or row[2] or row[3] or row[4] or row[5]
