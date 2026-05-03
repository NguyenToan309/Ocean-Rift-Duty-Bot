"""
config.py — Load toàn bộ biến môi trường từ .env
Tất cả module khác import Settings từ đây, không dùng os.getenv trực tiếp

Hỗ trợ 2 mode env vars:
1. Local/VPS: DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD (từ .env)
2. Cloud (Railway/Render/Heroku): DATABASE_URL + REDIS_URL trực tiếp
"""
import os
from functools import lru_cache
from urllib.parse import urlparse, unquote
from dotenv import load_dotenv


# ─── Patch starlette.config để tránh lỗi cp1252 đọc .env trên Windows ────────
# Starlette dùng mã hoá hệ thống (cp1252 trên Windows tiếng Việt) → nếu .env
# có bất kỳ ký tự non-ASCII (vd tiếng Việt trong comment) → UnicodeDecodeError
# Slowapi gọi starlette.config.Config() → blocking khi import web.main
# Patch ở đây vì bot/config.py được mọi module (bot, web, scripts) import sớm
def _patch_starlette_config_encoding() -> None:
    try:
        import starlette.config as _sc
        if getattr(_sc.Config, "_dutybot_patched", False):
            return
        _orig_read = _sc.Config._read_file

        def _safe_read_file(self, file_path):
            if file_path is None:
                return {}
            try:
                return _orig_read(self, file_path)
            except UnicodeDecodeError:
                # Fallback: đọc lại bằng UTF-8 và parse thủ công
                import codecs
                try:
                    data = {}
                    with codecs.open(str(file_path), encoding="utf-8-sig") as f:
                        for line in f:
                            line = line.strip()
                            if not line or line.startswith("#") or "=" not in line:
                                continue
                            k, _, v = line.partition("=")
                            data[k.strip()] = v.strip().strip("\"'")
                    return data
                except Exception:
                    return {}

        _sc.Config._read_file = _safe_read_file
        _sc.Config._dutybot_patched = True
    except (ImportError, AttributeError):
        pass

_patch_starlette_config_encoding()
# ──────────────────────────────────────────────────────────────────────────────

load_dotenv(encoding="utf-8")


def _parse_database_url(url: str) -> dict:
    """Parse postgres://user:pass@host:port/db → dict components."""
    p = urlparse(url)
    return {
        "user":     unquote(p.username or ""),
        "password": unquote(p.password or ""),
        "host":     p.hostname or "localhost",
        "port":     p.port or 5432,
        "name":     (p.path or "/").lstrip("/") or "postgres",
    }


def _parse_redis_url(url: str) -> dict:
    """Parse redis://[:pass@]host:port[/db] → dict."""
    p = urlparse(url)
    db = 0
    if p.path and p.path != "/":
        try:
            db = int(p.path.lstrip("/"))
        except ValueError:
            pass
    return {
        "host":     p.hostname or "localhost",
        "port":     p.port or 6379,
        "password": unquote(p.password or "") if p.password else "",
        "db":       db,
    }


class Settings:
    # ----- Discord -----
    DISCORD_BOT_TOKEN: str = os.environ["DISCORD_BOT_TOKEN"]
    DISCORD_CLIENT_ID: int = int(os.environ["DISCORD_CLIENT_ID"])
    DISCORD_CLIENT_SECRET: str = os.environ["DISCORD_CLIENT_SECRET"]
    DISCORD_REDIRECT_URI: str = os.environ["DISCORD_REDIRECT_URI"]

    # ----- Database -----
    # Cloud (Railway/Render): DATABASE_URL được set sẵn
    # Local: dùng từng biến rời
    _db_url_env = os.getenv("DATABASE_URL", "").strip()
    if _db_url_env:
        _db = _parse_database_url(_db_url_env)
        DB_HOST     = _db["host"]
        DB_PORT     = _db["port"]
        DB_NAME     = _db["name"]
        DB_USER     = _db["user"]
        DB_PASSWORD = _db["password"]
    else:
        DB_HOST     = os.getenv("DB_HOST", "localhost")
        DB_PORT     = int(os.getenv("DB_PORT", "5432"))
        DB_NAME     = os.getenv("DB_NAME", "duty_logger")
        DB_USER     = os.environ["DB_USER"]
        DB_PASSWORD = os.environ["DB_PASSWORD"]

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    @property
    def DATABASE_URL_SYNC(self) -> str:
        """Dùng cho Alembic migration (sync driver)"""
        return (
            f"postgresql+psycopg2://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    # ----- Redis -----
    _redis_url_env = os.getenv("REDIS_URL", "").strip()
    if _redis_url_env:
        _r = _parse_redis_url(_redis_url_env)
        REDIS_HOST     = _r["host"]
        REDIS_PORT     = _r["port"]
        REDIS_PASSWORD = _r["password"]
        REDIS_DB       = _r["db"]
    else:
        REDIS_HOST     = os.getenv("REDIS_HOST", "localhost")
        REDIS_PORT     = int(os.getenv("REDIS_PORT", "6379"))
        REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
        REDIS_DB       = int(os.getenv("REDIS_DB", "0"))

    @property
    def REDIS_URL(self) -> str:
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # ----- JWT -----
    SECRET_KEY: str = os.environ["SECRET_KEY"]
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
    REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

    # ----- Mã hoá -----
    FERNET_KEY: str = os.environ["FERNET_KEY"]
    HMAC_SECRET: str = os.environ["HMAC_SECRET"]

    # ----- Web -----
    # Cloud platforms (Railway/Render/Heroku) inject PORT — fallback WEB_PORT cho local
    WEB_HOST: str = os.getenv("WEB_HOST", "0.0.0.0")
    WEB_PORT: int = int(os.getenv("PORT") or os.getenv("WEB_PORT", "8000"))
    ALLOWED_ORIGINS: list[str] = os.getenv("ALLOWED_ORIGINS", "http://localhost:8000").split(",")
    DEBUG: bool = os.getenv("DEBUG", "False").lower() == "true"

    # ----- Export -----
    EXPORT_DIR: str = os.getenv("EXPORT_DIR", "/tmp/duty-exports")
    EXPORT_TTL_MINUTES: int = int(os.getenv("EXPORT_TTL_MINUTES", "10"))

    # ----- Timezone -----
    DEFAULT_TIMEZONE: str = os.getenv("DEFAULT_TIMEZONE", "Asia/Ho_Chi_Minh")

    # ----- File upload giới hạn -----
    MAX_FILE_SIZE_MB: int = 5
    ALLOWED_IMAGE_MIME: frozenset[str] = frozenset({"image/jpeg", "image/png", "image/webp"})


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton — dùng dependency injection trong FastAPI hoặc import trực tiếp"""
    return Settings()


# Shortcut để import nhanh
settings = get_settings()
