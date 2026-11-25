<#
  ADPP: chạy toàn bộ hệ thống local bằng một lệnh, mỗi service một cửa sổ PowerShell (đóng cửa sổ = tắt service).

    .\run-all.ps1                 # DB local: SQL Server (localhost) + Postgres Docker (5433)
    .\run-all.ps1 -Azure          # DB trên Azure: đọc connection string từ .azure-db.env (không commit)
    .\run-all.ps1 -Stop           # tắt mọi service đã chạy bằng script này
    .\run-all.ps1 -NoFrontend     # không chạy FE

  Cổng: Opponent 8002 · Evaluator 8000 · Multimodal 8003 · SystemService 5001 · Gateway 5000 · FE 5173.
  FE nằm ở ..\frontend\frontend-adpp (đổi bằng -FrontendPath).

  .azure-db.env (mỗi dòng TÊN=giá trị; xem .azure-db.env.example):
    SYSTEM_SQL_CONNECTION   connection string SQL của SystemService (Azure SQL)
    OPPONENT_DATABASE_URL   postgresql+asyncpg://...?ssl=require (DB ai_generation trên Azure Postgres)
    RAG_DATABASE_URL        tùy chọn: postgresql://...?sslmode=require (kho fact ai_evaluation) -> bật RAG local
#>
param(
  [switch]$Azure,
  [switch]$Stop,
  [switch]$NoFrontend,
  [string]$FrontendPath = (Join-Path $PSScriptRoot "..\frontend\frontend-adpp")
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$titles = "ADPP Opponent 8002", "ADPP Evaluator 8000", "ADPP Multimodal 8003", "ADPP SystemService 5001",
          "ADPP Gateway 5000", "ADPP Frontend 5173"
$ports = 8002, 8000, 8003, 5001, 5000, 5173

function Stop-Adpp {
  Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $ports -contains $_.LocalPort } |
    Select-Object -ExpandProperty OwningProcess -Unique |
    ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
  Get-Process powershell -ErrorAction SilentlyContinue |
    Where-Object { $titles -contains $_.MainWindowTitle } |
    ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
  Write-Host "Đã tắt các service ADPP." -ForegroundColor Green
}

if ($Stop) { Stop-Adpp; return }

$busy = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $ports -contains $_.LocalPort }
if ($busy) {
  Write-Host "Cổng đang bận: $(($busy.LocalPort | Sort-Object -Unique) -join ', '). Chạy .\run-all.ps1 -Stop trước." -ForegroundColor Red
  return
}

# ---- Connection string theo chế độ DB (chỉ đặt cho tiến trình con, không sửa .env của service) ----
$sqlConnection = "Server=localhost;Database=DebatePracticePlatformDB;Trusted_Connection=True;TrustServerCertificate=True"
$opponentDb = $null   # null = dùng DATABASE_URL trong .env của opponent
$ragDb = $null
if ($Azure) {
  $envFile = Join-Path $root ".azure-db.env"
  if (-not (Test-Path $envFile)) { throw "Thiếu $envFile (xem .azure-db.env.example)." }
  $cfg = @{}
  Get-Content $envFile -Encoding UTF8 | Where-Object { $_ -match '^\s*[A-Z_]+\s*=' } | ForEach-Object {
    $k, $v = $_ -split '=', 2; $cfg[$k.Trim()] = $v.Trim().Trim('"')
  }
  if (-not $cfg["OPPONENT_DATABASE_URL"]) { throw "$envFile thiếu OPPONENT_DATABASE_URL" }
  $opponentDb = $cfg["OPPONENT_DATABASE_URL"]
  $ragDb = $cfg["RAG_DATABASE_URL"]
  Write-Host "Chế độ DB: Azure (giá trị lấy từ .azure-db.env, không in ra)." -ForegroundColor Cyan
  Write-Host "  Opponent: Azure Postgres (ai_generation)" -ForegroundColor Gray
  if ($ragDb) { Write-Host "  Evaluator: RAG bật, kho fact Azure (ai_evaluation); khởi động lâu hơn vì nạp bge-m3" -ForegroundColor Gray }
  if ($cfg["SYSTEM_SQL_CONNECTION"]) {
    $sqlConnection = $cfg["SYSTEM_SQL_CONNECTION"]
    Write-Host "  SystemService: Azure SQL" -ForegroundColor Gray
  } else {
    Write-Host "  SystemService: SQL Server LOCAL (.azure-db.env chưa có SYSTEM_SQL_CONNECTION)" -ForegroundColor Yellow
  }
} else {
  Write-Host "Chế độ DB: local." -ForegroundColor Cyan
  docker info --format '{{.ServerVersion}}' 2>$null | Out-Null
  if ($LASTEXITCODE -ne 0) {
    $docker = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    if (Test-Path $docker) { Write-Host "Đang mở Docker Desktop..." -ForegroundColor Gray; Start-Process $docker }
    for ($i = 0; $i -lt 30; $i++) { Start-Sleep 3; docker info 2>$null | Out-Null; if ($LASTEXITCODE -eq 0) { break } }
  }
  docker start adpp-ai-generation-postgres adpp-ai-evaluation-postgres 2>$null | Out-Null
}

# Gán biến môi trường trong cửa sổ con. Giá trị đi qua file tạm (không nằm trên dòng lệnh, không hiện trong log).
function Start-AdppWindow([string]$title, [string]$dir, [string]$command, [hashtable]$vars = @{}) {
  $lines = @("`$host.UI.RawUI.WindowTitle = '$title'", "Set-Location '$dir'")
  if ($vars.Count -gt 0) {
    $tmp = [IO.Path]::Combine([IO.Path]::GetTempPath(), "adpp-$([guid]::NewGuid().ToString('N')).json")
    ($vars | ConvertTo-Json -Compress) | Set-Content -Path $tmp -Encoding UTF8
    $lines += "`$v = Get-Content '$tmp' -Raw | ConvertFrom-Json; Remove-Item '$tmp'"
    $lines += "`$v.PSObject.Properties | ForEach-Object { Set-Item -Path ('env:' + `$_.Name) -Value `$_.Value }"
  }
  $lines += $command
  Start-Process powershell -ArgumentList "-NoExit", "-Command", ($lines -join "; ")
}

$ai = Join-Path $root "AiServices"
$opponentVars = @{}; if ($opponentDb) { $opponentVars["DATABASE_URL"] = $opponentDb }
$evaluatorVars = @{}; if ($ragDb) { $evaluatorVars["RAG_ENABLED"] = "true"; $evaluatorVars["RAG_DATABASE_URL"] = $ragDb }

Start-AdppWindow "ADPP Opponent 8002" "$ai\ai-opponent-service" ".\venv\Scripts\python -m uvicorn app.main:app --port 8002" $opponentVars
Start-AdppWindow "ADPP Evaluator 8000" "$ai\ai-evaluator-service" ".\venv\Scripts\python -m uvicorn app.main:app --port 8000" $evaluatorVars
# Realtime STT (chữ hiện ngay khi nói) cần DEEPGRAM_API_KEY trong .env của multimodal. Một số máy ghi là DEEPGRAM_KEY:
# khi đó key được chuyển sang đúng tên cho tiến trình con (không sửa .env, không in giá trị).
$multimodalVars = @{}
$mmEnv = Join-Path $ai "ai-multimodal-service\.env"
$mmCfg = @{}
if (Test-Path $mmEnv) {
  Get-Content $mmEnv -Encoding UTF8 | Where-Object { $_ -match '^\s*[A-Z_]+\s*=' } | ForEach-Object {
    $k, $v = $_ -split '=', 2; $mmCfg[$k.Trim()] = $v.Trim().Trim('"')
  }
}
if ($env:DEEPGRAM_API_KEY -or $mmCfg["DEEPGRAM_API_KEY"]) {
  $sttExpected = $true
} elseif ($mmCfg["DEEPGRAM_KEY"]) {
  $multimodalVars["DEEPGRAM_API_KEY"] = $mmCfg["DEEPGRAM_KEY"]
  $sttExpected = $true
  Write-Host "Multimodal: .env ghi DEEPGRAM_KEY, đã chuyển thành DEEPGRAM_API_KEY cho realtime STT." -ForegroundColor Gray
} else {
  $sttExpected = $false
  Write-Host "Cảnh báo: multimodal\.env thiếu DEEPGRAM_API_KEY -> không có chữ khi đang nói (chỉ có Whisper sau khi dừng ghi)." -ForegroundColor Yellow
}
Start-AdppWindow "ADPP Multimodal 8003" "$ai\ai-multimodal-service" ".\venv\Scripts\python -m uvicorn app.main:app --port 8003" $multimodalVars
$systemVars = @{
  "ConnectionStrings__DefaultConnection" = $sqlConnection
  "AiServices__EvaluatorUrl"             = "http://localhost:8000"
}
# Gọi đồng đội (2v2, phút chuẩn bị): TURN miễn phí của Cloudflare Realtime, key đọc từ .azure-db.env ở cả hai chế độ DB.
# Thiếu key -> cuộc gọi chỉ dùng STUN (đa số mạng vẫn nối được).
$secretsFile = Join-Path $root ".azure-db.env"
$secrets = @{}
if (Test-Path $secretsFile) {
  Get-Content $secretsFile -Encoding UTF8 | Where-Object { $_ -match '^\s*TEAMCALL_[A-Z_]+\s*=' } | ForEach-Object {
    $k, $v = $_ -split '=', 2; $secrets[$k.Trim()] = $v.Trim().Trim('"')
  }
}
if ($secrets["TEAMCALL_TURN_KEY_ID"] -and $secrets["TEAMCALL_TURN_API_TOKEN"]) {
  $systemVars["TeamCall__Cloudflare__TurnKeyId"] = $secrets["TEAMCALL_TURN_KEY_ID"]
  $systemVars["TeamCall__Cloudflare__TurnKeyApiToken"] = $secrets["TEAMCALL_TURN_API_TOKEN"]
  Write-Host "  SystemService: gọi đồng đội có TURN (Cloudflare)" -ForegroundColor Gray
} else {
  Write-Host "  SystemService: gọi đồng đội chỉ STUN (.azure-db.env chưa có TEAMCALL_TURN_KEY_ID / TEAMCALL_TURN_API_TOKEN)" -ForegroundColor Yellow
}
Start-AdppWindow "ADPP SystemService 5001" $root "dotnet run --project Services/SystemService --urls http://localhost:5001" $systemVars
Start-AdppWindow "ADPP Gateway 5000" "$root\Gateway" "dotnet run"
if (-not $NoFrontend) {
  $fe = (Resolve-Path $FrontendPath).Path
  # vite.config.js cũ (sinh từ tsc -b) được Vite ưu tiên hơn vite.config.ts và thiếu proxy /multimodal
  if (Test-Path "$fe\vite.config.js") { Write-Host "Cảnh báo: $fe\vite.config.js tồn tại và sẽ che vite.config.ts." -ForegroundColor Yellow }
  Start-AdppWindow "ADPP Frontend 5173" $fe "npm run dev"
}

Write-Host "`nĐang khởi động... kiểm tra sau ~60 s:" -ForegroundColor Green
Write-Host "  FE            http://localhost:5173"
Write-Host "  SystemService http://localhost:5001/swagger"
Write-Host "  Opponent      http://localhost:8002/health   Evaluator http://localhost:8000/health   Multimodal http://localhost:8003/health"
Write-Host "Tắt tất cả: .\run-all.ps1 -Stop"

# Chờ multimodal lên (nạp DeepFace/Whisper) rồi báo realtime STT bật hay tắt
if ($sttExpected) {
  Write-Host "`nĐang chờ Multimodal để kiểm tra realtime STT (tối đa 3 phút)..." -ForegroundColor Gray
  $sttState = $null
  for ($i = 0; $i -lt 60 -and $null -eq $sttState; $i++) {
    Start-Sleep 3
    try {
      $r = Invoke-RestMethod "http://localhost:8003/multimodal/realtime-stt/config" -TimeoutSec 3
      $sttState = [bool]$r.configured
    } catch { }
  }
  if ($null -eq $sttState) {
    Write-Host "Realtime STT: Multimodal chưa lên sau 3 phút, xem cửa sổ 'ADPP Multimodal 8003'." -ForegroundColor Yellow
  } elseif ($sttState) {
    Write-Host "Realtime STT: BẬT (Deepgram) - chữ hiện ngay khi nói." -ForegroundColor Green
  } else {
    Write-Host "Realtime STT: TẮT - Multimodal không nhận được DEEPGRAM_API_KEY." -ForegroundColor Yellow
  }
}
