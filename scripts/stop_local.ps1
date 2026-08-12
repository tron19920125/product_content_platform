$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RunRoot = Join-Path $ProjectRoot ".run"
$EnvFile = Join-Path $ProjectRoot ".env"

function Get-ConfiguredPort {
    param(
        [string]$Name,
        [int]$Default
    )

    $processValue = [Environment]::GetEnvironmentVariable($Name, "Process")
    if ($processValue -and $processValue -match '^\d+$') {
        return [int]$processValue
    }
    if (Test-Path -LiteralPath $EnvFile) {
        $entry = Get-Content -LiteralPath $EnvFile -Encoding UTF8 |
            Where-Object { $_ -match "^$Name=(\d+)\s*$" } |
            Select-Object -Last 1
        if ($entry -and $entry -match "^$Name=(\d+)\s*$") {
            return [int]$Matches[1]
        }
    }
    return $Default
}

function Stop-TrackedProcess {
    param(
        [string]$Name,
        [string]$PidFile
    )

    if (-not (Test-Path -LiteralPath $PidFile)) {
        Write-Host "$Name is not tracked."
        return
    }
    $storedPid = (Get-Content -LiteralPath $PidFile -Raw).Trim()
    if ($storedPid -match '^\d+$') {
        $process = Get-Process -Id ([int]$storedPid) -ErrorAction SilentlyContinue
        if ($process) {
            Stop-Process -Id $process.Id -Force
            Write-Host "Stopped $Name (PID $storedPid)."
        } else {
            Write-Host "$Name was already stopped."
        }
    }
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
}

function Stop-ListeningProcess {
    param(
        [string]$Name,
        [int]$Port
    )

    if ($Port -lt 1 -or $Port -gt 65535) {
        throw "Invalid ${Name} port: $Port"
    }
    for ($attempt = 1; $attempt -le 5; $attempt += 1) {
        $listenerPids = @(netstat.exe -ano -p TCP | ForEach-Object {
            if ($_ -match "^\s*TCP\s+\S+:${Port}\s+\S+\s+LISTENING\s+(\d+)\s*$") {
                [int]$Matches[1]
            }
        } | Sort-Object -Unique)
        foreach ($listenerPid in $listenerPids) {
            $process = Get-Process -Id $listenerPid -ErrorAction SilentlyContinue
            if ($process) {
                Stop-Process -Id $listenerPid -Force
                Write-Host "Stopped lingering $Name listener (PID $listenerPid, port $Port)."
            }
        }
        if (-not $listenerPids) {
            return
        }
        Start-Sleep -Milliseconds 200
    }
}

Stop-TrackedProcess -Name "frontend" -PidFile (Join-Path $RunRoot "frontend.pid")
Stop-TrackedProcess -Name "backend" -PidFile (Join-Path $RunRoot "backend.pid")
Stop-ListeningProcess -Name "frontend" -Port (Get-ConfiguredPort -Name "PCP_FRONTEND_PORT" -Default 5173)
Stop-ListeningProcess -Name "backend" -Port (Get-ConfiguredPort -Name "PCP_BACKEND_PORT" -Default 8000)

