import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, Request, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.deps import client_ip, get_app_settings, get_db, get_redis, ok
from app.modules.auth import schemas as s
from app.modules.auth.deps import Principal, current_principal
from app.modules.auth.otp_sender import build_otp_sender
from app.modules.auth.pin import PinService
from app.modules.auth.service import AuthService, ClientContext

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _auth(db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis),
          settings: Settings = Depends(get_app_settings)) -> AuthService:
    return AuthService(db, redis, settings, build_otp_sender(settings, redis))


def _pin(db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis),
         settings: Settings = Depends(get_app_settings)) -> PinService:
    return PinService(db, redis, settings)


def _ctx(request: Request, x_device_label: str | None = Header(default=None)) -> ClientContext:
    return ClientContext(ip=client_ip(request), user_agent=request.headers.get("user-agent"),
                         device_label=x_device_label)


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(body: s.RegisterIn, svc: AuthService = Depends(_auth),
                   ctx: ClientContext = Depends(_ctx)) -> dict[str, Any]:
    tokens = await svc.register(body.phone, body.password, body.full_name, body.email, ctx, body.referral_code)
    return ok(tokens, "Account created. You are now signed in.")


@router.post("/phone/verification/request", status_code=status.HTTP_202_ACCEPTED)
async def request_phone_verification(p: Principal = Depends(current_principal),
                                     svc: AuthService = Depends(_auth),
                                     ctx: ClientContext = Depends(_ctx)) -> dict[str, Any]:
    await svc.request_phone_verification(p.user, ctx)
    return ok(message="If verification is needed, a code has been sent.")


@router.post("/verify-phone")
async def verify_phone(body: s.VerifyPhoneIn, svc: AuthService = Depends(_auth),
                       ctx: ClientContext = Depends(_ctx)) -> dict[str, Any]:
    return ok(await svc.verify_phone(body.phone, body.code, ctx), "Phone verified.")


@router.post("/login")
async def login(body: s.LoginIn, svc: AuthService = Depends(_auth),
                ctx: ClientContext = Depends(_ctx)) -> dict[str, Any]:
    return ok(await svc.login(body.phone, body.password, ctx))


@router.post("/refresh")
async def refresh(body: s.RefreshIn, svc: AuthService = Depends(_auth),
                  ctx: ClientContext = Depends(_ctx)) -> dict[str, Any]:
    return ok(await svc.refresh(body.refresh_token, ctx))


@router.post("/logout")
async def logout(p: Principal = Depends(current_principal), svc: AuthService = Depends(_auth),
                 ctx: ClientContext = Depends(_ctx)) -> dict[str, Any]:
    await svc.logout(p.user.id, p.family_id, ctx)
    return ok(message="Signed out.")


@router.get("/sessions")
async def sessions(p: Principal = Depends(current_principal),
                   svc: AuthService = Depends(_auth)) -> dict[str, Any]:
    return ok(await svc.list_sessions(p.user.id, p.family_id))


@router.delete("/sessions/{session_id}")
async def revoke_session(session_id: uuid.UUID, p: Principal = Depends(current_principal),
                         svc: AuthService = Depends(_auth),
                         ctx: ClientContext = Depends(_ctx)) -> dict[str, Any]:
    await svc.revoke_session(p.user.id, session_id, ctx)
    return ok(message="Session ended.")


@router.post("/password/reset/request", status_code=status.HTTP_202_ACCEPTED)
async def reset_request(body: s.ResetRequestIn, svc: AuthService = Depends(_auth),
                        ctx: ClientContext = Depends(_ctx)) -> dict[str, Any]:
    await svc.request_password_reset(body.phone, ctx)
    return ok(message="If the number is registered, a reset code has been sent.")


@router.post("/password/reset/confirm")
async def reset_confirm(body: s.ResetConfirmIn, svc: AuthService = Depends(_auth),
                        ctx: ClientContext = Depends(_ctx)) -> dict[str, Any]:
    await svc.confirm_password_reset(body.phone, body.code, body.new_password, ctx)
    return ok(message="Password updated. Please sign in again.")


@router.post("/pin/set")
async def set_pin(body: s.SetPinIn, p: Principal = Depends(current_principal),
                  svc: PinService = Depends(_pin), ctx: ClientContext = Depends(_ctx)) -> dict[str, Any]:
    await svc.set_pin(p.user, body.password, body.pin, ctx.ip)
    return ok(message="Transaction PIN set.")


@router.post("/pin/change")
async def change_pin(body: s.ChangePinIn, p: Principal = Depends(current_principal),
                     svc: PinService = Depends(_pin), ctx: ClientContext = Depends(_ctx)) -> dict[str, Any]:
    await svc.change_pin(p.user, body.current_pin, body.new_pin, ctx.ip)
    return ok(message="Transaction PIN changed.")


@router.post("/pin/verify")
async def verify_pin(body: s.VerifyPinIn, p: Principal = Depends(current_principal),
                     svc: PinService = Depends(_pin), ctx: ClientContext = Depends(_ctx)) -> dict[str, Any]:
    token = await svc.verify_pin(p.user, body.pin, ctx.ip)
    return ok({"pin_token": token})
