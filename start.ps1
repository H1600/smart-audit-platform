param(
  [int]$Port = 8000
)

$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
  Write-Error ".venv was not found. Run .\setup-python312.ps1 first."
  exit 1
}

& $Python -m uvicorn backend.main:app --host 127.0.0.1 --port $Port --reload
