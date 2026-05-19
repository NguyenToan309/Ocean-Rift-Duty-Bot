"""
leave.py — Web API cho đơn xin nghỉ + xin out ngành.

Endpoints:
  GET  /api/leave/list                    — list đơn (filter status, type)
  GET  /api/leave/my                      — đơn của tôi
  GET  /api/leave/{id}                    — chi tiết 1 đơn (kèm history)
  GET  /api/leave/user/{uid}/history      — lịch sử nghỉ trước đó của 1 user
  POST /api/leave/{id}/decision           — Admin duyệt qua web (Q8=c chỉ ADMIN)
  POST /api/leave/{id}/revert             — Admin revert quyết định (Q13=b)
"""
from __future__ import annotations
import logging
from fastapi import APIRouter, Depends, Query, Path, Request, HTTPException, Body
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.base import get_db
from models.leave import LeaveRequest, LeaveRequestType, LeaveRequestStatus
from models.audit_log import AuditLog, AuditAction
from web.middleware.auth_guard import require_auth, require_guild_role
from web.middleware.rate_limit import limiter
from bot.utils.time_utils import utcnow

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/leave", tags=["leave"])


def _serialize(req: LeaveRequest, avatar_url: str | None = None) -> dict:
    return {
        "id": req.id,
        "user_id": str(req.user_id),
        "username": req.username,
        "avatar_url": avatar_url,
        "type": req.request_type,
        "status": req.status,
        "start_date": req.start_date.isoformat() if req.start_date else None,
        "end_date": req.end_date.isoformat() if req.end_date else None,
        "days_count": (
            (req.end_date - req.start_date).days + 1
            if req.end_date else None
        ),
        "reason": req.reason,
        "decided_by": str(req.decided_by) if req.decided_by else None,
        "decided_at": req.decided_at.isoformat() if req.decided_at else None,
        "decision_note": req.decision_note,
        "processed_at": req.processed_at.isoformat() if req.processed_at else None,
        "vote_message_id": str(req.vote_message_id) if req.vote_message_id else None,
        "vote_channel_id": str(req.vote_channel_id) if req.vote_channel_id else None,
        "detail": req.detail or {},
        "created_at": req.created_at.isoformat() if req.created_at else None,
    }


# ─── /list ────────────────────────────────────────────────────────────────────

@router.get("/list")
@limiter.limit("30/minute")
async def list_leaves(
    request: Request,
    guild_id: int = Query(...),
    status: str | None = Query(None, description="pending/approved/rejected"),
    request_type: str | None = Query(None, description="leave/resign"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """List đơn (Mod+ xem được tất cả)"""
    await require_guild_role(guild_id, "DUTY_MOD", current_user, session)

    q = select(LeaveRequest).where(LeaveRequest.guild_id == guild_id)
    if status:
        q = q.where(LeaveRequest.status == status)
    if request_type:
        q = q.where(LeaveRequest.request_type == request_type)
    q = q.order_by(LeaveRequest.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    rows = await session.execute(q)
    items = rows.scalars().all()

    # Count theo status (để hiển thị badge tab)
    counts = {}
    for s in (LeaveRequestStatus.PENDING, LeaveRequestStatus.APPROVED, LeaveRequestStatus.REJECTED):
        cnt = (await session.execute(
            select(func.count(LeaveRequest.id))
            .where(LeaveRequest.guild_id == guild_id)
            .where(LeaveRequest.status == s)
        )).scalar() or 0
        counts[s] = cnt

    # Batch resolve avatars cho danh sách leave
    from web.utils.discord_resolver import batch_resolve_user_info
    _uids = {r.user_id for r in items}
    _info = await batch_resolve_user_info(_uids) if _uids else {}

    return {
        "page": page,
        "page_size": page_size,
        "counts": counts,
        "items": [
            _serialize(r, avatar_url=(_info.get(r.user_id) or {}).get("avatar_url"))
            for r in items
        ],
    }


# ─── /my ──────────────────────────────────────────────────────────────────────

@router.get("/my")
@limiter.limit("30/minute")
async def my_leaves(
    request: Request,
    guild_id: int = Query(...),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    await require_guild_role(guild_id, "DUTY_MEMBER", current_user, session)
    uid = int(current_user["sub"])

    rows = await session.execute(
        select(LeaveRequest)
        .where(LeaveRequest.guild_id == guild_id)
        .where(LeaveRequest.user_id == uid)
        .order_by(LeaveRequest.created_at.desc())
        .limit(50)
    )
    return {"items": [_serialize(r) for r in rows.scalars().all()]}


# ─── /{id} ────────────────────────────────────────────────────────────────────

@router.get("/{leave_id}")
@limiter.limit("30/minute")
async def get_leave_detail(
    request: Request,
    leave_id: int = Path(..., gt=0),
    guild_id: int = Query(...),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """Chi tiết 1 đơn + lịch sử các đơn trước của cùng user"""
    await require_guild_role(guild_id, "DUTY_MOD", current_user, session)

    row = await session.execute(
        select(LeaveRequest)
        .where(LeaveRequest.id == leave_id)
        .where(LeaveRequest.guild_id == guild_id)
    )
    req = row.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=404, detail="Đơn không tồn tại")

    # Lịch sử các đơn trước của cùng user
    history_rows = await session.execute(
        select(LeaveRequest)
        .where(LeaveRequest.guild_id == guild_id)
        .where(LeaveRequest.user_id == req.user_id)
        .where(LeaveRequest.id != leave_id)
        .order_by(LeaveRequest.created_at.desc())
        .limit(20)
    )

    return {
        "request": _serialize(req),
        "history": [_serialize(r) for r in history_rows.scalars().all()],
    }


# ─── /user/{uid}/history ──────────────────────────────────────────────────────

@router.get("/user/{user_id_target}/history")
@limiter.limit("30/minute")
async def user_history(
    request: Request,
    user_id_target: int = Path(..., gt=0),
    guild_id: int = Query(...),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """Lịch sử các đơn của 1 user (Mod+ hoặc chính user đó)"""
    current_uid = int(current_user["sub"])
    if user_id_target != current_uid:
        await require_guild_role(guild_id, "DUTY_MOD", current_user, session)
    else:
        await require_guild_role(guild_id, "DUTY_MEMBER", current_user, session)

    rows = await session.execute(
        select(LeaveRequest)
        .where(LeaveRequest.guild_id == guild_id)
        .where(LeaveRequest.user_id == user_id_target)
        .order_by(LeaveRequest.created_at.desc())
        .limit(50)
    )
    return {"items": [_serialize(r) for r in rows.scalars().all()]}


# ─── POST /{id}/decision ──────────────────────────────────────────────────────

@router.post("/{leave_id}/decision")
@limiter.limit("30/minute")
async def decide_leave(
    request: Request,
    leave_id: int = Path(..., gt=0),
    guild_id: int = Query(...),
    body: dict = Body(...),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """
    Admin duyệt qua web (Q8=c — CHỈ ADMIN). Body:
      {"approved": bool, "note": str}

    Rule (Q9=b):
    - approved=False → BẮT BUỘC có note (lý do từ chối)
    - approved=True  → note optional

    Sau khi update DB:
    - Bot background task `process_web_decisions_loop` sẽ:
      - DM kết quả cho member
      - Update embed Discord vote message (nếu có vote_message_id)
      - Cleanup roles + schedules nếu RESIGN approved
      - Set processed_at để không xử lý 2 lần
    """
    # Q8=c: chỉ ADMIN duyệt qua web
    await require_guild_role(guild_id, "DUTY_ADMIN", current_user, session)

    approved = bool(body.get("approved"))
    note = (body.get("note") or "").strip() or None

    # Audit policy nghiêm ngặt: MỌI quyết định đều cần lý do (cả duyệt + từ chối)
    if not note:
        action_word = "duyệt" if approved else "từ chối"
        raise HTTPException(
            status_code=400,
            detail=f"Bắt buộc phải có lý do/ghi chú khi {action_word} đơn (field 'note').",
        )

    row = await session.execute(
        select(LeaveRequest)
        .where(LeaveRequest.id == leave_id)
        .where(LeaveRequest.guild_id == guild_id)
    )
    req = row.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=404, detail="Đơn không tồn tại")
    if req.status != LeaveRequestStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"Đơn đã ở trạng thái {req.status}")

    req.status = LeaveRequestStatus.APPROVED if approved else LeaveRequestStatus.REJECTED
    req.decided_by = int(current_user["sub"])
    req.decided_at = utcnow()
    req.decision_note = note
    req.processed_at = None    # Reset để bot xử lý

    audit_action = (
        AuditAction.LEAVE_APPROVED if (approved and req.request_type == LeaveRequestType.LEAVE)
        else AuditAction.LEAVE_REJECTED if (not approved and req.request_type == LeaveRequestType.LEAVE)
        else AuditAction.RESIGN_APPROVED if approved
        else AuditAction.RESIGN_REJECTED
    )
    session.add(AuditLog(
        guild_id=guild_id,
        user_id=int(current_user["sub"]),
        username=current_user.get("username", f"user_{current_user['sub']}"),
        action=audit_action,
        detail={
            "request_id": req.id,
            "for_user": str(req.user_id),
            "note": note,
            "via": "web",
        },
        created_at=utcnow(),
    ))
    await session.commit()

    # Realtime broadcast
    from web.realtime import broadcaster
    await broadcaster.publish(guild_id, {
        "type": "leave_decided",
        "leave_id": leave_id,
        "status": req.status,
        "approved": approved,
    })

    return {"success": True, "request": _serialize(req)}


# ─── POST /{id}/revert (Q13=b) ────────────────────────────────────────────────

@router.post("/{leave_id}/revert")
@limiter.limit("10/minute")
async def revert_leave(
    request: Request,
    leave_id: int = Path(..., gt=0),
    guild_id: int = Query(...),
    body: dict = Body(...),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """
    Admin revert quyết định đã duyệt/từ chối → đơn về PENDING để duyệt lại.
    Body: {"reason": str}  — bắt buộc phải có lý do revert (audit).

    NOTE: Nếu đơn RESIGN đã approved + bot đã cleanup → KHÔNG tự rollback role.
    Admin phải tự cấp lại role thủ công nếu cần.
    """
    await require_guild_role(guild_id, "DUTY_ADMIN", current_user, session)

    reason = (body.get("reason") or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="Bắt buộc phải có lý do revert.")

    row = await session.execute(
        select(LeaveRequest)
        .where(LeaveRequest.id == leave_id)
        .where(LeaveRequest.guild_id == guild_id)
    )
    req = row.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=404, detail="Đơn không tồn tại")
    if req.status == LeaveRequestStatus.PENDING:
        raise HTTPException(status_code=400, detail="Đơn đang pending, không cần revert")

    previous_status = req.status
    previous_decided_by = req.decided_by
    previous_decided_at = req.decided_at
    previous_note = req.decision_note

    req.status = LeaveRequestStatus.PENDING
    req.decided_by = None
    req.decided_at = None
    req.decision_note = None
    # KHÔNG reset processed_at — bot sẽ không re-DM/cleanup vì đã processed trước đó.
    # Nếu cần re-process, bot có thể check processed_at < decided_at trong logic mới.

    session.add(AuditLog(
        guild_id=guild_id,
        user_id=int(current_user["sub"]),
        username=current_user.get("username", f"user_{current_user['sub']}"),
        action="LEAVE_REVERTED",
        detail={
            "request_id": req.id,
            "for_user": str(req.user_id),
            "reason": reason[:500],
            "previous_status": previous_status,
            "previous_decided_by": str(previous_decided_by) if previous_decided_by else None,
            "previous_note": previous_note,
            "warning": "Role đã gỡ KHÔNG tự cấp lại — admin phải xử lý thủ công",
        },
        created_at=utcnow(),
    ))
    await session.commit()

    from web.realtime import broadcaster
    await broadcaster.publish(guild_id, {
        "type": "leave_reverted",
        "leave_id": leave_id,
    })

    return {
        "success": True,
        "request": _serialize(req),
        "warning": (
            "Đơn đã được revert về PENDING. "
            "LƯU Ý: Nếu là đơn RESIGN đã approved, role đã gỡ trước đó "
            "KHÔNG tự cấp lại. Admin phải xử lý thủ công."
        ),
    }
