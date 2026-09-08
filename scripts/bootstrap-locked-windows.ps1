[CmdletBinding()]
param(
    [ValidatePattern("^[A-Za-z0-9_.-]+$")]
    [string]$EnvironmentName = "ankora-locked"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$condaCommand = (Get-Command "conda.exe" -ErrorAction SilentlyContinue).Source
if ([string]::IsNullOrWhiteSpace($condaCommand)) {
    $condaCommand = @("anaconda3", "miniconda3", "miniforge3", "mambaforge") |
        ForEach-Object { Join-Path $env:USERPROFILE "$_\Scripts\conda.exe" } |
        Where-Object { Test-Path -LiteralPath $_ } |
        Select-Object -First 1
    if ([string]::IsNullOrWhiteSpace($condaCommand)) {
        throw "conda.exe was not found. Install Anaconda, Miniconda, or Miniforge first."
    }
}

function Assert-LastCommandSucceeded([string]$step) {
    if ($LASTEXITCODE -ne 0) {
        throw "$step failed with exit code $LASTEXITCODE."
    }
}

$environmentList = & $condaCommand env list --json | ConvertFrom-Json
Assert-LastCommandSucceeded "Reading Conda environments"
$existingNames = $environmentList.envs | ForEach-Object { Split-Path -Leaf $_ }
if ($EnvironmentName -in $existingNames) {
    throw "Conda environment '$EnvironmentName' already exists. Refusing to mutate a locked environment; choose a new name or remove it explicitly."
}

Push-Location $projectRoot
try {
    & $condaCommand create --name $EnvironmentName --file "environment\windows-64.conda.lock" --yes
    Assert-LastCommandSucceeded "Creating the SHA-256-bound Conda environment"
    & $condaCommand run --name $EnvironmentName python -m pip install -r "requirements\windows-py312.lock"
    Assert-LastCommandSucceeded "Installing the hash-locked Python wheels"
    & $condaCommand run --name $EnvironmentName python -m pip install --no-deps --editable backend
    Assert-LastCommandSucceeded "Installing the Ankora backend without changing locked dependencies"
    & $condaCommand run --name $EnvironmentName python scripts\verify_windows_environment_lock.py --runtime
    Assert-LastCommandSucceeded "Verifying the locked Windows runtime"
    Write-Host "Locked Ankora environment '$EnvironmentName' is ready."
}
finally {
    Pop-Location
}
