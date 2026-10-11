import httpx

from app.core.config import Settings
from app.modules.payments.processors.base import PaymentProcessor
from app.modules.payments.processors.paystack import PaystackProcessor
from app.modules.payments.processors.sandbox import SandboxProcessor


def build_processor(settings: Settings, client: httpx.AsyncClient) -> PaymentProcessor:
    if settings.payment_processor == "paystack":
        return PaystackProcessor(client, settings.paystack_secret_key.get_secret_value())
    return SandboxProcessor(settings.webhook_secret.get_secret_value())
