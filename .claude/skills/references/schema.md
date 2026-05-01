# Database Schema — Duty Logger

## Bảng: guild_configs
```sql
CREATE TABLE guild_configs (
    id              BIGSERIAL PRIMARY KEY,
    guild_id        BIGINT UNIQUE NOT NULL,
    guild_name      VARCHAR(100),
    log_channel_id  BIGINT,
    timezone        VARCHAR(50) DEFAULT 'Asia/Ho_Chi_Minh',
    role_admin      BIGINT,        -- Discord role ID cho DUTY_ADMIN
    role_mod        BIGINT,        -- Discord role ID cho DUTY_MOD
    role_member     BIGINT,        -- Discord role ID cho DUTY_MEMBER
    whitelist_channels  BIGINT[],  -- Chỉ nhận log từ các channel này
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
```

## Bảng: users
```sql
CREATE TABLE users (
    id          BIGSERIAL PRIMARY KEY,
    discord_id  BIGINT UNIQUE NOT NULL,
    username    VARCHAR(100) NOT NULL,
    avatar_url  TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);
```

## Bảng: duty_logs (bảng chính)
```sql
CREATE TABLE duty_logs (
    id              BIGSERIAL PRIMARY KEY,
    guild_id        BIGINT NOT NULL REFERENCES guild_configs(guild_id),
    user_id         BIGINT NOT NULL REFERENCES users(discord_id),
    username        VARCHAR(100) NOT NULL,   -- snapshot tại thời điểm log
    duration_minutes INTEGER NOT NULL CHECK (duration_minutes > 0),
    started_at      TIMESTAMPTZ NOT NULL,
    ended_at        TIMESTAMPTZ NOT NULL,
    source          VARCHAR(20) NOT NULL DEFAULT 'ocr',  -- 'ocr' | 'forward' | 'manual'
    raw_text        TEXT,                    -- text gốc từ OCR/forward
    message_id      BIGINT,                  -- Discord message ID gốc
    logged_by       BIGINT,                  -- Discord user ID người upload
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Index bắt buộc để query thống kê nhanh
CREATE INDEX idx_duty_logs_guild_date ON duty_logs(guild_id, started_at DESC);
CREATE INDEX idx_duty_logs_guild_user ON duty_logs(guild_id, user_id);
CREATE INDEX idx_duty_logs_user_date  ON duty_logs(user_id, started_at DESC);
```

## Bảng: audit_logs
```sql
CREATE TABLE audit_logs (
    id          BIGSERIAL PRIMARY KEY,
    guild_id    BIGINT NOT NULL,
    user_id     BIGINT NOT NULL,
    action      VARCHAR(50) NOT NULL,  -- 'EXPORT_CSV','DELETE_LOG','CHANGE_ROLE','LOGIN','LOGOUT'
    detail      JSONB DEFAULT '{}',
    ip_address  INET,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_audit_logs_guild ON audit_logs(guild_id, created_at DESC);
```

## Bảng: token_blacklist
```sql
CREATE TABLE token_blacklist (
    jti         VARCHAR(64) PRIMARY KEY,   -- JWT ID
    user_id     BIGINT NOT NULL,
    expired_at  TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Tự xóa token hết hạn (chạy cron hàng ngày)
CREATE INDEX idx_token_blacklist_exp ON token_blacklist(expired_at);
```

## Bảng: web_sessions (cho 2FA)
```sql
CREATE TABLE web_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         BIGINT NOT NULL,
    guild_id        BIGINT,
    totp_verified   BOOLEAN DEFAULT FALSE,
    ip_address      INET,
    user_agent      TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    last_active_at  TIMESTAMPTZ DEFAULT NOW(),
    expired_at      TIMESTAMPTZ NOT NULL
);
```

## Query thống kê TOP chuẩn

```sql
-- Top trực theo khoảng thời gian
SELECT
    user_id,
    username,
    COUNT(*) AS session_count,
    SUM(duration_minutes) AS total_minutes,
    ROUND(AVG(duration_minutes), 1) AS avg_minutes
FROM duty_logs
WHERE guild_id = :guild_id
  AND started_at >= :start_date
  AND started_at <= :end_date
GROUP BY user_id, username
ORDER BY total_minutes DESC
LIMIT 10;
```

## SQLAlchemy Models

```python
# models/duty_log.py
from sqlalchemy import Column, BigInteger, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import INET, JSONB
from .base import Base

class DutyLog(Base):
    __tablename__ = "duty_logs"

    id               = Column(BigInteger, primary_key=True, autoincrement=True)
    guild_id         = Column(BigInteger, nullable=False, index=True)
    user_id          = Column(BigInteger, nullable=False)
    username         = Column(String(100), nullable=False)
    duration_minutes = Column(Integer, nullable=False)
    started_at       = Column(DateTime(timezone=True), nullable=False)
    ended_at         = Column(DateTime(timezone=True), nullable=False)
    source           = Column(String(20), default="ocr")
    raw_text         = Column(Text)
    message_id       = Column(BigInteger)
    logged_by        = Column(BigInteger)
    created_at       = Column(DateTime(timezone=True), server_default="NOW()")
```