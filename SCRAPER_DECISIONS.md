# Scraper Architecture Decisions

Historical note:

- The live scraper runtime now targets MSSQL.
- PostgreSQL references in this document describe an earlier planning direction and are retained as design history only.

This file records the currently agreed architectural decisions for the scraper rework so implementation starts from fixed assumptions instead of reopening design questions.

Companion documents:

- [SCRAPER_REWORK_REVIEW.md](SCRAPER_REWORK_REVIEW.md)
- [SCRAPER_TARGET_ARCHITECTURE.md](SCRAPER_TARGET_ARCHITECTURE.md)
- [SCRAPER_IMPLEMENTATION_BLUEPRINT.md](SCRAPER_IMPLEMENTATION_BLUEPRINT.md)

## Confirmed Decisions

### 1. Image binaries are required

Decision:

- The reworked scraper must retain image binaries.

Implementation implication:

- Do not store image bytes in the primary jobs table.
- Store them in a separate PostgreSQL table keyed by job and asset role, using `BYTEA`.

### 2. Full schema rework is allowed

Decision:

- Downstream consumers can tolerate new tables and a new schema layout.

Implementation implication:

- The target design should favor a clean PostgreSQL model over compatibility with the current SQL Server layout.

### 3. Unchanged jobs update only `last_seen_at`

Decision:

- When a job is unchanged, the scraper should update only `last_seen_at`.

Implementation implication:

- No detail refresh.
- No image refresh.
- No enrichment rerun.
- No other field updates in the unchanged path.

### 4. Listing pages appear viable over plain HTTP

Research result from May 1, 2026:

- A direct HTTP GET to `https://www.jobindex.dk/jobsoegning?subid=1` returned `200` and exposed `jobad-wrapper-` markers in the response body.
- A headless Selenium check on the same page found `20` live job wrappers and a normal next-page URL: `https://www.jobindex.dk/jobsoegning/it/systemudvikling?page=2`.
- A direct HTTP GET to that page 2 URL also returned `200` and exposed `20` listing markers.

Conclusion:

- Listing collection should be HTTP-first.
- Selenium should remain only as a fallback path for categories or pages that stop exposing parseable listing payloads over HTTP.
- The parser must be redesigned to extract listing content from the embedded server response payload instead of assuming the cards exist as direct DOM nodes in the raw HTML.

### 5. Raw HTML should not be retained

Decision:

- Raw HTML should be processed in memory only and not stored in the database.

Implementation implication:

- Persist hashes, provenance, and normalized/raw extracted fields instead of the full page source.

### 6. Richer detailed storage is preferred

Decision:

- The existing fields are the minimum acceptable data set.
- A more detailed normalized schema is preferred.

Implementation implication:

- Keep a current-state jobs table.
- Add richer observation and snapshot-style tables so extraction quality and changes are auditable over time.

### 7. Host-level rate limits are deferred for now

Decision:

- Do not block the architecture on exact host-level request-rate rules yet.

Implementation implication:

- Keep per-host throttling hooks in the design, but do not treat final rate-limit policy as a blocker for implementation planning.

### 8. Target database is PostgreSQL and quarantine is not persisted

Decision:

- The reworked scraper should use PostgreSQL.
- Quarantine records should not be stored in the database.

Implementation implication:

- Use PostgreSQL-native patterns such as `TIMESTAMPTZ`, `BYTEA`, `JSONB`, and `INSERT ... ON CONFLICT`.
- Validation failures should be logged and counted in run summaries, but not persisted as quarantine rows.

## Immediate Consequences For Implementation Planning

1. The new persistence layer should be designed for PostgreSQL first, not adapted from SQL Server.
2. The target schema should include separate tables for jobs, observations, snapshots, categories, keywords, and image binaries.
3. The unchanged path should be extremely cheap: canonicalize URL, compare state, update `last_seen_at`, and stop.
4. Listing collection should be redesigned around HTTP parsing before any Selenium-heavy rewrite is attempted.
5. No raw HTML archive or quarantine table should be included in the initial schema.
