# run_all.ps1 - Chay Homie Medic TOAN BO: Discord Bot + FastAPI + Vite dev server.
#
# Mo 3 cua so PowerShell rieng cho:
#   1. [BOT] Discord bot
#   2. [API] FastAPI uvicorn :8000 (--reload)
#   3. [WEB] Vite dev server :3000 (HMR)
#
# Cua so hien tai chi log status + giu mo cho ban theo doi.
#
# Cach dung:
#   .\scripts\run_all.ps1
#
# Truy cap:
#   - Dashboard: http://localhost:3000
#   - API:       http://localhost:8000
#   - Bot:       online tren Discord trong vai giay

# LUU Y: KHONG dat $ErrorActionPreference = "Stop" — PowerShell se treat moi
# stderr cua native exe (vd alembic INFO logs) la error -> RemoteException.
# Thay vao do, check $LASTEXITCODE thu cong sau moi lenh quan trong.
$ROOT = Split-Path -Parent $PSScriptRoot
Set-Location $ROOT

Write-Host ""
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host "  HOMIE MEDIC - STARTUP" -ForegroundColor Cyan
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host ""

# ---------- Check .env ----------
if (-not (Test-Path ".env")) {
    Write-Host "[ERROR] Khong tim thay .env. Chay scripts\gen_secrets.py truoc." -ForegroundColor Red
    exit 1
}

# ---------- STEP 0: Free port 8000 + 3000 if zombie ----------
Write-Host "[STEP 0/5] Giai phong port 8000 + 3000..." -ForegroundColor Cyan
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
    try {
        Stop-Process -Id $_.OwningProcess -Force -ErrorAction Stop
        Write-Host "  Killed PID $($_.OwningProcess) on :8000" -ForegroundColor Yellow
    } catch {}
}
Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
    try {
        Stop-Process -Id $_.OwningProcess -Force -ErrorAction Stop
        Write-Host "  Killed PID $($_.OwningProcess) on :3000" -ForegroundColor Yellow
    } catch {}
}
Start-Sleep -Seconds 1

# ---------- STEP 1: Docker postgres ----------
Write-Host "[STEP 1/5] Docker postgres..." -ForegroundColor Cyan
$dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
if ($dockerCmd) {
    $exists = docker ps -a --format "{{.Names}}" 2>$null | Select-String -Pattern "^duty_postgres$" -Quiet
    if ($exists) {
        $running = docker ps --format "{{.Names}}" 2>$null | Select-String -Pattern "^duty_postgres$" -Quiet
        if (-not $running) {
            Write-Host "  Starting duty_postgres container..." -ForegroundColor Yellow
            docker start duty_postgres | Out-Null
            Start-Sleep -Seconds 4
        } else {
            Write-Host "  duty_postgres dang chay." -ForegroundColor Green
        }
    } else {
        Write-Host "  [WARN] Container duty_postgres chua ton tai. Tao bang docker compose up -d truoc." -ForegroundColor Yellow
    }
}

# ---------- STEP 2: Alembic migration ----------
Write-Host "[STEP 2/5] Alembic migration (upgrade head)..." -ForegroundColor Cyan
# Goi qua cmd /c de tach PowerShell ra khoi stderr handling. Output van hien ra
# console nhung khong bi treat la error stream.
cmd /c "`"$ROOT\.venv\Scripts\python.exe`" -m alembic upgrade head 2>&1"
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Alembic that bai (exit $LASTEXITCODE). Check DB connection." -ForegroundColor Red
    exit 1
}
Write-Host "  Schema da update toi head." -ForegroundColor Green

# ---------- STEP 3: Install npm deps if needed ----------
$dashboardDir = Join-Path $ROOT "homie-medic-dashboard"
if (-not (Test-Path (Join-Path $dashboardDir "node_modules"))) {
    Write-Host "[STEP 3/5] Cai npm deps (lan dau)..." -ForegroundColor Cyan
    Push-Location $dashboardDir
    npm install --silent
    Pop-Location
} else {
    Write-Host "[STEP 3/5] npm deps da cai." -ForegroundColor Cyan
}

# ---------- STEP 4: Khoi dong 3 process song song ----------
Write-Host "[STEP 4/5] Khoi dong 3 cua so..." -ForegroundColor Cyan

$python = "$ROOT\.venv\Scripts\python.exe"

# 1) BOT
$botCmd = @"
Set-Location '$ROOT'
`$Host.UI.RawUI.WindowTitle = '[BOT] Homie Medic Bot'
Write-Host '======================================' -ForegroundColor Magenta
Write-Host '  [BOT] DISCORD BOT' -ForegroundColor Magenta
Write-Host '======================================' -ForegroundColor Magenta
& '$python' -m bot.main
Write-Host ''
Write-Host '[BOT] Da dung. Nhan Enter de dong cua so...' -ForegroundColor Yellow
`$null = Read-Host
"@
Start-Process powershell -ArgumentList "-NoExit", "-Command", $botCmd
Write-Host "  [1/3] BOT window da mo." -ForegroundColor Magenta

# 2) FastAPI
$apiCmd = @"
Set-Location '$ROOT'
`$Host.UI.RawUI.WindowTitle = '[API] FastAPI :8000'
Write-Host '======================================' -ForegroundColor Blue
Write-Host '  [API] uvicorn :8000 (--reload)' -ForegroundColor Blue
Write-Host '======================================' -ForegroundColor Blue
& '$python' -m uvicorn web.main:app --host 0.0.0.0 --port 8000 --reload
Write-Host ''
Write-Host '[API] Da dung. Nhan Enter de dong cua so...' -ForegroundColor Yellow
`$null = Read-Host
"@
Start-Process powershell -ArgumentList "-NoExit", "-Command", $apiCmd
Write-Host "  [2/3] API window da mo." -ForegroundColor Blue

# Cho API ready truoc khi start Vite (Vite proxy se goi /api ngay khi load)
Start-Sleep -Seconds 3

# 3) Vite
$viteCmd = @"
Set-Location '$dashboardDir'
`$Host.UI.RawUI.WindowTitle = '[WEB] Vite :3000'
Write-Host '======================================' -ForegroundColor Green
Write-Host '  [WEB] Vite dev :3000 (HMR)' -ForegroundColor Green
Write-Host '======================================' -ForegroundColor Green
npm run dev
Write-Host ''
Write-Host '[WEB] Da dung. Nhan Enter de dong cua so...' -ForegroundColor Yellow
`$null = Read-Host
"@
Start-Process powershell -ArgumentList "-NoExit", "-Command", $viteCmd
Write-Host "  [3/3] WEB window da mo." -ForegroundColor Green

# ---------- STEP 5: Summary ----------
Write-Host ""
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host "  [STEP 5/5] HOMIE MEDIC DA KHOI DONG" -ForegroundColor Cyan
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Dashboard:  " -NoNewline; Write-Host "http://localhost:3000" -ForegroundColor Green
Write-Host "  API:        " -NoNewline; Write-Host "http://localhost:8000" -ForegroundColor Blue
Write-Host "  Bot:        " -NoNewline; Write-Host "Discord (kiem tra log cua so [BOT])" -ForegroundColor Magenta
Write-Host ""
Write-Host "  - Cua so [BOT] hien log bot Discord"
Write-Host "  - Cua so [API] hien log uvicorn + SQL queries"
Write-Host "  - Cua so [WEB] hien log Vite + HMR"
Write-Host ""
Write-Host "  De dung tat ca: dong 3 cua so do (Ctrl+C tren tung cai)" -ForegroundColor Yellow
Write-Host "  Hoac chay: .\scripts\stop_all.ps1" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Bao loi gi? Xem cua so tuong ung de tim message [ERROR]." -ForegroundColor Yellow
Write-Host ""
Write-Host "Nhan Enter de dong cua so nay (3 cua so kia van chay)..." -ForegroundColor DarkGray
$null = Read-Host
