"""
base.py — SQLAlchemy Base, async engine, session factory
Tất cả model kế thừa từ Base ở đây
"""
import sys
import os

# Cho phép import từ thư mục gốc dự án
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from bot.config import settings


class Base(DeclarativeBase):
    pass


# Engine async — dùng cho toàn bộ ứng dụng
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,       # Log SQL khi DEBUG=True
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,        # Kiểm tra connection trước khi dùng
)

# Session factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,    # Tránh lazy-load lỗi sau commit
    autoflush=False,
)


async def get_db() -> AsyncSession:
    """Dependency injection cho FastAPI — trả về async session"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def create_all_tables():
    """Tạo tất cả bảng — chỉ dùng khi dev, production dùng alembic"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
