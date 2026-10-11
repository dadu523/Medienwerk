#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_dir"

if [[ ! -x .venv/bin/python || ! -f web/node_modules/next/dist/bin/next ]]; then
  printf 'Bitte zuerst die Abhängigkeiten installieren. Siehe LOCAL_TESTING.md.\n' >&2
  exit 1
fi

.venv/bin/python - <<'PY'
import socket
for port in (3000, 8008):
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind(('127.0.0.1', port))
        except OSError:
            raise SystemExit(f'Port {port} ist bereits belegt. Die laufende Anwendung zuerst beenden.')
PY

backend_pid=""
frontend_pid=""
cleanup() {
  for pid in "$backend_pid" "$frontend_pid"; do
    if [[ -n "$pid" ]]; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  wait || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

.venv/bin/python -m uvicorn server.main:app --host 127.0.0.1 --port 8008 &
backend_pid=$!
(
  cd web
  export BACKEND_URL="http://127.0.0.1:8008"
  exec node node_modules/next/dist/bin/next dev --hostname 127.0.0.1 --port 3000
) &
frontend_pid=$!

printf 'Medienwerk startet unter http://localhost:3000. Beenden mit Strg+C.\n'
wait -n "$backend_pid" "$frontend_pid"
