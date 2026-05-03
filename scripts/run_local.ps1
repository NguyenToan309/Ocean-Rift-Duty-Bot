# run_local.ps1 — Chạy bot + web dashboard cục bộ (Windows)
# Yêu cầu: Python 3.11+, PostgreSQL đang chạy, Redis đang chạy (tuỳ chọn)
#
# Cách dùng:
#   .\scripts\run_local.ps1          # Chạy cả bot + web
#   .\scripts\run_local.ps1 -bot     # Chỉ chạy bot
#   .\scripts\run_local.ps1 -web     # Chỉ chạy web
#
param(
    [switch]$bot,
    [switch]$web
)

$ROOT = Split-Path -Parent $PSScriptRoot
Set-Location $ROOT

# Kiểm tra .env
if (-not (Test-Path ".env")) {
    Write-Host "❌ Không tìm thấy file .env!" -ForegroundColor Red
    Write-Host "   Chạy: python scripts\gen_secrets.py để tạo .env mẫu" -ForegroundColor Yellow
    exit 1
}

# Chạy migration trước
Write-Host "📦 Chạy Alembic migration..." -ForegroundColor Cyan
python -m alembic upgrade head
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Migration thất bại. Kiểm tra DATABASE_URL trong .env" -ForegroundColor Red
    exit 1
}
Write-Host "✅ Migration OK" -ForegroundColor Green

# Quyết định chạy gì
$runBot = $bot -or (-not $bot -and -not $web)
$runWeb = $web -or (-not $bot -and -not $web)

if ($runBot -and $runWeb) {
    Write-Host "`n🚀 Khởi động Bot + Web Dashboard..." -ForegroundColor Cyan

    # Chạy bot trong cửa sổ mới
    Start-Process powershell -ArgumentList "-NoExit", "-Command",
        "Set-Location '$ROOT'; Write-Host '[BOT]' -ForegroundColor Blue; python -m bot.main"

    # Chạy web trong cửa sổ hiện tại
    Write-Host "🌐 Web Dashboard: http://localhost:8000" -ForegroundColor Green
    python -m uvicorn web.main:app --host 0.0.0.0 --port 8000 --reload

} elseif ($runBot) {
    Write-Host "`n🤖 Khởi động Bot..." -ForegroundColor Blue
    python -m bot.main

} elseif ($runWeb) {
    Write-Host "`n🌐 Khởi động Web Dashboard: http://localhost:8000" -ForegroundColor Green
    python -m uvicorn web.main:app --host 0.0.0.0 --port 8000 --reload
}
