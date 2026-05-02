# Scraper Rework Review

Reviewed target:
- `jobindex.dk` listing pages and the linked employer-hosted job detail pages.
- Primary hotspots: the listing-to-detail enrichment loop in `extract_job_data()` and the persistence path in `DatabaseWriter`.

Compliance note:
- The current implementation fans out across `jobindex.dk` and third-party employer domains without explicit per-host throttling. Before increasing concurrency, confirm `robots.txt`, terms of service, and any anti-bot limits for both the index site and downstream hosts.

## Executive Summary

The scraper is functional, but most of its expensive work happens before it knows whether a listing is new. That single design choice cascades into the main reliability, performance, and data-quality problems:

- Existing jobs are re-enriched because the in-memory dedupe bootstrap exists but is never called.
- Each job detail page can trigger multiple network requests, multiple spaCy passes, and image downloads even when the row already exists in SQL Server.
- The database writer performs row-by-row lookups and commits, which will become the dominant bottleneck as volume grows.
- Key fields such as `JobUrl` and `Published` are stored without canonicalization or normalization, which weakens dedupe quality and downstream analytics.

The highest-value rework is to split the scraper into two stages:

1. Discover listing metadata cheaply.
2. Enrich only unseen or changed jobs.

That should be paired with URL normalization, a stronger scrape-state model, and batch-oriented database writes.

Companion architecture: [SCRAPER_TARGET_ARCHITECTURE.md](SCRAPER_TARGET_ARCHITECTURE.md).
Resolved design decisions: [SCRAPER_DECISIONS.md](SCRAPER_DECISIONS.md).

## Highest-Priority Findings

| Priority | Finding | Evidence | Impact | Recommended change |
| --- | --- | --- | --- | --- |
| P0 | Existing-URL bootstrap is never used | `setup_existing_joburls()` is defined in `scraper.py:119-139`, but the main entrypoint only calls `setup_database_connection()` and `setup_scraping_urls()` in `scraper.py:1085-1087` | Every run treats existing jobs as candidates for detail fetch, NLP, image download, and "new job" counting until the database writer rejects them | Call the bootstrap before launching category threads, but only after canonicalizing URLs. If memory becomes a concern, load a time-bounded set or a persisted hash/Bloom filter instead of raw strings |
| P0 | The hot path performs expensive enrichment before dedupe is resolved | Listing parsing reads `job_url` in `scraper.py:541`, downloads images in `scraper.py:569` and `scraper.py:578`, fetches detail HTML in `scraper.py:590`, and runs keywords only later in `scraper.py:660` | Existing jobs still consume network, CPU, and memory; repeated runs get slower as data grows | Canonicalize the URL immediately, check recent and persisted state immediately, and skip detail/image/NLP work for known jobs unless the listing metadata indicates change |
| P0 | The same text is processed by spaCy more than once per language | `extract_job_description()` creates `doc_da` and `doc_en` in `scraper.py:453-454`, and the caller repeats `doc_da = nlp_da(...)` and `doc_en = nlp_en(...)` in `scraper.py:600-601` | Roughly doubles the most expensive CPU step in the scraper | Parse each detail document once per language, reuse the docs for sentence selection and fallback extraction, and move to `nlp.pipe()` batching where possible |
| P1 | The database write path is query-heavy and commit-heavy | `update_category_for_joburl()` commits per row in `scraper.py:193`; insert flow re-selects `JobID` in `scraper.py:323`; category and join-table helpers issue more selects in `scraper.py:856-874` | Higher latency, more lock churn, and poor scalability once category volume increases | Replace row-by-row checks with set-based upserts, cache category IDs in memory, and return inserted IDs via `OUTPUT INSERTED.JobID` or `SCOPE_IDENTITY()` |
| P1 | `JobUrl` is stored in the raw href format rather than a canonical form | `job_url = job_link.get('href')` in `scraper.py:541`, while a separate absolute URL is only built for detail fetch in `scraper.py:585-589` | The same logical posting can appear as relative vs absolute, or with query-string variations, which weakens dedupe and uniqueness guarantees | Introduce a canonical URL function that resolves relative paths, strips fragments and non-essential query parameters, lowercases the host, and stores the normalized form |
| P1 | `Published` is copied from HTML without normalization | `published_date = time_tag.get('datetime')` in `scraper.py:615` | The database receives mixed string/date input, and timezone semantics are unclear for downstream analytics | Parse to timezone-aware UTC `datetime` objects before enqueueing; optionally store both raw and normalized published values |
| P2 | Category discovery brute-forces numeric subids via Selenium | `setup_scraping_urls()` loops `for subid in range(1, 250)` in `scraper.py:175` | The scraper pays browser startup and page-load cost for categories that may not exist or may be retired | Replace this with a maintained category seed list, or scrape the category directory once and reuse the discovered IDs |
| P2 | Each category thread owns both a browser and a dedicated DB writer | Per-category queue/writer setup starts in `scraper.py:931-932`, while thread fan-out is controlled by `max_concurrent_threads = 6` in `scraper.py:1121` | Browser memory, database connections, and writer coordination all scale together instead of independently | Use one central writer and separate listing/detail worker pools so browser, HTTP, NLP, and SQL concurrency can be tuned independently |
| P2 | Inline image download is expensive and increases database size quickly | Images are downloaded during listing parse in `scraper.py:569` and `scraper.py:578`, then stored as `VARBINARY(MAX)` | Increased runtime, more bandwidth, and larger backup/restore footprint | Store image URLs by default, and only materialize binaries when there is a concrete downstream need or a change event |

## Reliability Enhancements

### 1. Introduce explicit scrape state

The current logic mixes three concepts:

- seen recently in this process (`RECENT_URL_CACHE`)
- seen recently in the database (`setup_existing_joburls()`)
- inserted in the current batch (`DatabaseWriter` duplicate handling)

That should become a single authoritative state model. Recommended columns:

- `CanonicalJobUrl`
- `FirstSeenAt`
- `LastSeenAt`
- `LastDetailFetchedAt`
- `LastHTTPStatus`
- `ContentHash`
- `ExtractionVersion`
- `IsActive`

Benefits:

- repeat runs can skip unchanged detail pages safely
- failures can be retried intelligently
- schema changes can trigger selective reprocessing using `ExtractionVersion`

### 2. Separate listing discovery from detail enrichment

The listing page should produce a lightweight record first:

- canonical URL
- title from listing
- company name from listing
- location from listing
- published text/raw timestamp
- listing category

Only if the canonical URL is unseen or the listing hash has changed should the scraper fetch the detail page, NLP fields, and optional images.

This change is the single biggest reliability and performance improvement because it reduces the amount of work coupled to HTML variability on downstream employer sites.

### 3. Add bounded retries and per-host throttling

The shared `requests.Session` has generic retries, but the current design still lacks host-aware protection.

Recommended behavior:

- separate retry policy for listing pages vs employer-hosted detail pages
- cap concurrent requests per host
- add jittered backoff for `429` and `5xx`
- log host-level failure rates and automatically reduce concurrency for noisy hosts

### 4. Replace broad `print()`-based error handling with structured logging

Current logging makes it difficult to answer operational questions such as:

- which hosts fail most often?
- how many detail pages timed out?
- which selectors are drifting?
- how many jobs were skipped because they already existed?

Recommended minimum fields per event:

- `category`
- `canonical_job_url`
- `source_host`
- `event`
- `http_status`
- `elapsed_ms`
- `exception_type`
- `attempt`

### 5. Make the pipeline restart-safe

The scraper should be able to stop and resume without wasting work. Add:

- a persisted queue or checkpoint for pending detail fetches
- `ScrapedAt` / `EnrichedAt` markers
- content hash or ETag comparison where available
- idempotent upserts for the core job record

## Performance Enhancements

### 1. Move enrichment behind dedupe

Current order:

1. Parse listing HTML
2. Download banner/footer images
3. Fetch detail HTML
4. Run spaCy
5. Run YAKE
6. Let the writer decide whether the row already exists

Target order:

1. Parse listing HTML
2. Build canonical URL
3. Check persisted scrape state
4. If existing and unchanged: update `LastSeenAt`, category linkage, and stop
5. If new or changed: fetch detail HTML, run NLP, and optionally fetch images

This should dramatically reduce:

- HTTP calls per job
- CPU time per job
- memory churn inside BeautifulSoup and spaCy
- queue pressure on the database writer

### 2. Batch NLP with `nlp.pipe()` and disable unused components

Today the scraper performs document parsing inside a tight per-job loop. That is expensive and defeats spaCy's batching optimizations.

Recommended approach:

- collect detail texts for new/changed jobs in small batches
- run `nlp_da.pipe()` and `nlp_en.pipe()` over those batches
- disable components that are not needed for a given field
- avoid reparsing the same text for fallback extraction

If language detection is introduced first, many jobs will only need one language pipeline instead of both.

### 3. Reduce browser usage

Selenium is appropriate when a page truly requires client-side rendering, but the current design uses a browser for every category page and then uses `requests` for every detail page.

Recommended sequence:

1. Verify whether listing pages can be fetched with `requests` after a single cookie/session bootstrap.
2. If yes, reserve Selenium for the rare pages that actually need it.
3. If not, keep Selenium only for listing pagination, but move detail fetching to a bounded HTTP worker pool.

This will cut memory usage and browser startup cost significantly.

### 4. Collapse write-time round trips

The write path should become set-based.

Recommended changes:

- maintain a local cache of `category_name -> category_id`
- use bulk insert for new jobs
- capture inserted IDs without a second `SELECT`
- bulk insert job-category links and keywords
- avoid `commit()` inside per-row update helpers

Database-layer improvements:

- keep the unique index on canonical URL
- add an index on `JobCategories(CategoryID, JobID)` if category-based reads matter
- add an index on `JobKeywords(JobID)`
- use timezone-aware timestamp types in the target database

### 5. Stop storing large binaries inline

Banner and footer image binaries are required, but storing them inline with the primary job row is still costly.

Recommended direction:

- store binaries in a dedicated asset table keyed by job and asset role
- deduplicate binaries by content hash when practical
- fetch binaries only for new jobs or when the image URL changes

## Data Quality Enhancements

### 1. Canonicalize all source identifiers

The scraper should normalize:

- job URL
- company URL
- source host
- category identifier

Suggested rules for job URLs:

- resolve relative paths to absolute URLs
- lowercase scheme and host
- strip fragments
- drop tracking query parameters
- sort remaining query parameters if any are semantically relevant

This is the foundation for reliable dedupe.

### 2. Preserve raw and normalized values side by side

For fields that may need debugging or reprocessing, store both:

- `PublishedRaw` and `PublishedUtc`
- `LocationRaw` and `LocationNormalized`
- `CompanyNameRaw` and `CompanyNameNormalized`
- `JobDescriptionRaw` and `JobDescriptionClean`

That makes extractor improvements reversible and auditable.

### 3. Track field provenance

Several fields can come from either the listing page, the detail page, or NLP fallback logic. Persisting provenance improves trust.

Recommended provenance values:

- `listing`
- `detail_page`
- `nlp_fallback`
- `manual_override`

This is especially important for:

- `CompanyName`
- `CompanyURL`
- `JobLocation`
- `JobDescription`

### 4. Add language detection before keyword extraction

Current keyword extraction can run both Danish and English YAKE pipelines on the same description. That increases noise and cost.

Recommended flow:

1. detect dominant language on the cleaned description
2. run the matching spaCy/YAKE pipeline first
3. only run the second language pipeline when confidence is low or the text is clearly mixed-language

### 5. Improve description cleaning and change detection

The description extractor currently contains site-specific logic plus a generic fallback, but it does not persist enough metadata to know when extraction quality regresses.

Recommended additions:

- store `DetailHTMLHash`
- store `DescriptionTextHash`
- store `SourceHost`
- store `ExtractionPattern` or selector name

With those fields, a parser regression becomes measurable instead of anecdotal.

### 6. Normalize dates and locations early

For analytics and dedupe, convert dates and location text before persistence.

Recommended normalizations:

- `PublishedUtc` as timezone-aware UTC
- `ScrapedAtUtc` and `SeenAtUtc`
- parse remote/hybrid/on-site flags from location text
- split municipality/region/country when available

### 7. Add hard validation rules before insert

At minimum, reject or quarantine rows that lack:

- canonical job URL
- non-empty title
- non-empty category
- valid scrape timestamp

Soft validation warnings should flag:

- empty description after detail fetch
- company URL host mismatch
- suspiciously short titles or descriptions
- duplicate keywords after normalization

## Suggested Rework Plan

### Phase 1: Immediate low-risk fixes

These are the highest-value changes with the least architectural disruption.

1. Call `setup_existing_joburls()` during startup.
2. Introduce `canonicalize_job_url()` and store only canonical URLs.
3. Skip detail fetch, NLP, and image download for jobs already known in scrape state.
4. Parse `Published` into UTC `datetime` objects before enqueueing.
5. Remove duplicate spaCy parsing by reusing docs.
6. Cache category IDs in memory and remove per-row commits from update helpers.

Expected result:

- materially lower repeat-run time
- fewer unnecessary external requests
- better duplicate suppression
- cleaner date values in the database

### Phase 2: Pipeline separation

1. Create a lightweight listing-stage DTO.
2. Send only unseen or changed jobs to a detail-enrichment worker pool.
3. Centralize database writes in one writer component.
4. Batch NLP and keyword extraction.

Expected result:

- better throughput
- lower memory use
- clearer failure isolation between listing parse, detail fetch, NLP, and SQL

### Phase 3: Data model and observability improvements

1. Add scrape-state metadata and content hashes.
2. Add structured logs and metrics.
3. Split raw vs normalized fields.
4. Move required image binaries into a dedicated asset table.

Expected result:

- stronger auditability
- easier incident response
- measurable data-quality trends over time

## Success Metrics

Track these before and after the rework:

- listing pages processed per minute
- detail fetches per newly discovered job
- median and p95 detail fetch latency
- NLP seconds per enriched job
- SQL batch latency
- percentage of jobs skipped as already known before enrichment
- percentage of rows with null or fallback-derived `CompanyName`, `JobLocation`, and `Published`
- duplicate canonical URL rate
- bytes of image data stored per run

## Recommended Regression Test Set

Build a fixed corpus of representative postings from:

- `jobindex.dk` native detail pages
- Workday-hosted jobs
- Oracle Cloud-hosted jobs
- HR Manager-hosted jobs
- at least one source with heavy boilerplate
- at least one source with mixed Danish/English content

For each fixture, assert:

- canonical URL stability
- non-empty title
- normalized published date
- stable company name
- stable location extraction
- non-empty cleaned description
- keyword count and uniqueness limits

## Documentation and Operational Follow-up

The current README is directionally useful, but it should be updated once the rework starts so it matches the real pipeline. In particular:

- category coverage in the README should match the actual crawler behavior
- configuration should document rate limits, concurrency, and host-specific overrides
- operational docs should explain what qualifies a job as new, changed, inactive, and failed

## Bottom Line

If only a few changes are made first, they should be these:

1. Canonicalize URLs and load existing URLs at startup.
2. Skip detail fetch, image download, and NLP for known unchanged jobs.
3. Remove duplicate spaCy passes.
4. Make database writes set-based instead of row-by-row.

Those four changes attack the root of the current reliability, performance, and data-quality problems without requiring an immediate full rewrite.
