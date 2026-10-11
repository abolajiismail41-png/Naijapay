from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, StringConstraints
from typing import Annotated
from sqlalchemy import select
from app.core.errors import ConflictError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, ok
from app.modules.auth.deps import Principal, current_principal
from app.modules.users.models import Credential, User

router = APIRouter(prefix="/api/v1/users", tags=["users"])


class EmailIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: Annotated[str, StringConstraints(min_length=5, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")]


@router.get("/me")
async def me(principal: Principal = Depends(current_principal),
             db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    cred = await db.get(Credential, principal.user.id)
    u = principal.user
    return ok({"id": str(u.id), "phone": u.phone, "full_name": u.full_name, "email": u.email, "role": u.role,
               "has_pin": bool(cred and cred.pin_hash)})


@router.put("/me/email")
async def update_email(body: EmailIn, principal: Principal = Depends(current_principal),
                       db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    email = body.email.strip().lower()
    existing = (await db.execute(select(User.id)
                                 .where(User.email == email, User.id != principal.user.id))).scalar_one_or_none()
    if existing is not None:
        raise ConflictError("That email address is already linked to another account.")
    principal.user.email = email
    await db.commit()
    return ok({"email": email}, "Email address saved.")
