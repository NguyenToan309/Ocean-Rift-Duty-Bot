"""
purge_before_date.py — Xoa sach data lich su truoc 1 ngay cu the.

Mac dinh xoa: duty_logs, audit_logs, leave_requests truoc cutoff.
Co confirmation step truoc khi xoa thuc su.

CHAY:
  # Dry-run (preview - khong xoa)
  python scripts/purge_before_date.py <guild_id> 2026-05-17 --dry-run

  # Xoa that (yeu cau go YES)
  python scripts/purge_before_date.py <guild_id> 2026-05-17

  # Chi xoa duty_logs (giu audit + leave)
  python scripts/purge_before_date.py <guild_id> 2026-05-17 --only=duty_logs

Vidu:
  python scripts/purge_before_date.py 1497538323672207492 2026-05-17
"""
import asyncio
import os
import sys
from datetime import datetime, date, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, delete, func
from models.base import AsyncSessionLocal
from models.duty_log import DutyLog
from models.audit_log import AuditLog
from models.leave import LeaveRequest


TABLES_DEFAULT = ["duty_logs", "audit_logs", "leave_requests"]


async def count_data(guild_id: int, cutoff_dt: datetime, cutoff_date: date, tables: list[str]) -> dict:
    """Dem so row se bi xoa cho moi table."""
    counts: dict[str, int] = {}
    async with AsyncSessionLocal() as session:
        if "duty_logs" in tables:
            r = await session.execute(
                select(func.count(DutyLog.id))
                .where(DutyLog.guild_id == guild_id)
                .where(DutyLog.started_at < cutoff_dt)
            )
            counts["duty_logs"] = r.scalar() or 0
        if "audit_logs" in tables:
            r = await session.execute(
                select(func.count(AuditLog.id))
                .where(AuditLog.guild_id == guild_id)
                .where(AuditLog.created_at < cutoff_dt)
            )
            counts["audit_logs"] = r.scalar() or 0
        if "leave_requests" in tables:
            r = await session.execute(
                select(func.count(LeaveRequest.id))
                .where(LeaveRequest.guild_id == guild_id)
                .where(LeaveRequest.created_at < cutoff_dt)
            )
            counts["leave_requests"] = r.scalar() or 0
    return counts


async def purge(guild_id: int, cutoff_dt: datetime, cutoff_date: date, tables: list[str]) -> dict:
    """Xoa that. Tra so row da xoa per table."""
    deleted: dict[str, int] = {}
    async with AsyncSessionLocal() as session:
        if "duty_logs" in tables:
            r = await session.execute(
                delete(DutyLog)
                .where(DutyLog.guild_id == guild_id)
                .where(DutyLog.started_at < cutoff_dt)
            )
            deleted["duty_logs"] = r.rowcount or 0
        if "audit_logs" in tables:
            r = await session.execute(
                delete(AuditLog)
                .where(AuditLog.guild_id == guild_id)
                .where(AuditLog.created_at < cutoff_dt)
            )
            deleted["audit_logs"] = r.rowcount or 0
        if "leave_requests" in tables:
            r = await session.execute(
                delete(LeaveRequest)
                .where(LeaveRequest.guild_id == guild_id)
                .where(LeaveRequest.created_at < cutoff_dt)
            )
            deleted["leave_requests"] = r.rowcount or 0
        await session.commit()
    return deleted


def usage():
    print(__doc__)
    sys.exit(1)


async def main():
    if len(sys.argv) < 3:
        usage()

    try:
        guild_id = int(sys.argv[1])
        cutoff_date = datetime.strptime(sys.argv[2], "%Y-%m-%d").date()
    except (ValueError, IndexError):
        print("[ERR] Tham so khong hop le. Format: <guild_id> YYYY-MM-DD")
        usage()

    dry_run = "--dry-run" in sys.argv
    only_arg = next((a for a in sys.argv if a.startswith("--only=")), None)
    if only_arg:
        tables = only_arg.split("=", 1)[1].split(",")
    else:
        tables = TABLES_DEFAULT

    # Cutoff: rang sang ngay cutoff_date theo UTC
    cutoff_dt = datetime.combine(cutoff_date, datetime.min.time(), tzinfo=timezone.utc)

    print()
    print("=" * 60)
    print(f"  PURGE DATA TRUOC NGAY {cutoff_date}")
    print(f"  Guild ID: {guild_id}")
    print(f"  Cutoff UTC: {cutoff_dt.isoformat()}")
    print(f"  Tables: {', '.join(tables)}")
    print(f"  Mode: {'DRY-RUN (khong xoa)' if dry_run else 'PRODUCTION (xoa that)'}")
    print("=" * 60)
    print()

    counts = await count_data(guild_id, cutoff_dt, cutoff_date, tables)
    total = sum(counts.values())

    print("So row se bi xoa:")
    for t in tables:
        print(f"  - {t:<20} {counts.get(t, 0):>6} row")
    print(f"  {'TOTAL':<22} {total:>6} row")
    print()

    if total == 0:
        print("[OK] Khong co data nao truoc ngay nay. Khong can xoa.")
        return

    if dry_run:
        print("[DRY-RUN] Khong xoa. Bo --dry-run de xoa that.")
        return

    print("CANH BAO: Hanh dong nay KHONG THE HOAN TAC!")
    print(f"Toi se xoa {total} row khoi DB.")
    answer = input("Go 'YES' (chu hoa, du 3 chu) de xac nhan: ").strip()
    if answer != "YES":
        print("[CANCELLED] Khong xoa.")
        return

    print()
    print("[*] Dang xoa...")
    deleted = await purge(guild_id, cutoff_dt, cutoff_date, tables)
    print()
    print("[OK] Da xoa:")
    for t, n in deleted.items():
        print(f"  - {t:<20} {n:>6} row")
    print(f"  {'TOTAL':<22} {sum(deleted.values()):>6} row")
    print()
    print("DB clean. Bat dau tinh lai tu", cutoff_date)


if __name__ == "__main__":
    asyncio.run(main())
