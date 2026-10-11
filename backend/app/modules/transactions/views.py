from typing import Any

from app.core.money import Money
from app.modules.transactions.models import AirtimeOrder, DataOrder, EducationOrder, ElectricityOrder, TVOrder, Transaction
from app.modules.transactions.state import TxnStatus

_DISPLAY: dict[str, tuple[str, str]] = {
    "INITIATED": ("PROCESSING", "Your transaction is being processed."),
    "PENDING": ("PROCESSING", "Your transaction is being processed."),
    "PROCESSING": ("PROCESSING", "Your transaction is being processed. You have not been charged twice."),
    "UNKNOWN": ("PENDING", "We are confirming this with the provider. You have been charged once, and we will "
                           "resolve it for you. Please do not retry."),
    "SUCCESSFUL": ("SUCCESSFUL", "Your purchase was successful."),
    "FAILED": ("FAILED", "This purchase was not successful."),
    "REFUNDED": ("REFUNDED", "This purchase was not successful and your money has been returned to your wallet."),
    "REVERSED": ("REVERSED", "This purchase was reversed."),
}


def mask(value: str) -> str:
    return "*" * max(len(value) - 4, 0) + value[-4:]


def public_view(t: Transaction, o: AirtimeOrder | DataOrder | ElectricityOrder | EducationOrder | TVOrder | None) -> dict[str, Any]:
    """Customer-facing shape. Deliberately has no cost, markup, margin, discount or provider fields."""
    display, message = _DISPLAY[TxnStatus(t.status).value]
    out = {"reference": t.reference, "service": t.service_type, "status": t.status, "display_status": display,
            "message": message, "amount_kobo": t.amount_kobo, "amount": Money(t.amount_kobo).naira_str(),
            "price_kobo": t.price_kobo, "price": Money(t.price_kobo).naira_str(), "currency": t.currency,
            "network": getattr(o, "network", None), "phone": getattr(o, "phone", None),
            "plan": getattr(o, "plan_name", None), "validity": getattr(o, "validity", None) or None,
            "created_at": t.created_at.isoformat(), "completed_at": t.completed_at.isoformat() if t.completed_at else None}
    if isinstance(o, ElectricityOrder):
        out |= {"disco": o.disco_name, "meter_type": o.meter_type, "meter_number": mask(o.meter_number),
                "customer_name": o.customer_name, "token_available": o.token_status == "DELIVERED"}
        if t.status == "SUCCESSFUL" and o.token_status == "MISSING":
            out["message"] = "Your payment was successful. Your token is being retrieved and we will notify you."
    if isinstance(o, TVOrder):
        out |= {"operator": o.operator_name, "product": o.product_name,
                "smartcard_number": mask(o.smartcard_number), "customer_name": o.customer_name,
                "current_bouquet": o.current_bouquet}
    if isinstance(o, EducationOrder):
        out |= {"product": o.product_name, "quantity": o.quantity, "pins_available": o.pins_status in ("DELIVERED", "PARTIAL")}
        if t.status == "SUCCESSFUL" and o.pins_status == "MISSING":
            out["message"] = "Your payment was successful. Your PINs are being retrieved and we will notify you."
        elif t.status == "SUCCESSFUL" and o.pins_status == "PARTIAL":
            out["message"] = "Your payment was successful. Some PINs are ready now; our team is sorting out the rest."
    return out
