# Auth & Bảo mật — Duty Logger

## Discord OAuth2 Flow

```
User click "Login with Discord"
  → /oauth/login → redirect sang Discord
  → Discord callback → /oauth/callback?code=...
  → Exchange code → access_token Discord
  → Fetch user info từ Discord API
  → Tạo/update user trong DB
  → Nếu DUTY_ADMIN → yêu cầu 2FA TOTP
  → Tạo JWT access + refresh token
  → Set cookie HttpOnly + Secure
```

```python
# web/routers/auth.py

DISCORD_AUTH_URL = "https://discord.com/api/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_USER_URL = "https://discord.com/api/users/@me"

async def exchange_code(code: str) -> dict:
    """Đổi authorization code lấy access token Discord"""
    async with httpx.AsyncClient() as client:
        r = await client.post(DISCORD_TOKEN_URL, data={
            "client_id": settings.DISCORD_CLIENT_ID,
            "client_secret": settings.DISCORD_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.DISCORD_REDIRECT_URI,
        })
        return r.json()
```

## JWT — Tạo và Verify

```python
ACCESS_TOKEN_EXPIRE  = timedelta(minutes=15)
REFRESH_TOKEN_EXPIRE = timedelta(days=7)

def create_access_token(user_id: int, guild_id: int) -> str:
    jti = secrets.token_hex(16)
    payload = {
        "sub": str(user_id),
        "guild_id": guild_id,
        "type": "access",
        "jti": jti,
        "exp": datetime.utcnow() + ACCESS_TOKEN_EXPIRE,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")

async def verify_token(token: str, session: AsyncSession) -> dict:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token hết hạn")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token không hợp lệ")
    
    # Kiểm tra blacklist
    jti = payload.get("jti")
    blacklisted = await session.get(TokenBlacklist, jti)
    if blacklisted:
        raise HTTPException(status_code=401, detail="Token đã bị thu hồi")
    
    return payload
```

## 2FA TOTP (cho DUTY_ADMIN)

```python
import pyotp
import qrcode
import io

def generate_totp_secret() -> str:
    return pyotp.random_base32()

def generate_qr_code(secret: str, username: str) -> bytes:
    """Tạo QR code để user quét vào Google Authenticator"""
    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(username, issuer_name="DutyLogger")
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def verify_totp(secret: str, code: str) -> bool:
    """Verify mã 6 số từ Google Authenticator"""
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)  # cho phép lệch 1 khoảng (30s)
```

## Brute Force Protection

```python
# Lưu số lần đăng nhập sai trong Redis
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION    = 900  # 15 phút

async def check_brute_force(redis_client, ip: str):
    key = f"login_fail:{ip}"
    attempts = await redis_client.get(key)
    if attempts and int(attempts) >= MAX_FAILED_ATTEMPTS:
        raise HTTPException(
            status_code=429,
            detail="Tài khoản bị khóa 15 phút do đăng nhập sai nhiều lần"
        )

async def record_failed_login(redis_client, ip: str):
    key = f"login_fail:{ip}"
    await redis_client.incr(key)
    await redis_client.expire(key, LOCKOUT_DURATION)

async def clear_failed_login(redis_client, ip: str):
    await redis_client.delete(f"login_fail:{ip}")
```

## Security Headers (Nginx config)

```nginx
# /etc/nginx/sites-available/duty-logger
server {
    listen 443 ssl;
    server_name your-internal-domain.local;

    ssl_certificate     /etc/ssl/duty-logger.crt;
    ssl_certificate_key /etc/ssl/duty-logger.key;

    # Security Headers
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'" always;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

## Cookie chuẩn

```python
def set_auth_cookie(response: Response, token: str, token_type: str = "access"):
    max_age = 900 if token_type == "access" else 604800  # 15 phút hoặc 7 ngày
    response.set_cookie(
        key=f"{token_type}_token",
        value=token,
        max_age=max_age,
        httponly=True,      # Chống XSS
        secure=True,        # Chỉ qua HTTPS
        samesite="lax",     # Chống CSRF
        path="/",
    )
```