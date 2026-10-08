# Kich ban khoi chay dong thoi cac service trong he thong ADPP (AI Debate Practice Platform)
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "     ADPP - Khoi dong he thong Microservices              " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Bat Docker Postgres neu chua chay
Write-Host "`n[1/4] Kiem tra PostgreSQL Container (port 5433)..." -ForegroundColor Yellow
$pgStatus = docker inspect -f '{{.State.Running}}' adpp-ai-generation-postgres 2>$null
if ($pgStatus -ne "true") {
    Write-Host "Dang khoi dong container adpp-ai-generation-postgres..." -ForegroundColor Gray
    docker start adpp-ai-generation-postgres
} else {
    Write-Host "PostgreSQL container dang chay san sang." -ForegroundColor Green
}

# 2. Khoi dong AI Opponent Service (Port 8002)
Write-Host "`n[2/4] Khoi dong AI Opponent Service (Port 8002)..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd 'D:\AI-Debate\AiServices\ai-opponent-service'; if (Test-Path 'venv\Scripts\activate.ps1') { .\venv\Scripts\activate }; python -m uvicorn app.main:app --port 8002 --reload"

# 3. Khoi dong AI Evaluator Service (Port 8000)
Write-Host "`n[3/4] Khoi dong AI Evaluator Service (Port 8000)..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd 'D:\AI-Debate\AiServices\ai-evaluator-service'; if (Test-Path 'venv\Scripts\activate.ps1') { .\venv\Scripts\activate }; python -m uvicorn app.main:app --port 8000 --reload"

# 4. Khoi dong YARP API Gateway (Port 5000)
Write-Host "`n[4/4] Khoi dong YARP API Gateway (.NET 8, Port 5000)..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd 'D:\AI-Debate\Gateway'; dotnet run"

Write-Host "`n==========================================================" -ForegroundColor Green
Write-Host "Da khoi dong cac tien trinh thanh cong!" -ForegroundColor Green
Write-Host "Gateway:       http://localhost:5000" -ForegroundColor White
Write-Host "AI Opponent:   http://localhost:8002 (Gateway route: /api/opponent/*)" -ForegroundColor White
Write-Host "AI Evaluator:  http://localhost:8000 (Gateway route: /api/evaluate/*)" -ForegroundColor White
Write-Host "==========================================================" -ForegroundColor Green
