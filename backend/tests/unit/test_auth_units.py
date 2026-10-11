from datetime import timedelta

import pytest

from app.core.errors import UnauthorizedError
from app.core.phone import normalize_phone
from app.core.security import decode_token, encode_token, hash_secret, verify_secret
from app.modules.auth.pin import validate_pin_strength
from app.modules.auth.errors import WeakPinError
from app.modules.auth.rbac import ROLE_PERMISSIONS, Permission, has_permission
from app.modules.users.models import Role


@pytest.mark.parametrize("raw", ["08031234567", "+2348031234567", "2348031234567", "0803 123 4567"])
def test_phone_normalisation(raw: str) -> None:
    assert normalize_phone(raw) == "+2348031234567"


@pytest.mark.parametrize("raw", ["", "12345", "0603123456", "+1555123456", "080312345678", 123])
def test_phone_rejects_invalid(raw: object) -> None:
    with pytest.raises(ValueError):
        normalize_phone(raw)


async def test_hash_and_verify_with_dummy_path() -> None:
    h = await hash_secret("secret-value")
    assert h.startswith("$argon2id$")
    assert await verify_secret(h, "secret-value") and not await verify_secret(h, "other")
    assert not await verify_secret(None, "anything")


def test_token_type_confusion_rejected() -> None:
    tok = encode_token("k" * 32, "pin", "u1", timedelta(minutes=1))
    assert decode_token("k" * 32, tok, "pin")["sub"] == "u1"
    with pytest.raises(UnauthorizedError):
        decode_token("k" * 32, tok, "access")
    with pytest.raises(UnauthorizedError):
        decode_token("z" * 32, tok, "pin")


def test_rbac_matrix() -> None:
    assert not ROLE_PERMISSIONS[Role.USER]
    assert not has_permission("ADMIN", Permission.REFUND_APPROVE)
    assert not has_permission("ADMIN", Permission.LEDGER_ADJUST)
    assert has_permission("FINANCE", Permission.REFUND_APPROVE)
    assert not has_permission("FINANCE", Permission.PROVIDERS_MANAGE)
    assert not has_permission("NOT_A_ROLE", Permission.USERS_READ)
    for perm in (Permission.PRICING_MANAGE, Permission.FINANCE_PROFIT_READ, Permission.TRANSACTIONS_RESOLVE):
        assert has_permission("FINANCE", perm) and has_permission("SUPER_ADMIN", perm)
        assert not has_permission("ADMIN", perm) and not has_permission("SUPPORT", perm) and not has_permission("USER", perm)
    assert has_permission("SUPER_ADMIN", Permission.PRICING_SUBSIDY) and not has_permission("FINANCE", Permission.PRICING_SUBSIDY)
    held = set().union(*ROLE_PERMISSIONS.values())
    assert held == set(Permission)


@pytest.mark.parametrize("pin", ["1111", "1234", "4321", "0123"])
def test_weak_pins(pin: str) -> None:
    with pytest.raises(WeakPinError):
        validate_pin_strength(pin)


def test_strong_pin_ok() -> None:
    validate_pin_strength("4821")
