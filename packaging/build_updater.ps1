param(
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Spec = Join-Path $PSScriptRoot "ChitLogUpdater.spec"
$Verifier = Join-Path $PSScriptRoot "verify_frozen_updater.py"
$UpdaterDist = Join-Path $ProjectRoot "dist\updater-build"
$UpdaterWork = Join-Path $ProjectRoot "build\ChitLogUpdater"
$BuiltUpdater = Join-Path $UpdaterDist "ChitLogUpdater.exe"
$PortableDir = Join-Path $ProjectRoot "dist\ChitLog"
$PortableApp = Join-Path $PortableDir "ChitLog.exe"
$PackagedUpdater = Join-Path $PortableDir "ChitLogUpdater.exe"

function Invoke-Checked {
    param(
        [scriptblock]$Command,
        [string]$ErrorMessage
    )

    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw $ErrorMessage
    }
}

if ($env:OS -ne "Windows_NT") {
    throw "ChitLogUpdater.exe must be built on Windows."
}

Push-Location $ProjectRoot
try {
    Invoke-Checked {
        python -c "import sys,struct; assert sys.version_info[:2] == (3,14), sys.version; assert struct.calcsize('P') * 8 == 64; print(sys.version); print('Python architecture: x64')"
    } "Step 7F requires Python 3.14 x64."

    Invoke-Checked {
        python -m pip check
    } "Python dependency check failed."

    Invoke-Checked {
        python -c "import PyInstaller; print('PyInstaller', PyInstaller.__version__)"
    } "PyInstaller is not installed."

    if (-not $SkipTests) {
        Invoke-Checked {
            python -m pytest `
                tests\test_auto_updater_step7_handoff.py `
                tests\test_auto_updater_step7_process_skeleton.py `
                tests\test_auto_updater_step7_installer_execution.py `
                tests\test_auto_updater_step7_main_handoff.py `
                tests\test_auto_updater_step7_relaunch.py `
                tests\test_auto_updater_step7_packaging.py `
                -q
        } "Step 7 updater tests failed."
    }

    Invoke-Checked {
        python -m chitlog.core.security_audit
    } "ChitLog security audit failed."

    Remove-Item -Recurse -Force $UpdaterDist -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force $UpdaterWork -ErrorAction SilentlyContinue

    Invoke-Checked {
        python -m PyInstaller `
            --noconfirm `
            --clean `
            --distpath $UpdaterDist `
            --workpath $UpdaterWork `
            $Spec
    } "PyInstaller failed to build ChitLogUpdater.exe."

    if (-not (Test-Path $BuiltUpdater -PathType Leaf)) {
        throw "PyInstaller completed but ChitLogUpdater.exe was not created."
    }

    Invoke-Checked {
        python $Verifier $BuiltUpdater
    } "Frozen ChitLogUpdater.exe verification failed."

    if (-not (Test-Path $PortableApp -PathType Leaf)) {
        throw @"
The main portable build was not found at:
  $PortableApp

Build ChitLog first with:
  .\packaging\build_windows.ps1 -SkipTests

Then rerun:
  .\packaging\build_updater.ps1 -SkipTests
"@
    }

    Copy-Item -Force $BuiltUpdater $PackagedUpdater

    Invoke-Checked {
        python $Verifier $PackagedUpdater
    } "Copied ChitLogUpdater.exe verification failed."

    $Hash = (Get-FileHash -Algorithm SHA256 $PackagedUpdater).Hash.ToLowerInvariant()
    $Size = (Get-Item $PackagedUpdater).Length

    Write-Host ""
    Write-Host "CHITLOG STEP 7F FROZEN UPDATER BUILD: PASS" -ForegroundColor Green
    Write-Host "Built updater:    $BuiltUpdater"
    Write-Host "Packaged updater: $PackagedUpdater"
    Write-Host "Size:             $Size bytes"
    Write-Host "SHA256:           $Hash"
    Write-Host ""
    Write-Host "ChitLogUpdater.exe now sits beside ChitLog.exe as required by Step 7D."
}
finally {
    Pop-Location
}
