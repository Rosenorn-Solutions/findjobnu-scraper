#!/usr/bin/env bash
set -euo pipefail

load_env_file() {
  local env_file="$1"
  local line
  local name
  local value

  [[ -f "$env_file" ]] || return 0

  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^[[:space:]]*$ ]] && continue
    [[ "$line" =~ ^[[:space:]]*# ]] && continue

    if [[ "$line" =~ ^[[:space:]]*export[[:space:]]+ ]]; then
      line="${line#export }"
    fi

    if [[ ! "$line" =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)[[:space:]]*=(.*)$ ]]; then
      continue
    fi

    name="${BASH_REMATCH[1]}"
    value="${BASH_REMATCH[2]}"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"

    if [[ ${#value} -ge 2 && "$value" == \"*\" && "$value" == *\" ]]; then
      value="${value:1:${#value}-2}"
      value="${value//\\\"/\"}"
      value="${value//\\\\/\\}"
    elif [[ ${#value} -ge 2 && "$value" == \'*\' && "$value" == *\' ]]; then
      value="${value:1:${#value}-2}"
    fi

    printf -v "$name" '%s' "$value"
    export "$name"
  done < "$env_file"
}

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${JOBINDEX_SCRAPER_ENV_FILE:-/etc/jobindex-scraper.env}"

load_env_file "$ENV_FILE"

SCRAPER="${SCRAPER:-$APP_DIR/.venv/bin/jobindex-scraper}"
MAX_PAGES="${MAX_PAGES:-999}"

if [[ -z "${JOBINDEX_SCRAPER_DATABASE_URL:-}" ]]; then
  echo "JOBINDEX_SCRAPER_DATABASE_URL is not set. Define it in $ENV_FILE or export it before running this wrapper." >&2
  exit 1
fi

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