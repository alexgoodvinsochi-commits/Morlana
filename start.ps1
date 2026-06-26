# Morlana — запуск всех сервисов
# Использование: .\start.ps1

$ErrorActionPreference = "Stop"
$projectDir = $PSScriptRoot

Write-Host "=== Morlana: запуск сервисов ===" -ForegroundColor Cyan

# 1. Docker Desktop
Write-Host "`n[1/4] Docker..." -ForegroundColor Yellow
$dockerRunning = docker info 2>$null | Select-String "Server Version"
if ($dockerRunning) {
    Write-Host "  Docker уже запущен" -ForegroundColor Green
} else {
    Write-Host "  Запуск Docker Desktop..." -ForegroundColor Yellow
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    Write-Host "  Ожидание демона (~30 сек)..."
    Start-Sleep -Seconds 30
    docker info 2>$null | Select-String "Server Version" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  Docker не запустился. Запустите вручную и повторите." -ForegroundColor Red
        exit 1
    }
    Write-Host "  Docker запущен" -ForegroundColor Green
}

# 2. Docker Compose — все сервисы
Write-Host "`n[2/4] Docker Compose (db + backend + frontend)..." -ForegroundColor Yellow
Push-Location $projectDir
docker compose up --build -d
Pop-Location
Write-Host "  Контейнеры запущены" -ForegroundColor Green

# 3. Проверка health
Write-Host "`n[3/4] Проверка health..." -ForegroundColor Yellow
Start-Sleep -Seconds 5
try {
    $health = Invoke-RestMethod -Uri "http://localhost:8000/health" -TimeoutSec 5
    Write-Host "  Backend: $($health.status)" -ForegroundColor Green
} catch {
    Write-Host "  Backend не отвечает" -ForegroundColor Red
}
try {
    $fe = Invoke-WebRequest -Uri "http://localhost:3000" -Method Head -UseBasicParsing -TimeoutSec 5
    Write-Host "  Frontend: $($fe.StatusCode)" -ForegroundColor Green
} catch {
    Write-Host "  Frontend не отвечает" -ForegroundColor Red
}

# 4. Ngrok (с обязательной проверкой VPN)
Write-Host "`n[4/4] Ngrok..." -ForegroundColor Yellow

# Остановить старый ngrok (если есть) чтобы не было конфликтов портов
$ngrokRunning = Get-Process ngrok -ErrorAction SilentlyContinue
if ($ngrokRunning) {
    Write-Host "  Остановка старого ngrok (PID $($ngrokRunning.Id))..." -ForegroundColor Yellow
    Stop-Process -Name ngrok -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

# Обязательная проверка VPN
Write-Host "  Проверка VPN..." -ForegroundColor Yellow
try {
    $ip = (Test-Connection ifconfig.me -Count 1 -ErrorAction Stop).Address.IPAddressToString
    Write-Host "  Текущий IP: $ip"
    if ($ip -eq "5.35.113.65") {
        Write-Host "  ОШИБКА: VPN выключен! ngrok заблокирует этот IP." -ForegroundColor Red
        Write-Host "  Включите VPN и повторите запуск." -ForegroundColor Red
        exit 1
    }
    Write-Host "  VPN активен (IP: $ip)" -ForegroundColor Green
} catch {
    Write-Host "  ОШИБКА: Не удалось определить IP. Проверьте VPN." -ForegroundColor Red
    exit 1
}

# Запуск ngrok
Write-Host "  Запуск ngrok http 8000..." -ForegroundColor Yellow
Start-Process "C:\tools\ngrok.exe" -ArgumentList "http", "8000"
Start-Sleep -Seconds 3
$ngrokRunning = Get-Process ngrok -ErrorAction SilentlyContinue
if ($ngrokRunning) {
    Write-Host "  Ngrok запущен (PID $($ngrokRunning.Id))" -ForegroundColor Green
} else {
    Write-Host "  Ngrok не запустился" -ForegroundColor Red
}

# Итого
Write-Host "`n=== Готово ===" -ForegroundColor Cyan
Write-Host "Frontend:  http://localhost:3000"
Write-Host "Backend:   http://localhost:8000"
Write-Host "Health:    http://localhost:8000/health"
Write-Host "Ngrok:     http://localhost:4040 (dashboard)"
Write-Host ""
Write-Host "Для остановки: docker compose down" -ForegroundColor DarkGray
