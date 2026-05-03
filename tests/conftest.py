"""
conftest.py — Fixtures dùng chung cho toàn bộ test suite

Thứ tự import:
1. Mock heavy deps (easyocr, redis) TRƯỚC khi import bất kỳ module nào
2. Set env vars bắt buộc
3. Khai báo fixtures

Chạy toàn bộ:   pytest
Chạy 1 file:     pytest tests/test_parser.py -v
Chạy 1 test:     pytest tests/test_parser.py::test_parse_valid_log -v
Coverage:         pytest --cov=bot --cov-report=html
"""
import sys
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, AsyncMock

# ─── Mock heavy dependencies trước khi import bất kỳ thứ gì ───────────────
# easyocr tải model ~500MB khi import → mock để tests không cần model thật
_easyocr_mock = MagicMock()
_easyocr_mock.Reader.return_value = MagicMock()
sys.modules.setdefault("easyocr", _easyocr_mock)

# redis.asyncio mock (tests không cần Redis thật)
_redis_mock = MagicMock()
sys.modules.setdefault("redis", _redis_mock)
sys.modules.setdefault("redis.asyncio", _redis_mock)
# ──────────────────────────────────────────────────────────────────────────

# Patch starlette UTF-8 đã được áp dụng trong bot/config.py — không cần lặp lại ở đây.
# (config.py được import sớm nhất qua time_utils → tự xử lý cho cả tests và runtime.)

# Set env vars bắt buộc TRƯỚC khi import settings
os.environ.setdefault("DISCORD_BOT_TOKEN",     "test_bot_token_xxxxx")
os.environ.setdefault("DISCORD_CLIENT_ID",     "123456789012345678")
os.environ.setdefault("DISCORD_CLIENT_SECRET", "test_client_secret")
os.environ.setdefault("DISCORD_REDIRECT_URI",  "http://localhost:8000/auth/callback")
os.environ.setdefault("DB_USER",               "test_user")
os.environ.setdefault("DB_PASSWORD",           "test_password")
os.environ.setdefault("DB_NAME",               "test_duty_logger")
os.environ.setdefault("SECRET_KEY",            "a" * 64)
os.environ.setdefault("FERNET_KEY",            "ZmDfcTF7_60GrrY167zsiPd67pEvs0aGOv2oasOM1Pg=")
os.environ.setdefault("HMAC_SECRET",           "b" * 64)
os.environ.setdefault("REDIS_PASSWORD",        "")
os.environ.setdefault("DEBUG",                 "True")

import pytest
from bot.utils.time_utils import utcnow

# ─── Hằng số dùng trong tests ─────────────────────────────────────────────
GUILD_ID   = 111222333444555666
USER_ID    = 999888777666555444
MOD_ID     = 100200300400500600
ADMIN_ID   = 777666555444333222

# Timestamps chuẩn: ngày 01/05/2026, múi giờ UTC (= 08:00 ICT - 7h = 01:00 UTC)
T_START    = datetime(2026, 5, 1,  1, 0, 0, tzinfo=timezone.utc)   # 08:00 ICT
T_END      = datetime(2026, 5, 1,  3, 0, 0, tzinfo=timezone.utc)   # 10:00 ICT
T_MID      = datetime(2026, 5, 1,  2, 0, 0, tzinfo=timezone.utc)   # 09:00 ICT


# ─── Text fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def valid_log_text() -> str:
    """LOG DUTY hợp lệ chuẩn — 120 phút ngày 01/05/2026"""
    return (
        "LOG DUTY\n"
        "Tên: Nguyễn Văn A\n"
        "Thời gian làm việc: 120 phút\n"
        "Thời gian bắt đầu: 01/05/2026 08:00:00\n"
        "Thời gian kết thúc: 01/05/2026 10:00:00\n"
        "made by • DutyBot Friday May 01 08:00:00 2026"
    )

@pytest.fixture
def valid_log_text_90() -> str:
    """LOG DUTY hợp lệ — 90 phút"""
    return (
        "LOG DUTY\n"
        "Tên: Trần Thị B\n"
        "Thời gian làm việc: 90 phút\n"
        "Thời gian bắt đầu: 01/05/2026 14:00:00\n"
        "Thời gian kết thúc: 01/05/2026 15:30:00\n"
        "made by • DutyBot Friday May 01 14:00:00 2026"
    )

@pytest.fixture
def past_log_text() -> str:
    """LOG DUTY từ tháng trước — phải được chấp nhận"""
    return (
        "LOG DUTY\n"
        "Tên: Lê Văn C\n"
        "Thời gian làm việc: 60 phút\n"
        "Thời gian bắt đầu: 15/04/2026 09:00:00\n"
        "Thời gian kết thúc: 15/04/2026 10:00:00\n"
        "made by • DutyBot Wednesday April 15 09:00:00 2026"
    )

@pytest.fixture
def sample_duty_log_text() -> str:
    """Backward compat với test cũ"""
    return (
        "LOG DUTY\n"
        "Tên: Nguyễn Văn Test\n"
        "Thời gian làm việc: 90 phút\n"
        "Thời gian bắt đầu: 27/04/2026 09:00:00\n"
        "Thời gian kết thúc: 27/04/2026 10:30:00\n"
        "made by • DutyBot Sunday April 27 09:00:00 2026"
    )


# ─── Mock Discord object factories ────────────────────────────────────────

def make_discord_user(
    user_id: int = USER_ID,
    name: str = "testuser",
    display_name: str = "Test User",
    global_name: str | None = None,
    nick: str | None = None,
) -> MagicMock:
    """Tạo mock Discord Member/User"""
    user = MagicMock()
    user.id = user_id
    user.name = name
    user.display_name = display_name
    user.global_name = global_name
    user.nick = nick
    user.bot = False
    return user


def make_discord_role(role_id: int, name: str) -> MagicMock:
    role = MagicMock()
    role.id = role_id
    role.name = name
    return role


def make_guild_config_mock(
    guild_id: int = GUILD_ID,
    admin_role_id: int = 101,
    mod_role_id: int = 102,
    member_role_id: int = 103,
    log_channel_id: int | None = None,
    timezone: str = "Asia/Ho_Chi_Minh",
    is_active: bool = True,
) -> MagicMock:
    config = MagicMock()
    config.guild_id = guild_id
    config.is_active = is_active
    config.log_channel_id = log_channel_id
    config.timezone = timezone
    config.guild_name = "Test Guild"
    config.role_map = {
        "DUTY_ADMIN":  str(admin_role_id),
        "DUTY_MOD":    str(mod_role_id),
        "DUTY_MEMBER": str(member_role_id),
    }
    return config


# ─── Mock DB Session factory ───────────────────────────────────────────────

def make_session(*execute_return_values) -> AsyncMock:
    """
    Tạo mock AsyncSession với kết quả execute() được định nghĩa trước.
    Mỗi phần tử trong execute_return_values là giá trị .scalar_one_or_none() trả về
    cho lần execute() tương ứng (theo thứ tự).

    Ví dụ:
        session = make_session(None, None)          # 2 execute, cả hai trả None
        session = make_session(None, some_log_obj)  # execute #2 trả log (overlap)
    """
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    values = list(execute_return_values)
    call_idx = [0]

    async def mock_execute(query, *args, **kwargs):
        result = MagicMock()
        idx = call_idx[0]
        call_idx[0] += 1
        val = values[idx] if idx < len(values) else None
        result.scalar_one_or_none.return_value = val
        return result

    session.execute = mock_execute
    return session


def make_duty_log_mock(
    log_id: int = 1,
    started_at: datetime = T_START,
    ended_at: datetime = T_END,
    duration_minutes: int = 120,
    username: str = "Nguyễn Văn A",
    guild_id: int = GUILD_ID,
    user_id: int = USER_ID,
) -> MagicMock:
    """Tạo mock DutyLog object để dùng trong overlap/duplicate checks"""
    log = MagicMock()
    log.id = log_id
    log.guild_id = guild_id
    log.user_id = user_id
    log.username = username
    log.started_at = started_at
    log.ended_at = ended_at
    log.duration_minutes = duration_minutes
    log.source = "message"
    return log


# ─── Fixtures dùng cho nhiều test file ────────────────────────────────────

@pytest.fixture
def mock_user():
    return make_discord_user()

@pytest.fixture
def guild_config():
    return make_guild_config_mock()

@pytest.fixture
def past_start() -> datetime:
    """Thời điểm bắt đầu ca trong quá khứ (an toàn để test)"""
    return utcnow() - timedelta(hours=5)

@pytest.fixture
def past_end() -> datetime:
    """Thời điểm kết thúc ca trong quá khứ"""
    return utcnow() - timedelta(hours=3)

@pytest.fixture
def future_start() -> datetime:
    """Thời điểm bắt đầu ca trong tương lai (phải bị chặn)"""
    return utcnow() + timedelta(hours=2)

@pytest.fixture
def future_end() -> datetime:
    return utcnow() + timedelta(hours=4)
