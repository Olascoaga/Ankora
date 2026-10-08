[CmdletBinding()]
param(
    [string]$InstallerPath,
    [Parameter(Mandatory = $true)][string]$PythonPath,
    [switch]$ScientificMatrix
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$buildRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $projectRoot "build\windows-runtime")
)
$installDir = [System.IO.Path]::GetFullPath((Join-Path $buildRoot "installed-app"))
if (-not $installDir.StartsWith(
    $buildRoot.TrimEnd('\') + '\',
    [System.StringComparison]::OrdinalIgnoreCase
)) {
    throw "Installer smoke target escaped the Windows build directory."
}
if ([string]::IsNullOrWhiteSpace($InstallerPath)) {
    $installer = Get-ChildItem `
        (Join-Path $projectRoot "apps\desktop\src-tauri\target\release\bundle\nsis") `
        -Filter "*-setup.exe" |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($null -eq $installer) {
        throw "No Ankora NSIS installer was found."
    }
    $InstallerPath = $installer.FullName
}
$InstallerPath = [System.IO.Path]::GetFullPath($InstallerPath)
if (-not (Test-Path -LiteralPath $InstallerPath -PathType Leaf)) {
    throw "Installer not found: $InstallerPath"
}
if (Test-Path -LiteralPath $installDir) {
    throw "Installer smoke target already exists: $installDir"
}
foreach ($hive in @("HKCU:", "HKLM:")) {
    if (Test-Path -LiteralPath "$hive\Software\Microsoft\Windows\CurrentVersion\Uninstall\Ankora") {
        throw "An existing Ankora installation is registered. Refusing to replace it during smoke testing."
    }
}
if ($null -ne (Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue)) {
    throw "Port 8765 is already occupied before the installer smoke test."
}

$desktopProcess = $null
$uninstaller = $null
$oldPath = $env:Path
$evidence = Join-Path $buildRoot ("installed-smoke-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $evidence | Out-Null
try {
    $installation = Start-Process `
        -FilePath $InstallerPath `
        -ArgumentList @("/S", "/D=$installDir") `
        -Wait `
        -PassThru `
        -WindowStyle Hidden
    if ($installation.ExitCode -ne 0) {
        throw "NSIS installation failed with exit code $($installation.ExitCode)."
    }

    $desktopExecutable = Get-ChildItem -LiteralPath $installDir -Filter "*.exe" |
        Where-Object { $_.Name -notlike "uninstall*" } |
        Select-Object -First 1
    $uninstaller = Get-ChildItem -LiteralPath $installDir -Filter "uninstall*.exe" |
        Select-Object -First 1
    if ($null -eq $desktopExecutable -or $null -eq $uninstaller) {
        throw "Installed application or uninstaller was not found in $installDir."
    }

    $legalDir = Join-Path $installDir "legal"
    foreach ($legalFile in @(
        "ANKORA_LICENSE.txt",
        "SOURCE_AVAILABILITY.txt",
        "THIRD_PARTY_INVENTORY.json",
        "THIRD_PARTY_NOTICES.txt"
    )) {
        if (-not (Test-Path -LiteralPath (Join-Path $legalDir $legalFile) -PathType Leaf)) {
            throw "Installed third-party legal payload is missing $legalFile."
        }
    }
    $inventory = Get-Content `
        (Join-Path $legalDir "THIRD_PARTY_INVENTORY.json") `
        -Raw |
        ConvertFrom-Json
    if ($inventory.components.Count -lt 1) {
        throw "Installed third-party inventory is empty."
    }
    $bundledNames = @($inventory.components | ForEach-Object { $_.name })
    foreach ($bundledTool in @(
        "AutoDock Vina",
        "AutoGrid4",
        "AutoDock4",
        "AutoDock-GPU",
        "P2Rank",
        "Eclipse Temurin JRE"
    )) {
        if ($bundledNames -notcontains $bundledTool) {
            throw "Required scientific runtime missing from inventory: $bundledTool"
        }
    }
    Push-Location $projectRoot
    try {
        & $PythonPath -m scripts.complete_windows_legal --verify --tools (Join-Path $installDir "backend/tools") --output $legalDir
        if ($LASTEXITCODE -ne 0) { throw "Installed legal/scientific payload verification failed" }
    }
    finally { Pop-Location }
    $sourceAvailability = Get-Content `
        (Join-Path $legalDir "SOURCE_AVAILABILITY.txt") `
        -Raw
    foreach ($requiredSource in @("OpenMM", "Meeko", "Gemmi", "MPL-2.0")) {
        if ($sourceAvailability -notmatch [regex]::Escape($requiredSource)) {
            throw "Installed source-availability notice is missing $requiredSource."
        }
    }

    $env:Path = "$env:WINDIR\System32;$env:WINDIR"
    $desktopProcess = Start-Process `
        -FilePath $desktopExecutable.FullName `
        -PassThru `
        -WindowStyle Hidden
    $system = $null
    # First launch from a newly installed, unsigned scientific runtime can spend
    # more than 30 seconds in Windows application-control/antivirus inspection.
    for ($attempt = 0; $attempt -lt 240; $attempt++) {
        if ($desktopProcess.HasExited) {
            throw "Installed Ankora exited before its backend became healthy."
        }
        try {
            $health = Invoke-RestMethod `
                -Uri "http://127.0.0.1:8765/api/v1/health" `
                -TimeoutSec 1
            if ($health.status -eq "ok") {
                $system = Invoke-RestMethod `
                    -Uri "http://127.0.0.1:8765/api/v1/system" `
                    -TimeoutSec 2
                break
            }
        }
        catch {
            Start-Sleep -Milliseconds 250
        }
    }
    if ($null -eq $system) {
        throw "Installed Ankora did not start its bundled backend."
    }
    if (
        $system.app_mode -ne "packaged" -or
        $system.python_environment -ne "Bundled Python 3.12"
    ) {
        throw "Installed Ankora reported an unexpected backend identity."
    }
    $tools = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/v1/tools" -TimeoutSec 30
    foreach ($name in @("pdbfixer", "pdb2pqr", "propka", "meeko", "meeko_ligand", "vina", "autogrid4", "autodock4", "autodock_gpu", "p2rank")) {
        if (-not $tools.$name.available) { throw "Installed tool unavailable: $name" }
    }
    $system | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $evidence "system.json") -Encoding utf8
    $tools | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $evidence "tools.json") -Encoding utf8
    if ($ScientificMatrix) {
        & (Join-Path $installDir "backend/ankora-backend.exe") --worker native-smoke --root $projectRoot --output (Join-Path $evidence "scientific matrix á")
        if ($LASTEXITCODE -ne 0) { throw "Installed native scientific matrix failed" }
    }

    Stop-Process -Id $desktopProcess.Id
    $desktopProcess.WaitForExit()
    $desktopProcess = $null
    $backendStopped = $false
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        if ($null -eq (
            Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
        )) {
            $backendStopped = $true
            break
        }
        Start-Sleep -Milliseconds 250
    }
    if (-not $backendStopped) {
        throw "Bundled backend outlived the installed desktop process."
    }
    Write-Host "Installed Ankora includes complete verified tools/notices and runs without developer tools on PATH. Evidence: $evidence"
}
finally {
    if ($null -ne $desktopProcess -and -not $desktopProcess.HasExited) {
        Stop-Process -Id $desktopProcess.Id
    }
    $env:Path = $oldPath
    if ($null -ne $uninstaller -and (Test-Path -LiteralPath $uninstaller.FullName)) {
        $uninstallation = Start-Process `
            -FilePath $uninstaller.FullName `
            -ArgumentList "/S" `
            -Wait `
            -PassThru `
            -WindowStyle Hidden
        if ($uninstallation.ExitCode -ne 0) {
            throw "NSIS uninstaller returned $($uninstallation.ExitCode)."
        }
        for ($attempt = 0; $attempt -lt 40 -and (Test-Path -LiteralPath $desktopExecutable.FullName); $attempt++) { Start-Sleep -Milliseconds 250 }
        if (Test-Path -LiteralPath $desktopExecutable.FullName) { throw "Uninstaller left the desktop executable behind" }
        Write-Host "NSIS uninstall verified; project data was not deleted."
    }
}
