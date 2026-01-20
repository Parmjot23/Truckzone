#!/usr/bin/env sh
set -e

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT_DIR"

SLEEP_SECONDS="${RECURRING_WORKER_SLEEP_SECONDS:-86400}"

while true; do
  python manage.py runcrons
  sleep "$SLEEP_SECONDS"
done
