#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PORT="${PORT:-4174}"
HOST="${HOST:-127.0.0.1}"
PYTHON="${PYTHON:-python3}"

echo "Billywear KKLLA 로컬 서버를 시작합니다."
echo "주소: http://$HOST:$PORT"
echo "관리자 로그인 정보: $ROOT/runtime/admin-login.txt"
echo

exec "$PYTHON" "$ROOT/server.py" --host "$HOST" --port "$PORT"
