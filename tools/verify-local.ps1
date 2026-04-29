$ErrorActionPreference = "Stop"

$python = "C:\Users\bok\AppData\Local\Programs\Python\Python314\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $python = "python"
}

& $python -m compileall src tests
& $python -m unittest tests.test_trader_core

node --check web\static\js\app.js
node --check web\static\js\finrl.js
node --check web\static\js\ai_dashboard.js
node --check web\static\js\vendors.js
