[CmdletBinding()]
param(
    [string]$InstallerPath
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
if ($null -ne (Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue)) {
    throw "Port 8765 is already occupied before the installer smoke test."
}

$desktopProcess = $null
$uninstaller = $null
$oldPath = $env:Path
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

    $env:Path = "$env:WINDIR\System32;$env:WINDIR"
    $desktopProcess = Start-Process `
        -FilePath $desktopExecutable.FullName `
        -PassThru `
        -WindowStyle Hidden
    $system = $null
    for ($attempt = 0; $attempt -lt 120; $attempt++) {
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
    Write-Host "Installed Ankora started and stopped its bundled backend without Python on PATH."
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
            Write-Warning "NSIS uninstaller returned $($uninstallation.ExitCode)."
        }
    }
}
