$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvDir = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$EnvExample = Join-Path $ProjectRoot ".env.example"
$EnvFile = Join-Path $ProjectRoot ".env"

function Test-Python {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [string[]]$PrefixArguments = @()
    )
    try {
        $version = & $Executable @PrefixArguments -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $version) {
            return $null
        }
        $parts = $version.Trim().Split('.')
        if ([int]$parts[0] -gt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 11)) {
            return @{ Executable = $Executable; Arguments = $PrefixArguments; Version = $version.Trim() }
        }
    } catch {
        return $null
    }
    return $null
}

function Find-Python {
    if ($env:LIFECONTEXT_BOOTSTRAP_PYTHON) {
        $candidate = Test-Python -Executable $env:LIFECONTEXT_BOOTSTRAP_PYTHON
        if ($candidate) { return $candidate }
    }

    $pyLauncher = Get-Command "py.exe" -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        foreach ($selector in @("-3.12", "-3.11", "-3")) {
            $candidate = Test-Python -Executable $pyLauncher.Source -PrefixArguments @($selector)
            if ($candidate) { return $candidate }
        }
    }

    foreach ($name in @("python.exe", "python3.exe")) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command) {
            $candidate = Test-Python -Executable $command.Source
            if ($candidate) { return $candidate }
        }
    }

    $localPrograms = Join-Path $env:LOCALAPPDATA "Programs\Python"
    if (Test-Path -LiteralPath $localPrograms) {
        $paths = Get-ChildItem -LiteralPath $localPrograms -Filter "python.exe" -File -Recurse -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending
        foreach ($path in $paths) {
            $candidate = Test-Python -Executable $path.FullName
            if ($candidate) { return $candidate }
        }
    }
    return $null
}

function Install-PythonWithWinget {
    $winget = Get-Command "winget.exe" -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "Python 3.11+ was not found. Install it from https://www.python.org/downloads/windows/ and run this file again."
    }

    Write-Host "Python 3.11 or newer was not found." -ForegroundColor Yellow
    $answer = Read-Host "Install Python 3.12 for the current user with winget? [Y/N]"
    if ($answer -notin @("Y", "y", "YES", "Yes", "yes")) {
        throw "Setup cancelled. Install Python 3.11+ and run SETUP_LIFECONTEXT.cmd again."
    }

    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $winget.Source install --id Python.Python.3.12 -e --scope user `
        --accept-package-agreements --accept-source-agreements
    $installExitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorAction
    if ($installExitCode -ne 0) {
        throw "winget could not install Python. Install Python 3.11+ manually and retry."
    }
}

Write-Host "" 
Write-Host "LifeContext first-run check" -ForegroundColor Cyan
Write-Host "Project: $ProjectRoot" -ForegroundColor DarkGray

if (-not (Test-Path -LiteralPath $VenvPython)) {
    $python = Find-Python
    if (-not $python) {
        Install-PythonWithWinget
        $python = Find-Python
    }
    if (-not $python) {
        throw "Python was installed but could not be located. Open a new terminal and run SETUP_LIFECONTEXT.cmd again."
    }

    Write-Host "Creating local Python environment with Python $($python.Version)..." -ForegroundColor Cyan
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $python.Executable @($python.Arguments) -m venv $VenvDir
    $venvExitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorAction
    if ($venvExitCode -ne 0 -or -not (Test-Path -LiteralPath $VenvPython)) {
        throw "Could not create $VenvDir"
    }
}

$previousErrorAction = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $VenvPython -c "import fastapi,httpx,docx,pypdf,pydantic,multipart,uvicorn" 2>$null
$dependencyExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorAction
$dependenciesReady = $dependencyExitCode -eq 0
if (-not $dependenciesReady) {
    Write-Host "Installing LifeContext API dependencies. This may take a few minutes..." -ForegroundColor Cyan
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $VenvPython -m pip install --upgrade pip setuptools wheel
    $pipUpgradeExitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorAction
    if ($pipUpgradeExitCode -ne 0) { throw "Could not upgrade pip." }
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $VenvPython -m pip install -e $ProjectRoot
    $pipInstallExitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorAction
    if ($pipInstallExitCode -ne 0) {
        throw "Dependency installation failed. Check your network or proxy, then retry."
    }
}

if (-not (Test-Path -LiteralPath $EnvFile) -and (Test-Path -LiteralPath $EnvExample)) {
    Copy-Item -LiteralPath $EnvExample -Destination $EnvFile
}

Write-Host "LifeContext API environment is ready." -ForegroundColor Green
Write-Host "Local model and CosyVoice files are optional and are not downloaded by this setup." -ForegroundColor DarkGray
