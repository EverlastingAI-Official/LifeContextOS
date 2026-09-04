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

foreach ($Port in @(8787, 50000)) {
    $Listeners = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    foreach ($Listener in $Listeners) {
        Stop-Process -Id $Listener.OwningProcess -Force -ErrorAction SilentlyContinue
    }
}

Start-Sleep -Milliseconds 700
& $Python $Launcher
