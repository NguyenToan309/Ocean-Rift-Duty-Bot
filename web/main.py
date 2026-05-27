"""
web/main.py — FastAPI app entrypoint
Chạy song song với bot bằng: uvicorn web.main:app --host 0.0.0.0 --port 8000
"""
import logging
import os
import sys

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.config import settings
from web.middleware.rate_limit import limiter
from web.routers import auth, dashboard, export, audit, schedule, leave, realtime, staff, admin, setup as setup_router

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Homie Medic Dashboard",
    description="Web dashboard nội bộ cho hệ thống chấm công Discord",
    version="1.0.0",
    docs_url="/docs" if settings.DEBUG else None,   # Ẩn Swagger khi production
    redoc_url=None,
)

# ----- Rate Limiter -----
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ----- CORS — chỉ cho phép domain nội bộ -----
# Dev: tự thêm http://localhost:3000 (Vite dev server). Production: bám settings.
_cors_origins = list(settings.ALLOWED_ORIGINS)
if settings.DEBUG and "http://localhost:3000" not in _cors_origins:
    _cors_origins.append("http://localhost:3000")
if settings.DEBUG and "http://127.0.0.1:3000" not in _cors_origins:
    _cors_origins.append("http://127.0.0.1:3000")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,    # Cần True để gửi cookie
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# ----- CSRF protection (Origin-based) -----
# Phòng tuyến 1: SameSite=Lax/Strict cookies (đã có ở auth.py)
# Phòng tuyến 2: Origin header check — chặn POST/PUT/DELETE từ origin khác whitelist.
# Browser luôn gửi Origin trên non-GET requests (trừ navigation). Nếu thiếu hoặc không khớp → reject.
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_ALLOWED_ORIGINS_SET = {o.rstrip("/") for o in _cors_origins}


@app.middleware("http")
async def csrf_origin_guard(request: Request, call_next):
    """Reject mutation requests có Origin không thuộc whitelist.

    Origin TRỐNG hoặc Origin SAI đều bị reject, kể cả khi DEBUG=true. Browser
    luôn gửi Origin trên non-GET requests; request không có Origin là dấu hiệu
    CSRF/script lạ. Dev khi dùng curl/httpie phải set:
        -H "Origin: http://localhost:3000"
    """
    if request.method not in _SAFE_METHODS:
        origin = request.headers.get("origin", "").rstrip("/")
        if not origin:
            logger.warning(f"CSRF: blocked {request.method} {request.url.path} (no Origin header)")
            return JSONResponse(
                status_code=403,
                content={"error": "Thiếu Origin header", "detail": "CSRF protection"},
            )
        if origin not in _ALLOWED_ORIGINS_SET:
            logger.warning(f"CSRF: blocked {request.method} {request.url.path} from origin={origin}")
            return JSONResponse(
                status_code=403,
                content={"error": "Origin không được phép", "detail": "CSRF protection"},
            )
    return await call_next(request)


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
    # CSP — phục vụ React SPA (Vite bundle) + Google Fonts + legacy Tailwind CDN của Jinja cũ.
    # 'unsafe-inline' bắt buộc cho Vite injected styles + một số inline script trong template cũ.
    # WebSocket dùng ws:/wss: scheme generic. Trong DEBUG nới connect-src cho HMR.
    debug_extras = " ws://localhost:* http://localhost:*" if settings.DEBUG else ""
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' "
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
            "ws: wss: "                          # WebSocket cho real-time
            "https://cdn.jsdelivr.net "
            "https://unpkg.com"
            f"{debug_extras}; "
        "frame-ancestors 'none'; "      # Tăng cường chống clickjacking
        "base-uri 'self'; "             # Chặn <base href=...> attack
        "form-action 'self';"           # Form chỉ submit lên cùng origin
    )
    return response


# ----- Static files & Templates -----
_static_dir = os.path.join(os.path.dirname(__file__), "static")
_template_dir = os.path.join(os.path.dirname(__file__), "templates")
# React build output (homie-medic-dashboard/dist) — sinh ra bởi `npm run build`.
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_react_dist = os.path.join(_project_root, "homie-medic-dashboard", "dist")
_react_available = os.path.isdir(_react_dist) and os.path.isfile(os.path.join(_react_dist, "index.html"))

if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")

# Mount asset chunks của React (Vite mặc định bỏ trong /assets/)
if _react_available:
    _react_assets = os.path.join(_react_dist, "assets")
    if os.path.isdir(_react_assets):
        app.mount("/assets", StaticFiles(directory=_react_assets), name="react_assets")
    logger.info(f"[REACT] Serving SPA from {_react_dist}")
else:
    logger.info("[REACT] dist/ chưa build — fallback Jinja templates. Chạy `npm run build` trong homie-medic-dashboard/ để bật SPA.")

templates = Jinja2Templates(directory=_template_dir)

# ----- Routers -----
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(export.router)
app.include_router(audit.router)
app.include_router(schedule.router)
app.include_router(leave.router)
app.include_router(realtime.router)
app.include_router(staff.router)
app.include_router(admin.router)
app.include_router(setup_router.router)


# ----- Pages -----
# Khi đã có React build: serve index.html cho mọi route không khớp API/static.
# Chưa build: fallback Jinja templates cũ.
from fastapi.responses import FileResponse


def _serve_react_index(request: Request) -> FileResponse:
    """Serve React SPA index.html — client-side router của React lo phần còn lại."""
    return FileResponse(
        os.path.join(_react_dist, "index.html"),
        media_type="text/html",
        headers={"Cache-Control": "no-cache, must-revalidate"},  # index.html không cache
    )


@app.get("/")
async def index(request: Request):
    """
    Root. Nếu có cookie access_token hợp lệ → React SPA tự handle (gọi /api/dashboard/me).
    Nếu cookie expired, sai type, hoặc đã bị revoke (jti blacklist) → xoá cookie
    rồi serve index để user thấy login.
    """
    token = request.cookies.get("access_token")
    invalid_token = False
    if token and not request.query_params.get("require_2fa"):
        # Dùng decode_token() để áp dụng cùng tập rule như API:
        # check signature + exp + type=="access" + jti chưa bị blacklist.
        # Tránh trường hợp cookie zombie (sau logout/2FA reset) vẫn hợp lệ
        # về cryptography mà không bị xoá.
        from models.base import AsyncSessionLocal
        from web.routers.auth import decode_token
        try:
            async with AsyncSessionLocal() as session:
                await decode_token(token, session, expected_type="access")
        except Exception:
            invalid_token = True

    if _react_available:
        response = _serve_react_index(request)
    else:
        response = templates.TemplateResponse("index.html", {"request": request})

    if invalid_token:
        response.delete_cookie("access_token")
        response.delete_cookie("refresh_token")
        response.delete_cookie("2fa_pending")
    return response


@app.get("/dashboard")
async def dashboard_page(request: Request):
    if _react_available:
        return _serve_react_index(request)
    return templates.TemplateResponse("dashboard.html", {"request": request})


# ----- Health check (không yêu cầu auth) -----
@app.get("/health")
async def health():
    return {"status": "ok"}


# ----- SPA Catch-all -----
# React Router dùng client-side routing. Khi user F5 ở /rankings, /staff, /settings...,
# browser gửi GET tới FastAPI. FastAPI cần trả index.html để React Router xử lý URL.
# CHỈ áp dụng cho route không bắt đầu bằng /api/, /auth/, /ws, /assets/, /static/.
SPA_KNOWN_ROUTES = {
    "login", "settings", "staff", "duty-logs", "schedule",
    "leave-requests", "resign-requests", "rankings", "audit-log",
    "403", "404", "500",
}


@app.get("/{full_path:path}")
async def spa_catch_all(full_path: str, request: Request):
    """Serve React SPA cho mọi route không match API/static. React Router lo phần còn lại."""
    # Bỏ qua các prefix API/static — để FastAPI 404 đúng nghĩa
    if full_path.startswith(("api/", "auth/", "ws", "assets/", "static/")):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Not Found")
    # Nếu có .ext (file thật) → 404 (không serve index cho file requests)
    if "." in full_path.split("/")[-1] and not full_path.endswith(".html"):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Not Found")

    if _react_available:
        return _serve_react_index(request)
    return templates.TemplateResponse("index.html", {"request": request})


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
