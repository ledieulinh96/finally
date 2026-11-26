#!/usr/bin/env bash
# Stop and remove the FinAlly container (macOS/Linux). Keeps the finally-data volume. Idempotent.
set -euo pipefail
CONTAINER="finally"
if docker container inspect "$CONTAINER" >/dev/null 2>&1; then
  docker rm -f "$CONTAINER" >/dev/null
  echo "FinAlly stopped. Data kept in volume 'finally-data' (remove with: docker volume rm finally-data)."
else
  echo "FinAlly is not running."
fi
