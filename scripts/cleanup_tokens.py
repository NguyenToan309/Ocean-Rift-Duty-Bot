r"""
cleanup_tokens.py — Dọn dẹp BlacklistedToken đã hết hạn
Chạy thủ công hoặc đặt lịch (Windows Task Scheduler / cron) hàng ngày.

Cách dùng:
    python scripts/cleanup_tokens.py

Hoặc tự động hàng ngày (Windows Task Scheduler):
    Chương trình: python
    Tham số: E:\Discord\Bot\Duty-bot\scripts\cleanup_tokens.py
    Thư mục khởi động: E:\Discord\Bot\Duty-bot
"""
import asyncio
import sys
import os

# Đảm bảo import từ thư mục gốc
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import delete
from models.base import AsyncSessionLocal
from models.token_blacklist import BlacklistedToken
from bot.utils.time_utils import utcnow


async def cleanup():
    now = utcnow()
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            delete(BlacklistedToken).where(BlacklistedToken.expires_at < now)
        )
        deleted = result.rowcount
        await session.commit()
    print(f"[cleanup_tokens] Đã xóa {deleted} token hết hạn. ({now.strftime('%Y-%m-%d %H:%M UTC')})")


if __name__ == "__main__":
    asyncio.run(cleanup())
