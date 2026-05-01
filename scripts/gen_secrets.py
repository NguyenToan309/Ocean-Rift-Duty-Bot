"""
gen_secrets.py — Tạo các secret key cần thiết cho .env
Chạy: python scripts/gen_secrets.py
Copy giá trị output vào file .env
"""
import secrets
from cryptography.fernet import Fernet

print("=" * 60)
print("DUTY LOGGER — Generated Secrets")
print("Copy các giá trị này vào file .env của bạn")
print("=" * 60)
print()

secret_key = secrets.token_hex(32)
print(f"SECRET_KEY={secret_key}")

fernet_key = Fernet.generate_key().decode()
print(f"FERNET_KEY={fernet_key}")

hmac_secret = secrets.token_hex(32)
print(f"HMAC_SECRET={hmac_secret}")

redis_pass = secrets.token_urlsafe(24)
print(f"REDIS_PASSWORD={redis_pass}")

db_pass = secrets.token_urlsafe(24)
print(f"DB_PASSWORD={db_pass}")

print()
print("⚠️  Lưu ý:")
print("  - Không chia sẻ các giá trị này với bất kỳ ai")
print("  - Không commit file .env lên git")
print("  - Backup .env ở nơi an toàn")
