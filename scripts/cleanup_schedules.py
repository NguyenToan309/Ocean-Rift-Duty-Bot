"""
cleanup_schedules.py — Script quan ly lich truc (deactivate/restore).

Chay:
  list <guild_id> [user_id]                   - Xem lich trong guild (toan bo hoac 1 user)
  reset <guild_id> <user_id>                  - Deactivate tat ca lich cua user
  restore-all <guild_id>                      - Reactivate TAT CA inactive trong guild
  restore-user <guild_id> <user_id>           - Reactivate lich cua 1 user cu the
  purge <guild_id>                            - Xoa han cac entry inactive
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, update, delete
from models.base import AsyncSessionLocal
from models.schedule import MemberSchedule, WEEKDAY_LABELS
from bot.utils.time_utils import utcnow


async def list_schedules(guild_id: int, user_id: int | None = None):
    async with AsyncSessionLocal() as session:
        q = (
            select(MemberSchedule)
            .where(MemberSchedule.guild_id == guild_id)
            .order_by(MemberSchedule.user_id, MemberSchedule.is_active.desc(), MemberSchedule.weekday)
        )
        if user_id is not None:
            q = q.where(MemberSchedule.user_id == user_id)
        rows = await session.execute(q)
        schedules = list(rows.scalars().all())
        if not schedules:
            target = f"user {user_id}" if user_id else "guild"
            print(f"Khong co schedule nao trong {target}.")
            return
        active = sum(1 for s in schedules if s.is_active)
        inactive = len(schedules) - active
        print(f"\n=== Schedules trong guild {guild_id} ===")
        print(f"Total: {len(schedules)}  |  Active: {active}  |  Inactive: {inactive}\n")
        print(f"{'ID':<6}{'Active':<8}{'User':<22}{'Day':<10}{'Time':<20}{'Updated':<20}")
        print("-" * 86)
        for s in schedules:
            print(
                f"{s.id:<6}"
                f"{'YES' if s.is_active else 'no':<8}"
                f"{str(s.user_id):<22}"
                f"{WEEKDAY_LABELS[s.weekday]:<10}"
                f"{s.start_time.strftime('%H:%M')} - {s.end_time.strftime('%H:%M'):<10}"
                f"{s.updated_at.strftime('%Y-%m-%d %H:%M'):<20}"
            )


async def restore_all(guild_id: int):
    """Reactivate TAT CA inactive schedules trong guild."""
    async with AsyncSessionLocal() as session:
        rows = await session.execute(
            select(MemberSchedule)
            .where(MemberSchedule.guild_id == guild_id)
            .where(MemberSchedule.is_active == False)  # noqa: E712
        )
        schedules = list(rows.scalars().all())
        count = len(schedules)
        if count == 0:
            print(f"Khong co inactive schedule nao trong guild {guild_id}.")
            return
        for s in schedules:
            s.is_active = True
            s.updated_at = utcnow()
        await session.commit()
        print(f"[OK] Da khoi phuc {count} schedules trong guild {guild_id}.")


async def restore_user(guild_id: int, user_id: int):
    """Reactivate inactive schedules cua 1 user."""
    async with AsyncSessionLocal() as session:
        rows = await session.execute(
            select(MemberSchedule)
            .where(MemberSchedule.guild_id == guild_id)
            .where(MemberSchedule.user_id == user_id)
            .where(MemberSchedule.is_active == False)  # noqa: E712
        )
        schedules = list(rows.scalars().all())
        count = len(schedules)
        if count == 0:
            print(f"User {user_id} khong co inactive schedule nao.")
            return
        for s in schedules:
            s.is_active = True
            s.updated_at = utcnow()
        await session.commit()
        print(f"[OK] Da khoi phuc {count} schedules cua user {user_id}.")


async def reset_user(guild_id: int, user_id: int):
    """Deactivate TAT CA schedule cua user. User co the /dangky lai."""
    async with AsyncSessionLocal() as session:
        rows = await session.execute(
            select(MemberSchedule)
            .where(MemberSchedule.guild_id == guild_id)
            .where(MemberSchedule.user_id == user_id)
            .where(MemberSchedule.is_active == True)  # noqa: E712
        )
        schedules = list(rows.scalars().all())
        count = len(schedules)
        if count == 0:
            print(f"User {user_id} khong co active schedule nao.")
            return
        for s in schedules:
            s.is_active = False
            s.updated_at = utcnow()
        await session.commit()
        print(f"[OK] Deactivated {count} schedules cua user {user_id}.")
        print("    User co the chay /dangky de tao lai.")


async def purge_inactive(guild_id: int):
    """Xoa han cac entry inactive (giu lich su qua audit log)."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            delete(MemberSchedule)
            .where(MemberSchedule.guild_id == guild_id)
            .where(MemberSchedule.is_active == False)  # noqa: E712
        )
        await session.commit()
        print(f"[OK] Da xoa {result.rowcount} inactive schedules trong guild {guild_id}.")


def usage():
    print(__doc__)
    sys.exit(1)


async def main():
    if len(sys.argv) < 3:
        usage()
    cmd = sys.argv[1]
    if cmd == "list":
        if len(sys.argv) == 3:
            await list_schedules(int(sys.argv[2]))
        elif len(sys.argv) == 4:
            await list_schedules(int(sys.argv[2]), int(sys.argv[3]))
        else:
            usage()
    elif cmd == "reset":
        if len(sys.argv) != 4:
            usage()
        await reset_user(int(sys.argv[2]), int(sys.argv[3]))
    elif cmd == "restore-all":
        if len(sys.argv) != 3:
            usage()
        await restore_all(int(sys.argv[2]))
    elif cmd == "restore-user":
        if len(sys.argv) != 4:
            usage()
        await restore_user(int(sys.argv[2]), int(sys.argv[3]))
    elif cmd == "purge":
        if len(sys.argv) != 3:
            usage()
        await purge_inactive(int(sys.argv[2]))
    else:
        usage()


if __name__ == "__main__":
    asyncio.run(main())
