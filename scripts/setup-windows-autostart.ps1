# =============================================================================
# Duty Logger — Windows Auto-Start Setup
#
# Tạo Task Scheduler entry để mỗi lần Windows login:
#   1. Đợi Docker Desktop ready (max 2 phút)
#   2. Chạy `docker-compose up -d` cho postgres+redis
#   3. Chạy bot + web với auto-restart
#
# Run as Administrator:
#   Right-click PowerShell → "Run as Administrator"
#   cd E:\Discord\Bot\Duty-bot
#   .\scripts\setup-windows-autostart.ps1
# =============================================================================

#Requires -RunAsAdministrator

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  Duty Logger — Windows Auto-Start Setup" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""
Write-Host "Project dir: $ProjectDir" -ForegroundColor Gray
Write-Host ""

# ── Check Docker Desktop ──
$dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
if (-not $dockerCmd) {
    Write-Host "Docker chưa cài. Cài Docker Desktop trước:" -ForegroundColor Red
    Write-Host "  https://www.docker.com/products/docker-desktop" -ForegroundColor Yellow
    exit 1
}

# ── Tạo startup script ──
$StartupScript = Join-Path $ProjectDir "scripts\windows-startup.ps1"
@"
# Auto-generated startup script — KHÔNG sửa file này
`$ErrorActionPreference = "Continue"
`$LogFile = Join-Path "$ProjectDir" "logs\autostart.log"
New-Item -ItemType Directory -Force -Path (Split-Path `$LogFile) | Out-Null

function Log(`$msg) {
    `$ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "`$ts `$msg" | Out-File -FilePath `$LogFile -Append -Encoding utf8
}

Log "── Auto-start triggered ──"
Set-Location "$ProjectDir"

# Đợi Docker Desktop ready (tối đa 2 phút)
`$timeout = 120
`$elapsed = 0
while (`$elapsed -lt `$timeout) {
    try {
        docker info 2>`$null | Out-Null
        if (`$LASTEXITCODE -eq 0) {
            Log "Docker ready after `$elapsed seconds."
            break
        }
    } catch {}
    Start-Sleep -Seconds 5
    `$elapsed += 5
}

if (`$elapsed -ge `$timeout) {
    Log "ERROR: Docker không ready sau `$timeout s — abort."
    exit 1
}

# Start containers
Log "Starting docker-compose…"
docker-compose up -d 2>&1 | ForEach-Object { Log `$_ }
Log "✓ All services started. Bot và web đang chạy 24/24."
"@ | Set-Content -Path $StartupScript -Encoding UTF8

Write-Host "✓ Startup script created: $StartupScript" -ForegroundColor Green

# ── Tạo scheduled task ──
$TaskName = "DutyLoggerAutoStart"
$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$StartupScript`""

$Trigger = New-ScheduledTaskTrigger -AtLogOn

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest

# Remove old task if exists
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask `
    -TaskName $TaskName `
    -Description "Auto-start Duty Logger Discord bot + web dashboard on Windows login" `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal | Out-Null

Write-Host "✓ Scheduled Task created: $TaskName" -ForegroundColor Green
Write-Host ""
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  ✓ Setup hoàn tất!" -ForegroundColor Green
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""
Write-Host "Mỗi lần Windows login, bot+web sẽ auto-start." -ForegroundColor White
Write-Host ""
Write-Host "Verify:"
Write-Host "  Task Scheduler (taskschd.msc) → Task Scheduler Library → tìm '$TaskName'" -ForegroundColor Gray
Write-Host ""
Write-Host "Test ngay (không cần restart):"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'" -ForegroundColor Gray
Write-Host ""
Write-Host "Logs auto-start:"
Write-Host "  Get-Content $ProjectDir\logs\autostart.log -Tail 50" -ForegroundColor Gray
Write-Host ""
Write-Host "Disable auto-start:"
Write-Host "  Disable-ScheduledTask -TaskName '$TaskName'" -ForegroundColor Gray
Write-Host ""
Write-Host "⚠️  Cũng cần config Docker Desktop:" -ForegroundColor Yellow
Write-Host "  Settings → General → Tick 'Start Docker Desktop when you sign in'" -ForegroundColor Gray
