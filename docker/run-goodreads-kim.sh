#!/bin/bash
# Cron entrypoint. Everything the container prints — including tracebacks on
# stderr — is appended to logs/cron/goodreads-kim.log. Without this, cron
# discards the output and a crashed run leaves no trace anywhere.
set -uo pipefail
cd "$(dirname "$0")/.."

mkdir -p logs/cron
LOG="logs/cron/goodreads-kim.log"

{
    echo "============================================================"
    echo "CRON START — $(date '+%Y-%m-%d %H:%M:%S %Z')"
    docker compose run --rm goodreads-kim
    rc=$?
    echo "CRON END — exit=$rc — $(date '+%Y-%m-%d %H:%M:%S %Z')"
    echo
    exit $rc
} >>"$LOG" 2>&1
