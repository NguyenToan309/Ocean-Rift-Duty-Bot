"""
export.py (web) — Download CSV/Excel qua one-time token
Token có TTL 10 phút, dùng 1 lần duy nhất (lưu jti vào blacklist sau khi dùng)
"""
import io
import hmac
import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from jose import jwt, JWTError
from fastapi import Request

from models.base import get_db
from models.duty_log import DutyLog
from models.guild import GuildConfig
from models.token_blacklist import BlacklistedToken
from models.audit_log import AuditLog, AuditAction
from web.middleware.auth_guard import require_auth, require_guild_role
from web.middleware.rate_limit import limiter
from bot.utils.time_utils import get_period_range, get_custom_range, utcnow
from bot.config import settings
from utils.export_utils import logs_to_dataframe, generate_csv_bytes, generate_excel_bytes, sign_file

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/export", tags=["export"])
ALGORITHM = "HS256"

# Whitelist các giá trị an toàn — phòng filename injection
VALID_PERIODS = {"day", "week", "month", "quarter", "custom"}
VALID_FORMATS = {"csv", "excel"}


def generate_download_token(user_id: int, guild_id: int, format: str, period: str) -> str:
    """Tạo one-time download token, hết hạn sau EXPORT_TTL_MINUTES"""
    payload = {
        "sub": str(user_id),
        "guild_id": guild_id,
        "format": format,
        "period": period,
        "type": "download",
        "jti": secrets.token_hex(16),
        "exp": utcnow() + timedelta(minutes=settings.EXPORT_TTL_MINUTES),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


@router.post("/prepare")
@limiter.limit("2/5minutes")
async def prepare_export(
    request: Request,
    guild_id: int = Query(...),
    format: str = Query(..., description="csv|excel"),
    period: str = Query("month"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """
    Tạo download token → trả URL download dùng 1 lần.
    Client dùng URL này để tải file trong 10 phút.
    """
    if format not in VALID_FORMATS:
        raise HTTPException(status_code=400, detail="Format phải là csv hoặc excel")
    if period not in VALID_PERIODS:
        raise HTTPException(status_code=400, detail=f"Period không hợp lệ. Chọn: {', '.join(VALID_PERIODS)}")

    await require_guild_role(guild_id, "DUTY_MOD", current_user, session)

    user_id = int(current_user["sub"])
    token = generate_download_token(user_id, guild_id, format, period)

    return {
        "download_url": f"/api/export/download?token={token}",
        "expires_in_minutes": settings.EXPORT_TTL_MINUTES,
    }


@router.get("/download")
async def download_export(
    token: str = Query(...),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    session: AsyncSession = Depends(get_db),
):
    """
    Endpoint download thực sự — dùng one-time token.
    Token bị blacklist ngay sau khi dùng.
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Token không hợp lệ hoặc đã hết hạn")

    if payload.get("type") != "download":
        raise HTTPException(status_code=401, detail="Sai loại token")

    jti = payload["jti"]
    guild_id = payload["guild_id"]
    format = payload["format"]
    period = payload["period"]
    user_id = int(payload["sub"])
    exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)

    # Kiểm tra token đã dùng chưa (one-time)
    bl = await session.execute(select(BlacklistedToken).where(BlacklistedToken.jti == jti))
    if bl.scalar_one_or_none():
        raise HTTPException(status_code=410, detail="Link này đã được dùng rồi")

    # Blacklist ngay lập tức
    session.add(BlacklistedToken(jti=jti, user_id=user_id, expires_at=exp, blacklisted_at=utcnow()))

    # Lấy dữ liệu
    tz_result = await session.execute(
        select(GuildConfig.timezone, GuildConfig.guild_name)
        .where(GuildConfig.guild_id == guild_id)
    )
    guild_row = tz_result.first()
    guild_tz = guild_row.timezone if guild_row else "Asia/Ho_Chi_Minh"
    guild_name = guild_row.guild_name if guild_row else str(guild_id)

    if date_from and date_to:
        start, end = get_custom_range(date_from, date_to, guild_tz)
        period_label = f"{date_from} đến {date_to}"
    else:
        start, end = get_period_range(period, tz_str=guild_tz)
        period_label = {"day": "Hôm nay", "week": "Tuần này", "month": "Tháng này", "quarter": "Quý này"}.get(period, period)

    logs_result = await session.execute(
        select(DutyLog)
        .where(DutyLog.guild_id == guild_id)
        .where(DutyLog.started_at >= start)
        .where(DutyLog.started_at <= end)
        .order_by(DutyLog.started_at.asc())
    )
    logs = logs_result.scalars().all()

    session.add(AuditLog(
        guild_id=guild_id, user_id=user_id, username="web_user",
        action=AuditAction.EXPORT_CSV if format == "csv" else AuditAction.EXPORT_EXCEL,
        detail={"period": period, "rows": len(logs)},
        created_at=utcnow(),
    ))
    await session.commit()

    df = logs_to_dataframe(logs, guild_name)
    timestamp = utcnow().strftime("%Y%m%d_%H%M%S")

    if format == "csv":
        file_bytes = generate_csv_bytes(df)
        filename = f"duty_log_{guild_id}_{period}_{timestamp}.csv"
        media_type = "text/csv"
    else:
        file_bytes = generate_excel_bytes(df, period_label)
        filename = f"duty_log_{guild_id}_{period}_{timestamp}.xlsx"
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    return StreamingResponse(
        io.BytesIO(file_bytes),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-File-Signature": sign_file(file_bytes)[:32],
        },
    )
