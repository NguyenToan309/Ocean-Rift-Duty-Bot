"""
conftest.py — Pytest fixtures dùng chung cho tất cả tests
Setup: database test, mock settings
"""
import os
import pytest
import pytest_asyncio

# Override env vars TRƯỚC khi import bất kỳ module nào dùng settings
os.environ.setdefault("DISCORD_BOT_TOKEN",     "test_token")
os.environ.setdefault("DISCORD_CLIENT_ID",     "123456789")
os.environ.setdefault("DISCORD_CLIENT_SECRET", "test_secret")
os.environ.setdefault("DISCORD_REDIRECT_URI",  "http://localhost/callback")
os.environ.setdefault("DB_USER",               "test")
os.environ.setdefault("DB_PASSWORD",           "test")
os.environ.setdefault("DB_NAME",               "test_duty")
os.environ.setdefault("SECRET_KEY",            "a" * 64)
os.environ.setdefault("FERNET_KEY",            "ZmDfcTF7_60GrrY167zsiPd67pEvs0aGOv2oasOM1Pg=")
os.environ.setdefault("HMAC_SECRET",           "b" * 64)
os.environ.setdefault("REDIS_PASSWORD",        "")
os.environ.setdefault("DEBUG",                 "True")


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture
def sample_duty_log_text() -> str:
    return (
        "LOG DUTY\n"
        "Tên: Nguyễn Văn Test\n"
        "Thời gian làm việc: 90 phút\n"
        "Thời gian bắt đầu: 27/04/2026 09:00:00\n"
        "Thời gian kết thúc: 27/04/2026 10:30:00\n"
        "made by • DutyBot Sunday April 27 09:00:00 2026"
    )
