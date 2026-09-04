$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Launcher = Join-Path $ProjectRoot "scripts\launcher.py"
$Bootstrap = Join-Path $PSScriptRoot "bootstrap.ps1"

if (-not (Test-Path -LiteralPath $Python)) {
    & $Bootstrap
}
if (-not (Test-Path -LiteralPath $Python)) {
    throw "API environment could not be prepared: $Python"
}

Write-Host "Reloading LifeContext API on port 8787..." -ForegroundColor Cyan
$ProcessIds = @(
    & "$env:SystemRoot\System32\netstat.exe" -ano -p TCP |
        ForEach-Object {
            if ($_ -match '^\s*TCP\s+127\.0\.0\.1:8787\s+\S+\s+LISTENING\s+(\d+)\s*$') {
                [int]$Matches[1]
            }
        } |
        Sort-Object -Unique
)
foreach ($ProcessId in $ProcessIds) {
    Write-Host "Stopping old API process $ProcessId..."
    Stop-Process -Id $ProcessId -Force -ErrorAction Stop
}

Start-Sleep -Milliseconds 700

Write-Host "CosyVoice on port 50000 will remain loaded." -ForegroundColor Green
& $Python $Launcher
