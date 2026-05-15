# migrate_to_compose.ps1 - Migrate data tu container duty_postgres cu (anonymous volume)
# sang named volume duoc quan ly boi docker-compose.yml.
#
# Chay 1 LAN duy nhat. Sau khi chay xong: dung 'docker compose up -d' moi luc.
#
# Cach dung:
#   .\scripts\migrate_to_compose.ps1
#
# Quy trinh:
#   1. Dump database tu container hien tai vao file .sql
#   2. Stop + remove container duty_postgres (giu lai volume cu nhu backup)
#   3. docker compose up -d -> tao container moi voi named volume
#   4. Cho postgres ready
#   5. Import .sql vao container moi
#   6. Xac nhan
#
# An toan: KHONG xoa volume cu. Co the rollback bang docker run lai voi anonymous volume.

$ErrorActionPreference = "Stop"
$ROOT = Split-Path -Parent $PSScriptRoot
Set-Location $ROOT

# ---------- Pre-flight ----------
$dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
if (-not $dockerCmd) {
    Write-Host "[ERROR] Docker khong tim thay trong PATH" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path ".env")) {
    Write-Host "[ERROR] Khong tim thay .env" -ForegroundColor Red
    exit 1
}

# Doc DB_USER, DB_NAME tu .env
$envContent = Get-Content ".env" -Raw
$dbUser = if ($envContent -match '(?m)^DB_USER=(.+)$') { $matches[1].Trim() } else { "duty_user" }
$dbName = if ($envContent -match '(?m)^DB_NAME=(.+)$') { $matches[1].Trim() } else { "duty_logger" }

$containerExists = docker ps -a --format "{{.Names}}" 2>$null | Select-String -Pattern "^duty_postgres$" -Quiet
if (-not $containerExists) {
    Write-Host "[INFO] Khong co container duty_postgres -> chay 'docker compose up -d' truc tiep duoc roi" -ForegroundColor Yellow
    exit 0
}

$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$dumpFile = "$ROOT\backup_pre_compose_$ts.sql"

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host " MIGRATE TO COMPOSE - duty_postgres -> docker-compose managed" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host " DB user:  $dbUser"
Write-Host " DB name:  $dbName"
Write-Host " Dump to:  $dumpFile"
Write-Host ""

# ---------- STEP 1: dump ----------
Write-Host "[STEP 1/5] Dump database tu container hien tai..." -ForegroundColor Cyan
$running = docker ps --format "{{.Names}}" 2>$null | Select-String -Pattern "^duty_postgres$" -Quiet
if (-not $running) {
    docker start duty_postgres | Out-Null
    Start-Sleep -Seconds 3
}
docker exec duty_postgres pg_dump -U $dbUser -d $dbName --clean --if-exists --no-owner --no-privileges > $dumpFile
if ($LASTEXITCODE -ne 0 -or (-not (Test-Path $dumpFile)) -or ((Get-Item $dumpFile).Length -eq 0)) {
    Write-Host "[ERROR] pg_dump that bai" -ForegroundColor Red
    exit 1
}
$dumpSize = [math]::Round((Get-Item $dumpFile).Length / 1KB, 1)
Write-Host "[OK] Dumped $dumpSize KB" -ForegroundColor Green

# ---------- STEP 2: stop + remove container (giu volume) ----------
Write-Host "[STEP 2/5] Stop + remove container duty_postgres (volume cu duoc giu nhu backup)..." -ForegroundColor Cyan
docker stop duty_postgres | Out-Null
docker rm duty_postgres | Out-Null
Write-Host "[OK] Container removed. Volume cu van con - co the dung 'docker volume ls' de xem." -ForegroundColor Green

# ---------- STEP 3: compose up ----------
Write-Host "[STEP 3/5] docker compose up -d..." -ForegroundColor Cyan
docker compose up -d postgres
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] docker compose up that bai" -ForegroundColor Red
    Write-Host "        Rollback: docker run -d --name duty_postgres -p 127.0.0.1:5433:5432 ..." -ForegroundColor Yellow
    exit 1
}

# ---------- STEP 4: cho postgres ready ----------
Write-Host "[STEP 4/5] Cho postgres ready..." -ForegroundColor Cyan
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    docker exec duty_postgres pg_isready -U $dbUser -d $dbName 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $ready = $true; break }
}
if (-not $ready) {
    Write-Host "[ERROR] Postgres khong san sang sau 30s" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Postgres ready" -ForegroundColor Green

# ---------- STEP 5: restore ----------
Write-Host "[STEP 5/5] Restore tu $dumpFile..." -ForegroundColor Cyan
Get-Content $dumpFile -Raw | docker exec -i duty_postgres psql -U $dbUser -d $dbName 2>&1 | Out-String | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[WARN] psql restore exit code $LASTEXITCODE - co the chi la warning, kiem tra du lieu." -ForegroundColor Yellow
}

# Verify (dung single-quoted string + stop-parsing token de PowerShell khong dien giai SQL)
$sql = 'SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = ''public'';'
$tableCount = docker exec duty_postgres psql -U $dbUser -d $dbName -tAc $sql
Write-Host ""
Write-Host "================================================================" -ForegroundColor Green
Write-Host " HOAN TAT - restored $($tableCount.Trim()) tables vao named volume" -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Green
Write-Host " Tu lan sau:" -ForegroundColor Cyan
Write-Host "   docker compose up -d        # Start postgres + redis" -ForegroundColor White
Write-Host "   docker compose down         # Stop (data persist trong volume)" -ForegroundColor White
Write-Host ""
Write-Host " Backup an toan tai: $dumpFile" -ForegroundColor Cyan
Write-Host " Volume cu (anonymous) van con - xoa bang: docker volume prune" -ForegroundColor Yellow
