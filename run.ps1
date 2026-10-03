$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$VenvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $VenvPython -PathType Leaf)) {
    throw 'Run .\setup.ps1 -SkipFrontend first to create the local Python environment (or .\setup.ps1 to rebuild the interface).'
}
& $VenvPython -m scanner @args
exit $LASTEXITCODE
