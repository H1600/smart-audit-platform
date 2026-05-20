param(
  [string[]]$PythonCommand = @("py", "-3.12")
)

$ErrorActionPreference = "Stop"
$VenvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (Test-Path $VenvPython) {
  $version = & $VenvPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
  if ($version -eq "3.12") {
    Write-Host "Python 3.12 virtual environment already exists: .venv"
  } else {
    throw ".venv uses Python $version. Remove .venv and run this script again."
  }
} else {
  Write-Host "Creating Python 3.12 virtual environment..."
  $pythonArgs = @()
  if ($PythonCommand.Length -gt 1) {
    $pythonArgs = $PythonCommand[1..($PythonCommand.Length - 1)]
  }
  & $PythonCommand[0] @pythonArgs -m venv .venv
  if ($LASTEXITCODE -ne 0 -or -not (Test-Path $VenvPython)) {
    throw "Failed to create .venv with Python 3.12. Install Python 3.12 from python.org, then rerun this script."
  }
}

Write-Host "Upgrading pip and installing dependencies..."
& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed." }
& $VenvPython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "dependency installation failed." }

Write-Host "Environment ready:"
& $VenvPython --version
& $VenvPython -m pip --version
