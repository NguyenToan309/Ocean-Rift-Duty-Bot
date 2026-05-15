# run_dashboard.ps1 - Chay Homie Medic dashboard React SPA (dev mode)
#
# Tu dong:
#   - Khoi dong Docker postgres container neu can
#   - Chay alembic migration
#   - Chay FastAPI tren port 8000 (background)
#   - Chay Vite dev server tren port 3000 (foreground)
#
# Cach dung:
#   .\scripts\run_dashboard.ps1
#
# Truy cap dashboard: http://localhost:3000
# Vite proxy /api, /auth, /ws tu dong sang FastAPI :8000

$ErrorActionPreference = "Stop"
$ROOT = Split-Path -Parent $PSScriptRoot
Set-Location $ROOT

if (-not (Test-Path ".env")) {
    Write-Host "[ERROR] Khong tim thay .env" -ForegroundColor Red
    exit 1
}

# ---------- STEP 0: Docker postgres ----------
$dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
if ($dockerCmd) {
    $exists = docker ps -a --format "{{.Names}}" 2>$null | Select-String -Pattern "^duty_postgres$" -Quiet
    if ($exists) {
        $running = docker ps --format "{{.Names}}" 2>$null | Select-String -Pattern "^duty_postgres$" -Quiet
        if (-not $running) {
            Write-Host "[STEP 0] Starting duty_postgres..." -ForegroundColor Cyan
            docker start duty_postgres | Out-Null
            Start-Sleep -Seconds 3
        }
    }
}

# ---------- STEP 1: Migration ----------
Write-Host "[STEP 1/3] Alembic migration..." -ForegroundColor Cyan
python -m alembic upgrade head
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Migration failed" -ForegroundColor Red
    exit 1
}

# ---------- STEP 2: Install React deps ----------
$dashboardDir = Join-Path $ROOT "homie-medic-dashboard"
if (-not (Test-Path (Join-Path $dashboardDir "node_modules"))) {
    Write-Host "[STEP 2/3] Installing dashboard deps (1 lan dau)..." -ForegroundColor Cyan
    Push-Location $dashboardDir
    npm install
    Pop-Location
}

# ---------- STEP 3: Chay 2 process song song ----------
Write-Host "[STEP 3/3] Khoi dong FastAPI + Vite dashboard..." -ForegroundColor Cyan
Write-Host ""
Write-Host "  Dashboard:    http://localhost:3000" -ForegroundColor Green
Write-Host "  API backend:  http://localhost:8000" -ForegroundColor Green
Write-Host "  API docs:     http://localhost:8000/docs (neu DEBUG=true)" -ForegroundColor Green
Write-Host ""
Write-Host "Nhan Ctrl+C tren cua so nay de dung Vite. FastAPI chay terminal rieng." -ForegroundColor Yellow
Write-Host ""

# FastAPI o cua so moi
$apiCmd = "Set-Location '$ROOT'; `$Host.UI.RawUI.WindowTitle = 'Homie Medic - API'; Write-Host '[API] uvicorn :8000' -ForegroundColor Blue; python -m uvicorn web.main:app --host 0.0.0.0 --port 8000 --reload"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $apiCmd

# Vite o cua so hien tai
Start-Sleep -Seconds 2
Set-Location $dashboardDir
npm run dev
