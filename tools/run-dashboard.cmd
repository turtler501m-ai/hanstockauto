@echo off
cd /d "%~dp0\.."
"C:\Users\bok\AppData\Local\Programs\Python\Python314\python.exe" -m uvicorn src.dashboard:app --host 127.0.0.1 --port 8000 --no-use-colors > .runtime\dashboard-server.log 2>&1
