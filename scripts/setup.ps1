# Requires an existing Python with pip and Node 24.11.x/npm 11.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    $uvExecutable = Join-Path $projectRoot '.tools\bin\uv.exe'
    if (-not (Test-Path -LiteralPath $uvExecutable)) {
        python -m pip install --target .tools uv==0.13.8 --disable-pip-version-check
        if ($LASTEXITCODE -ne 0) { throw 'Local uv installation failed.' }
    }
    if ((& $uvExecutable --version) -notmatch '^uv 0\.13\.8(?:\s|$)') {
        throw 'Expected local uv 0.13.8; check .tools before upgrading it.'
    }
    & "$PSScriptRoot\uv.ps1" sync --locked
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
    npm ci --cache .npm-cache --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'Node dependency installation failed.' }
} finally {
    Pop-Location
}
