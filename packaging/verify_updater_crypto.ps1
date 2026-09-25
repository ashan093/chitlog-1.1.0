$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Exe = Join-Path $ProjectRoot "dist\ChitLog\ChitLog.exe"

if (-not (Test-Path $Exe)) {
    throw "Frozen ChitLog executable not found at '$Exe'. Run .\packaging\build_windows.ps1 first."
}

Write-Host "Running frozen updater cryptography self-test..."

$Process = Start-Process `
    -FilePath $Exe `
    -ArgumentList "--updater-crypto-self-test" `
    -Wait `
    -PassThru

if ($Process.ExitCode -ne 0) {
    throw "Frozen updater cryptography self-test failed with exit code $($Process.ExitCode)."
}

Write-Host "FROZEN UPDATER CRYPTO SELF-TEST: PASS" -ForegroundColor Green
