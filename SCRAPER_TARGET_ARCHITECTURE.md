# Scraper Target Architecture

Historical note:

- The live scraper runtime now targets MSSQL.
- PostgreSQL references in this architecture note describe the earlier target state, not the current provider choice.

Companion to [SCRAPER_REWORK_REVIEW.md](SCRAPER_REWORK_REVIEW.md).

Greenfield implementation plan: [SCRAPER_IMPLEMENTATION_BLUEPRINT.md](SCRAPER_IMPLEMENTATION_BLUEPRINT.md).

This document defines the target end-state for the scraper before implementation begins. It is intentionally more concrete than the review document and focuses on architecture, execution flow, schema evolution, operational behavior, and migration sequencing.

## Purpose

The current scraper works as a single-file pipeline, but it couples listing discovery, detail fetching, extraction, NLP enrichment, image download, and database persistence into one hot path. That makes it harder to:

- skip unchanged jobs cheaply
- control memory and concurrency independently by stage
- recover cleanly from partial failures
- measure data quality over time
- evolve the schema without destabilizing collection

The target architecture separates those concerns while keeping the initial implementation pragmatic:

- Python remains the runtime.
- PostgreSQL becomes the primary persistence layer.
- Selenium stays available, but only where a browser is actually required.
- Requests-based HTTP remains the default for detail fetching.

Resolved decisions for this architecture are tracked in [SCRAPER_DECISIONS.md](SCRAPER_DECISIONS.md).

## Design Goals

### Primary goals

- Reliability: the run can stop, resume, and retry without losing state or repeating large amounts of work.
- Performance: expensive stages run only for jobs that are new or changed.
- Data quality: raw and normalized fields are both preserved where needed.
- Maintainability: each stage has a single responsibility and clear inputs and outputs.
- Observability: the pipeline exposes enough information to debug host failures, parser drift, and data regressions.

### Secondary goals

- Keep migration incremental instead of requiring a one-shot rewrite.
- Preserve compatibility with current downstream consumers where feasible.
- Make category, host, and selector behavior configurable.

### Non-goals

- Replacing Python with a distributed scraper framework.
- Introducing Kafka, Redis, or other external infrastructure in the first rework.
- Perfect normalization on the first pass.
- Solving every historical data issue before rollout.

## Current-State Snapshot

Today the scraper effectively behaves like this:

1. Build a category URL list by brute-forcing subids.
2. Start one Selenium-driven scrape loop per category thread.
3. Parse listing cards.
4. Immediately fetch detail pages and images during listing extraction.
5. Run NLP and keyword extraction inline.
6. Push hydrated job dictionaries to a category-local database writer thread.
7. Let the writer determine whether the row already exists.

Current pain points created by this design:

- expensive enrichment happens before dedupe settles
- browser, HTTP, NLP, and SQL concurrency are bound together
- backpressure is local to a category, not global to the run
- retries are stage-unaware
- state needed for smart skipping is incomplete

## Target Architecture Overview

### High-level flow

```text
RunCoordinator
  -> CategoryCatalog
  -> ListingCollectorPool
       -> ListingParser
       -> ChangeDetector
       -> DetailTaskQueue
  -> DetailFetcherPool
       -> DetailExtractor
       -> Normalizer
       -> Validator
       -> PersistenceWriter
  -> MetricsLogger
  -> ScrapeStateStore
```

### Core principle

Listing discovery is cheap and frequent.
Detail enrichment is expensive and selective.

The architecture must make that distinction explicit.

## Component Model

### 1. RunCoordinator

Responsibilities:

- create the scrape run record
- load configuration
- initialize caches, queues, rate limiters, and shared clients
- start and stop workers in dependency order
- record run-level success and failure status

Inputs:

- configuration files
- category seed set
- extraction version

Outputs:

- `ScrapeRun` metadata
- bounded worker pools
- coordinated shutdown

### 2. CategoryCatalog

Responsibilities:

- provide the categories that should be scraped this run
- resolve category metadata such as subid, URL, display name, and active flag
- support either static seeding or discovery from a category directory page

Target behavior:

- do not brute-force unknown subids during the steady-state run
- support periodic category refresh as a separate maintenance task

Recommended output contract:

- `category_key`
- `category_name`
- `listing_url`
- `source_type`
- `is_active`

### 3. ListingCollectorPool

Responsibilities:

- fetch paginated listing pages
- manage browser or HTTP session lifecycle for listing pages
- handle cookie banners and listing-page-specific modal behavior
- emit raw listing page payloads to the parser

Design choice:

- Start with a small number of listing workers.
- Prefer HTTP-only collection because current research indicates the listing payload is available without Selenium.
- Keep Selenium as a fallback path, not the default for every page if it is avoidable.

Research note:

- On May 1, 2026, direct HTTP fetches of a sample listing page and its page 2 URL both returned `200` and exposed listing payload markers.
- Selenium was still useful for proving the next-page URL shape, but not for proving that listing content requires browser rendering.
- The key rework is therefore parser-side: extract the embedded listing payload from the HTTP response instead of relying on browser-expanded DOM nodes.

### 4. ListingParser

Responsibilities:

- parse a listing page into lightweight observations
- extract only fields available from the listing card
- avoid detail fetch, NLP, and image download

Target output contract: `ListingObservation`

- `scrape_run_id`
- `category_key`
- `category_name`
- `listing_page_url`
- `listing_position`
- `job_url_raw`
- `canonical_job_url`
- `job_title_raw`
- `company_name_raw`
- `company_url_raw`
- `location_raw`
- `published_raw`
- `banner_image_url_raw`
- `footer_image_url_raw`
- `listing_hash`
- `discovered_at_utc`

`listing_hash` should be computed from the normalized listing-visible fields so change detection can happen without a detail fetch.

### 5. ChangeDetector

Responsibilities:

- decide whether a listing observation is new, changed, unchanged, or invalid
- compare against persisted scrape state and the in-process run cache
- update `LastSeenAt` cheaply for unchanged jobs

Decision outcomes:

- `new`
- `changed_listing`
- `unchanged`
- `invalid`
- `quarantined`

Rules:

- `unchanged` jobs do not proceed to detail fetching and only update `last_seen_at`.
- `changed_listing` jobs proceed to detail fetching only if change affects downstream data or if policy says to refresh.
- `invalid` jobs are logged and excluded from the expensive path.

### 6. DetailTaskQueue

Responsibilities:

- buffer only jobs that require enrichment
- enforce bounded memory through queue sizing
- support resume-safe replay if a run stops mid-flight

Queue item contract: `DetailFetchTask`

- `scrape_run_id`
- `canonical_job_url`
- `category_key`
- `category_name`
- `listing_hash`
- `detail_refresh_reason`
- `company_name_raw`
- `company_url_raw`
- `location_raw`
- `published_raw`
- `banner_image_url_raw`
- `footer_image_url_raw`

### 7. DetailFetcherPool

Responsibilities:

- fetch job detail pages using HTTP by default
- apply per-host concurrency caps and retry policies
- capture fetch metadata for diagnostics
- emit raw detail payloads to extraction

Target behavior:

- one shared `requests.Session` or equivalent session pool
- per-host semaphore or token bucket
- jittered backoff for `429` and transient `5xx`
- circuit-breaker behavior for repeatedly failing hosts

Output contract: `DetailPayload`

- `canonical_job_url`
- `source_host`
- `http_status`
- `fetched_at_utc`
- `response_url`
- `response_headers_subset`
- `detail_html`
- `detail_html_hash`
- `elapsed_ms`
- `attempt_count`

`detail_html` is an in-memory stage payload only. It must not be stored in PostgreSQL.

### 8. DetailExtractor

Responsibilities:

- extract clean detail text from site-specific or generic selectors
- tag which extraction pattern succeeded
- preserve enough raw context to debug parser drift

Output contract: `ExtractedDetail`

- `canonical_job_url`
- `source_host`
- `extraction_pattern`
- `job_description_raw`
- `job_description_clean`
- `company_name_detail_raw`
- `company_url_detail_raw`
- `location_detail_raw`
- `extracted_banner_image_url`
- `extracted_footer_image_url`
- `extraction_warnings`

### 9. Normalizer

Responsibilities:

- canonicalize URLs
- normalize datetime values to UTC
- normalize location strings
- combine listing and detail signals into a single candidate record
- compute content hashes for change detection

Output contract: `NormalizedJob`

- `canonical_job_url`
- `job_url_raw`
- `source_host`
- `job_title_raw`
- `job_title_normalized`
- `company_name_raw`
- `company_name_normalized`
- `company_url_raw`
- `company_url_normalized`
- `location_raw`
- `location_normalized`
- `published_raw`
- `published_utc`
- `job_description_raw`
- `job_description_clean`
- `listing_hash`
- `detail_html_hash`
- `description_text_hash`
- `field_provenance`
- `banner_image_url`
- `footer_image_url`
- `scraped_at_utc`
- `extraction_version`

### 10. EnrichmentEngine

Responsibilities:

- perform language detection
- run spaCy and YAKE only for jobs that passed validation
- batch NLP work using `nlp.pipe()`
- add structured enrichment output instead of embedding opaque strings

Important implementation constraint:

- Start with a single bounded enrichment worker that batches documents.
- Only add parallel NLP workers after memory behavior is measured on the target machine.

Output contract additions:

- `dominant_language`
- `language_confidence`
- `keywords_detailed`
- `enrichment_warnings`

### 11. Validator

Responsibilities:

- apply hard rejects before persistence
- downgrade suspicious records to warnings where possible
- route unrecoverable cases to diagnostic logs and run metrics

Hard reject conditions:

- missing canonical job URL
- missing title after normalization
- invalid published value when the source claims one exists
- unparseable payload that yields no usable job identity

Soft warning conditions:

- empty description after successful detail fetch
- company URL host mismatch
- very short description
- fallback-only company or location

### 12. PersistenceWriter

Responsibilities:

- perform all SQL writes for the run through one central component
- update state for unchanged jobs cheaply
- write enriched jobs in batches
- keep database interactions idempotent

Rules:

- no per-row commits inside helper methods
- use one transaction per write batch
- capture inserted IDs without follow-up lookups when possible
- cache category IDs in memory for the lifetime of the run

### 13. MetricsLogger

Responsibilities:

- emit structured logs
- record stage timings and counts
- summarize the run by category and host

Minimum run summary:

- categories attempted
- listing pages fetched
- listing observations emitted
- jobs marked unchanged
- detail fetch attempts and failures
- enriched jobs persisted
- quarantined jobs
- bytes stored for images if enabled

## Data Contracts

### Contract design rules

- raw fields and normalized fields must coexist when debugging or reprocessing value matters
- identifiers must be canonicalized before persistence decisions are made
- contracts should be serializable so they can be logged or checkpointed
- stage outputs should not require the next stage to reparse prior inputs

### Contract boundaries

1. `ListingObservation`
2. `DetailFetchTask`
3. `DetailPayload`
4. `ExtractedDetail`
5. `NormalizedJob`
6. `ValidatedJob`
7. `PersistResult`

This is deliberately more structured than the current untyped job dictionary passed through the queue.

## Persistence Model

Chosen direction:

- Full rework is allowed.
- PostgreSQL is the target database.
- The target schema should be normalized rather than adapted from the current SQL Server layout.
- Raw HTML should not be stored.
- Quarantine rows should not be stored.

### PostgreSQL conventions

- `TIMESTAMPTZ` for all timestamps
- `BYTEA` for required image binaries
- `JSONB` for provenance or warning payloads when structured storage is useful
- `INSERT ... ON CONFLICT DO UPDATE` for idempotent writes
- `COPY` or batched inserts for high-volume observation loading

### Target tables

#### `jobs`

- one row per canonical job identity
- stores current state and the pointer to the latest normalized snapshot

Suggested columns:

- `job_id`
- `canonical_job_url`
- `source_host`
- `first_seen_at`
- `last_seen_at`
- `last_detail_fetched_at`
- `last_http_status`
- `current_snapshot_id`
- `is_active`

Notes:

- `canonical_job_url` must be unique.
- The unchanged path updates only `last_seen_at`.

#### `job_snapshots`

- one row per meaningful extracted version of a job
- stores detailed normalized and raw extracted fields without retaining raw HTML

Suggested columns:

- `job_snapshot_id`
- `job_id`
- `extraction_version`
- `listing_hash`
- `detail_html_hash`
- `description_text_hash`
- `job_title_raw`
- `job_title_normalized`
- `company_name_raw`
- `company_name_normalized`
- `company_url_raw`
- `company_url_normalized`
- `location_raw`
- `location_normalized`
- `published_raw`
- `published_utc`
- `job_description_raw`
- `job_description_clean`
- `field_provenance`
- `dominant_language`
- `language_confidence`
- `banner_image_id`
- `footer_image_id`
- `created_at`

#### `job_observations`

- one row per listing observation per run
- stores cheap listing evidence used for change detection and debugging

Suggested columns:

- `job_observation_id`
- `scrape_run_id`
- `canonical_job_url`
- `category_key`
- `listing_page_url`
- `listing_position`
- `job_title_raw`
- `company_name_raw`
- `company_url_raw`
- `location_raw`
- `published_raw`
- `listing_hash`
- `observed_at`

#### `job_images`

- stores required image binaries outside the main jobs and snapshots tables

Suggested columns:

- `job_image_id`
- `job_id`
- `image_role`
- `source_url`
- `content_type`
- `content_sha256`
- `image_bytes`
- `fetched_at`

Notes:

- `image_role` should distinguish banner vs footer.
- Image dedupe by `content_sha256` is recommended.

#### `categories`

- canonical category dimension

Suggested columns:

- `category_id`
- `category_key`
- `category_name`
- `listing_url`
- `is_active`

#### `job_categories`

- many-to-many link between jobs and categories

Suggested columns:

- `job_id`
- `category_id`
- `linked_at`

#### `job_keywords`

- one row per keyword for a given snapshot

Suggested columns:

- `job_keyword_id`
- `job_snapshot_id`
- `keyword`
- `source`
- `confidence_score`
- `created_at`

#### `scrape_runs`

- one row per scraper run

Suggested columns:

- `scrape_run_id`
- `started_at`
- `ended_at`
- `status`
- `extraction_version`
- `config_fingerprint`
- `notes`

#### `scrape_events`

- optional operational log table for run diagnostics
- should not be used as quarantine storage

Suggested columns:

- `scrape_event_id`
- `scrape_run_id`
- `stage`
- `event`
- `canonical_job_url`
- `source_host`
- `status`
- `details_json`
- `created_at`

### Explicit exclusions

- No raw HTML archive table.
- No persisted quarantine table.
- No compatibility layer for the current SQL Server schema as a design constraint.

## State Model

Each job should move through a small explicit state machine.

### Lifecycle states

- `discovered`
- `unchanged`
- `queued_for_detail`
- `detail_fetched`
- `enriched`
- `persisted`
- `failed_temporary`
- `failed_permanent`
- `inactive`

`quarantined` remains a transient processing outcome for logging and metrics only. It is not a persisted database state.

### State transition rules

- `discovered -> unchanged` when canonical URL exists and listing hash matches current state
- `discovered -> queued_for_detail` when new or changed
- `queued_for_detail -> detail_fetched` on successful HTTP fetch
- `detail_fetched -> enriched` on successful extraction and NLP
- `enriched -> persisted` on successful batch write
- any stage can move to `failed_temporary` when retryable
- any stage can move to `failed_permanent` when policy says do not retry automatically
- validation failures move to `quarantined`

## Concurrency Model

The target architecture should decouple stage concurrency.

### Recommended starting configuration

- listing collectors: `1-2`
- detail fetch workers: `4-8`
- per-host detail concurrency: `2`
- enrichment worker: `1`
- SQL writer: `1`

These are starting values, not fixed values.

### Why this shape

- listing collection is limited by page navigation and anti-bot tolerance
- detail fetching is mostly I/O-bound and benefits from bounded parallelism
- enrichment is CPU- and memory-sensitive
- SQL writes should be serialized through one writer for simpler idempotency and batching

### Backpressure rules

- if the detail queue is full, listing collectors pause after the current page
- if the writer queue is full, enrichment pauses
- if a host exceeds failure thresholds, tasks for that host are delayed or reduced in concurrency

## Fetch Strategy

### Listing fetch strategy

Preferred order:

1. HTTP-first listing collection.
2. Selenium only for categories or pages that stop exposing parseable listing payloads over HTTP.
3. Browser restart only on measured leak thresholds, not blind intervals if avoidable.

Research-backed conclusion:

- The sample category page and its page 2 URL were both retrievable over plain HTTP with listing payload markers present.
- Selenium exposed a normal next-page URL rather than a browser-only navigation mechanism.
- The likely blocker is not transport but extraction: the listing HTML appears embedded in the response payload rather than directly parseable as top-level DOM.

### Detail fetch strategy

- use HTTP by default
- respect redirects and capture final response URL
- set explicit connect and read timeouts
- maintain a separate retry policy for detail hosts
- capture fetch timing and status for every request

### Image fetch strategy

Required direction:

- store image binaries because they are a business requirement
- do not store them inline with the main jobs table
- store them in `job_images` with `BYTEA` and a content hash

If binaries are required:

- fetch them after the normalized job passes validation
- fetch only for new or changed image URLs
- store outside the primary jobs table

## Extraction Strategy

### Selector model

Extraction rules should be represented as host-specific strategies plus a generic fallback.

Suggested strategy order:

1. host-specific extractor
2. family-of-sites extractor
3. generic semantic extractor
4. quarantine if extraction yields no usable identity or content

Each extraction result should record:

- extractor name
- extractor version
- warnings
- whether fallback logic was used

### NLP strategy

Recommended order:

1. detect dominant language from cleaned description
2. batch documents with `nlp.pipe()`
3. run only the necessary language pipeline first
4. run secondary language extraction only when confidence is low or text is mixed

## Validation Strategy

Validation must happen before persistence and after normalization.

### Hard validations

- canonical URL is present and parseable
- title is present after normalization
- category key is known
- scrape timestamp is present

### Soft validations

- description is non-empty after detail fetch
- published value is parseable if present
- company and location are not purely fallback noise
- keyword count is within allowed limits

### Quarantine policy

Quarantine instead of silently dropping when:

- extractor returns contradictory identity fields
- parser drift is suspected
- required fields are missing but the page was fetched successfully

Persistence rule:

- Do not store quarantine rows in PostgreSQL.
- Emit structured logs and run-summary counters instead.

## Observability and Operations

### Structured logging fields

- `scrape_run_id`
- `category_key`
- `canonical_job_url`
- `source_host`
- `stage`
- `event`
- `status`
- `elapsed_ms`
- `attempt`
- `exception_type`
- `warning_count`

### Metrics to capture

- pages fetched per minute
- listing observations per page
- unchanged ratio
- detail fetch success ratio
- p50 and p95 detail latency
- enrichment seconds per job
- SQL batch latency
- quarantined ratio
- image bytes stored per run

### Operational safeguards

- host-level rate limiting
- retry caps by stage
- circuit breaker for noisy hosts
- graceful drain on shutdown
- run summary persisted even on failure

## Security and Compliance Notes

- Respect `robots.txt`, published terms, and host-specific rate limits before increasing concurrency.
- Do not attempt to cross authentication boundaries or protected content flows.
- Preserve only the data required for the business purpose.
- Treat raw HTML retention as optional and configurable if storage or privacy policies require minimization.

## Module Layout Proposal

The code does not need to be split into many files immediately, but the target boundaries should look like this:

```text
scraper/
  config.py
  coordinator.py
  catalog.py
  listing/
    collector.py
    parser.py
  detail/
    fetcher.py
    extractor.py
  enrich/
    language.py
    keywords.py
    normalizer.py
    validator.py
  persistence/
    writer.py
    schema.py
    state_store.py
  observability/
    logging.py
    metrics.py
  models.py
```

This is a logical target layout. The first implementation pass can keep fewer files if that reduces migration risk.

## Migration Plan

### Phase 0: Measurement baseline

Before refactoring behavior, capture:

- runtime by category
- detail fetch count
- average SQL batch size
- null rates for company, location, published, and description
- duplicate job URL count

This baseline is necessary to prove the rework is an improvement.

### Phase 1: Internal contracts and central writer

- introduce structured DTOs inside the current codebase
- create one central writer
- stop passing free-form dictionaries between stages
- remove per-row commits

Exit criteria:

- identical functional output
- lower database round trips

### Phase 2: Listing and detail separation

- split listing parsing from detail fetching
- add change detection before detail fetch
- enqueue only new or changed jobs for enrichment

Exit criteria:

- repeat runs issue materially fewer detail HTTP requests
- repeat runs finish materially faster

### Phase 3: Normalization and state model

- add canonical URL storage
- add published datetime normalization
- add hashes and extraction version
- add explicit job lifecycle states

Exit criteria:

- duplicate suppression improves
- restart behavior is predictable

### Phase 4: Extraction and enrichment hardening

- batch NLP
- add language detection
- add extractor provenance
- quarantine drifted pages instead of silently degrading

Exit criteria:

- lower NLP cost per enriched job
- fewer low-quality rows make it to persistence

### Phase 5: Schema evolution

- decide whether to stay evolutionary or move to the normalized target schema
- migrate downstream consumers if needed

Exit criteria:

- schema supports auditability and long-term maintenance without compatibility hacks

## Resolved Decisions

The decisions that were previously open are now recorded in [SCRAPER_DECISIONS.md](SCRAPER_DECISIONS.md).

The architecture now assumes:

1. PostgreSQL is the target database.
2. Full schema rework is acceptable.
3. Image binaries are required and live in a separate table.
4. Unchanged jobs update only `last_seen_at`.
5. Listing collection is HTTP-first, with Selenium retained only as fallback.
6. Raw HTML is not retained.
7. Quarantine is logged but not stored.

## Recommended First Implementation Order

When implementation begins, the most defensible order is:

1. add canonical URL handling and structured DTOs
2. define the PostgreSQL schema and centralize writes around it
3. separate listing observations from detail tasks
4. introduce change detection before detail fetch
5. batch NLP and add language detection
6. add binary image persistence in the dedicated table

This order delivers performance gains early while keeping rollback risk manageable.

## Acceptance Criteria For The Rework

The architecture should not be considered complete until these outcomes are true:

- repeat runs skip unchanged jobs before detail fetch
- the pipeline can stop and resume without duplicate writes
- browser, HTTP, NLP, and PostgreSQL concurrency are tunable independently
- canonical URLs are stable and drive dedupe
- raw and normalized published values are both available where needed
- extraction provenance is recorded
- image binaries are stored outside the primary jobs table
- raw HTML is not stored
- the run produces a structured summary with error counts and stage timings
- at least one representative regression corpus exists for parser verification

## Bottom Line

The target architecture is a staged pipeline with one cheap discovery path and one selective enrichment path, both coordinated by a central state and persistence model. If the implementation follows that shape, the scraper will become materially more reliable, faster on repeat runs, and easier to evolve without silent data-quality regressions.
