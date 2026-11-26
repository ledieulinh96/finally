#!/usr/bin/env bash
# Start FinAlly in Docker (macOS/Linux). Idempotent.
# Usage: scripts/start_mac.sh [--build] [--no-open]
set -euo pipefail

IMAGE="finally"
CONTAINER="finally"
VOLUME="finally-data"
PORT="${FINALLY_PORT:-8000}"
URL="http://localhost:${PORT}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BUILD=0
OPEN=1
for arg in "$@"; do
  case "$arg" in
    --build) BUILD=1 ;;
    --no-open) OPEN=0 ;;
    -h|--help) echo "Usage: $0 [--build] [--no-open]"; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

if ! command -v docker >/dev/null 2>&1; then
  echo "Error: docker is not installed or not on PATH." >&2; exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "Error: the Docker daemon is not running. Start Docker Desktop and retry." >&2; exit 1
fi

if [[ $BUILD -eq 1 ]] || ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Building image '$IMAGE'..."
  docker build -t "$IMAGE" "$ROOT"
fi

# Already running? Nothing to do (unless we just rebuilt).
if [[ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null || true)" == "true" ]]; then
  if [[ $BUILD -eq 1 ]]; then
    echo "Restarting container with the new image..."
    docker rm -f "$CONTAINER" >/dev/null
  else
    echo "FinAlly is already running at $URL"
    [[ $OPEN -eq 1 ]] && command -v open >/dev/null 2>&1 && open "$URL" || true
    exit 0
  fi
fi

# Remove a stale stopped container with the same name.
if docker container inspect "$CONTAINER" >/dev/null 2>&1; then
  docker rm -f "$CONTAINER" >/dev/null
fi

port_in_use_error() {
  echo "Error: host port $PORT is already in use by another process or container." >&2
  if [[ -n "${1:-}" ]]; then echo "  Held by: $1" >&2; fi
  echo "  Pick a free port, e.g.:  FINALLY_PORT=8012 $0 ${*:2}" >&2
  exit 1
}

# Fail early and clearly if the host port is taken.
HOLDER="$(docker ps --filter "publish=$PORT" --format '{{.Names}}' 2>/dev/null | head -n1 || true)"
if [[ -n "$HOLDER" ]]; then
  port_in_use_error "container '$HOLDER'" "$@"
elif command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  port_in_use_error "$(lsof -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | awk 'NR==2{print $1" (pid "$2")"}')" "$@"
fi

ENV_ARGS=()
if [[ -f "$ROOT/.env" ]]; then
  ENV_ARGS=(--env-file "$ROOT/.env")
else
  echo "Warning: .env not found — starting without it (AI chat needs OPENROUTER_API_KEY; see .env.example)." >&2
fi

if ! RUN_ERR="$(docker run -d --name "$CONTAINER" \
  -v "$VOLUME":/app/db \
  -p "$PORT":8000 \
  ${ENV_ARGS[@]+"${ENV_ARGS[@]}"} \
  "$IMAGE" 2>&1 >/dev/null)"; then
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  if grep -qiE 'port is already allocated|address already in use' <<<"$RUN_ERR"; then
    port_in_use_error "" "$@"
  fi
  echo "Error: docker run failed:" >&2
  echo "$RUN_ERR" >&2
  exit 1
fi

echo -n "Waiting for FinAlly to become healthy"
for _ in $(seq 1 30); do
  if curl -fsS "$URL/api/health" >/dev/null 2>&1; then break; fi
  echo -n "."; sleep 1
done
echo
echo "FinAlly is running at $URL"
echo "Logs: docker logs -f $CONTAINER    Stop: scripts/stop_mac.sh"

if [[ $OPEN -eq 1 ]]; then
  if command -v open >/dev/null 2>&1; then open "$URL"
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1 || true
  fi
fi
