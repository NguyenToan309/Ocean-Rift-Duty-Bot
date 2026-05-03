"""
rate_limit.py — Khởi tạo SlowAPI limiter dùng chung toàn web app
Import `limiter` vào các router cần rate limit.

Key function thông minh:
- Ưu tiên `user:<sub>` (từ JWT cookie) cho user đã đăng nhập → tránh false-positive
  khi nhiều user qua cùng IP (proxy/VPN/CGNAT/NAT-ed office chia chung 1 IP).
- Fallback `ip:<addr>` cho user chưa đăng nhập (login, callback, refresh).
"""
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def _smart_key(request: Request) -> str:
    """
    Key ưu tiên user_id, fallback IP. Decode JWT chỉ để lấy sub
    (không validate exp — endpoint sẽ tự authenticate qua require_auth).
    """
    token = request.cookies.get("access_token")
    if token:
        try:
            from jose import jwt
            from bot.config import settings
            payload = jwt.decode(
                token, settings.SECRET_KEY, algorithms=["HS256"],
                options={"verify_exp": False},
            )
            sub = payload.get("sub")
            if sub:
                return f"user:{sub}"
        except Exception:
            pass
    return f"ip:{get_remote_address(request)}"


limiter = Limiter(key_func=_smart_key)
