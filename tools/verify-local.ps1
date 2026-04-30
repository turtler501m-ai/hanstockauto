$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONDONTWRITEBYTECODE = "1"

$python = "C:\Users\bok\AppData\Local\Programs\Python\Python314\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $python = "python"
}

powershell -ExecutionPolicy Bypass -File tools\check-encoding.ps1
& $python -c "import pathlib; [compile(p.read_text(encoding='utf-8'), str(p), 'exec') for root in ('src','tests') for p in pathlib.Path(root).rglob('*.py')]"
& $python -m unittest discover -s tests

node --check web\static\js\app.js
node --check web\static\js\finrl.js
node --check web\static\js\ai_dashboard.js
node --check web\static\js\vendors.js
