# Use the project-local uv/Python installation without changing system Python.
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$UvArgs)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$uvExecutable = Join-Path $projectRoot '.tools\bin\uv.exe'
if (-not (Test-Path -LiteralPath $uvExecutable)) {
    throw 'Run .\scripts\setup.ps1 first.'
}
$env:UV_PYTHON_INSTALL_DIR = Join-Path $projectRoot '.runtime'
$env:UV_CACHE_DIR = Join-Path $projectRoot '.cache\uv'
Push-Location $projectRoot
try {
    & $uvExecutable @UvArgs
    $commandExit = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $commandExit
