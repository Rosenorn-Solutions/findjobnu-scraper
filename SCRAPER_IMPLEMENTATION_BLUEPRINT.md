# Scraper Implementation Blueprint

Historical note:

- The live scraper runtime now targets MSSQL.
- PostgreSQL references in this blueprint reflect the earlier implementation plan and are kept for historical context.

Companion documents:

- [SCRAPER_REWORK_REVIEW.md](SCRAPER_REWORK_REVIEW.md)
- [SCRAPER_TARGET_ARCHITECTURE.md](SCRAPER_TARGET_ARCHITECTURE.md)
- [SCRAPER_DECISIONS.md](SCRAPER_DECISIONS.md)

## Scope

This blueprint is a greenfield plan.

Assumptions:

- Ignore the current single-file scraper implementation.
- Ignore the current SQL Server schema.
- Do not plan migration, cutover, or compatibility work.
- Build the new scraper as a clean PostgreSQL-backed system from zero.

## Target Outcome

The finished system should provide:

- HTTP-first listing discovery for Jobindex category pages
- selective detail fetching only for new or changed jobs
- a normalized PostgreSQL schema built from scratch
- required image-binary retention in dedicated asset storage tables
- raw and normalized field storage for debugging and analytics
- structured run/event logging without persisted quarantine storage
- a parser regression corpus and repeatable integration tests

## Recommended Technical Stack

### Runtime

- Python 3.12
- PostgreSQL 16+
- `psycopg[binary,pool]` for PostgreSQL connections and pooling
- `httpx` for HTTP collection and detail fetches
- `selectolax` for fast HTML parsing
- `beautifulsoup4` only where ad hoc parsing is more convenient than high-speed selectors
- `spacy` for NLP
- `yake` for keywords
- `lingua-language-detector` for dominant-language detection
- `pydantic-settings` for configuration loading
- `structlog` or JSON-formatted standard logging for structured logs
- `pytest` for unit and integration tests
- `testcontainers` for PostgreSQL integration tests

### Browser fallback

- Selenium remains available as a fallback collector only for pages that stop exposing parseable listing payloads over HTTP.

### Packaging

- `src/` layout
- one `pyproject.toml`
- no notebook dependency
- no framework dependency beyond what the pipeline needs

## Repository Layout

```text
findjobnu-scraper/
  pyproject.toml
  README.md
  .env.example
  sql/
    001_init.sql
  src/
    jobindex_scraper/
      __init__.py
      main.py
      config.py
      logging.py
      models.py
      enums.py
      catalog.py
      coordinator.py
      change_detector.py
      normalizer.py
      validator.py
      http/
        client.py
        throttling.py
      listing/
        collector.py
        jobindex_parser.py
        pagination.py
        fallback_browser.py
      detail/
        fetcher.py
        extractor_registry.py
        extractors/
          base.py
          generic.py
          jobindex.py
          workday.py
          oracle.py
          hrmanager.py
      enrich/
        language.py
        descriptions.py
        keywords.py
        images.py
      persistence/
        pool.py
        writer.py
        repositories.py
        ddl.py
      telemetry/
        events.py
        metrics.py
  tests/
    unit/
    integration/
    fixtures/
      listing/
      detail/
```

## Module-by-Module Plan

### `config.py`

Responsibilities:

- load environment-based configuration
- validate required settings
- expose immutable runtime settings object

Minimum settings:

- `DATABASE_URL`
- `EXTRACTION_VERSION`
- `LISTING_CONCURRENCY`
- `DETAIL_CONCURRENCY`
- `DETAIL_PER_HOST_CONCURRENCY`
- `NLP_BATCH_SIZE`
- `HTTP_TIMEOUT_SECONDS`
- `USER_AGENT`
- `HEADLESS_BROWSER_ENABLED`
- `LOG_LEVEL`

### `models.py`

Responsibilities:

- define typed DTOs passed between stages
- keep stage boundaries explicit

Required DTOs:

- `CategoryRecord`
- `ListingObservation`
- `DetailFetchTask`
- `DetailPayload`
- `ExtractedDetail`
- `NormalizedJob`
- `ValidatedJob`
- `PersistResult`
- `RunSummary`

Use frozen dataclasses unless validation pressure justifies Pydantic models.

### `catalog.py`

Responsibilities:

- provide the category seed set
- expose category metadata for the run

Greenfield recommendation:

- store the initial category catalog in PostgreSQL
- support bootstrapping from a checked-in seed file if preferred

### `http/client.py`

Responsibilities:

- manage shared HTTP clients
- set headers, timeouts, retry rules, and transport defaults

Behavior:

- one shared client for listing pages
- one shared client for detail pages
- explicit connect/read timeouts
- configurable retry wrapper for transient errors

### `http/throttling.py`

Responsibilities:

- enforce per-host concurrency ceilings for detail pages
- support future rate-limit tuning without rewriting fetch code

### `listing/collector.py`

Responsibilities:

- fetch listing pages over HTTP
- handle pagination
- emit raw page payloads to the listing parser

Key rule:

- do not fetch detail pages here

### `listing/jobindex_parser.py`

Responsibilities:

- extract listing observations from Jobindex listing responses
- parse the embedded `var Stash = ...` payload rather than relying on top-level DOM cards

Observed payload fact:

- the listing response contains a script tag with `var Stash = {...}` and entries containing an `html` field whose content includes `jobad-wrapper-*` markup

Implementation approach:

1. locate the script containing `var Stash =`
2. isolate the JavaScript object literal
3. parse the relevant branch that holds the listing payload
4. extract each `html` fragment
5. parse each fragment into a `ListingObservation`

Fallback behavior:

- if the HTTP parser fails for a category page, record an event and optionally delegate that page to `fallback_browser.py`

### `listing/pagination.py`

Responsibilities:

- derive next-page URLs from the current listing response
- normalize category-relative pagination URLs

Observed fact:

- Selenium exposed a normal next-page URL shape such as `https://www.jobindex.dk/jobsoegning/it/systemudvikling?page=2`

### `listing/fallback_browser.py`

Responsibilities:

- provide a Selenium-based fallback for HTTP collection failures
- return HTML in the same shape expected by the listing parser where possible

Constraint:

- this module is not part of the default hot path

### `change_detector.py`

Responsibilities:

- canonicalize the job URL
- compare listing hash against current persisted state
- decide `new`, `changed_listing`, or `unchanged`

Critical rule:

- `unchanged` means update only `last_seen_at` and stop

### `detail/fetcher.py`

Responsibilities:

- fetch detail pages for new or changed jobs
- capture final response URL, status, elapsed time, and in-memory HTML payload

Constraint:

- raw HTML must not be persisted

### `detail/extractor_registry.py`

Responsibilities:

- dispatch detail pages to host-specific extractors first
- fall back to a generic extractor when no host-specific extractor matches

### `detail/extractors/*.py`

Responsibilities:

- extract clean description, company data, location, and image URLs
- report extractor name, version, and warnings

Initial extractors to build first:

- `jobindex.py`
- `workday.py`
- `oracle.py`
- `hrmanager.py`
- `generic.py`

### `normalizer.py`

Responsibilities:

- canonicalize URLs
- normalize timestamps to UTC
- normalize location and company URL fields
- merge listing and detail signals
- compute hashes for listing, detail, and description text

### `validator.py`

Responsibilities:

- reject invalid normalized jobs before persistence
- emit warnings for suspicious but usable jobs

Hard rejects:

- no canonical job URL
- no normalized title
- no valid scrape timestamp
- no usable job identity after extraction

Important rule:

- rejected jobs are logged and counted, not stored as quarantine rows

### `enrich/language.py`

Responsibilities:

- detect the dominant language of the cleaned description
- route text to the right NLP pipeline

### `enrich/descriptions.py`

Responsibilities:

- run batched spaCy parsing
- produce sentence-level or chunk-level derived fields if required later

### `enrich/keywords.py`

Responsibilities:

- run YAKE on validated descriptions
- merge keywords with provenance and confidence
- enforce dedupe and count limits

### `enrich/images.py`

Responsibilities:

- fetch required banner/footer images only after a job passes validation
- compute binary content hashes
- emit persistence payloads for image storage

### `persistence/pool.py`

Responsibilities:

- create and manage the PostgreSQL connection pool
- expose transaction helpers

### `persistence/repositories.py`

Responsibilities:

- keep SQL isolated from orchestration logic
- expose upsert and batch-write primitives

Repository areas:

- runs
- categories
- jobs
- observations
- snapshots
- images
- keywords
- events

### `persistence/writer.py`

Responsibilities:

- perform all writes through one central writer component
- batch observations, snapshots, keywords, images, and events
- execute cheap unchanged-path `last_seen_at` updates

### `telemetry/events.py`

Responsibilities:

- define structured event schema for logging and optional event-table writes

### `telemetry/metrics.py`

Responsibilities:

- track stage counts and timings
- emit a run summary at completion

### `coordinator.py`

Responsibilities:

- orchestrate the end-to-end run
- own queue sizing and worker startup/shutdown
- publish the final run summary

### `main.py`

Responsibilities:

- provide the CLI entrypoint
- start a scrape run
- support category filtering and dry-run modes later if needed

## Runtime Flow

```text
Run start
  -> load config
  -> open PostgreSQL pool
  -> create scrape_run row
  -> load active categories
  -> fetch listing pages over HTTP
  -> parse listing observations from embedded Stash payload
  -> canonicalize URL and compute listing hash
  -> upsert job identity
  -> if unchanged: update last_seen_at only
  -> if new/changed: queue detail fetch
  -> fetch detail page
  -> extract normalized fields and image URLs
  -> validate
  -> enrich language and keywords
  -> fetch required image binaries
  -> write snapshot, keywords, category links, images, and current job pointers
  -> write run summary
Run end
```

## PostgreSQL Schema DDL

This schema assumes a fresh PostgreSQL database.

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TYPE run_status AS ENUM ('running', 'completed', 'failed', 'cancelled');
CREATE TYPE event_status AS ENUM ('info', 'warning', 'error');
CREATE TYPE image_role AS ENUM ('banner', 'footer');

CREATE TABLE scrape_runs (
    scrape_run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMPTZ NULL,
    status run_status NOT NULL DEFAULT 'running',
    extraction_version TEXT NOT NULL,
    config_fingerprint TEXT NOT NULL,
    notes TEXT NULL
);

CREATE TABLE categories (
    category_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    category_key TEXT NOT NULL UNIQUE,
    category_name TEXT NOT NULL,
    listing_url TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE jobs (
    job_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    canonical_job_url TEXT NOT NULL UNIQUE,
    source_host TEXT NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_detail_fetched_at TIMESTAMPTZ NULL,
    last_http_status SMALLINT NULL,
    current_snapshot_id BIGINT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE job_observations (
    job_observation_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    scrape_run_id UUID NOT NULL REFERENCES scrape_runs(scrape_run_id) ON DELETE CASCADE,
    job_id BIGINT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    category_id BIGINT NOT NULL REFERENCES categories(category_id),
    listing_page_url TEXT NOT NULL,
    listing_position INTEGER NOT NULL,
    job_url_raw TEXT NOT NULL,
    job_title_raw TEXT NULL,
    company_name_raw TEXT NULL,
    company_url_raw TEXT NULL,
    location_raw TEXT NULL,
    published_raw TEXT NULL,
    banner_image_url_raw TEXT NULL,
    footer_image_url_raw TEXT NULL,
    listing_hash CHAR(64) NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (scrape_run_id, job_id, category_id, listing_page_url, listing_position)
);

CREATE TABLE job_images (
    job_image_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_id BIGINT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    image_role image_role NOT NULL,
    source_url TEXT NOT NULL,
    content_type TEXT NULL,
    content_sha256 CHAR(64) NOT NULL,
    image_bytes BYTEA NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (job_id, image_role, content_sha256)
);

CREATE TABLE job_snapshots (
    job_snapshot_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_id BIGINT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    extraction_version TEXT NOT NULL,
    listing_hash CHAR(64) NOT NULL,
    detail_html_hash CHAR(64) NOT NULL,
    description_text_hash CHAR(64) NOT NULL,
    job_title_raw TEXT NULL,
    job_title_normalized TEXT NOT NULL,
    company_name_raw TEXT NULL,
    company_name_normalized TEXT NULL,
    company_url_raw TEXT NULL,
    company_url_normalized TEXT NULL,
    location_raw TEXT NULL,
    location_normalized TEXT NULL,
    published_raw TEXT NULL,
    published_utc TIMESTAMPTZ NULL,
    job_description_raw TEXT NULL,
    job_description_clean TEXT NULL,
    field_provenance JSONB NOT NULL DEFAULT '{}'::JSONB,
    extraction_warnings JSONB NOT NULL DEFAULT '[]'::JSONB,
    dominant_language TEXT NULL,
    language_confidence DOUBLE PRECISION NULL,
    banner_image_id BIGINT NULL REFERENCES job_images(job_image_id),
    footer_image_id BIGINT NULL REFERENCES job_images(job_image_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (job_id, extraction_version, detail_html_hash)
);

ALTER TABLE jobs
ADD CONSTRAINT jobs_current_snapshot_fk
FOREIGN KEY (current_snapshot_id)
REFERENCES job_snapshots(job_snapshot_id);

CREATE TABLE job_categories (
    job_id BIGINT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    category_id BIGINT NOT NULL REFERENCES categories(category_id),
    linked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (job_id, category_id)
);

CREATE TABLE job_keywords (
    job_keyword_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_snapshot_id BIGINT NOT NULL REFERENCES job_snapshots(job_snapshot_id) ON DELETE CASCADE,
    keyword TEXT NOT NULL,
    source TEXT NOT NULL,
    confidence_score DOUBLE PRECISION NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (job_snapshot_id, keyword, source)
);

CREATE TABLE scrape_events (
    scrape_event_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    scrape_run_id UUID NOT NULL REFERENCES scrape_runs(scrape_run_id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    event TEXT NOT NULL,
    status event_status NOT NULL,
    canonical_job_url TEXT NULL,
    source_host TEXT NULL,
    details_json JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_jobs_last_seen_at ON jobs (last_seen_at);
CREATE INDEX idx_jobs_is_active ON jobs (is_active);
CREATE INDEX idx_job_observations_job_id ON job_observations (job_id);
CREATE INDEX idx_job_observations_scrape_run_id ON job_observations (scrape_run_id);
CREATE INDEX idx_job_snapshots_job_id_created_at ON job_snapshots (job_id, created_at DESC);
CREATE INDEX idx_job_categories_category_id_job_id ON job_categories (category_id, job_id);
CREATE INDEX idx_job_keywords_snapshot_id ON job_keywords (job_snapshot_id);
CREATE INDEX idx_scrape_events_run_stage ON scrape_events (scrape_run_id, stage);
```

## Persistence Rules

### `jobs`

- one row per canonical job URL
- unchanged path updates only `last_seen_at` and `updated_at`

### `job_observations`

- cheap listing evidence for each observed card
- written even when the job is unchanged, because observations are useful for run diagnostics

### `job_snapshots`

- written only for new or meaningfully changed jobs
- represent the current extracted version of the job

### `job_images`

- written only after a job passes validation
- reused if the same binary hash already exists for that job and role

### `scrape_events`

- used for diagnostics and counters
- not a quarantine table

## Build Plan

### Phase 1: Scaffold and project foundation

Deliverables:

- `pyproject.toml`
- `src/` package layout
- environment-based config loader
- structured logger
- DTO definitions
- local CLI entrypoint

Acceptance criteria:

- the project starts without importing the legacy script
- configuration validates at startup
- structured logs emit valid JSON lines

### Phase 2: PostgreSQL foundation

Deliverables:

- `sql/001_init.sql`
- connection pool
- repository methods for runs, categories, jobs, and events
- central persistence writer skeleton

Acceptance criteria:

- a fresh PostgreSQL database can be initialized from the DDL
- the scraper can create a run row and write a completion row

### Phase 3: HTTP-first listing collector

Deliverables:

- category loader
- HTTP listing fetcher
- Jobindex `var Stash` parser
- listing pagination logic
- `ListingObservation` emission

Acceptance criteria:

- sample categories produce parsed listing observations without Selenium
- page 1 and page 2 both parse successfully via HTTP

### Phase 4: Identity and unchanged-path handling

Deliverables:

- canonical URL function
- listing hash function
- `jobs` upsert logic
- `last_seen_at` only update path
- category-link upsert logic

Acceptance criteria:

- repeat observations of the same unchanged job do not trigger detail fetch
- unchanged jobs update only `last_seen_at`

### Phase 5: Detail extraction and normalization

Deliverables:

- detail fetcher
- extractor registry
- host-specific extractors for initial priority hosts
- generic extractor
- normalization and validation layers

Acceptance criteria:

- new jobs produce validated normalized records
- invalid jobs produce events and counters rather than persisted quarantine rows

### Phase 6: Enrichment and binary image persistence

Deliverables:

- language detection
- batched spaCy execution
- YAKE keyword pipeline
- image fetcher and `job_images` writes
- snapshot and keyword persistence

Acceptance criteria:

- new jobs create snapshots, keywords, and required image binaries
- repeat unchanged jobs do not refetch images or rerun enrichment

### Phase 7: Coordinator and operational hardening

Deliverables:

- queue-based orchestration
- graceful shutdown
- run summary output
- browser fallback path for listing failures

Acceptance criteria:

- the run drains cleanly on stop
- run summary includes category counts, unchanged counts, detail failures, and image-byte totals

## Parser Design Notes For Jobindex Listing Pages

### Current known facts

- raw HTTP listing responses contain listing payload markers without browser rendering
- the payload is embedded inside a script tag containing `var Stash = {...}`
- listing fragments are available through an `html` field whose value contains job-card markup

### Recommended parser strategy

1. locate the `var Stash =` script text
2. isolate the full object literal safely
3. decode the relevant branch containing result objects
4. iterate result objects and parse each `html` fragment
5. derive the next-page URL from the page response or known pagination URLs

### Fallback triggers

Use Selenium only when one of these happens:

- `var Stash =` cannot be found
- the result branch no longer contains parseable `html` fragments
- the page returns an anti-bot shape that still works in a browser session

## Hashing Strategy

Use SHA-256 hex digests for:

- `listing_hash`
- `detail_html_hash`
- `description_text_hash`
- `content_sha256` for image binaries

Canonical hash inputs:

- `listing_hash`: canonical URL, normalized title, normalized company name, raw published, raw location
- `detail_html_hash`: raw detail HTML bytes in memory
- `description_text_hash`: cleaned description text after normalization

## Testing Strategy

### Unit tests

- canonical URL normalization
- Jobindex listing payload extraction
- pagination parsing
- listing hash generation
- change detector decisions
- host-specific detail extractor behavior
- validation rules
- keyword dedupe behavior

### Integration tests

- PostgreSQL DDL bootstrap
- repository upserts and snapshot writes
- unchanged-path `last_seen_at` updates only
- image-binary writes and dedupe behavior

### Fixture corpus

Store fixtures for:

- Jobindex native detail pages
- Workday-hosted pages
- Oracle-hosted pages
- HR Manager-hosted pages
- one page with heavy boilerplate
- one page with mixed Danish/English content
- one raw Jobindex listing response containing the embedded `Stash` payload

### Smoke test command

Target command after Phases 1-5:

```bash
python -m jobindex_scraper.main --category subid_1 --max-pages 2
```

## Definition Of Done

The greenfield build is ready when all of the following are true:

- a fresh PostgreSQL instance can be initialized from `sql/001_init.sql`
- HTTP-only listing collection works for sample categories without Selenium in the normal path
- new jobs create `jobs`, `job_observations`, `job_snapshots`, `job_keywords`, and `job_images` rows as appropriate
- unchanged jobs update only `last_seen_at`
- raw HTML is not persisted anywhere
- validation failures are logged and counted, not stored as quarantine rows
- image binaries are stored outside the primary jobs table
- the run emits a structured summary with counts and timings
- the regression corpus passes in CI

## Explicitly Out Of Scope

- migration from the existing script
- migration from SQL Server
- compatibility layers for current tables
- data backfill from old runs
- cutover planning

## Bottom Line

Starting from zero, the most effective build order is: PostgreSQL foundation first, HTTP-first listing collection second, unchanged-path change detection third, detail extraction fourth, enrichment and binary persistence fifth, and operational hardening last. That keeps the build grounded in the final architecture while avoiding any time spent preserving legacy behavior.
