# stop_all.ps1 - Dung tat ca process Homie Medic: Bot + FastAPI + Vite.
#
# Khong dung Docker postgres (de data persist + restart nhanh lan sau).

$ErrorActionPreference = "SilentlyContinue"

Write-Host "Dung Homie Medic processes..." -ForegroundColor Yellow

# Kill processes on port 8000 (FastAPI) + 3000 (Vite)
Get-NetTCPConnection -LocalPort 8000 -State Listen | ForEach-Object {
    Stop-Process -Id $_.OwningProcess -Force
    Write-Host "  Killed PID $($_.OwningProcess) on :8000 (API)" -ForegroundColor Blue
}
Get-NetTCPConnection -LocalPort 3000 -State Listen | ForEach-Object {
    Stop-Process -Id $_.OwningProcess -Force
    Write-Host "  Killed PID $($_.OwningProcess) on :3000 (Vite)" -ForegroundColor Green
}

# Kill bot — tim python process co cmdline chua "bot.main"
Get-WmiObject Win32_Process | Where-Object {
    $_.Name -eq "python.exe" -and $_.CommandLine -like "*bot.main*"
} | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force
    Write-Host "  Killed PID $($_.ProcessId) bot.main (BOT)" -ForegroundColor Magenta
}

Write-Host "Done. Docker postgres van chay (data persist)." -ForegroundColor Green
Write-Host "Neu can stop DB: docker stop duty_postgres" -ForegroundColor DarkGray
