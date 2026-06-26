# Morlana — остановка всех сервисов
# Использование: .\stop.ps1

Write-Host "=== Morlana: остановка ===" -ForegroundColor Cyan

# Остановка контейнеров
Write-Host "Остановка Docker контейнеров..." -ForegroundColor Yellow
docker compose down

# Остановка ngrok
$ngrok = Get-Process ngrok -ErrorAction SilentlyContinue
if ($ngrok) {
    Write-Host "Остановка ngrok (PID $($ngrok.Id))..." -ForegroundColor Yellow
    Stop-Process -Name ngrok -Force
    Write-Host "Ngrok остановлен" -ForegroundColor Green
}

Write-Host "=== Все сервисы остановлены ===" -ForegroundColor Cyan
