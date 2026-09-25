$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Exe = Join-Path $ProjectRoot "dist\ChitLog\ChitLog.exe"
$ReleaseDir = Join-Path $ProjectRoot "release"
$Installer = Join-Path $ReleaseDir "ChitLog-1.1.0-Setup.exe"

if (-not (Test-Path -LiteralPath $Exe)) {
    throw "Build the Step 24 one-folder release first: .\packaging\build_windows.ps1"
}

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

Set-Location $ProjectRoot
& $MakeNsisPath /V2 "/DPROJECT_ROOT=$ProjectRoot" "packaging\installer\ChitLog.nsi"
if ($LASTEXITCODE -ne 0) {
    throw "NSIS installer build failed."
}
if (-not (Test-Path -LiteralPath $Installer)) {
    throw "NSIS completed without producing the expected installer: $Installer"
}

$Hash = (Get-FileHash -Algorithm SHA256 $Installer).Hash.ToLowerInvariant()
Set-Content -Path (Join-Path $ReleaseDir "ChitLog-1.1.0-Setup.sha256.txt") -Value "$Hash  ChitLog-1.1.0-Setup.exe" -Encoding ascii

Write-Host ""
Write-Host "CHITLOG STEP 24 INSTALLER BUILD: PASS"
Write-Host "Installer: $Installer"
Write-Host "SHA256:    $Hash"
Write-Host "The installer requires acceptance of EULA.txt and preserves ChitLog user data on uninstall."
