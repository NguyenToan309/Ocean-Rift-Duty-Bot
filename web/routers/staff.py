"""
staff.py — Web API quản lý nhân sự (chức vụ y tế).

Endpoints:
  GET    /api/staff/positions              — metadata các chức vụ + nhóm
  GET    /api/staff/list                   — danh sách nhân sự trong guild
  GET    /api/staff/{user_id}              — chi tiết 1 nhân sự
  POST   /api/staff                        — thêm nhân sự mới (Admin)
  PUT    /api/staff/{user_id}              — sửa chức vụ/khoa/note (Admin, bắt buộc note)
  DELETE /api/staff/{user_id}              — gỡ khỏi danh sách (Admin, bắt buộc note)
  GET    /api/staff/config/position-roles  — đọc config position→role mapping
  PUT    /api/staff/config/position-roles  — sửa config (Admin, bắt buộc note)

Strict audit policy: MỌI mutation đều bắt buộc kèm `note` (≥3 chars).
"""
from __future__ import annotations
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Path, Request, HTTPException, Body
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.base import get_db
from models.staff_member import (
    StaffMember, StaffPosition, POSITION_METADATA, GROUP_METADATA,
    is_valid_position,
)
from models.guild import GuildConfig
from models.audit_log import AuditLog, AuditAction
from web.middleware.auth_guard import require_auth, require_guild_role
from web.middleware.rate_limit import limiter
from web.utils.discord_role_sync import sync_staff_position_role
from bot.utils.time_utils import utcnow

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/staff", tags=["staff"])

# Valid system role keys cho position_role_map values
VALID_SYSTEM_ROLES = {"DUTY_ADMIN", "DUTY_MOD", "DUTY_MEMBER"}


def _serialize(m: StaffMember, avatar_url: str | None = None) -> dict:
    meta = POSITION_METADATA.get(m.position, {})
    return {
        "id": m.id,
        "guild_id": str(m.guild_id),
        "user_id": str(m.user_id),
        "username": m.username,
        "avatar_url": avatar_url,
        "position": m.position,
        "position_label": meta.get("label", m.position),
        "position_group": meta.get("group"),
        "position_color": meta.get("color"),
        "position_icon": meta.get("icon"),
        "position_level": meta.get("level", 99),
        "department": m.department,
        "note": m.note,
        "is_active": m.is_active,
        "joined_at": m.joined_at.isoformat() if m.joined_at else None,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
    }


async def _serialize_with_avatars(members: list[StaffMember]) -> list[dict]:
    """Batch resolve Discord avatars cho cả list rồi serialize."""
    if not members:
        return []
    try:
        from web.utils.discord_resolver import batch_resolve_user_info
        user_ids = {m.user_id for m in members}
        info_map = await batch_resolve_user_info(user_ids)
    except Exception as e:
        logger.warning(f"Resolve avatars failed: {e}")
        info_map = {}
    return [
        _serialize(m, avatar_url=(info_map.get(m.user_id) or {}).get("avatar_url"))
        for m in members
    ]


def _require_note(body: dict, action_word: str) -> str:
    """Audit policy: mọi mutation bắt buộc note ≥3 chars."""
    note = (body.get("note") or "").strip()
    if len(note) < 3:
        raise HTTPException(
            status_code=400,
            detail=f"Bắt buộc phải có lý do (≥3 ký tự) khi {action_word}. Field 'note'.",
        )
    return note


# ─── GET /positions ───────────────────────────────────────────────────────────

@router.get("/positions")
@limiter.limit("60/minute")
async def get_positions_metadata(request: Request):
    """Trả về metadata tất cả chức vụ + nhóm. KHÔNG cần auth (public, chỉ là constant)."""
    positions = []
    for code in StaffPosition.ALL:
        meta = POSITION_METADATA[code]
        positions.append({
            "code": code,
            "label": meta["label"],
            "group": meta["group"],
            "color": meta["color"],
            "icon": meta["icon"],
            "level": meta["level"],
        })
    # Sort theo level (1 = cao nhất)
    positions.sort(key=lambda p: p["level"])

    groups = []
    for code, meta in GROUP_METADATA.items():
        groups.append({
            "code": code,
            "label": meta["label"],
            "color": meta["color"],
            "icon": meta["icon"],
            "order": meta["order"],
        })
    groups.sort(key=lambda g: g["order"])

    return {"positions": positions, "groups": groups}


# ─── GET /list ────────────────────────────────────────────────────────────────

@router.get("/list")
@limiter.limit("60/minute")
async def list_staff(
    request: Request,
    guild_id: int = Query(...),
    group: str | None = Query(None, description="Filter theo nhóm: LANH_DAO/Y_TE/DAO_TAO"),
    position: str | None = Query(None, description="Filter theo chức vụ cụ thể"),
    is_active: bool | None = Query(None),
    search: str | None = Query(None, description="Tìm theo username"),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """List nhân sự trong guild (Mod+ xem được tất cả)."""
    await require_guild_role(guild_id, "DUTY_MOD", current_user, session)

    q = select(StaffMember).where(StaffMember.guild_id == guild_id)
    if position and is_valid_position(position):
        q = q.where(StaffMember.position == position)
    if is_active is not None:
        q = q.where(StaffMember.is_active == is_active)
    if search:
        like = f"%{search.strip()}%"
        q = q.where(StaffMember.username.ilike(like))

    rows = await session.execute(q)
    members = list(rows.scalars().all())
    items = await _serialize_with_avatars(members)

    # Filter group ở Python vì group là computed từ POSITION_METADATA
    if group:
        items = [m for m in items if m.get("position_group") == group]

    # Sort: level ASC (cao nhất trước), trong cùng level thì theo username
    items.sort(key=lambda m: (m.get("position_level", 99), m.get("username", "")))

    # Count theo group
    counts_by_group = {"LANH_DAO": 0, "Y_TE": 0, "DAO_TAO": 0}
    for m in items:
        g = m.get("position_group")
        if g in counts_by_group:
            counts_by_group[g] += 1

    return {
        "items": items,
        "total": len(items),
        "counts_by_group": counts_by_group,
    }


# ─── GET /{user_id} ───────────────────────────────────────────────────────────

@router.get("/{user_id_target}")
@limiter.limit("60/minute")
async def get_staff_detail(
    request: Request,
    user_id_target: int = Path(..., gt=0),
    guild_id: int = Query(...),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """Chi tiết 1 nhân sự (Mod+ hoặc chính user đó)."""
    current_uid = int(current_user["sub"])
    if user_id_target != current_uid:
        await require_guild_role(guild_id, "DUTY_MOD", current_user, session)
    else:
        await require_guild_role(guild_id, "DUTY_MEMBER", current_user, session)

    row = await session.execute(
        select(StaffMember)
        .where(StaffMember.guild_id == guild_id)
        .where(StaffMember.user_id == user_id_target)
    )
    m = row.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="Không tìm thấy nhân sự")
    items = await _serialize_with_avatars([m])
    return {"staff": items[0]}


# ─── POST / ───────────────────────────────────────────────────────────────────

@router.post("")
@limiter.limit("20/minute")
async def add_staff(
    request: Request,
    guild_id: int = Query(...),
    body: dict = Body(...),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """
    Thêm nhân sự mới (Admin). Body:
      {
        "user_id": "1119880453671899196",  (string để tránh BigInt JS)
        "username": "BS. Nguyễn Văn A",
        "position": "BAC_SI",
        "department": "Khoa Nội",       (optional)
        "joined_at": "2024-01-15",      (optional ISO date)
        "note": "Thêm nhân sự mới"      (BẮT BUỘC ≥3 chars)
      }
    """
    await require_guild_role(guild_id, "DUTY_ADMIN", current_user, session)
    note = _require_note(body, "thêm nhân sự")

    try:
        user_id = int(body.get("user_id"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="user_id phải là số nguyên (Discord ID).")

    username = (body.get("username") or "").strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username bắt buộc.")
    if len(username) > 100:
        username = username[:100]

    position = body.get("position") or StaffPosition.BAC_SI
    if not is_valid_position(position):
        raise HTTPException(
            status_code=400,
            detail=f"Chức vụ không hợp lệ: {position}. Hợp lệ: {StaffPosition.ALL}",
        )

    department = (body.get("department") or "").strip() or None
    if department and len(department) > 100:
        department = department[:100]

    joined_at = None
    if body.get("joined_at"):
        try:
            joined_at = datetime.fromisoformat(body["joined_at"].replace("Z", "+00:00"))
        except Exception:
            raise HTTPException(status_code=400, detail="joined_at phải là ISO date.")

    # Check duplicate
    existing = await session.execute(
        select(StaffMember)
        .where(StaffMember.guild_id == guild_id)
        .where(StaffMember.user_id == user_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail="Nhân sự này đã tồn tại trong guild. Dùng PUT /{user_id} để cập nhật.",
        )

    member = StaffMember(
        guild_id=guild_id,
        user_id=user_id,
        username=username,
        position=position,
        department=department,
        joined_at=joined_at,
        is_active=True,
    )
    session.add(member)
    await session.flush()  # Lấy ID

    session.add(AuditLog(
        guild_id=guild_id,
        user_id=int(current_user["sub"]),
        username=current_user.get("username", f"user_{current_user['sub']}"),
        action=AuditAction.STAFF_ADDED,
        detail={
            "staff_user_id": str(user_id),
            "staff_username": username,
            "position": position,
            "department": department,
            "note": note,
            "via": "web",
        },
        created_at=utcnow(),
    ))

    # Auto-sync Discord role theo position_role_map
    sync_result = await sync_staff_position_role(
        session=session,
        guild_id=guild_id,
        user_id=user_id,
        new_position=position,
        old_position=None,
        actor_id=int(current_user["sub"]),
        actor_username=current_user.get("username"),
        reason=f"Thêm nhân sự: {note}",
    )

    await session.commit()
    await session.refresh(member)

    # Realtime broadcast
    try:
        from web.realtime import broadcaster
        await broadcaster.publish(guild_id, {
            "type": "staff_added",
            "staff_user_id": str(user_id),
            "position": position,
        })
    except Exception as e:
        logger.warning(f"Realtime publish failed: {e}")

    return {"success": True, "staff": _serialize(member), "role_sync": sync_result}


# ─── PUT /{user_id} ───────────────────────────────────────────────────────────

@router.put("/{user_id_target}")
@limiter.limit("30/minute")
async def update_staff(
    request: Request,
    user_id_target: int = Path(..., gt=0),
    guild_id: int = Query(...),
    body: dict = Body(...),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """
    Cập nhật chức vụ/khoa/note của 1 nhân sự (Admin). Body:
      {
        "position": "VIEN_TRUONG",      (optional, nếu đổi)
        "department": "Khoa Cấp cứu",   (optional)
        "username": "...",              (optional, sync từ Discord)
        "is_active": true,              (optional)
        "joined_at": "2024-01-15",      (optional)
        "note": "Bổ nhiệm chức vụ mới"  (BẮT BUỘC ≥3 chars)
      }
    """
    await require_guild_role(guild_id, "DUTY_ADMIN", current_user, session)
    note = _require_note(body, "cập nhật nhân sự")

    row = await session.execute(
        select(StaffMember)
        .where(StaffMember.guild_id == guild_id)
        .where(StaffMember.user_id == user_id_target)
    )
    m = row.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="Không tìm thấy nhân sự")

    # Lưu state cũ cho audit
    before = {
        "position": m.position,
        "department": m.department,
        "username": m.username,
        "is_active": m.is_active,
    }

    if "position" in body:
        new_pos = body["position"]
        if not is_valid_position(new_pos):
            raise HTTPException(
                status_code=400,
                detail=f"Chức vụ không hợp lệ: {new_pos}",
            )
        m.position = new_pos

    if "department" in body:
        dept = (body["department"] or "").strip() or None
        if dept and len(dept) > 100:
            dept = dept[:100]
        m.department = dept

    if "username" in body:
        uname = (body["username"] or "").strip()
        if uname:
            m.username = uname[:100]

    if "is_active" in body:
        m.is_active = bool(body["is_active"])

    if "joined_at" in body:
        if body["joined_at"]:
            try:
                m.joined_at = datetime.fromisoformat(
                    body["joined_at"].replace("Z", "+00:00")
                )
            except Exception:
                raise HTTPException(status_code=400, detail="joined_at phải là ISO date.")
        else:
            m.joined_at = None

    after = {
        "position": m.position,
        "department": m.department,
        "username": m.username,
        "is_active": m.is_active,
    }

    # Compute changes (only fields that actually differ)
    changes = {k: {"before": before[k], "after": after[k]} for k in before if before[k] != after[k]}

    session.add(AuditLog(
        guild_id=guild_id,
        user_id=int(current_user["sub"]),
        username=current_user.get("username", f"user_{current_user['sub']}"),
        action=AuditAction.STAFF_UPDATED,
        detail={
            "staff_user_id": str(m.user_id),
            "staff_username": m.username,
            "changes": changes,
            "note": note,
            "via": "web",
        },
        created_at=utcnow(),
    ))

    # Auto-sync Discord role nếu chức vụ thay đổi
    sync_result = None
    if "position" in changes:
        sync_result = await sync_staff_position_role(
            session=session,
            guild_id=guild_id,
            user_id=m.user_id,
            new_position=after["position"],
            old_position=before["position"],
            actor_id=int(current_user["sub"]),
            actor_username=current_user.get("username"),
            reason=f"Đổi chức vụ {before['position']} → {after['position']}: {note}",
        )

    await session.commit()
    await session.refresh(m)

    try:
        from web.realtime import broadcaster
        await broadcaster.publish(guild_id, {
            "type": "staff_updated",
            "staff_user_id": str(m.user_id),
            "position": m.position,
        })
    except Exception as e:
        logger.warning(f"Realtime publish failed: {e}")

    return {
        "success": True,
        "staff": _serialize(m),
        "changes": changes,
        "role_sync": sync_result,
    }


# ─── DELETE /{user_id} ────────────────────────────────────────────────────────

@router.delete("/{user_id_target}")
@limiter.limit("20/minute")
async def remove_staff(
    request: Request,
    user_id_target: int = Path(..., gt=0),
    guild_id: int = Query(...),
    note: str = Query(..., min_length=3, description="Lý do gỡ (bắt buộc)"),
    hard: bool = Query(False, description="True = xoá hẳn, False = chỉ set is_active=False"),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """
    Gỡ nhân sự khỏi danh sách (Admin).
    - hard=False (default): set is_active=False, giữ lại lịch sử
    - hard=True: xoá hẳn record (chỉ dùng khi nhập nhầm)
    """
    await require_guild_role(guild_id, "DUTY_ADMIN", current_user, session)

    note_clean = (note or "").strip()
    if len(note_clean) < 3:
        raise HTTPException(
            status_code=400,
            detail="Bắt buộc phải có lý do (≥3 ký tự).",
        )

    row = await session.execute(
        select(StaffMember)
        .where(StaffMember.guild_id == guild_id)
        .where(StaffMember.user_id == user_id_target)
    )
    m = row.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="Không tìm thấy nhân sự")

    snapshot = {
        "position": m.position,
        "department": m.department,
        "username": m.username,
        "hard_delete": hard,
    }

    old_position_for_sync = m.position
    if hard:
        await session.delete(m)
    else:
        m.is_active = False

    session.add(AuditLog(
        guild_id=guild_id,
        user_id=int(current_user["sub"]),
        username=current_user.get("username", f"user_{current_user['sub']}"),
        action=AuditAction.STAFF_REMOVED,
        detail={
            "staff_user_id": str(user_id_target),
            "snapshot": snapshot,
            "note": note_clean,
            "via": "web",
        },
        created_at=utcnow(),
    ))

    # Auto-gỡ role Discord khi gỡ nhân sự
    sync_result = await sync_staff_position_role(
        session=session,
        guild_id=guild_id,
        user_id=user_id_target,
        new_position=None,    # Không cấp role mới
        old_position=old_position_for_sync,
        actor_id=int(current_user["sub"]),
        actor_username=current_user.get("username"),
        reason=f"Gỡ nhân sự: {note_clean}",
    )

    await session.commit()

    try:
        from web.realtime import broadcaster
        await broadcaster.publish(guild_id, {
            "type": "staff_removed",
            "staff_user_id": str(user_id_target),
        })
    except Exception as e:
        logger.warning(f"Realtime publish failed: {e}")

    return {
        "success": True,
        "user_id": str(user_id_target),
        "hard_delete": hard,
        "role_sync": sync_result,
    }


# ─── GET /config/position-roles ───────────────────────────────────────────────

@router.get("/config/position-roles")
@limiter.limit("30/minute")
async def get_position_role_map(
    request: Request,
    guild_id: int = Query(...),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """Đọc config map chức vụ → role hệ thống."""
    await require_guild_role(guild_id, "DUTY_MOD", current_user, session)

    row = await session.execute(
        select(GuildConfig).where(GuildConfig.guild_id == guild_id)
    )
    config = row.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Guild chưa setup")

    return {
        "position_role_map": config.position_role_map or {},
        "valid_system_roles": sorted(VALID_SYSTEM_ROLES),
    }


# ─── PUT /config/position-roles ───────────────────────────────────────────────

@router.put("/config/position-roles")
@limiter.limit("10/minute")
async def update_position_role_map(
    request: Request,
    guild_id: int = Query(...),
    body: dict = Body(...),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """
    Sửa config map chức vụ → role hệ thống (Admin). Body:
      {
        "map": {"VIEN_TRUONG": "DUTY_ADMIN", "BAC_SI": "DUTY_MEMBER", ...},
        "note": "Cập nhật phân quyền"
      }
    Set value = null để xoá mapping cho chức vụ đó.
    """
    await require_guild_role(guild_id, "DUTY_ADMIN", current_user, session)
    note = _require_note(body, "cập nhật map chức vụ→quyền")

    new_map = body.get("map") or {}
    if not isinstance(new_map, dict):
        raise HTTPException(status_code=400, detail="Field 'map' phải là object.")

    # Validate keys (positions) và values (system roles)
    clean_map: dict[str, str] = {}
    for pos, role in new_map.items():
        if not is_valid_position(pos):
            raise HTTPException(status_code=400, detail=f"Chức vụ không hợp lệ: {pos}")
        if role is None or role == "":
            continue  # Xoá mapping cho chức vụ này
        if role not in VALID_SYSTEM_ROLES:
            raise HTTPException(
                status_code=400,
                detail=f"Role hệ thống không hợp lệ: {role}. Hợp lệ: {sorted(VALID_SYSTEM_ROLES)}",
            )
        clean_map[pos] = role

    row = await session.execute(
        select(GuildConfig).where(GuildConfig.guild_id == guild_id)
    )
    config = row.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Guild chưa setup")

    before = dict(config.position_role_map or {})
    config.position_role_map = clean_map

    session.add(AuditLog(
        guild_id=guild_id,
        user_id=int(current_user["sub"]),
        username=current_user.get("username", f"user_{current_user['sub']}"),
        action=AuditAction.POSITION_ROLE_MAP_CHANGED,
        detail={
            "before": before,
            "after": clean_map,
            "note": note,
            "via": "web",
        },
        created_at=utcnow(),
    ))
    await session.commit()

    return {"success": True, "position_role_map": clean_map}
