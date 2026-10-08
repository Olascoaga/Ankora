[CmdletBinding()]
param(
    [string]$PythonPath,
    [string]$CertificateThumbprint,
    [string]$TimestampUrl,
    [string]$ScientificTools = "build/windows-runtime/scientific-tools",
    [string]$SourceCompanion = "build/windows-runtime/source-companion",
    [string]$GpuSource = "build/windows-runtime/autodock-gpu-1.6-ankora-source.zip",
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
$legalRoot = Join-Path $projectRoot "apps\desktop\src-tauri\resources\complete-legal"
$tauriCommand = Join-Path $projectRoot "node_modules\.bin\tauri.cmd"
$signingConfig = Join-Path $buildRoot "tauri-signing-config.json"

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

$hasThumbprint = -not [string]::IsNullOrWhiteSpace($CertificateThumbprint)
$hasTimestampUrl = -not [string]::IsNullOrWhiteSpace($TimestampUrl)
if ($hasThumbprint -ne $hasTimestampUrl) {
    throw "CertificateThumbprint and TimestampUrl must be supplied together."
}
if ($hasThumbprint) {
    if ($CertificateThumbprint -notmatch '^[A-Fa-f0-9]{40}$') {
        throw "CertificateThumbprint must contain exactly 40 hexadecimal characters."
    }
    $parsedTimestampUrl = $null
    if (
        -not [System.Uri]::TryCreate(
            $TimestampUrl,
            [System.UriKind]::Absolute,
            [ref]$parsedTimestampUrl
        ) -or
        $parsedTimestampUrl.Scheme -ne "https"
    ) {
        throw "TimestampUrl must be an absolute HTTPS URL."
    }
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
    foreach ($inputPath in @($ScientificTools, $SourceCompanion, $GpuSource)) {
        if (-not (Test-Path -LiteralPath $inputPath)) {
            throw "Complete installer input missing: $inputPath. Stage the reviewed scientific payload and corresponding sources first; a Python-only installer is no longer permitted."
        }
    }
    $ScientificTools = (Resolve-Path -LiteralPath $ScientificTools).Path
    $SourceCompanion = (Resolve-Path -LiteralPath $SourceCompanion).Path
    $GpuSource = (Resolve-Path -LiteralPath $GpuSource).Path
    & $PythonPath -c "from pathlib import Path; from scripts.complete_windows_legal import verify_companion; import sys; verify_companion(*map(Path, sys.argv[1:]))" $ScientificTools $SourceCompanion $GpuSource
    Assert-LastCommandSucceeded "Reviewed scientific payload and source verification"
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

    Copy-Item -LiteralPath $ScientificTools -Destination (Join-Path $builtBackend "tools") -Recurse
    $legalBuild = Join-Path $buildRoot ("complete-legal-" + [guid]::NewGuid().ToString("N"))
    & $PythonPath -m scripts.complete_windows_legal `
        --analysis (Join-Path $workRoot "ankora_backend\Analysis-00.toc") `
        --tools $ScientificTools --companion $SourceCompanion --gpu-source $GpuSource --output $legalBuild
    Assert-LastCommandSucceeded "Complete third-party notices and corresponding sources"
    & $PythonPath -m scripts.complete_windows_legal --verify --tools $ScientificTools --output $legalBuild
    Assert-LastCommandSucceeded "Complete legal integrity verification"

    $resourceParent = Split-Path -Parent $resourceRoot
    if (-not (Test-Path -LiteralPath $resourceParent)) {
        New-Item -ItemType Directory -Path $resourceParent | Out-Null
    }
    Reset-BuildDirectory $resourceRoot $resourceParent
    Copy-Item -Path (Join-Path $builtBackend "*") -Destination $resourceRoot -Recurse
    Reset-BuildDirectory $legalRoot $resourceParent
    Copy-Item -Path (Join-Path $legalBuild "*") -Destination $legalRoot -Recurse

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
        foreach ($toolName in @("pdbfixer", "pdb2pqr", "propka", "meeko", "meeko_ligand", "vina", "autogrid4", "autodock4", "autodock_gpu", "p2rank")) {
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
    & $PythonPath -m scripts.prepare_windows_webview2
    Assert-LastCommandSucceeded "Signed offline WebView2 input verification"
    Push-Location (Join-Path $projectRoot "apps\desktop")
    try {
        $tauriArguments = @("build", "--bundles", "nsis", "--ci")
        if ($hasThumbprint) {
            $override = @{
                bundle = @{
                    windows = @{
                        certificateThumbprint = $CertificateThumbprint.ToUpperInvariant()
                        digestAlgorithm = "sha256"
                        timestampUrl = $TimestampUrl
                    }
                }
            }
            $overrideJson = $override | ConvertTo-Json -Depth 4
            [System.IO.File]::WriteAllText(
                $signingConfig,
                $overrideJson,
                [System.Text.UTF8Encoding]::new($false)
            )
            $tauriArguments += @("--config", $signingConfig)
            Write-Host "Building with a user-controlled Authenticode identity."
        }
        elseif (Test-Path -LiteralPath $signingConfig) {
            Remove-Item -LiteralPath $signingConfig -Force
        }
        & $tauriCommand @tauriArguments
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
    & $PythonPath -m scripts.prepare_windows_webview2 --verify-nsis (Join-Path $projectRoot "apps\desktop\src-tauri\target\release\nsis\x64\installer.nsi")
    Assert-LastCommandSucceeded "Embedded offline WebView2 identity verification"
    Write-Host "Windows installer ready: $($installer.FullName)"
}
finally {
    Pop-Location
}
