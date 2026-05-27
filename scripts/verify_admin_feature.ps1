# verify_admin_feature.ps1 — 1-shot verification cho feature Admin Overview
#
# Chay:
#   .\scripts\verify_admin_feature.ps1
#
# Kiem tra:
#   1. Smoke import backend
#   2. Pytest full suite (khong regression)
#   3. Build frontend Vite (TypeScript + bundle)
#   4. Bao cao trang thai cuoi
#
# Khong start server — chi verify code/test. De chay app dung run_local.ps1.

$ErrorActionPreference = "Continue"
$ROOT = Split-Path -Parent $PSScriptRoot
Set-Location $ROOT

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$failed = 0

function Step($name, $block) {
    Write-Host ""
    Write-Host "=== $name ===" -ForegroundColor Cyan
    & $block
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[FAIL] $name (exit $LASTEXITCODE)" -ForegroundColor Red
        $script:failed++
    } else {
        Write-Host "[OK] $name" -ForegroundColor Green
    }
}

Step "1/4 Smoke import backend" {
    python -X utf8 scripts/_verify_admin_imports.py
}

Step "2/4 Pytest full suite" {
    python -X utf8 -m pytest --override-ini="addopts=" -q
}

Step "3/4 Build frontend (Vite)" {
    Push-Location homie-medic-dashboard
    npm run build
    $code = $LASTEXITCODE
    Pop-Location
    $global:LASTEXITCODE = $code
}

Step "4/4 Kiem tra .env BOT_OWNER_IDS" {
    if (-not (Test-Path ".env")) {
        Write-Host "  CANH BAO: chua co file .env" -ForegroundColor Yellow
        Write-Host "  Endpoint /api/admin/* se 500 cho moi request." -ForegroundColor Yellow
        Write-Host "  Tao .env tu .env.example, dien BOT_OWNER_IDS." -ForegroundColor Yellow
        # Khong fail vi day chi la canh bao deployment
        $global:LASTEXITCODE = 0
    } else {
        $hasOwner = (Get-Content .env | Select-String "^BOT_OWNER_IDS=.+" -Quiet)
        if ($hasOwner) {
            Write-Host "  BOT_OWNER_IDS da set trong .env" -ForegroundColor Green
        } else {
            Write-Host "  CANH BAO: .env co nhung BOT_OWNER_IDS trong/khong co" -ForegroundColor Yellow
            Write-Host "  Endpoint /api/admin/* se 500 cho moi request." -ForegroundColor Yellow
        }
        $global:LASTEXITCODE = 0
    }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
if ($failed -eq 0) {
    Write-Host "TAT CA 4/4 BUOC PASS" -ForegroundColor Green
    Write-Host "Feature admin overview da san sang." -ForegroundColor Green
    Write-Host ""
    Write-Host "De chay app:" -ForegroundColor Cyan
    Write-Host "  .\scripts\run_local.ps1" -ForegroundColor White
    Write-Host ""
    Write-Host "Mo http://localhost:8000/admin/overview (sau khi login bot owner)." -ForegroundColor Cyan
    exit 0
} else {
    Write-Host "$failed/4 BUOC FAIL" -ForegroundColor Red
    Write-Host "Xem chi tiet o output ben tren." -ForegroundColor Red
    exit 1
}
