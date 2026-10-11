"""Local development helpers. Refuses to run outside ENVIRONMENT=local/test.

    python -m app.cli seed-dev                      # admin + demo users, sandbox catalogue, demo wallet balance
    python -m app.cli create-user --phone 08011112222 --name "Ada Obi" --password "Str0ng-pass!" --role FINANCE --pin 4821
    python -m app.cli credit --phone 08011112222 --naira 5000
"""
import argparse
import asyncio
import sys
import uuid
from datetime import UTC, datetime

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Environment, get_settings
from app.core.db import make_engine, make_session_factory
from app.core.money import Money
from app.core.phone import normalize_phone
from app.core.security import hash_secret, keyed_digest
from app.modules.education.models import EducationProduct
from app.modules.electricity.sync import sync_electricity
from app.modules.ledger.interface import SystemAccount
from app.modules.providers import build_bill_providers
from app.modules.providers.models import ProviderPrice
from app.modules.providers.prices import sync_costs, sync_data_plans
from app.modules.users.models import Credential, Role, User
from app.modules.wallet.service import WalletService

ADMIN_PHONE, DEMO_PHONE = "08000000001", "08000000002"
ADMIN_PASSWORD, DEMO_PASSWORD, DEMO_PIN = "Admin-pass-1!", "Demo-pass-1!", "4821"


def _guard() -> None:
    if get_settings().environment not in (Environment.LOCAL, Environment.TEST):
        sys.exit("refusing to run: this command is for local development only")


async def create_user(db: AsyncSession, phone: str, name: str, password: str, role: str, pin: str | None) -> User:
    settings, phone = get_settings(), normalize_phone(phone)
    user = (await db.execute(select(User).where(User.phone == phone))).scalar_one_or_none()
    if user is None:
        user = User(phone=phone, full_name=name, role=role, phone_verified_at=datetime.now(UTC))
        db.add(user)
        await db.flush()
        db.add(Credential(user_id=user.id, password_hash=await hash_secret(password)))
    else:
        user.role = role
    cred = await db.get(Credential, user.id)
    if pin and cred is not None and not cred.pin_hash:
        cred.pin_hash = await hash_secret(keyed_digest(settings.encryption_key.get_secret_value(), "pin", str(user.id), pin))
    await db.commit()
    return user


async def credit(db: AsyncSession, phone: str, naira: int) -> None:
    user = (await db.execute(select(User).where(User.phone == normalize_phone(phone)))).scalar_one()
    await WalletService(db).credit(user.id, Money.from_naira(naira), reference=f"dev:credit:{uuid.uuid4().hex}",
                                   kind="dev.credit", source=SystemAccount.PROCESSOR_CLEARING, description="Dev credit")
    await db.commit()


async def seed_catalogue(db: AsyncSession) -> None:
    settings = get_settings()
    if settings.bill_provider != "sandbox":
        sys.exit("seed-catalogue only works with BILL_PROVIDER=sandbox")
    async with httpx.AsyncClient() as client:
        provider = build_bill_providers(settings, client)["inlomax"]
        await sync_costs(db, provider, "inlomax")
        await sync_data_plans(db, provider, "inlomax")
        await sync_electricity(db, provider, "inlomax")
    await db.execute(text("UPDATE data_plans SET listed = true"))
    await db.execute(text("UPDATE electricity_discos SET listed = true"))
    for code, name, sid, cost in (("WAEC", "WAEC Result Checker PIN", "1", 517_000), ("NECO", "NECO Result Checker Token", "2", 220_000)):
        if (await db.execute(select(EducationProduct.id).where(EducationProduct.provider_service_id == sid))).first():
            continue
        db.add(EducationProduct(provider_code="inlomax", code=code, name=name, provider_service_id=sid, listed=True))
        db.add(ProviderPrice(provider_code="inlomax", category="EDUCATION", scope_key=sid, provider_service_id=sid,
                             kind="FIXED_KOBO", value=cost, source="MANUAL", active=True))
    await db.commit()


async def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed-dev")
    cu = sub.add_parser("create-user")
    cu.add_argument("--phone", required=True)
    cu.add_argument("--name", default="Dev User")
    cu.add_argument("--password", required=True)
    cu.add_argument("--role", default="USER", choices=[r.value for r in Role])
    cu.add_argument("--pin")
    cr = sub.add_parser("credit")
    cr.add_argument("--phone", required=True)
    cr.add_argument("--naira", type=int, required=True)
    args = ap.parse_args()
    _guard()
    engine = make_engine(get_settings())
    async with make_session_factory(engine)() as db:
        if args.cmd == "seed-dev":
            await seed_catalogue(db)
            await create_user(db, ADMIN_PHONE, "Local Admin", ADMIN_PASSWORD, Role.SUPER_ADMIN.value, DEMO_PIN)
            await create_user(db, DEMO_PHONE, "Demo Customer", DEMO_PASSWORD, Role.USER.value, DEMO_PIN)
            await credit(db, DEMO_PHONE, 50_000)
            print(f"\nAdmin   {ADMIN_PHONE}  {ADMIN_PASSWORD}  (SUPER_ADMIN, PIN {DEMO_PIN})"
                  f"\nCustomer {DEMO_PHONE}  {DEMO_PASSWORD}  (PIN {DEMO_PIN}, NGN 50,000 wallet)\n")
        elif args.cmd == "create-user":
            u = await create_user(db, args.phone, args.name, args.password, args.role, args.pin)
            print(f"user {u.phone} ready ({u.role})")
        else:
            await credit(db, args.phone, args.naira)
            print("credited")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
