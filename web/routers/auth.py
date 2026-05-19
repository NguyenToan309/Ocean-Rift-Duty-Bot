"""
auth.py — Discord OAuth2 + JWT + 2FA (TOTP)
Luồng: user click Login → redirect Discord → callback → issue JWT
2FA: sau khi login thành công, nếu user có 2FA thì yêu cầu nhập OTP

Security notes:
- OAuth2 state lưu in-memory với TTL 5 phút (đủ cho single-process local)
- JWT dùng HS256 với SECRET_KEY từ .env
- 2fa_pending token bị blacklist ngay sau khi dùng thành công (prevent reuse)
- Refresh token dùng samesite=strict để ngăn CSRF trên POST endpoint
- Cookie HttpOnly + Secure (khi không phải DEBUG)
"""
import secrets
import logging
from datetime import datetime, timedelta, timezone

import httpx
import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from jose import jwt, JWTError

from models.base import get_db
from models.user import User
from models.audit_log import AuditLog, AuditAction
from models.token_blacklist import BlacklistedToken
from bot.config import settings
from bot.utils.time_utils import utcnow
from web.middleware.rate_limit import limiter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

DISCORD_API = "https://discord.com/api/v10"
ALGORITHM = "HS256"

# State param chống CSRF trong OAuth2 flow.
# Lưu in-memory với TTL 5 phút — đủ cho single-process (local/single-worker).
#
# ⚠️ MULTI-WORKER WARNING: Nếu chạy uvicorn với --workers N > 1, state bị split
# giữa các worker → request /auth/login sang worker A, callback rơi worker B
# → state miss → CSRF rejection. Production multi-worker phải dùng Redis:
#
#   import redis.asyncio as redis
#   _redis = redis.from_url(settings.REDIS_URL)
#   await _redis.setex(f"oauth_state:{state}", 300, "1")
#   exists = await _redis.delete(f"oauth_state:{state}")  # one-time use
#
# Hiện tại (local/single-worker) → dict in-memory đủ dùng.
_OAUTH_STATE_TTL_SECONDS = 300
_oauth_states: dict[str, datetime] = {}  # state -> created_at (aware UTC)


def _store_oauth_state(state: str) -> None:
    """Lưu state với timestamp tạo, đồng thời dọn các state hết hạn"""
    now = utcnow()
    cutoff = now - timedelta(seconds=_OAUTH_STATE_TTL_SECONDS)
    expired = [s for s, ts in _oauth_states.items() if ts < cutoff]
    for s in expired:
        _oauth_states.pop(s, None)
    _oauth_states[state] = now


def _consume_oauth_state(state: str) -> bool:
    """Validate + xóa state (one-time use). Trả True nếu hợp lệ và còn hạn."""
    ts = _oauth_states.pop(state, None)
    if ts is None:
        return False
    return (utcnow() - ts).total_seconds() < _OAUTH_STATE_TTL_SECONDS


def _create_token(payload: dict, expire_delta: timedelta) -> str:
    data = payload.copy()
    data["exp"] = utcnow() + expire_delta
    data["jti"] = secrets.token_hex(16)
    return jwt.encode(data, settings.SECRET_KEY, algorithm=ALGORITHM)


def create_access_token(user_id: int, username: str) -> str:
    return _create_token(
        {"sub": str(user_id), "username": username, "type": "access"},
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def create_refresh_token(user_id: int) -> str:
    return _create_token(
        {"sub": str(user_id), "type": "refresh"},
        timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )


async def decode_token(token: str, session: AsyncSession, expected_type: str = "access") -> dict:
    """Decode và validate JWT, kiểm tra blacklist"""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Token không hợp lệ: {e}")

    if payload.get("type") != expected_type:
        raise HTTPException(status_code=401, detail="Sai loại token")

    jti = payload.get("jti")
    if jti:
        bl = await session.execute(
            select(BlacklistedToken).where(BlacklistedToken.jti == jti)
        )
        if bl.scalar_one_or_none():
            raise HTTPException(status_code=401, detail="Token đã bị thu hồi")

    return payload


@router.get("/login")
@limiter.limit("5/minute")
async def login(request: Request):
    """Khởi tạo OAuth2 flow — redirect sang Discord"""
    state = secrets.token_hex(16)
    _store_oauth_state(state)

    discord_url = (
        f"{DISCORD_API.replace('/api/v10', '')}/oauth2/authorize"
        f"?client_id={settings.DISCORD_CLIENT_ID}"
        f"&redirect_uri={settings.DISCORD_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope=identify"
        f"&state={state}"
    )
    return RedirectResponse(discord_url)


@router.get("/callback")
@limiter.limit("10/minute")
async def oauth_callback(
    request: Request,
    code: str,
    state: str,
    session: AsyncSession = Depends(get_db),
):
    """Nhận code từ Discord → lấy user info → issue JWT"""
    # Validate state chống CSRF (one-time use, TTL 5 phút)
    if not _consume_oauth_state(state):
        raise HTTPException(
            status_code=400,
            detail="State không hợp lệ hoặc đã hết hạn. Vui lòng thử đăng nhập lại."
        )

    # Đổi code lấy access token Discord
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            f"{DISCORD_API.replace('/api/v10', '')}/api/oauth2/token",
            data={
                "client_id": settings.DISCORD_CLIENT_ID,
                "client_secret": settings.DISCORD_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.DISCORD_REDIRECT_URI,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    if token_resp.status_code != 200:
        raise HTTPException(status_code=400, detail="Không lấy được token Discord")

    discord_token = token_resp.json()["access_token"]

    # Lấy thông tin user từ Discord
    async with httpx.AsyncClient() as client:
        user_resp = await client.get(
            f"{DISCORD_API}/users/@me",
            headers={"Authorization": f"Bearer {discord_token}"},
        )

    if user_resp.status_code != 200:
        raise HTTPException(status_code=400, detail="Không lấy được thông tin user")

    discord_user = user_resp.json()
    discord_id = int(discord_user["id"])
    username = discord_user["username"]
    ip = request.client.host if request.client else "unknown"

    # Tìm hoặc tạo user trong DB
    result = await session.execute(select(User).where(User.discord_id == discord_id))
    user = result.scalar_one_or_none()

    avatar = discord_user.get("avatar")
    avatar_url = (
        f"https://cdn.discordapp.com/avatars/{discord_id}/{avatar}.png"
        if avatar else None
    )

    if user is None:
        user = User(
            discord_id=discord_id,
            username=username,
            discriminator=discord_user.get("discriminator"),
            avatar_url=avatar_url,
            created_at=utcnow(),
        )
        session.add(user)
    else:
        user.avatar_url = avatar_url  # Update avatar nếu thay đổi

    # Kiểm tra lockout
    if user.is_locked():
        session.add(AuditLog(
            guild_id=None, user_id=discord_id, username=username,
            action=AuditAction.LOGIN_FAILED,
            detail={"reason": "account_locked"},
            ip_address=ip,
            created_at=utcnow(),
        ))
        await session.commit()
        raise HTTPException(
            status_code=403,
            detail="Tài khoản tạm thời bị khóa do đăng nhập sai nhiều lần. Thử lại sau 30 phút."
        )

    user.username = username
    user.last_login_ip = ip

    # Nếu user có 2FA, set cookie 2fa_pending HttpOnly + redirect về login page
    # Frontend đọc URL flag ?require_2fa=1 → mở modal nhập OTP → POST /auth/verify-2fa
    # (cookie 2fa_pending tự gửi, không cần truyền token qua URL → tránh leak qua Referer)
    if user.is_2fa_enabled:
        temp_token = _create_token(
            {"sub": str(discord_id), "username": username, "type": "2fa_pending"},
            timedelta(minutes=5),
        )
        await session.commit()
        response = RedirectResponse(url="/?require_2fa=1", status_code=302)
        response.set_cookie(
            "2fa_pending",
            temp_token,
            httponly=True,
            samesite="lax",
            secure=not settings.DEBUG,
            max_age=300,  # 5 phút — khớp TTL của temp_token
        )
        return response

    user.last_login_at = utcnow()
    user.failed_login_attempts = 0

    session.add(AuditLog(
        guild_id=None, user_id=discord_id, username=username,
        action=AuditAction.LOGIN_SUCCESS,
        ip_address=ip,
        detail={},
        created_at=utcnow(),
    ))
    await session.commit()

    access_token = create_access_token(discord_id, username)
    refresh_token = create_refresh_token(discord_id)

    # Set cookie + redirect về dashboard
    # samesite="lax": cookie được gửi khi redirect từ Discord (cross-site GET redirect)
    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie(
        "access_token", access_token,
        httponly=True, samesite="lax", secure=not settings.DEBUG
    )
    response.set_cookie(
        "refresh_token", refresh_token,
        httponly=True, samesite="strict", secure=not settings.DEBUG
    )
    return response


@router.post("/verify-2fa")
@limiter.limit("5/minute")
async def verify_2fa(
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    """
    Xác minh OTP 2FA sau khi login.
    Sau khi verify thành công, temp_token bị blacklist ngay để ngăn reuse.
    """
    body = await request.json()
    # Lấy temp_token từ HttpOnly cookie (an toàn hơn URL/body) — fallback body cho backward compat
    temp_token = request.cookies.get("2fa_pending") or body.get("temp_token")
    otp_code = body.get("otp_code", "").strip()

    if not temp_token or not otp_code:
        raise HTTPException(status_code=400, detail="Thiếu temp_token hoặc otp_code")

    payload = await decode_token(temp_token, session, expected_type="2fa_pending")
    discord_id = int(payload["sub"])
    username = payload["username"]
    ip = request.client.host if request.client else "unknown"

    result = await session.execute(select(User).where(User.discord_id == discord_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User không tồn tại")

    # Verify OTP
    totp_secret = user.get_totp_secret()
    if not totp_secret:
        raise HTTPException(status_code=400, detail="2FA chưa được thiết lập")

    totp = pyotp.TOTP(totp_secret)
    if not totp.verify(otp_code, valid_window=1):  # ±30 giây drift
        user.failed_login_attempts = (user.failed_login_attempts or 0) + 1

        if user.failed_login_attempts >= 5:
            user.locked_until = utcnow() + timedelta(minutes=30)
            session.add(AuditLog(
                guild_id=None, user_id=discord_id, username=username,
                action=AuditAction.ACCOUNT_LOCKED,
                ip_address=ip, detail={"reason": "too_many_2fa_failures"},
                created_at=utcnow(),
            ))

        session.add(AuditLog(
            guild_id=None, user_id=discord_id, username=username,
            action=AuditAction.LOGIN_2FA_FAILED,
            ip_address=ip, detail={},
            created_at=utcnow(),
        ))
        await session.commit()
        raise HTTPException(status_code=401, detail="Mã OTP không đúng")

    # ── OTP hợp lệ — blacklist temp_token ngay để ngăn reuse ──
    jti = payload.get("jti")
    if jti:
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        session.add(BlacklistedToken(
            jti=jti,
            user_id=discord_id,
            expires_at=exp,
            blacklisted_at=utcnow(),
        ))

    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = utcnow()
    user.last_login_ip = ip

    session.add(AuditLog(
        guild_id=None, user_id=discord_id, username=username,
        action=AuditAction.LOGIN_SUCCESS,
        ip_address=ip, detail={"method": "2fa"},
        created_at=utcnow(),
    ))
    await session.commit()

    access_token = create_access_token(discord_id, username)
    refresh_token = create_refresh_token(discord_id)

    response = JSONResponse({"message": "Đăng nhập thành công", "username": username})
    response.set_cookie(
        "access_token", access_token,
        httponly=True, samesite="lax", secure=not settings.DEBUG
    )
    response.set_cookie(
        "refresh_token", refresh_token,
        httponly=True, samesite="strict", secure=not settings.DEBUG
    )
    # Xoá cookie 2fa_pending sau khi đã verify thành công
    response.delete_cookie("2fa_pending")
    return response


@router.post("/logout")
async def logout(request: Request, session: AsyncSession = Depends(get_db)):
    """Thu hồi access + refresh token, xóa cookie"""
    access_token = request.cookies.get("access_token")
    refresh_token = request.cookies.get("refresh_token")

    for token in [access_token, refresh_token]:
        if not token:
            continue
        try:
            # verify_exp=False để vẫn blacklist được token đã hết hạn — bảo vệ
            # trường hợp clock skew hoặc user logout đúng lúc token vừa expire.
            payload = jwt.decode(
                token, settings.SECRET_KEY, algorithms=[ALGORITHM],
                options={"verify_exp": False},
            )
            jti = payload.get("jti")
            exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
            if jti:
                session.add(BlacklistedToken(
                    jti=jti,
                    user_id=int(payload["sub"]),
                    expires_at=exp,
                    blacklisted_at=utcnow(),
                ))
        except JWTError:
            pass

    await session.commit()
    response = JSONResponse({"message": "Đã đăng xuất"})
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")
    return response


@router.post("/refresh")
async def refresh_token(request: Request, session: AsyncSession = Depends(get_db)):
    """Cấp access token mới từ refresh token còn hạn"""
    refresh = request.cookies.get("refresh_token")
    if not refresh:
        raise HTTPException(status_code=401, detail="Không tìm thấy refresh token")

    payload = await decode_token(refresh, session, expected_type="refresh")
    discord_id = int(payload["sub"])

    result = await session.execute(select(User).where(User.discord_id == discord_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User không tồn tại")

    new_access = create_access_token(discord_id, user.username)
    response = JSONResponse({"message": "Token đã được làm mới"})
    response.set_cookie(
        "access_token", new_access,
        httponly=True, samesite="lax", secure=not settings.DEBUG
    )
    return response
