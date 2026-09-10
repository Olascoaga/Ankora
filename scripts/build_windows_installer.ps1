[CmdletBinding()]
param(
    [string]$PythonPath,
    [switch]$BackendOnly
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$buildRoot = Join-Path $projectRoot "build\windows-runtime"
$distRoot = Join-Path $buildRoot "dist"
$workRoot = Join-Path $buildRoot "pyinstaller"
$resourceRoot = Join-Path $projectRoot "apps\desktop\src-tauri\resources\backend"
$specPath = Join-Path $projectRoot "backend\packaging\ankora_backend.spec"
$packagingLock = Join-Path $projectRoot "requirements\windows-packaging.lock"
$legalGenerator = Join-Path $projectRoot "scripts\generate_third_party_notices.py"
$tauriCommand = Join-Path $projectRoot "node_modules\.bin\tauri.cmd"

function Assert-LastCommandSucceeded([string]$step) {
    if ($LASTEXITCODE -ne 0) {
        throw "$step failed with exit code $LASTEXITCODE."
    }
}

function Reset-BuildDirectory([string]$path, [string]$allowedRoot) {
    $resolvedPath = [System.IO.Path]::GetFullPath($path)
    $resolvedRoot = [System.IO.Path]::GetFullPath($allowedRoot).TrimEnd('\') + '\'
    if (-not $resolvedPath.StartsWith(
        $resolvedRoot,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Refusing to reset build directory outside $resolvedRoot"
    }
    if (Test-Path -LiteralPath $resolvedPath) {
        Remove-Item -LiteralPath $resolvedPath -Recurse -Force
    }
    New-Item -ItemType Directory -Path $resolvedPath | Out-Null
}

if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    $activeCondaPython = if (
        -not [string]::IsNullOrWhiteSpace($env:CONDA_PREFIX) -and
        (Split-Path -Leaf $env:CONDA_PREFIX) -eq "ankora-locked"
    ) {
        Join-Path $env:CONDA_PREFIX "python.exe"
    }
    else {
        $null
    }
    $namedCandidates = @("anaconda3", "miniconda3", "miniforge3", "mambaforge") |
        ForEach-Object { Join-Path $env:USERPROFILE "$_\envs\ankora-locked\python.exe" }
    $namedPython = $namedCandidates |
        Where-Object { Test-Path -LiteralPath $_ } |
        Select-Object -First 1
    if ($null -ne $activeCondaPython -and (Test-Path -LiteralPath $activeCondaPython)) {
        $PythonPath = $activeCondaPython
    }
    elseif ($null -ne $namedPython) {
        $PythonPath = $namedPython
    }
    else {
        throw "Activate the SHA-256-locked 'ankora-locked' Conda environment or pass -PythonPath."
    }
}
$PythonPath = [System.IO.Path]::GetFullPath($PythonPath)
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Python executable not found: $PythonPath"
}

Push-Location $projectRoot
try {
    & $PythonPath scripts\verify_windows_environment_lock.py --runtime
    Assert-LastCommandSucceeded "Locked runtime verification"
    & $PythonPath -m pip install --no-deps -r $packagingLock
    Assert-LastCommandSucceeded "Installing hash-locked packaging tools"

    Reset-BuildDirectory $distRoot $buildRoot
    Reset-BuildDirectory $workRoot $buildRoot
    & $PythonPath -m PyInstaller `
        --noconfirm `
        --distpath $distRoot `
        --workpath $workRoot `
        $specPath
    Assert-LastCommandSucceeded "Building the bundled Ankora backend"

    $builtBackend = Join-Path $distRoot "ankora-backend"
    $builtExecutable = Join-Path $builtBackend "ankora-backend.exe"
    if (-not (Test-Path -LiteralPath $builtExecutable -PathType Leaf)) {
        throw "PyInstaller did not create $builtExecutable"
    }

    & $PythonPath $legalGenerator `
        --analysis (Join-Path $workRoot "ankora_backend\Analysis-00.toc") `
        --check
    Assert-LastCommandSucceeded "Third-party redistribution notice verification"

    $resourceParent = Split-Path -Parent $resourceRoot
    if (-not (Test-Path -LiteralPath $resourceParent)) {
        New-Item -ItemType Directory -Path $resourceParent | Out-Null
    }
    Reset-BuildDirectory $resourceRoot $resourceParent
    Copy-Item -Path (Join-Path $builtBackend "*") -Destination $resourceRoot -Recurse

    $oldDataDir = $env:ANKORA_DATA_DIR
    $oldAppMode = $env:ANKORA_APP_MODE
    $oldPythonEnvironment = $env:ANKORA_PYTHON_ENVIRONMENT
    $oldPath = $env:Path
    $smokeData = Join-Path $buildRoot "smoke-data"
    Reset-BuildDirectory $smokeData $buildRoot
    $backendProcess = $null
    try {
        try {
            Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/v1/health" -TimeoutSec 1 | Out-Null
            throw "Port 8765 is already serving a backend. Close it before packaging."
        }
        catch {
            if ($_.Exception.Message -like "Port 8765 is already serving*") {
                throw
            }
        }

        $env:ANKORA_DATA_DIR = $smokeData
        $env:ANKORA_APP_MODE = "packaged"
        $env:ANKORA_PYTHON_ENVIRONMENT = "Bundled Python 3.12"
        $env:Path = "$env:WINDIR\System32;$env:WINDIR"
        $backendProcess = Start-Process -FilePath $builtExecutable `
            -ArgumentList @("--parent-pid", $PID) `
            -PassThru `
            -WindowStyle Hidden

        $system = $null
        for ($attempt = 0; $attempt -lt 120; $attempt++) {
            if ($backendProcess.HasExited) {
                throw "Bundled backend exited during smoke test with code $($backendProcess.ExitCode)."
            }
            try {
                $health = Invoke-RestMethod `
                    -Uri "http://127.0.0.1:8765/api/v1/health" `
                    -TimeoutSec 1
                if ($health.status -eq "ok") {
                    $system = Invoke-RestMethod `
                        -Uri "http://127.0.0.1:8765/api/v1/system" `
                        -TimeoutSec 3
                    break
                }
            }
            catch {
                Start-Sleep -Milliseconds 250
            }
        }
        if ($null -eq $system) {
            throw "Bundled backend did not become healthy."
        }
        if (
            $system.app_mode -ne "packaged" -or
            $system.python_environment -ne "Bundled Python 3.12"
        ) {
            throw "Bundled backend reported an unexpected runtime identity."
        }
        $tools = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/v1/tools" -TimeoutSec 10
        foreach ($toolName in @("pdbfixer", "pdb2pqr", "propka", "meeko", "meeko_ligand")) {
            if (-not $tools.$toolName.available) {
                throw "Bundled backend did not expose required tool '$toolName'."
            }
        }
        Write-Host "Bundled backend smoke passed without Python or Conda on PATH."
    }
    finally {
        if ($null -ne $backendProcess -and -not $backendProcess.HasExited) {
            Stop-Process -Id $backendProcess.Id
            $backendProcess.WaitForExit()
        }
        $env:ANKORA_DATA_DIR = $oldDataDir
        $env:ANKORA_APP_MODE = $oldAppMode
        $env:ANKORA_PYTHON_ENVIRONMENT = $oldPythonEnvironment
        $env:Path = $oldPath
    }

    if ($BackendOnly) {
        Write-Host "Bundled backend staged at $resourceRoot"
        exit 0
    }
    if (-not (Test-Path -LiteralPath $tauriCommand -PathType Leaf)) {
        throw "Tauri CLI not found. Run npm install first."
    }
    Push-Location (Join-Path $projectRoot "apps\desktop")
    try {
        & $tauriCommand build --bundles nsis
        Assert-LastCommandSucceeded "Building the Ankora NSIS installer"
    }
    finally {
        Pop-Location
    }

    $installer = Get-ChildItem `
        (Join-Path $projectRoot "apps\desktop\src-tauri\target\release\bundle\nsis") `
        -Filter "*-setup.exe" |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($null -eq $installer) {
        throw "Tauri did not create an NSIS installer."
    }
    Write-Host "Windows installer ready: $($installer.FullName)"
}
finally {
    Pop-Location
}
