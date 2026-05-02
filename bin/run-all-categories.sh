#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
SCRAPER="${SCRAPER:-$APP_DIR/.venv/bin/jobindex-scraper}"
MAX_PAGES="${MAX_PAGES:-999}"

if [[ -n "${JOBINDEX_SCRAPER_SUBIDS:-}" ]]; then
  read -r -a subids <<<"$JOBINDEX_SCRAPER_SUBIDS"
else
  mapfile -t subids < <(seq 1 28)
fi

for subid in "${subids[@]}"; do
  echo "$(date -u +%FT%TZ) starting subid ${subid}"
  "$SCRAPER" \
    --subid "$subid" \
    --max-pages "$MAX_PAGES" \
    --record-run \
    --fetch-details
done