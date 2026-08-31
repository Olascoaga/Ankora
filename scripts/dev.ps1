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
$backendProcess = $null

function Assert-LastCommandSucceeded([string]$step) {
    if ($LASTEXITCODE -ne 0) {
        throw "$step failed with exit code $LASTEXITCODE."
    }
}

Push-Location $projectRoot
try {
    try {
        $existingSystem = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/v1/system" -TimeoutSec 1
        $existingEnvironment = if ($null -ne $existingSystem.python_environment) {
            $existingSystem.python_environment
        }
        else {
            "unknown"
        }
        throw "An Ankora backend is already using 127.0.0.1:8765 (Python environment: $existingEnvironment). Stop the previous Ankora development session before starting a new one; reusing it could hide installed scientific tools."
    }
    catch {
        if ($_.Exception.Message -like "An Ankora backend is already using*") {
            throw
        }
    }

    Write-Host "Starting Ankora backend with $pythonCommand"
    $backendProcess = Start-Process -FilePath $pythonCommand `
        -ArgumentList @("-m", "ankora_backend") `
        -PassThru `
        -WindowStyle Hidden

    $backendReady = $false
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        if ($backendProcess.HasExited) {
            throw "The Ankora backend exited before becoming healthy (exit code $($backendProcess.ExitCode))."
        }
        try {
            $response = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/v1/health" -TimeoutSec 1
            if ($response.status -eq "ok") {
                $backendReady = $true
                break
            }
        }
        catch {
            Start-Sleep -Milliseconds 250
        }
    }

    if (-not $backendReady) {
        throw "The Ankora backend did not become healthy on 127.0.0.1:8765."
    }

    & $npmCommand run dev
    Assert-LastCommandSucceeded "Starting the frontend development server"
}
finally {
    if ($null -ne $backendProcess -and -not $backendProcess.HasExited) {
        Stop-Process -Id $backendProcess.Id
    }
    Pop-Location
}
