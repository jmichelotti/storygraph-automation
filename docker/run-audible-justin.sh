#!/bin/bash
# Cron entrypoint. Everything the container prints — including tracebacks on
# stderr — is appended to logs/cron/audible-justin.log. Without this, cron
# discards the output and a crashed run leaves no trace anywhere.
set -uo pipefail
cd "$(dirname "$0")/.."

mkdir -p logs/cron
LOG="logs/cron/audible-justin.log"

{
    echo "============================================================"
    echo "CRON START — $(date '+%Y-%m-%d %H:%M:%S %Z')"
    docker compose run --rm audible-justin
    rc=$?
    echo "CRON END — exit=$rc — $(date '+%Y-%m-%d %H:%M:%S %Z')"
    echo
    exit $rc
} >>"$LOG" 2>&1
