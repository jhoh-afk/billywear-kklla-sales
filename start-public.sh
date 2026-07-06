#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PORT="${PORT:-4174}"
HOST="${HOST:-127.0.0.1}"
PYTHON="${PYTHON:-python3}"
SERVER_LOG="$ROOT/runtime/server.log"
TUNNEL_LOG="$ROOT/runtime/tunnel.log"

mkdir -p "$ROOT/runtime"

echo "Billywear KKLLA 서버를 시작합니다."
echo "관리자 로그인 정보: $ROOT/runtime/admin-login.txt"
echo "로컬 주소: http://$HOST:$PORT"

"$PYTHON" "$ROOT/server.py" --host "$HOST" --port "$PORT" > "$SERVER_LOG" 2>&1 &
SERVER_PID=$!

cleanup() {
  if kill -0 "$SERVER_PID" >/dev/null 2>&1; then
    kill "$SERVER_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

sleep 1

if ! curl -sS "http://$HOST:$PORT/api/health" >/dev/null; then
  echo "서버 시작에 실패했습니다. 로그를 확인하세요: $SERVER_LOG"
  exit 1
fi

echo
echo "공개 주소를 생성합니다."
echo "아래에 표시되는 https://...trycloudflare.com 주소를 사용하세요."
echo "이 창을 닫으면 공개 주소도 종료됩니다."
echo

"$ROOT/tools/cloudflared" tunnel \
  --protocol http2 \
  --no-autoupdate \
  --url "http://$HOST:$PORT" 2>&1 | tee "$TUNNEL_LOG"
