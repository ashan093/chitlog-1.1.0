$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$DistDir = Join-Path $ProjectRoot "dist\ChitLog"
$ReleaseDir = Join-Path $ProjectRoot "release"
$PortableZip = Join-Path $ReleaseDir "ChitLog-1.1.0-windows-x64-portable.zip"
$PortableHashFile = Join-Path $ReleaseDir "ChitLog-1.1.0-windows-x64-portable.sha256.txt"
$StagingDir = Join-Path $ReleaseDir ".portable-staging"

function Invoke-Checked {
    param([scriptblock]$Command, [string]$FailureMessage)
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw $FailureMessage
    }
}

function Stop-PackagedChitLogProcesses {
    $DistPrefix = [System.IO.Path]::GetFullPath($DistDir).TrimEnd('\') + '\'
    $Processes = Get-Process -Name "ChitLog" -ErrorAction SilentlyContinue
    foreach ($Process in $Processes) {
        $ProcessPath = $null
        try {
            $ProcessPath = $Process.Path
        } catch {
            $ProcessPath = $null
        }
        if (-not $ProcessPath) {
            continue
        }
        $FullProcessPath = [System.IO.Path]::GetFullPath($ProcessPath)
        if ($FullProcessPath.StartsWith($DistPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            Write-Host "Stopping leftover packaged ChitLog process $($Process.Id) before archive creation..."
            Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
            Wait-Process -Id $Process.Id -Timeout 5 -ErrorAction SilentlyContinue
        }
    }
}

Set-Location $ProjectRoot

if (-not $env:VIRTUAL_ENV) {
    throw "Activate the ChitLog build virtual environment before finalizing."
}
if (-not (Test-Path (Join-Path $DistDir "ChitLog.exe"))) {
    throw "The verified PyInstaller output was not found at dist\ChitLog. Run build_windows.ps1 first."
}
if (-not (Test-Path (Join-Path $DistDir "LICENSES"))) {
    throw "The third-party LICENSES folder is missing. Do not finalize this build."
}

Invoke-Checked { python packaging\verify_release.py --release-dir $DistDir --project-root $ProjectRoot } "Release verification failed. Do not create the portable archive."

Stop-PackagedChitLogProcesses
Start-Sleep -Milliseconds 750

New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null
Remove-Item -Recurse -Force $StagingDir -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $StagingDir | Out-Null

Write-Host "Creating a stable staging copy of the verified portable folder..."
& robocopy $DistDir $StagingDir /MIR /R:12 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Host
$RoboCode = $LASTEXITCODE
if ($RoboCode -gt 7) {
    Remove-Item -Recurse -Force $StagingDir -ErrorAction SilentlyContinue
    throw "Could not create the portable staging copy. Robocopy exit code: $RoboCode"
}

Remove-Item -Force $PortableZip -ErrorAction SilentlyContinue
Remove-Item -Force $PortableHashFile -ErrorAction SilentlyContinue
Compress-Archive -Path (Join-Path $StagingDir "*") -DestinationPath $PortableZip -CompressionLevel Optimal -Force -ErrorAction Stop
Remove-Item -Recurse -Force $StagingDir -ErrorAction SilentlyContinue

if (-not (Test-Path $PortableZip)) {
    throw "Portable ZIP was not created."
}

$ZipHash = (Get-FileHash -Algorithm SHA256 $PortableZip).Hash.ToLowerInvariant()
Set-Content -Path $PortableHashFile -Value "$ZipHash  ChitLog-1.1.0-windows-x64-portable.zip" -Encoding ascii

Write-Host ""
Write-Host "CHITLOG STEP 24 PORTABLE FINALIZATION: PASS"
Write-Host "Portable folder: $DistDir"
Write-Host "Portable ZIP:    $PortableZip"
Write-Host "Portable SHA256: $ZipHash"
Write-Host "Next: launch dist\ChitLog\ChitLog.exe and perform the packaged-app checklist before building the installer."
