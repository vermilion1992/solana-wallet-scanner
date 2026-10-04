param([switch]$SkipFrontend)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Executable failed with exit code $LASTEXITCODE." }
}

if ($env:SCANNER_PYTHON) {
    $PythonCommand = $env:SCANNER_PYTHON
    $PythonArguments = @()
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $PythonCommand = 'py'
    $PythonArguments = @('-3')
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonCommand = 'python'
    $PythonArguments = @()
} else {
    throw 'Python 3.11 or later is required. Set SCANNER_PYTHON to its executable if needed.'
}
try {
    # Avoid embedded quotes so Windows PowerShell 5.1 native argument passing works.
    Invoke-Checked $PythonCommand ($PythonArguments + @('-c', 'import sys; sys.exit(sys.version_info < (3,11))'))
} catch {
    throw 'Python 3.11 or later is required. Set SCANNER_PYTHON to its executable if needed.'
}
Invoke-Checked $PythonCommand ($PythonArguments + @('-m', 'venv', '.venv'))
$VenvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
Invoke-Checked $VenvPython @('-m', 'pip', 'install', '--disable-pip-version-check', '--require-hashes', '-r', 'requirements.txt')
Invoke-Checked $VenvPython @('-m', 'pip', 'install', '--disable-pip-version-check', '--no-deps', '--no-build-isolation', '-e', '.')
Invoke-Checked $VenvPython @('-m', 'pip', 'check')

if (-not $SkipFrontend) {
    if (-not (Get-Command node -ErrorAction SilentlyContinue) -or -not (Get-Command npm -ErrorAction SilentlyContinue)) {
        throw 'Node.js 22.12 or later and npm are required to build the interface. Install Node, then run setup again.'
    }
    try {
        Invoke-Checked 'node' @('-e', 'const [major,minor]=process.versions.node.split(String.fromCharCode(46)).map(Number); if(major<22 || (major===22 && minor<12)) process.exit(1)')
    } catch {
        throw 'Node.js 22.12 or later is required.'
    }
    Push-Location frontend
    try {
        Invoke-Checked 'npm' @('ci', '--no-audit', '--no-fund')
        Invoke-Checked 'npm' @('run', 'build')
    } finally {
        Pop-Location
    }
}
Write-Host 'Setup complete. Start the scanner with .\run.ps1'
