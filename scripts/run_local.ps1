# run_local.ps1 - Chay bot Homie Medic + web dashboard tren Windows
# Yeu cau: Python 3.11+, PostgreSQL dang chay
#
# Cach dung:
#   .\scripts\run_local.ps1          # Chay ca bot + web
#   .\scripts\run_local.ps1 -bot     # Chi chay bot
#   .\scripts\run_local.ps1 -web     # Chi chay web
#
# Luu y: Khong dung emoji trong script de tranh loi encoding cp1252.
# Cac thong bao dung [TAG] thay vi icon.

param(
    [switch]$bot,
    [switch]$web
)

$ErrorActionPreference = "Stop"
$ROOT = Split-Path -Parent $PSScriptRoot
Set-Location $ROOT

# Kiem tra .env
if (-not (Test-Path ".env")) {
    Write-Host "[ERROR] Khong tim thay file .env!" -ForegroundColor Red
    Write-Host "        Chay: python scripts\gen_secrets.py de sinh secret keys" -ForegroundColor Yellow
    Write-Host "        Sau do copy output vao .env va dien DISCORD_BOT_TOKEN, DB_PASSWORD..." -ForegroundColor Yellow
    exit 1
}

# [STEP 0/3] Bao dam Docker postgres container dang chay (neu cai bang Docker)
# Bo qua neu khong co docker hoac khong tim thay container ten 'duty_postgres'.
$dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
if ($dockerCmd) {
    $containerExists = docker ps -a --format "{{.Names}}" 2>$null | Select-String -Pattern "^duty_postgres$" -Quiet
    if ($containerExists) {
        $containerRunning = docker ps --format "{{.Names}}" 2>$null | Select-String -Pattern "^duty_postgres$" -Quiet
        if (-not $containerRunning) {
            Write-Host "[STEP 0/3] Khoi dong Docker container duty_postgres..." -ForegroundColor Cyan
            docker start duty_postgres | Out-Null
            # Cho 2-3 giay de postgres ready
            Start-Sleep -Seconds 3
            Write-Host "[OK] Container duty_postgres da chay" -ForegroundColor Green
        } else {
            Write-Host "[OK] Container duty_postgres dang chay" -ForegroundColor Green
        }
    }
}

# [STEP 1/3] Chay Alembic migration
Write-Host "[STEP 1/3] Chay Alembic migration..." -ForegroundColor Cyan
python -m alembic upgrade head
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Migration that bai. Kiem tra:" -ForegroundColor Red
    Write-Host "        - PostgreSQL dang chay (Docker: docker ps | Native: Services -> postgresql)" -ForegroundColor Yellow
    Write-Host "        - DB_HOST / DB_PORT / DB_USER / DB_PASSWORD / DB_NAME trong .env dung" -ForegroundColor Yellow
    Write-Host "        - Database 'duty_logger' da duoc tao" -ForegroundColor Yellow
    exit 1
}
Write-Host "[OK] Migration thanh cong" -ForegroundColor Green

# Quyet dinh chay gi
$runBot = $bot -or (-not $bot -and -not $web)
$runWeb = $web -or (-not $bot -and -not $web)

if ($runBot -and $runWeb) {
    Write-Host ""
    Write-Host "[STEP 2/3] Khoi dong Homie Medic Bot + Web Dashboard..." -ForegroundColor Cyan

    # Chay bot trong cua so moi
    $botCmd = "Set-Location '$ROOT'; `$Host.UI.RawUI.WindowTitle = 'Homie Medic - BOT'; Write-Host '[BOT] Khoi dong...' -ForegroundColor Blue; python -m bot.main"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $botCmd

    # Chay web trong cua so hien tai
    Write-Host "[WEB] Dashboard: http://localhost:8000" -ForegroundColor Green
    Write-Host "[WEB] Khoi dong uvicorn... (Ctrl+C de dung)" -ForegroundColor Green
    python -m uvicorn web.main:app --host 0.0.0.0 --port 8000 --reload

} elseif ($runBot) {
    Write-Host ""
    Write-Host "[BOT] Khoi dong Homie Medic Bot..." -ForegroundColor Blue
    python -m bot.main

} elseif ($runWeb) {
    Write-Host ""
    Write-Host "[WEB] Khoi dong Web Dashboard: http://localhost:8000" -ForegroundColor Green
    python -m uvicorn web.main:app --host 0.0.0.0 --port 8000 --reload
}
