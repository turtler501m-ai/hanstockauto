#!/usr/bin/env bash
# Restart the local dashboard server.

set -e
cd "$(dirname "$0")"

PORT=${PORT:-8000}
RELOAD=${RELOAD:-true}
if [ -z "${PYTHON:-}" ]; then
    if [ -x "/c/Users/bok/AppData/Local/Programs/Python/Python314/python.exe" ]; then
        PYTHON="/c/Users/bok/AppData/Local/Programs/Python/Python314/python.exe"
    else
        PYTHON="python"
    fi
fi

echo "[restart] stopping existing server on port ${PORT}..."
if command -v taskkill.exe >/dev/null 2>&1; then
    PIDS=$(
        powershell.exe -NoProfile -Command "\
            \$pids = Get-NetTCPConnection -State Listen -LocalPort ${PORT} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique; \
            if (-not \$pids) { \
                netstat -ano | Select-String ':${PORT}\s+.*LISTENING\s+(\d+)' | ForEach-Object { \$_.Matches[0].Groups[1].Value } | Select-Object -Unique; \
            } else { \$pids }" 2>/dev/null \
        | tr -d '\r' \
        | grep -E '^[0-9]+$' || true
    )
    if [ -n "$PIDS" ]; then
        for PID in $PIDS; do
            taskkill.exe /PID "$PID" /F >/dev/null 2>&1 \
                && echo "[restart] stopped PID $PID" \
                || echo "[restart] stop skipped PID $PID"
        done
    else
        echo "[restart] no listening server found"
    fi
else
    pkill -f "uvicorn src.dashboard" 2>/dev/null || true
fi

sleep 2

CACHE=".runtime/candidate_snapshot.json"
if [ -f "$CACHE" ]; then
    rm "$CACHE"
    echo "[restart] removed cache: $CACHE"
fi

echo "[restart] starting server -- http://localhost:${PORT}"
RELOAD_FLAG=""
[ "$RELOAD" = "true" ] && RELOAD_FLAG="--reload"

exec "$PYTHON" -m uvicorn src.dashboard:app $RELOAD_FLAG --host 127.0.0.1 --port "$PORT"
