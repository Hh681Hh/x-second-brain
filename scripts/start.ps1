param([switch]$Basic)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonExecutable = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    throw 'Create .venv and install the project first. See README.md.'
}
if ($Basic) { $env:EMBEDDING_PROVIDER = 'none' }
& $pythonExecutable -m xsecondbrain.main
exit $LASTEXITCODE
