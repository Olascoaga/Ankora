[CmdletBinding()]
param(
    [ValidateSet("Venv", "Conda")]
    [string]$PythonEnvironment = "Venv",
    [switch]$ReceptorTools
)

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

function Assert-LastCommandSucceeded([string]$step) {
    if ($LASTEXITCODE -ne 0) {
        throw "$step failed with exit code $LASTEXITCODE."
    }
}

Push-Location $projectRoot

try {
    if ($PythonEnvironment -eq "Conda") {
        if ([string]::IsNullOrWhiteSpace($env:CONDA_PREFIX)) {
            throw "No Conda environment is active. Run 'conda activate ankora-dev' first."
        }
        if ($env:CONDA_DEFAULT_ENV -eq "base") {
            throw "Do not install Ankora into the Conda base environment. Activate 'ankora-dev' first."
        }
        $pythonCommand = Join-Path $env:CONDA_PREFIX "python.exe"
        if (-not (Test-Path -LiteralPath $pythonCommand)) {
            throw "The active Conda environment does not contain python.exe."
        }
    }
    else {
        if (-not (Get-Command "python" -ErrorAction SilentlyContinue)) {
            throw "Required command 'python' was not found. Install Python 3.12+ or use an active Conda environment."
        }
        if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
            python -m venv .venv
            Assert-LastCommandSucceeded "Creating the Python virtual environment"
        }
        $pythonCommand = Join-Path $projectRoot ".venv\Scripts\python.exe"
    }

    & $pythonCommand -m pip install --upgrade pip
    Assert-LastCommandSucceeded "Updating pip"
    $backendRequirement = if ($ReceptorTools) { "backend[dev,receptor]" } else { "backend[dev]" }
    & $pythonCommand -m pip install -e $backendRequirement
    Assert-LastCommandSucceeded "Installing backend dependencies"
    & $npmCommand install
    Assert-LastCommandSucceeded "Installing frontend dependencies"

    Write-Host "Ankora development dependencies are ready using $PythonEnvironment Python."
    if ($ReceptorTools -and $PythonEnvironment -ne "Conda") {
        Write-Warning "PDBFixer is distributed through conda-forge. Repair actions remain unavailable in a plain venv."
    }
    Write-Host "Run '.\scripts\test.ps1' to verify or 'npm run tauri:dev' to open the app."
}
finally {
    Pop-Location
}
