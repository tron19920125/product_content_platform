$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RunRoot = Join-Path $ProjectRoot ".run"

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

Stop-TrackedProcess -Name "frontend" -PidFile (Join-Path $RunRoot "frontend.pid")
Stop-TrackedProcess -Name "backend" -PidFile (Join-Path $RunRoot "backend.pid")

