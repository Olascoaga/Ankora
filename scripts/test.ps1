[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$npmCommand = (Get-Command "npm.cmd" -ErrorAction SilentlyContinue).Source
if ([string]::IsNullOrWhiteSpace($npmCommand)) {
    $standardNpm = Join-Path $env:ProgramFiles "nodejs\npm.cmd"
    if (Test-Path -LiteralPath $standardNpm) {
        $npmCommand = $standardNpm
    }
    else {
        throw "npm.cmd was not found. Install Node.js as listed in README.md."
    }
}
$nodeDirectory = Split-Path -Parent $npmCommand
$env:Path = "$nodeDirectory;$env:Path"
$cargoCommand = (Get-Command "cargo.exe" -ErrorAction SilentlyContinue).Source
if ([string]::IsNullOrWhiteSpace($cargoCommand)) {
    $standardCargo = Join-Path $env:USERPROFILE ".cargo\bin\cargo.exe"
    if (Test-Path -LiteralPath $standardCargo) {
        $cargoCommand = $standardCargo
    }
    else {
        throw "cargo.exe was not found. Install Rust stable as listed in README.md."
    }
}
$cargoDirectory = Split-Path -Parent $cargoCommand
$env:Path = "$cargoDirectory;$env:Path"
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$configuredPython = if (-not [string]::IsNullOrWhiteSpace($env:ANKORA_PYTHON_PATH)) {
    $env:ANKORA_PYTHON_PATH
}
else {
    $null
}
$condaPython = if (-not [string]::IsNullOrWhiteSpace($env:CONDA_PREFIX)) {
    Join-Path $env:CONDA_PREFIX "python.exe"
}
else {
    $null
}
$namedCondaCandidates = @()
if (-not [string]::IsNullOrWhiteSpace($env:CONDA_EXE)) {
    $condaBase = Split-Path -Parent (Split-Path -Parent $env:CONDA_EXE)
    $namedCondaCandidates += Join-Path $condaBase "envs\ankora-dev\python.exe"
}
foreach ($distribution in @("anaconda3", "miniconda3", "miniforge3", "mambaforge")) {
    $namedCondaCandidates += Join-Path $env:USERPROFILE "$distribution\envs\ankora-dev\python.exe"
}
$namedCondaPython = $namedCondaCandidates |
    Select-Object -Unique |
    Where-Object { Test-Path -LiteralPath $_ } |
    Select-Object -First 1

$pythonCommand = if (
    $null -ne $configuredPython -and
    (Test-Path -LiteralPath $configuredPython)
) {
    $configuredPython
}
elseif (
    $env:CONDA_DEFAULT_ENV -ne "base" -and
    $null -ne $condaPython -and
    (Test-Path -LiteralPath $condaPython)
) {
    $condaPython
}
elseif ($null -ne $namedCondaPython) {
    $namedCondaPython
}
elseif (Test-Path -LiteralPath $venvPython) {
    $venvPython
}
else {
    $systemPython = Get-Command "python" -ErrorAction SilentlyContinue
    if ($null -eq $systemPython) {
        throw "No usable Python was found. Activate 'ankora-dev' or run scripts/bootstrap.ps1."
    }
    $systemPython.Source
}
$pythonRoot = Split-Path -Parent $pythonCommand
if (Test-Path -LiteralPath (Join-Path $pythonRoot "conda-meta")) {
    $pythonScripts = Join-Path $pythonRoot "Scripts"
    $pythonLibraryBin = Join-Path $pythonRoot "Library\bin"
    $env:CONDA_PREFIX = $pythonRoot
    $env:CONDA_DEFAULT_ENV = Split-Path -Leaf $pythonRoot
    $env:Path = "$pythonRoot;$pythonScripts;$pythonLibraryBin;$env:Path"
}

function Assert-LastCommandSucceeded([string]$step) {
    if ($LASTEXITCODE -ne 0) {
        throw "$step failed with exit code $LASTEXITCODE."
    }
}

Push-Location $projectRoot
try {
    & $pythonCommand scripts/check_public_paths.py
    Assert-LastCommandSucceeded "Public path check"
    $pytestBasetemp = Join-Path $projectRoot "backend\.pytest_tmp"
    & $pythonCommand -m pytest backend -p no:cacheprovider --basetemp=$pytestBasetemp
    Assert-LastCommandSucceeded "Backend tests"
    & $pythonCommand -m ruff check backend
    Assert-LastCommandSucceeded "Backend lint"
    & $pythonCommand -m mypy --config-file backend/pyproject.toml backend/src
    Assert-LastCommandSucceeded "Backend type check"
    & $npmCommand run test:frontend
    Assert-LastCommandSucceeded "Frontend tests"
    & $npmCommand run typecheck
    Assert-LastCommandSucceeded "Frontend type check"
    & $npmCommand run build
    Assert-LastCommandSucceeded "Frontend build"
    & $cargoCommand fmt --manifest-path apps/desktop/src-tauri/Cargo.toml --all -- --check
    Assert-LastCommandSucceeded "Rust formatting check"
    & $cargoCommand clippy --manifest-path apps/desktop/src-tauri/Cargo.toml --all-targets -- -D warnings
    Assert-LastCommandSucceeded "Native shell lint"
    & $cargoCommand test --manifest-path apps/desktop/src-tauri/Cargo.toml
    Assert-LastCommandSucceeded "Native shell tests"
    & $npmCommand run tauri:build
    Assert-LastCommandSucceeded "Native Tauri build"
    Write-Host "All Ankora checks passed, including the native Windows application."
}
finally {
    Pop-Location
}
