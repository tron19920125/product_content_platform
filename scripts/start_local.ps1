param(
    [switch]$Check
)

$ErrorActionPreference = "Stop"
# Some launchers inject both `Path` and `PATH`. Windows PowerShell treats the
# process environment as case-insensitive when spawning a child and otherwise
# fails with "Item has already been added". Canonicalize it before Start-Process.
$processEnvironment = [Environment]::GetEnvironmentVariables("Process")
$pathKeys = @($processEnvironment.Keys | Where-Object { [string]$_ -ieq "Path" })
if ($pathKeys.Count -gt 1) {
    $canonicalPath = [Environment]::GetEnvironmentVariable("Path", "Process")
    [Environment]::SetEnvironmentVariable("PATH", $null, "Process")
    [Environment]::SetEnvironmentVariable("Path", $canonicalPath, "Process")
}
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RunRoot = Join-Path $ProjectRoot ".run"
$LogRoot = Join-Path $ProjectRoot "data\logs"
$EnvFile = Join-Path $ProjectRoot ".env"

function Import-SafeDotEnv {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    $lineNumber = 0
    foreach ($rawLine in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $lineNumber += 1
        $line = $rawLine.Trim()
        if (-not $line -or $line.StartsWith("#")) {
            continue
        }
        if ($line -notmatch '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
            throw "Invalid .env entry at line $lineNumber. Expected KEY=VALUE."
        }
        $name = $Matches[1]
        $value = $Matches[2].Trim()
        if ($value.Length -ge 2) {
            $first = $value.Substring(0, 1)
            $last = $value.Substring($value.Length - 1, 1)
            if (($first -eq '"' -and $last -eq '"') -or ($first -eq "'" -and $last -eq "'")) {
                $value = $value.Substring(1, $value.Length - 2)
            }
        }
        if (-not (Test-Path -LiteralPath "Env:$name")) {
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}

function Test-TrackedProcess {
    param([string]$PidFile)

    if (-not (Test-Path -LiteralPath $PidFile)) {
        return $false
    }
    $storedPid = (Get-Content -LiteralPath $PidFile -Raw).Trim()
    if ($storedPid -notmatch '^\d+$') {
        return $false
    }
    return $null -ne (Get-Process -Id ([int]$storedPid) -ErrorAction SilentlyContinue)
}

function Wait-HttpReady {
    param(
        [string]$Url,
        [int]$Attempts = 40
    )

    for ($attempt = 1; $attempt -le $Attempts; $attempt += 1) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return $true
            }
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    return $false
}

Import-SafeDotEnv -Path $EnvFile

if (-not $env:PCP_DATA_ROOT) {
    $env:PCP_DATA_ROOT = Join-Path $ProjectRoot "data"
}
$hostAddress = if ($env:PCP_HOST) { $env:PCP_HOST } else { "127.0.0.1" }
$backendPort = if ($env:PCP_BACKEND_PORT) { [int]$env:PCP_BACKEND_PORT } else { 8000 }
$frontendPort = if ($env:PCP_FRONTEND_PORT) { [int]$env:PCP_FRONTEND_PORT } else { 5173 }
$env:VITE_API_BASE_URL = if ($env:VITE_API_BASE_URL) { $env:VITE_API_BASE_URL } else { "http://${hostAddress}:${backendPort}/api" }

$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
$node = if ($nodeCommand) { $nodeCommand.Source } else { $null }
if (-not $node) {
    $bundledNodeRoot = Join-Path (Split-Path $ProjectRoot -Parent) ".tools\node22"
    if (Test-Path -LiteralPath $bundledNodeRoot) {
        $node = Get-ChildItem -LiteralPath $bundledNodeRoot -Filter node.exe -File -Recurse |
            Select-Object -First 1 -ExpandProperty FullName
    }
}
if (-not (Test-Path -LiteralPath $python)) {
    throw "Python environment is missing. Create .venv and install backend[dev] first."
}
if (-not $node) {
    throw "Node.js is missing from PATH. Install Node.js 20+ first."
}
$vite = Join-Path $ProjectRoot "frontend\node_modules\vite\bin\vite.js"
if (-not (Test-Path -LiteralPath $vite)) {
    throw "Frontend dependencies are missing. Run pnpm install in frontend first."
}

$generationMode = if ($env:PCP_GENERATION_MODE) { $env:PCP_GENERATION_MODE } else { "local" }
$qaMode = if ($env:PCP_QA_MODE) { $env:PCP_QA_MODE } else { "local" }
Write-Host "Configuration ready: generation=$generationMode, qa=$qaMode, backend=$backendPort, frontend=$frontendPort"
if ($Check) {
    exit 0
}

New-Item -ItemType Directory -Force -Path $RunRoot, $LogRoot | Out-Null
$backendPidFile = Join-Path $RunRoot "backend.pid"
$frontendPidFile = Join-Path $RunRoot "frontend.pid"
if ((Test-TrackedProcess $backendPidFile) -or (Test-TrackedProcess $frontendPidFile)) {
    throw "Tracked services are already running. Use scripts\stop_local.ps1 before starting again."
}

$backendLog = Join-Path $LogRoot "backend.log"
$frontendLog = Join-Path $LogRoot "frontend.log"
$backendErrorLog = Join-Path $LogRoot "backend.error.log"
$frontendErrorLog = Join-Path $LogRoot "frontend.error.log"
$backendLauncher = Join-Path $PSScriptRoot "run_backend.cmd"
$frontendLauncher = Join-Path $PSScriptRoot "run_frontend.cmd"
$backend = $null
$frontend = $null
try {
    $backend = Start-Process -FilePath $backendLauncher -ArgumentList @(
        $python, $hostAddress, "$backendPort", $backendLog, $backendErrorLog
    ) -WorkingDirectory $ProjectRoot -WindowStyle Hidden -PassThru
    Set-Content -LiteralPath $backendPidFile -Value $backend.Id -Encoding ASCII

    $frontend = Start-Process -FilePath $frontendLauncher -ArgumentList @(
        $node, $vite, $hostAddress, "$frontendPort", $frontendLog, $frontendErrorLog
    ) -WorkingDirectory (Join-Path $ProjectRoot "frontend") -WindowStyle Hidden -PassThru
    Set-Content -LiteralPath $frontendPidFile -Value $frontend.Id -Encoding ASCII

    if (-not (Wait-HttpReady "http://${hostAddress}:${backendPort}/api/health")) {
        throw "Backend health check timed out. See $backendLog."
    }
    # The tracked process can be a launcher parent on some Python builds. Do
    # not query Get-NetTCPConnection here: in restricted desktop hosts that
    # cmdlet can block for minutes even after the health endpoint is ready.
    # stop_local.ps1 already falls back to the listener when needed.
    if (-not (Wait-HttpReady "http://${hostAddress}:${frontendPort}/")) {
        throw "Frontend health check timed out. See $frontendLog."
    }
} catch {
    if ($frontend -and -not $frontend.HasExited) { Stop-Process -Id $frontend.Id -Force -ErrorAction SilentlyContinue }
    if ($backend -and -not $backend.HasExited) { Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue }
    Remove-Item -LiteralPath $backendPidFile, $frontendPidFile -Force -ErrorAction SilentlyContinue
    throw
}

Write-Host "Services are ready: http://${hostAddress}:${frontendPort}/"
Write-Host "API docs: http://${hostAddress}:${backendPort}/docs"
Write-Host "Logs: $LogRoot"
