"""
web/main.py — FastAPI app entrypoint
Chạy song song với bot bằng: uvicorn web.main:app --host 0.0.0.0 --port 8000
"""
import logging
import os
import sys

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.config import settings
from web.middleware.rate_limit import limiter
from web.routers import auth, dashboard, export, audit

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Duty Logger Dashboard",
    description="Web dashboard nội bộ cho hệ thống chấm công Discord",
    version="1.0.0",
    docs_url="/docs" if settings.DEBUG else None,   # Ẩn Swagger khi production
    redoc_url=None,
)

# ----- Rate Limiter -----
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ----- CORS — chỉ cho phép domain nội bộ -----
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,    # Cần True để gửi cookie
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

# ----- Security Headers middleware -----
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if not settings.DEBUG:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    # CSP — cho phép CDN cần thiết: Tailwind, Lucide, Chart.js, Google Fonts
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
            "https://cdn.tailwindcss.com "
            "https://unpkg.com "
            "https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' "
            "https://fonts.googleapis.com "
            "https://cdn.jsdelivr.net; "
        "font-src 'self' "
            "https://fonts.gstatic.com "
            "data:; "
        "img-src 'self' https://cdn.discordapp.com data: blob:; "
        "connect-src 'self' "
            "https://cdn.jsdelivr.net "
            "https://unpkg.com;"
    )
    return response


# ----- Static files & Templates -----
_static_dir = os.path.join(os.path.dirname(__file__), "static")
_template_dir = os.path.join(os.path.dirname(__file__), "templates")

if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")

templates = Jinja2Templates(directory=_template_dir)

# ----- Routers -----
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(export.router)
app.include_router(audit.router)


# ----- Pages (Jinja2) -----
@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/dashboard")
async def dashboard_page(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})


# ----- Health check (không yêu cầu auth) -----
@app.get("/health")
async def health():
    return {"status": "ok"}


# ----- Global error handler -----
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(
        f"Unhandled exception @ {request.method} {request.url.path}: "
        f"{type(exc).__name__}: {exc}",
        exc_info=True,
    )
    # DEBUG mode: trả chi tiết để debug; Production: chỉ message generic
    if settings.DEBUG:
        import traceback
        return JSONResponse(
            status_code=500,
            content={
                "error": "Lỗi server (DEBUG)",
                "type": type(exc).__name__,
                "message": str(exc),
                "path": str(request.url.path),
                "traceback": traceback.format_exc().splitlines()[-15:],
            },
        )
    return JSONResponse(
        status_code=500,
        content={"error": "Đã xảy ra lỗi server", "status": 500},
    )
