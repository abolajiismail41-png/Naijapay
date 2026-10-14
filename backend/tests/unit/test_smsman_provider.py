from decimal import Decimal
import pytest
from app.modules.virtual_numbers.provider import SMSManError, provider_cost_to_kobo


def test_provider_cost_conversion_uses_decimal_minor_units() -> None:
    assert provider_cost_to_kobo("0.25", Decimal("1500")) == 37500


def test_provider_cost_conversion_requires_configured_fx() -> None:
    with pytest.raises(SMSManError):
        provider_cost_to_kobo("1", Decimal("0"))


def test_provider_cost_conversion_rejects_non_positive_cost() -> None:
    with pytest.raises(SMSManError):
        provider_cost_to_kobo("0", Decimal("1500"))
