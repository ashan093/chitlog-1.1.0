param(
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$DistDir = Join-Path $ProjectRoot "dist\ChitLog"
$ReleaseDir = Join-Path $ProjectRoot "release"
$PortableZip = Join-Path $ReleaseDir "ChitLog-1.1.0-windows-x64-portable.zip"
$PortableHashFile = Join-Path $ReleaseDir "ChitLog-1.1.0-windows-x64-portable.sha256.txt"
$SpecFile = Join-Path $ProjectRoot "packaging\ChitLog.spec"
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

function New-PortableArchive {
    Stop-PackagedChitLogProcesses
    Start-Sleep -Milliseconds 750

    Remove-Item -Recurse -Force $StagingDir -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $StagingDir | Out-Null

    # Archive a staging copy rather than the live PyInstaller output. Windows can
    # briefly keep PyInstaller's base_library.zip open after the smoke test (for
    # example while a child process or security scanner releases it). Robocopy's
    # retry behavior makes this reliable without weakening release verification.
    & robocopy $DistDir $StagingDir /MIR /R:12 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Host
    $RoboCode = $LASTEXITCODE
    if ($RoboCode -gt 7) {
        Remove-Item -Recurse -Force $StagingDir -ErrorAction SilentlyContinue
        throw "Could not create the portable staging copy. Robocopy exit code: $RoboCode"
    }

    Remove-Item -Force $PortableZip -ErrorAction SilentlyContinue
    Compress-Archive -Path (Join-Path $StagingDir "*") -DestinationPath $PortableZip -CompressionLevel Optimal -Force -ErrorAction Stop
    Remove-Item -Recurse -Force $StagingDir -ErrorAction SilentlyContinue

    if (-not (Test-Path $PortableZip)) {
        throw "Portable ZIP was not created."
    }
}

Set-Location $ProjectRoot

if (-not $env:VIRTUAL_ENV) {
    throw "Activate the ChitLog virtual environment before building."
}

Invoke-Checked { python -c "import sys; assert sys.version_info[:2] == (3,14), sys.version; print(sys.version)" } "Step 24 requires Python 3.14.x."
Invoke-Checked { python -c "import struct; assert struct.calcsize('P')*8 == 64; print('Python architecture: x64')" } "Build ChitLog with 64-bit Python."
Invoke-Checked { python -m pip check } "The build virtual environment has dependency conflicts."
Invoke-Checked { python -c "import PyInstaller; print('PyInstaller', PyInstaller.__version__)" } "PyInstaller is not installed. Run: python -m pip install -r requirements-build.txt"

if (-not $SkipTests) {
    Invoke-Checked { python -m pytest -q } "The test suite failed. Packaging stopped."
}
Invoke-Checked { python -m chitlog.core.security_audit } "The ChitLog security audit failed. Packaging stopped."

Remove-Item -Recurse -Force (Join-Path $ProjectRoot "build") -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force (Join-Path $ProjectRoot "dist") -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null
Remove-Item -Force $PortableZip -ErrorAction SilentlyContinue
Remove-Item -Force $PortableHashFile -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force $StagingDir -ErrorAction SilentlyContinue

Write-Host "Project root: $ProjectRoot"
Write-Host "Entry script: $(Join-Path $ProjectRoot 'app.py')"
Write-Host "Spec file:    $SpecFile"
Invoke-Checked { python -m PyInstaller --clean --noconfirm $SpecFile } "PyInstaller build failed."

if (-not (Test-Path (Join-Path $DistDir "ChitLog.exe"))) {
    throw "PyInstaller did not create dist\ChitLog\ChitLog.exe."
}

Copy-Item (Join-Path $ProjectRoot "EULA.txt") $DistDir -Force
Copy-Item (Join-Path $ProjectRoot "THIRD_PARTY_NOTICES.txt") $DistDir -Force
Copy-Item (Join-Path $ProjectRoot "QT_LGPL_COMPLIANCE.txt") $DistDir -Force

Invoke-Checked { python packaging\collect_licenses.py --output (Join-Path $DistDir "LICENSES") } "Third-party license collection failed. Do not distribute this build."

$Exe = Join-Path $DistDir "ChitLog.exe"
Invoke-Checked { & $Exe --preview-only --smoke-test } "Packaged ChitLog preview smoke test failed."
Invoke-Checked { & $Exe --show-paths } "Packaged ChitLog path-selection test failed."

Invoke-Checked { python packaging\verify_release.py --release-dir $DistDir --project-root $ProjectRoot } "Release verification failed."

New-PortableArchive
$ZipHash = (Get-FileHash -Algorithm SHA256 $PortableZip).Hash.ToLowerInvariant()
Set-Content -Path $PortableHashFile -Value "$ZipHash  ChitLog-1.1.0-windows-x64-portable.zip" -Encoding ascii

Write-Host ""
Write-Host "CHITLOG STEP 24 WINDOWS BUILD: PASS"
Write-Host "Portable folder: $DistDir"
Write-Host "Portable ZIP:    $PortableZip"
Write-Host "Portable SHA256: $ZipHash"
Write-Host "Next: test dist\ChitLog on a clean Windows 10/11 machine, then build the NSIS installer."
