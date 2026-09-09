param([int]$Port = 8010)
$ErrorActionPreference = 'Stop'
$studioRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonPath = Join-Path $studioRoot '.venv\Scripts\python.exe'
$azureEnvPath = Join-Path $studioRoot '.env'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Python environment is missing.' }
if (-not (Test-Path -LiteralPath $azureEnvPath)) { throw 'Azure configuration .env is missing.' }
$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    Write-Output "Port $Port is already in use. Open http://127.0.0.1:$Port/ or stop the existing service before restarting."
    exit 0
}
$runRoot = Join-Path $studioRoot '.run'
New-Item -ItemType Directory -Force -Path $runRoot | Out-Null
$env:PYTHONPATH = Join-Path $studioRoot 'backend\src'
$env:PYTHONUTF8 = '1'
$env:PCP_STUDIO_DATA_ROOT = Join-Path $studioRoot 'data-refactor'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$stdoutPath = Join-Path $runRoot "studio-azure-$stamp.stdout.log"
$stderrPath = Join-Path $runRoot "studio-azure-$stamp.stderr.log"
$serverProcess = Start-Process -FilePath $pythonPath -ArgumentList @('-m', 'product_content_platform.studio', '--port', "$Port", '--azure-env', ('"' + $azureEnvPath + '"')) -WorkingDirectory $studioRoot -WindowStyle Hidden -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -PassThru
Set-Content -LiteralPath (Join-Path $runRoot 'studio.pid') -Value $serverProcess.Id
$ready = $false
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    try {
        $status = Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 2
        if ($status.workspace -eq 'studio') { $ready = $true; break }
    } catch { Start-Sleep -Milliseconds 500 }
    if ($serverProcess.HasExited) { break }
}
if (-not $ready) { throw "Studio did not start. Inspect $stderrPath" }
Write-Output "Studio started (PID $($serverProcess.Id)): http://127.0.0.1:$Port/"
Write-Output 'Azure authentication is checked in the background; inspect Service configuration on the page.'
