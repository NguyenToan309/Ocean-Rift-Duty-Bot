"""
rate_limit.py — Khởi tạo SlowAPI limiter dùng chung toàn web app
Import `limiter` vào các router cần rate limit
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

# Key function: giới hạn theo IP
limiter = Limiter(key_func=get_remote_address)
