$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Exe = Join-Path $ProjectRoot "dist\ChitLog\ChitLog.exe"
$Updater = Join-Path $ProjectRoot "dist\ChitLog\ChitLogUpdater.exe"
$UpdaterVerifier = Join-Path $ProjectRoot "packaging\verify_frozen_updater.py"
$ReleaseDir = Join-Path $ProjectRoot "release"
$Installer = Join-Path $ReleaseDir "ChitLog-1.1.0-Setup.exe"

if (-not (Test-Path -LiteralPath $Exe -PathType Leaf)) {
    throw "Build the Step 24 one-folder release first: .\packaging\build_windows.ps1"
}

if (-not (Test-Path -LiteralPath $Updater -PathType Leaf)) {
    throw "ChitLogUpdater.exe is missing. Build it first: .\packaging\build_updater.ps1"
}

if (-not (Test-Path -LiteralPath $UpdaterVerifier -PathType Leaf)) {
    throw "Updater verifier is missing: $UpdaterVerifier"
}

Write-Host "Verifying packaged ChitLogUpdater.exe before NSIS compilation..."
python $UpdaterVerifier $Updater
if ($LASTEXITCODE -ne 0) {
    throw "Packaged ChitLogUpdater.exe verification failed. Installer build stopped."
}

$UpdaterHashBefore = (Get-FileHash -Algorithm SHA256 $Updater).Hash.ToLowerInvariant()
$UpdaterSizeBefore = (Get-Item -LiteralPath $Updater).Length

# Resolve makensis.exe without indexing a scalar string. PowerShell collapses a
# one-item pipeline result to a scalar, and indexing that scalar with [0]
# returns its first character (for example, 'C') instead of the full path.
$MakeNsisPath = $null
$MakeNsisCommand = Get-Command makensis.exe -ErrorAction SilentlyContinue
if ($MakeNsisCommand) {
    $MakeNsisPath = $MakeNsisCommand.Source
}

if (-not $MakeNsisPath) {
    $CandidatePaths = @(
        (Join-Path ${env:ProgramFiles} "NSIS\makensis.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "NSIS\makensis.exe")
    )

    foreach ($CandidatePath in $CandidatePaths) {
        if ($CandidatePath -and (Test-Path -LiteralPath $CandidatePath)) {
            $MakeNsisPath = $CandidatePath
            break
        }
    }
}

if (-not $MakeNsisPath -or -not (Test-Path -LiteralPath $MakeNsisPath)) {
    throw "NSIS makensis.exe was not found. Install NSIS, then rerun this script."
}

New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null
Remove-Item -Force $Installer -ErrorAction SilentlyContinue

Write-Host "NSIS compiler: $MakeNsisPath"
Write-Host "Project root:  $ProjectRoot"
Write-Host "Portable EXE:  $Exe"
Write-Host "Updater EXE:   $Updater"
Write-Host "Updater SHA256: $UpdaterHashBefore"

Push-Location $ProjectRoot
try {
    & $MakeNsisPath /V2 "/DPROJECT_ROOT=$ProjectRoot" "packaging\installer\ChitLog.nsi"
    if ($LASTEXITCODE -ne 0) {
        throw "NSIS installer build failed."
    }
}
finally {
    Pop-Location
}

if (-not (Test-Path -LiteralPath $Installer -PathType Leaf)) {
    throw "NSIS completed without producing the expected installer: $Installer"
}

# Fail the release build if the verified updater changed while NSIS was
# compiling the package. The installer must only contain the updater artifact
# that was verified immediately before compilation.
$UpdaterHashAfter = (Get-FileHash -Algorithm SHA256 $Updater).Hash.ToLowerInvariant()
$UpdaterSizeAfter = (Get-Item -LiteralPath $Updater).Length
if ($UpdaterHashAfter -ne $UpdaterHashBefore -or $UpdaterSizeAfter -ne $UpdaterSizeBefore) {
    Remove-Item -Force $Installer -ErrorAction SilentlyContinue
    throw "ChitLogUpdater.exe changed during installer compilation. Installer was discarded."
}

$Hash = (Get-FileHash -Algorithm SHA256 $Installer).Hash.ToLowerInvariant()
Set-Content -Path (Join-Path $ReleaseDir "ChitLog-1.1.0-Setup.sha256.txt") -Value "$Hash  ChitLog-1.1.0-Setup.exe" -Encoding ascii

Write-Host ""
Write-Host "CHITLOG STEP 8A NSIS UPGRADE BUILD: PASS"
Write-Host "Installer:      $Installer"
Write-Host "Installer SHA256: $Hash"
Write-Host "Updater SHA256:   $UpdaterHashAfter"
Write-Host "Updater size:     $UpdaterSizeAfter bytes"
Write-Host ""
Write-Host "The installer includes the verified ChitLogUpdater.exe."
Write-Host "Existing install scope/path are restored through MultiUser registry state."
Write-Host "Per-user ChitLog finance data remains outside the installation directory."
