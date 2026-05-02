# Jobindex Scraper

Jobindex Scraper is a Python pipeline for collecting Jobindex listing pages, ranking third-party referral platforms, optionally persisting run state in MSSQL, and extracting normalized detail-page snapshots for supported external job hosts.

It is designed around two main workflows:

1. Stats-only discovery: collect Jobindex listings and inspect which external platforms show up most often.
2. Persisted scraping: store runs, observations, detail-fetch outcomes, and extracted snapshots in MSSQL so new and changed jobs can be tracked over time.

The current implementation is HTTP-only. It uses `requests` and `BeautifulSoup`, not browser automation.

## What the scraper does

- Collects category pages from Jobindex.
- Parses listing observations such as job URL, company, location, source host, and listing hash.
- Aggregates referral statistics by source host and platform domain.
- Optionally persists runs and listings in MSSQL.
- Queues detail fetches for new and changed jobs.
- Fetches detail pages and normalizes supported third-party job pages into a common snapshot model.
- Records detail-fetch failures and extraction failures for later analysis.

## Current capabilities

### Supported detail extractors

These hosts currently have dedicated detail extractors in `src/jobindex_scraper/detail/extractor.py`:

- `hr-manager.net`
- `thehub.io`
- `teamtailor.com`
- `myworkdayjobs.com`
- `emply.com`
- `midtjob.dk`
- `nytlaegejob.dk`
- `hr-on.com`
- `signatur.dk`

All other hosts fall back to a generic extractor that reads title and broad page text from the detail page. That fallback is useful, but it is not guaranteed to produce clean descriptions for heavily templated ATS sites.

### Runtime model

- One category is processed per invocation.
- Category selection is done with either `--subid` or `--category-url`.
- `--fetch-details` only works together with `--record-run`.
- Stats-only runs do not require MSSQL.
- Persisted runs require a SQL Server ODBC connection string in `JOBINDEX_SCRAPER_DATABASE_URL`.

## Repository guide

### Top-level layout

| Path | Purpose |
| --- | --- |
| `pyproject.toml` | Packaging metadata, dependencies, and console entry point. |
| `.env.example` | Safe environment-variable template for local or server deployment. |
| `config.ini` | Deprecated legacy placeholder. The current runtime does not read it. |
| `config.development.ini` | Deprecated legacy placeholder for local notes only. The current runtime does not read it. |
| `systemd/` | Checked-in `systemd` unit templates for Ubuntu server deployment. |
| `sql/001_init.sql` | SQL Server bootstrap schema. Run this on a fresh database before persisted scraping. |
| `src/jobindex_scraper/main.py` | CLI entry point and pipeline orchestration. |
| `src/jobindex_scraper/config.py` | Runtime settings loader. Reads environment variables only. |
| `src/jobindex_scraper/catalog.py` | Converts Jobindex `subid` values into category records. |
| `src/jobindex_scraper/listing/collector.py` | Fetches Jobindex listing pages and drives pagination. |
| `src/jobindex_scraper/listing/jobindex_parser.py` | Parses listing HTML into structured observations. |
| `src/jobindex_scraper/detail/fetcher.py` | Fetches detail pages for queued jobs. |
| `src/jobindex_scraper/detail/extractor.py` | Host-specific and generic detail extraction logic. |
| `src/jobindex_scraper/referral_stats.py` | Groups observations by source host and platform domain for prioritization. |
| `src/jobindex_scraper/persistence/` | MSSQL connection, repositories, DDL helpers, and writer orchestration. |
| `src/jobindex_scraper/models.py` | Shared dataclasses used across listing, detail, and persistence stages. |
| `tests/unit/` | Fast unit coverage for parser, main flow, extractor, fetcher, and stats logic. |
| `tests/integration/` | Optional live MSSQL smoke tests. |
| `SCRAPER_DECISIONS.md` | Design decisions and tradeoffs. |
| `SCRAPER_TARGET_ARCHITECTURE.md` | Higher-level architecture direction. |
| `SCRAPER_IMPLEMENTATION_BLUEPRINT.md` | Implementation planning notes. |
| `SCRAPER_REWORK_REVIEW.md` | Review notes from the scraper rework. |

### Data flow through the code

1. `main.py` parses CLI arguments and loads runtime settings.
2. `catalog.py` converts `--subid` into a `CategoryRecord`, or `main.py` builds one from `--category-url`.
3. `listing/collector.py` walks Jobindex pagination and hands each page to `listing/jobindex_parser.py`.
4. The parser emits `ListingObservation` records from `models.py`.
5. `referral_stats.py` can rank the referral hosts and platform domains immediately, even without persistence.
6. If `--record-run` is enabled, `persistence/writer.py` stores the observations and determines whether each job is `new`, `changed`, or `unchanged` based on the listing hash.
7. New and changed jobs become `DetailFetchTask` records.
8. `detail/fetcher.py` downloads the detail pages and records status, response URL, elapsed time, HTML hash, and raw HTML.
9. `detail/extractor.py` dispatches by platform domain and produces normalized `ExtractedDetail` snapshots.
10. `persistence/writer.py` stores detail fetch outcomes, extracted snapshots, and extraction failure events.

### Key dataclasses

The most important dataclasses in `src/jobindex_scraper/models.py` are:

- `CategoryRecord`: category identity and listing URL.
- `ListingObservation`: a single parsed job seen on a listing page.
- `DetailFetchTask`: a queued detail fetch created for a new or changed job.
- `DetailFetchResult`: the outcome of fetching a detail page.
- `ExtractedDetail`: the normalized detail snapshot that can be written to MSSQL.

## Configuration

### Source of truth

The current runtime reads configuration from environment variables only.

Use `.env.example` as the checked-in starting point for real configuration.

`config.ini` and `config.development.ini` still exist in the repository, but the current Python runtime does not load them. They are now deprecated placeholders only, kept to make that distinction explicit and to avoid carrying real secrets in git.

### Environment variables

| Variable | Required | Default | Meaning |
| --- | --- | --- | --- |
| `JOBINDEX_SCRAPER_USER_AGENT` | No | Chrome-like desktop UA | User-Agent header sent on all HTTP requests. |
| `JOBINDEX_SCRAPER_HTTP_TIMEOUT_SECONDS` | No | `20` | Per-request timeout in seconds. |
| `JOBINDEX_SCRAPER_LOG_LEVEL` | No | `INFO` | Python logging level. |
| `JOBINDEX_SCRAPER_DATABASE_URL` | Only with `--record-run` | unset | SQL Server ODBC connection string used by the persistence layer. |
| `JOBINDEX_SCRAPER_EXTRACTION_VERSION` | No | `dev` | Version tag stored with snapshots and scrape runs. |

### HTTP behavior

The shared HTTP session currently:

- retries `GET` and `HEAD` requests up to 3 times,
- uses a `0.5` backoff factor,
- retries on `429`, `500`, `502`, `503`, and `504`,
- sends `Accept-Language: da,en;q=0.8`.

This is enough for lightweight scraping, but it is not a substitute for site-specific rate limiting or compliance review. Start conservatively.

## Ubuntu 24.04 setup

The instructions below assume a fresh Ubuntu 24.04 server and a shell user with `sudo` access.

### 1. Install system packages

For a Python-only install:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip
```

If you also want a local MSSQL instance on the same server:

```bash
sudo apt install -y ca-certificates curl gnupg unixodbc

sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo \"$VERSION_CODENAME\") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | sudo gpg --dearmor -o /etc/apt/keyrings/microsoft.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/microsoft.gpg] https://packages.microsoft.com/ubuntu/24.04/prod noble main" | sudo tee /etc/apt/sources.list.d/microsoft-prod.list > /dev/null

sudo apt update
sudo ACCEPT_EULA=Y apt install -y msodbcsql18 mssql-tools18
```

### 2. Create an application user

This is optional, but recommended for a server deployment.

```bash
sudo adduser --system --group --home /opt/jobindex-scraper jobindex
sudo mkdir -p /opt/jobindex-scraper
sudo chown -R jobindex:jobindex /opt/jobindex-scraper
```

### 3. Clone the repository

```bash
cd /opt/jobindex-scraper
sudo -u jobindex git clone <your-repo-url> findjobnu-scraper
cd /opt/jobindex-scraper/findjobnu-scraper
```

If you are deploying from an existing checkout instead of cloning from Git, copy the repository to the target directory and ensure ownership is correct.

### 4. Create a virtual environment and install the package

```bash
sudo -u jobindex python3 -m venv /opt/jobindex-scraper/findjobnu-scraper/.venv
sudo -u jobindex /opt/jobindex-scraper/findjobnu-scraper/.venv/bin/python -m pip install --upgrade pip
sudo -u jobindex /opt/jobindex-scraper/findjobnu-scraper/.venv/bin/pip install -e /opt/jobindex-scraper/findjobnu-scraper
```

This creates the console script `jobindex-scraper` inside the virtual environment.

### 5. Smoke-test the install

Run a small stats-only scrape first. This does not require MSSQL.

```bash
sudo -u jobindex /opt/jobindex-scraper/findjobnu-scraper/.venv/bin/jobindex-scraper \
  --subid 1 \
  --max-pages 1 \
  --dump-referral-stats
```

If this works, packaging, dependencies, networking, and the basic parser path are all in place.

## MSSQL setup

SQL Server is only needed if you want persisted runs, change detection, or detail extraction snapshots.

### 1. Start a local SQL Server container

```bash
sudo docker volume create jobindex-mssql-data

sudo docker run -d \
  --name jobindex-mssql \
  --restart unless-stopped \
  -e ACCEPT_EULA=Y \
  -e MSSQL_SA_PASSWORD='ChangeThisPassword123!' \
  -p 127.0.0.1:1433:1433 \
  -v jobindex-mssql-data:/var/opt/mssql \
  mcr.microsoft.com/mssql/server:2022-latest
```

This binds SQL Server to localhost only.

### 2. Create the application database

```bash
/opt/mssql-tools18/bin/sqlcmd -S localhost,1433 -U sa -P 'ChangeThisPassword123!' -C -Q "IF DB_ID(N'jobindex_scraper') IS NULL CREATE DATABASE jobindex_scraper;"
```

### 3. Set the runtime connection string

Example connection string:

```bash
export JOBINDEX_SCRAPER_DATABASE_URL='Driver={ODBC Driver 18 for SQL Server};Server=localhost,1433;Database=jobindex_scraper;Uid=sa;Pwd=ChangeThisPassword123!;Encrypt=yes;TrustServerCertificate=yes'
```

### 4. Initialize the schema

Run the bootstrap SQL once against a fresh database:

```bash
python - <<'PY'
from pathlib import Path
import os

import pyodbc

connection = pyodbc.connect(os.environ["JOBINDEX_SCRAPER_DATABASE_URL"])
try:
  cursor = connection.cursor()
  for statement in Path("sql/001_init.sql").read_text(encoding="utf-8").split(";"):
    statement = statement.strip()
    if statement:
      cursor.execute(statement)
  connection.commit()
finally:
  connection.close()
PY
```

Important notes:

- `sql/001_init.sql` is the schema bootstrap. There is no migration framework in this repository today.
- The file creates the SQL Server tables, constraints, and indexes needed by the persistence layer.
- Run it on an empty database target.

### 5. Verify database connectivity

```bash
python - <<'PY'
import os

import pyodbc

connection = pyodbc.connect(os.environ["JOBINDEX_SCRAPER_DATABASE_URL"])
try:
  cursor = connection.cursor()
  cursor.execute("SELECT DB_NAME(), SYSUTCDATETIME()")
  print(cursor.fetchone())
finally:
  connection.close()
PY
```

## Getting started

### Fastest first run: stats only

Collect one category and print a referral leaderboard:

```bash
python -m jobindex_scraper.main \
  --subid 1 \
  --max-pages 5 \
  --dump-referral-stats \
  --referral-stats-limit 25
```

Use this mode when you want to answer questions like:

- Which external platforms show up most often?
- Which hosts are unsupported?
- How much of a category is still on Jobindex itself vs third-party ATS pages?

### Persist listing observations only

```bash
export JOBINDEX_SCRAPER_DATABASE_URL='Driver={ODBC Driver 18 for SQL Server};Server=localhost,1433;Database=jobindex_scraper;Uid=sa;Pwd=ChangeThisPassword123!;Encrypt=yes;TrustServerCertificate=yes'
export JOBINDEX_SCRAPER_EXTRACTION_VERSION='ubuntu-bootstrap'

python -m jobindex_scraper.main \
  --subid 1 \
  --max-pages 5 \
  --record-run
```

This stores the scrape run, observed jobs, and job-category links, and it decides which jobs are new or changed.

### Persist listings and fetch details

```bash
python -m jobindex_scraper.main \
  --subid 1 \
  --max-pages 5 \
  --record-run \
  --fetch-details
```

This adds:

- detail-page fetches for newly queued jobs,
- extracted snapshots for supported hosts,
- detail fetch events and extraction failure events.

### Limit detail-fetch volume during testing

```bash
python -m jobindex_scraper.main \
  --subid 1 \
  --max-pages 20 \
  --record-run \
  --fetch-details \
  --max-detail-tasks 10
```

### Dump listing observations

```bash
python -m jobindex_scraper.main \
  --subid 1 \
  --max-pages 1 \
  --dump-observations
```

### Dump queued detail tasks

```bash
python -m jobindex_scraper.main \
  --subid 1 \
  --max-pages 5 \
  --record-run \
  --dump-detail-tasks
```

### Scrape an explicit category URL

```bash
python -m jobindex_scraper.main \
  --category-url 'https://www.jobindex.dk/jobsoegning?subid=16' \
  --category-key 'subid_16_manual' \
  --category-name 'subid_16_manual' \
  --max-pages 3 \
  --dump-referral-stats
```

## CLI reference

| Argument | Meaning |
| --- | --- |
| `--subid` | Jobindex category id. Converted into `https://www.jobindex.dk/jobsoegning?subid=<id>`. |
| `--category-url` | Explicit listing URL for ad hoc categories. |
| `--category-key` | Category key for explicit URLs. Defaults to `ad_hoc`. |
| `--category-name` | Category name for explicit URLs. Defaults to the category key. |
| `--max-pages` | Maximum listing pages to walk. Default is `1`. |
| `--record-run` | Enable MSSQL persistence and scrape-run tracking. |
| `--fetch-details` | Fetch detail pages for queued new and changed jobs. Requires `--record-run`. |
| `--max-detail-tasks` | Limit the number of queued detail pages fetched in one invocation. |
| `--dump-observations` | Print parsed listing observations as JSON. |
| `--dump-detail-tasks` | Print queued detail fetch tasks as JSON. |
| `--dump-referral-stats` | Print referral statistics as JSON. Works without MSSQL. |
| `--referral-stats-limit` | Max number of leaderboard entries to include in stats output. |

## Example Ubuntu environment file

For a server deployment, it is usually cleaner to keep configuration in an environment file instead of exporting variables by hand each time.

Start from the checked-in `.env.example`:

```bash
cp .env.example /etc/jobindex-scraper.env
sudoedit /etc/jobindex-scraper.env
```

Example: `/etc/jobindex-scraper.env`

```bash
JOBINDEX_SCRAPER_USER_AGENT=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0 Safari/537.36
JOBINDEX_SCRAPER_HTTP_TIMEOUT_SECONDS=20
JOBINDEX_SCRAPER_LOG_LEVEL=INFO
JOBINDEX_SCRAPER_EXTRACTION_VERSION=ubuntu-prod-2026-05-02
JOBINDEX_SCRAPER_DATABASE_URL="Driver={ODBC Driver 18 for SQL Server};Server=localhost,1433;Database=jobindex_scraper;Uid=sa;Pwd=ChangeThisPassword123!;Encrypt=yes;TrustServerCertificate=yes"
```

Recommended permissions:

```bash
sudo chown root:jobindex /etc/jobindex-scraper.env
sudo chmod 640 /etc/jobindex-scraper.env
```

## Running under systemd

The scraper is a good fit for a one-shot `systemd` service plus a timer.

The repository ships parameterized templates you can install directly:

- `systemd/jobindex-scraper@.service`
- `systemd/jobindex-scraper@.timer`

Install them on Ubuntu:

```bash
sudo install -o root -g root -m 0644 systemd/jobindex-scraper@.service /etc/systemd/system/jobindex-scraper@.service
sudo install -o root -g root -m 0644 systemd/jobindex-scraper@.timer /etc/systemd/system/jobindex-scraper@.timer
sudo systemctl daemon-reload
```

### Single-category service

With the parameterized units, the systemd instance name is the Jobindex `subid`.

Example: `jobindex-scraper@16.service`

```ini
[Unit]
Description=Jobindex scraper for subid 16
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=jobindex
Group=jobindex
WorkingDirectory=/opt/jobindex-scraper/findjobnu-scraper
EnvironmentFile=/etc/jobindex-scraper.env
ExecStart=/opt/jobindex-scraper/findjobnu-scraper/.venv/bin/jobindex-scraper --subid 16 --max-pages 999 --record-run --fetch-details
```

The checked-in template already encodes that pattern, so you normally do not need to write this file yourself.

Example timer instance: `jobindex-scraper@16.timer`

```ini
[Unit]
Description=Run Jobindex scraper for subid 16 every 6 hours

[Timer]
OnBootSec=5m
OnUnitActiveSec=6h
Persistent=true

[Install]
WantedBy=timers.target
```

Enable it:

```bash
sudo systemctl enable --now jobindex-scraper@16.timer
```

Follow logs:

```bash
journalctl -u jobindex-scraper@16.service -f
```

### Multiple categories on a schedule

The application processes one category per invocation. For a full sweep, prefer one serial wrapper script over enabling a large number of `jobindex-scraper@<subid>.timer` instances at once. That keeps request volume predictable across Jobindex and downstream ATS hosts, and it makes overlap prevention much simpler.

### Full run across all top-level categories

For a practical full run, use one wrapper that walks the current top-level Jobindex category subid range.

At the time of writing, the top-level range is handled as `1..28`. If Jobindex changes that catalog later, set `JOBINDEX_SCRAPER_SUBIDS` in `/etc/jobindex-scraper.env` instead of editing the checked-in script.

The repository now ships these checked-in assets:

- `bin/run-all-categories.sh`
- `systemd/jobindex-scraper-all.service`
- `systemd/jobindex-scraper-all.timer`

Install the wrapper script:

```bash
sudo install -d -o jobindex -g jobindex /opt/jobindex-scraper/findjobnu-scraper/bin
sudo install -o jobindex -g jobindex -m 0755 bin/run-all-categories.sh /opt/jobindex-scraper/findjobnu-scraper/bin/run-all-categories.sh
```

Run it once manually first:

```bash
sudo -u jobindex /opt/jobindex-scraper/findjobnu-scraper/bin/run-all-categories.sh
```

The wrapper auto-loads `/etc/jobindex-scraper.env` before starting the scraper, so the manual command above uses the same environment file as the systemd service. If you keep the file somewhere else, set `JOBINDEX_SCRAPER_ENV_FILE=/path/to/file.env` before invoking the wrapper.

Optional overrides:

- Set `JOBINDEX_SCRAPER_SUBIDS` in `/etc/jobindex-scraper.env` to run only a specific subset, for example `JOBINDEX_SCRAPER_SUBIDS="1 10 11 16 17 21 24 27 28"`.
- Set `MAX_PAGES` in the service environment if you want the full-run wrapper to use something other than `999`.
- Set `JOBINDEX_SCRAPER_ENV_FILE` only if you want the wrapper to read a different env file than `/etc/jobindex-scraper.env`.

### systemd service for the full run

Install the dedicated one-shot service for the wrapper. It uses `flock` so a second full run exits immediately instead of overlapping with one already in progress.

```bash
sudo install -o root -g root -m 0644 systemd/jobindex-scraper-all.service /etc/systemd/system/jobindex-scraper-all.service
```

### systemd timer for the full run

Start conservatively. A full all-category sweep is much heavier than a single-category timer.

```bash
sudo install -o root -g root -m 0644 systemd/jobindex-scraper-all.timer /etc/systemd/system/jobindex-scraper-all.timer
```

Enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now jobindex-scraper-all.timer
```

Start one run immediately if you want to test the service path:

```bash
sudo systemctl start jobindex-scraper-all.service
```

Follow logs:

```bash
journalctl -u jobindex-scraper-all.service -f
```

If you only want a curated subset instead of a full sweep, set `JOBINDEX_SCRAPER_SUBIDS="1 10 11 16 17 21 24 27 28"` in `/etc/jobindex-scraper.env`.

## Testing

### Fast unit tests

```bash
python -m unittest discover -s tests/unit
```

### Focused extractor tests

```bash
python -m unittest tests.unit.test_detail_extractor
```

### Broader detail pipeline validation

```bash
python -m unittest \
  tests.unit.test_detail_fetcher \
  tests.unit.test_detail_extractor \
  tests.unit.test_persistence_writer \
  tests.integration.test_mssql_persistence
```

### MSSQL integration-test prerequisites

The live MSSQL smoke test uses `JOBINDEX_SCRAPER_TEST_DATABASE_URL`.

If the variable is unset, or the SQL Server target is unavailable, the integration test skips itself rather than failing the suite.

## Operational notes

- Start with small `--max-pages` values on a new server. Only use `999` when you intentionally want a full category sweep.
- Stats-only runs are the safest first production command because they do not mutate a database.
- `--fetch-details` requires persistence because detail fetch tasks come from new and changed jobs identified in MSSQL.
- The current extractor coverage is strongest on the hosts listed above. Unsupported platforms may need dedicated DOM or JSON-LD extractors later.
- This repository currently uses direct SQL bootstrap, not schema migrations. Plan database upgrades accordingly.

## Troubleshooting

### `README.md` missing during packaging

This repository expects a root `README.md` because `pyproject.toml` declares it as the project readme. If packaging fails with a missing readme error, ensure the root README is present.

### `JOBINDEX_SCRAPER_DATABASE_URL must be set`

That error means you used `--record-run` without providing a SQL Server ODBC connection string.

Fix it by exporting `JOBINDEX_SCRAPER_DATABASE_URL` first, or drop `--record-run` if you only want stats.

### `--fetch-details requires --record-run`

This is expected. Detail fetches are driven by queued tasks from persisted listing state.

### `pyodbc is required for MSSQL persistence`

Install project dependencies inside the active virtual environment:

```bash
python -m pip install -e .
```

### The scraper seems to ignore `config.ini`

That is expected with the current codebase. Runtime configuration is environment-variable based, using `JOBINDEX_SCRAPER_*` variables from your shell or `/etc/jobindex-scraper.env`.

### Detail descriptions contain site chrome or navigation text

That usually means the host is still using the generic extractor and needs a host-specific parser in `src/jobindex_scraper/detail/extractor.py`.

Use referral statistics plus a live sample URL to prioritize the next host to support.

## Further reading

If you want the design context behind the current implementation, start with:

- `SCRAPER_DECISIONS.md`
- `SCRAPER_TARGET_ARCHITECTURE.md`
- `SCRAPER_IMPLEMENTATION_BLUEPRINT.md`
- `SCRAPER_REWORK_REVIEW.md`

These files are useful when you need to understand why the scraper is organized around listing observations, detail tasks, snapshots, and referral-driven extractor prioritization.