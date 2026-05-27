$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$env:PYTHONPATH = Join-Path $Root "src"
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Project virtualenv Python was not found at $Python"
}

& $Python -m streamlit run "yourscript.py" --server.port 8501 --server.address localhost --server.headless true
