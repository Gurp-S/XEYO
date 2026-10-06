<#
.SYNOPSIS
    Build the self-contained Windows x64 XEYO installer.

.DESCRIPTION
    Prepares the slim Python app, a relocatable Python 3.11 runtime and the
    bundled ripgrep executable, then builds only the NSIS installer.
#>

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$Version = (Get-Content "gui/src-tauri/tauri.conf.json" -Raw | ConvertFrom-Json).version
if (-not $Version) {
    throw "Missing Tauri app version"
}

Write-Host "==[XEYO $Version Windows installer]=="

Write-Host "== 1/4 Prepare Python source =="
& python "scripts/build_slim_python.py"
if ($LASTEXITCODE -ne 0) { throw "Python source preparation failed ($LASTEXITCODE)" }

Write-Host "== 2/4 Build relocatable Python runtime =="
& python "scripts/build_slim_venv.py"
if ($LASTEXITCODE -ne 0) { throw "Python runtime build failed ($LASTEXITCODE)" }

Write-Host "== 3/4 Bundle ripgrep =="
& python "scripts/build_ripgrep.py"
if ($LASTEXITCODE -ne 0) { throw "ripgrep preparation failed ($LASTEXITCODE)" }

Write-Host "== 4/4 Build NSIS installer =="
Set-Location "gui"
& npm ci
if ($LASTEXITCODE -ne 0) { throw "npm ci failed ($LASTEXITCODE)" }
& npm run tauri:build -- --bundles nsis --ci
if ($LASTEXITCODE -ne 0) { throw "Tauri installer build failed ($LASTEXITCODE)" }

$Installer = "src-tauri/target/release/bundle/nsis/XEYO_" + $Version + "_x64-setup.exe"
if (-not (Test-Path $Installer)) {
    throw "Expected installer was not created: $Installer"
}

Write-Host "== Complete =="
Write-Host "NSIS: gui/$Installer"
