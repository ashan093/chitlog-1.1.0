param(
    [Parameter(Mandatory = $true)]
    [string]$PrivateKeyPath,

    [Parameter(Mandatory = $true)]
    [string]$InstallerUrl,

    [Parameter(Mandatory = $true)]
    [string]$ReleaseNotesUrl,

    [Parameter(Mandatory = $true)]
    [string]$PublishedAt,

    [Parameter(Mandatory = $true)]
    [string]$MinimumSupportedVersion,

    [switch]$Mandatory
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Signer = Join-Path $ProjectRoot "packaging\create_signed_update_manifest.py"

Set-Location $ProjectRoot

if (-not $env:VIRTUAL_ENV) {
    throw "Activate the ChitLog build virtual environment before signing."
}

if (-not (Test-Path -LiteralPath $Signer -PathType Leaf)) {
    throw "Release signing tool is missing: $Signer"
}

if (-not (Test-Path -LiteralPath $PrivateKeyPath -PathType Leaf)) {
    throw "Encrypted production private-key file was not found."
}

$Arguments = @(
    $Signer,
    "--private-key", $PrivateKeyPath,
    "--installer-url", $InstallerUrl,
    "--release-notes-url", $ReleaseNotesUrl,
    "--published-at", $PublishedAt,
    "--minimum-supported-version", $MinimumSupportedVersion
)

if ($Mandatory) {
    $Arguments += "--mandatory"
}

Write-Host ""
Write-Host "ChitLog Step 11A - offline release manifest signing"
Write-Host "The private-key passphrase will be requested by Python without echo."
Write-Host "The passphrase is never accepted as a command-line parameter."
Write-Host ""

& python @Arguments
if ($LASTEXITCODE -ne 0) {
    throw "ChitLog release-manifest signing failed."
}
