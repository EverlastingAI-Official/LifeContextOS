$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Bootstrap = Join-Path $PSScriptRoot "bootstrap.ps1"
$LogDir = Join-Path $ProjectRoot ".runtime\logs"

if (-not (Test-Path $Python)) {
    & $Bootstrap
}
if (-not (Test-Path $Python)) {
    throw "API environment could not be prepared: $Python"
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$ApiRunning = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*lifecontext_api.main:app*" }
if (-not $ApiRunning) {
    Start-Process -FilePath $Python -ArgumentList @(
        "-m", "uvicorn", "lifecontext_api.main:app", "--host", "127.0.0.1", "--port", "8787"
    ) -WorkingDirectory $ProjectRoot -WindowStyle Hidden `
      -RedirectStandardOutput (Join-Path $LogDir "api.log") `
      -RedirectStandardError (Join-Path $LogDir "api.err.log")
}

Start-Sleep -Milliseconds 900
Start-Process "http://127.0.0.1:8787/ui/"
