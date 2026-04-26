#!/usr/bin/env bash
# restart.sh — 대시보드 서버 재시작

set -e
cd "$(dirname "$0")"

PORT=${PORT:-8000}
RELOAD=${RELOAD:-true}   # 운영 시 RELOAD=false ./restart.sh

echo "[restart] 기존 서버 종료 중..."
if command -v taskkill.exe &>/dev/null; then
    PID=$(powershell.exe -Command "\$conn = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object LocalPort -eq ${PORT}; if (\$conn) { \$conn.OwningProcess } else { '' }" 2>/dev/null | tr -d '[:space:]')
    if [ -n "$PID" ]; then
        taskkill.exe /PID "$PID" /F 2>/dev/null && echo "[restart] PID $PID 종료" || echo "[restart] 종료 실패 (이미 없을 수 있음)"
    else
        echo "[restart] 실행중인 서버 없음"
    fi
else
    pkill -f "uvicorn src.dashboard" 2>/dev/null || true
fi

sleep 1

CACHE=".runtime/candidate_snapshot.json"
if [ -f "$CACHE" ]; then
    rm "$CACHE"
    echo "[restart] 캐시 삭제: $CACHE"
fi

echo "[restart] 서버 시작 -- http://localhost:${PORT}"
RELOAD_FLAG=""
[ "$RELOAD" = "true" ] && RELOAD_FLAG="--reload"

exec python -m uvicorn src.dashboard:app $RELOAD_FLAG --port "$PORT"
