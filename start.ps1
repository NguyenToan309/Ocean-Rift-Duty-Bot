# ============================================================
# Homie Medic - All-in-one launcher
# Chay: .\start.ps1                  (bot + web)
#       .\start.ps1 -SkipBuild       (bo qua npm build)
#       .\start.ps1 -DevFrontend     (kem vite dev server :3000)
#       .\start.ps1 -StopAll         (dung tat ca + thoat)
#       .\start.ps1 -SkipMigration   (bo qua alembic)
#       .\start.ps1 -SkipDocker      (bo qua docker check)
# ============================================================
param(
    [switch]$SkipBuild,
    [switch]$DevFrontend,
    [switch]$StopAll,
    [switch]$SkipMigration,
    [switch]$SkipDocker
)

$ErrorActionPreference = "Continue"
$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ROOT

function Write-Step($msg) {
    Write-Host ""
    Write-Host ">> $msg" -ForegroundColor Cyan
}
function Write-OK($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  [WARN] $msg" -ForegroundColor Yellow }
function Write-Err($msg)  { Write-Host "  [ERR] $msg" -ForegroundColor Red }

# --- Stop mode ----------------------------------------------------
if ($StopAll) {
    Write-Step "Dang dung tat ca jobs Homie Medic..."
    Get-Job -Name "homie-*" -ErrorAction SilentlyContinue | ForEach-Object {
        Stop-Job $_ -ErrorAction SilentlyContinue
        Remove-Job $_ -ErrorAction SilentlyContinue
        Write-OK "Da dung job: $($_.Name)"
    }
    Get-Process python, uvicorn -ErrorAction SilentlyContinue | Where-Object {
        $_.Path -like "*Duty-bot*"
    } | ForEach-Object {
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
        Write-OK "Da kill PID $($_.Id) ($($_.ProcessName))"
    }
    Write-Host "Done." -ForegroundColor Green
    exit 0
}

Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "       HOMIE MEDIC - Launching full stack" -ForegroundColor Cyan
Write-Host "       Discord Bot + FastAPI + React Dashboard" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan

# --- 1. PostgreSQL Docker -----------------------------------------
if (-not $SkipDocker) {
    Write-Step "Buoc 1/4: Kiem tra PostgreSQL Docker"
    $pgRunning = docker ps --filter "name=duty_postgres" --filter "status=running" --format "{{.Names}}" 2>$null
    if ($pgRunning -eq "duty_postgres") {
        Write-OK "duty_postgres dang chay"
    } else {
        $pgExists = docker ps -a --filter "name=duty_postgres" --format "{{.Names}}" 2>$null
        if ($pgExists -eq "duty_postgres") {
            Write-Warn "Container ton tai nhung da dung - dang start lai..."
            docker start duty_postgres | Out-Null
            Start-Sleep -Seconds 2
            Write-OK "duty_postgres da start"
        } else {
            Write-Warn "Chua co container duty_postgres. Tao bang tay:"
            Write-Host "    docker run -d --name duty_postgres --restart unless-stopped ``" -ForegroundColor DarkGray
            Write-Host "      -e POSTGRES_USER=duty -e POSTGRES_PASSWORD=duty123 -e POSTGRES_DB=duty_db ``" -ForegroundColor DarkGray
            Write-Host "      -p 5432:5432 postgres:16" -ForegroundColor DarkGray
        }
    }
} else {
    Write-Step "Buoc 1/4: Bo qua Docker (flag -SkipDocker)"
}

# --- 2. Alembic migration -----------------------------------------
if (-not $SkipMigration) {
    Write-Step "Buoc 2/4: Apply Alembic migrations"
    $migOut = alembic upgrade head 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-OK "Migrations up-to-date"
        $migOut | Where-Object { $_ -match "Running upgrade|Will assume" } | ForEach-Object {
            Write-Host "    $_" -ForegroundColor DarkGray
        }
    } else {
        Write-Err "Alembic loi:"
        $migOut | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
        Write-Warn "Van tiep tuc - bot/web co the khong hoat dong dung"
    }
} else {
    Write-Step "Buoc 2/4: Bo qua migration (flag -SkipMigration)"
}

# --- 3. Frontend build --------------------------------------------
if (-not $SkipBuild -and -not $DevFrontend) {
    Write-Step "Buoc 3/4: Build React frontend"
    $distIndex = Join-Path $ROOT "homie-medic-dashboard\dist\index.html"
    $srcChanged = $true
    if (Test-Path $distIndex) {
        $distTime = (Get-Item $distIndex).LastWriteTime
        $newerSrc = Get-ChildItem (Join-Path $ROOT "homie-medic-dashboard\src") -Recurse -File |
                    Where-Object { $_.LastWriteTime -gt $distTime } |
                    Select-Object -First 1
        if (-not $newerSrc) {
            $srcChanged = $false
            Write-OK "dist/ moi hon src/ - bo qua build"
        }
    }
    if ($srcChanged) {
        Push-Location (Join-Path $ROOT "homie-medic-dashboard")
        Write-Host "  Dang chay npm run build..." -ForegroundColor DarkGray
        $buildOut = & npm run build 2>&1
        $buildOut | Select-Object -Last 6 | ForEach-Object {
            Write-Host "    $_" -ForegroundColor DarkGray
        }
        Pop-Location
        if ($LASTEXITCODE -eq 0) { Write-OK "Build thanh cong" }
        else { Write-Err "Build loi - van tiep tuc" }
    }
} else {
    Write-Step "Buoc 3/4: Bo qua build (flag -SkipBuild hoac -DevFrontend)"
}

# --- 4. Start bot + web -------------------------------------------
Write-Step "Buoc 4/4: Khoi dong bot + web (background jobs)"

Get-Job -Name "homie-*" -ErrorAction SilentlyContinue | ForEach-Object {
    Stop-Job $_ -ErrorAction SilentlyContinue
    Remove-Job $_ -ErrorAction SilentlyContinue
}

$jobBot = Start-Job -Name "homie-bot" -ArgumentList $ROOT -ScriptBlock {
    param($root)
    Set-Location $root
    python -m bot.main 2>&1
}
Write-OK "Bot started - Job ID $($jobBot.Id)"

$jobWeb = Start-Job -Name "homie-web" -ArgumentList $ROOT -ScriptBlock {
    param($root)
    Set-Location $root
    python -m uvicorn web.main:app --host 0.0.0.0 --port 8000 2>&1
}
Write-OK "Web started on http://localhost:8000 - Job ID $($jobWeb.Id)"

if ($DevFrontend) {
    $jobVite = Start-Job -Name "homie-vite" -ArgumentList $ROOT -ScriptBlock {
        param($root)
        Set-Location (Join-Path $root "homie-medic-dashboard")
        npm run dev 2>&1
    }
    Write-OK "Vite dev started on http://localhost:3000 - Job ID $($jobVite.Id)"
}

Write-Host ""
Write-Host "================================================================" -ForegroundColor DarkCyan
Write-Host "  Web Dashboard:  http://localhost:8000" -ForegroundColor White
if ($DevFrontend) {
    Write-Host "  Vite Dev:       http://localhost:3000" -ForegroundColor White
}
Write-Host "  Bot Discord:    dang chay (xem log [BOT])" -ForegroundColor White
Write-Host ""
Write-Host "  Bam Ctrl+C de dung tat ca." -ForegroundColor Yellow
Write-Host "================================================================" -ForegroundColor DarkCyan
Write-Host ""

$cleanup = {
    Write-Host ""
    Write-Host "Dang dung tat ca..." -ForegroundColor Yellow
    Get-Job -Name "homie-*" -ErrorAction SilentlyContinue | ForEach-Object {
        Stop-Job $_ -ErrorAction SilentlyContinue
        Remove-Job $_ -ErrorAction SilentlyContinue
    }
    Write-Host "Done. Bye." -ForegroundColor Green
}

try {
    while ($true) {
        Get-Job -Name "homie-*" -ErrorAction SilentlyContinue | ForEach-Object {
            $j = $_
            $lines = Receive-Job $j -ErrorAction SilentlyContinue
            if ($lines) {
                $tag = switch ($j.Name) {
                    "homie-bot"  { "[BOT] " }
                    "homie-web"  { "[WEB] " }
                    "homie-vite" { "[VITE]" }
                    default      { "[$($j.Name)]" }
                }
                $color = switch ($j.Name) {
                    "homie-bot"  { "Magenta" }
                    "homie-web"  { "Cyan"    }
                    "homie-vite" { "Yellow"  }
                    default      { "White"   }
                }
                $lines | ForEach-Object {
                    $line = "$_".TrimEnd()
                    if ($line) { Write-Host "$tag $line" -ForegroundColor $color }
                }
            }
            if ($j.State -in @("Failed","Stopped","Completed")) {
                Write-Host "[WARN] Job $($j.Name) da ket thuc (State=$($j.State))" -ForegroundColor Red
                Receive-Job $j -ErrorAction SilentlyContinue | ForEach-Object {
                    Write-Host "  $_" -ForegroundColor DarkGray
                }
                Remove-Job $j -ErrorAction SilentlyContinue
            }
        }

        $alive = Get-Job -Name "homie-*" -ErrorAction SilentlyContinue
        if (-not $alive) {
            Write-Host "Tat ca jobs da thoat. Bye." -ForegroundColor Yellow
            break
        }
        Start-Sleep -Milliseconds 800
    }
} finally {
    & $cleanup
}
