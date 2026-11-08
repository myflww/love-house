param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-f]{40}$')]
    [string]$ExpectedSourceCommit,
    [Parameter(Mandatory = $true)]
    [string]$BuildTools,
    [Parameter(Mandatory = $true)]
    [string]$Keystore,
    [Parameter(Mandatory = $true)]
    [string]$Alias,
    [string]$Manifest = (Join-Path $PSScriptRoot '..\Android-0106-signing-input.json'),
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '..\signed-0106'),
    [string]$Python = 'python',
    [string]$Java = ''
)

$ErrorActionPreference = 'Stop'
$signingScript = Join-Path $PSScriptRoot 'sign_android_0106.py'
$signingArguments = @('-B', $signingScript,
    '--manifest', $Manifest,
    '--expected-source-commit', $ExpectedSourceCommit,
    '--build-tools', $BuildTools,
    '--keystore', $Keystore,
    '--alias', $Alias,
    '--output-dir', $OutputDirectory)
if ($Java) { $signingArguments += @('--java', $Java) }

Write-Host 'Verify the original-key handoff. Passwords are requested by Python without echo; do not paste them into command arguments.'
& $Python @signingArguments
if ($LASTEXITCODE -ne 0) {
    throw 'No complete verified signing handoff was delivered. Nothing was uploaded or installed.'
}
Write-Host 'Signature verification completed. The QA-only APK is not a public download. Real upgrade acceptance is still required.'
