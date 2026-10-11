import httpx

from app.core.config import Settings
from app.modules.providers.base import BillProvider
from app.modules.providers.inlomax import InlomaxProvider
from app.modules.providers.sandbox import SandboxBillProvider


def build_bill_providers(settings: Settings, client: httpx.AsyncClient) -> dict[str, BillProvider]:
    """Registry keyed by the provider code stored on provider_prices / transactions."""
    if settings.bill_provider == "inlomax":
        return {"inlomax": InlomaxProvider(
            client, settings.inlomax_api_key.get_secret_value(), settings.inlomax_base_url,
            electricity_path=settings.inlomax_electricity_path, meter_verify_path=settings.inlomax_meter_verify_path)}
    return {"inlomax": SandboxBillProvider()}
