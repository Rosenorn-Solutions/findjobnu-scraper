CREATE TABLE scrape_runs (
    scrape_run_id UNIQUEIDENTIFIER NOT NULL PRIMARY KEY,
    started_at DATETIME2(6) NOT NULL CONSTRAINT DF_scrape_runs_started_at DEFAULT SYSUTCDATETIME(),
    ended_at DATETIME2(6) NULL,
    status NVARCHAR(20) NOT NULL CONSTRAINT DF_scrape_runs_status DEFAULT N'running',
    extraction_version NVARCHAR(255) NOT NULL,
    config_fingerprint NVARCHAR(64) NOT NULL,
    notes NVARCHAR(MAX) NULL,
    CONSTRAINT CK_scrape_runs_status CHECK (status IN (N'running', N'completed', N'failed', N'cancelled'))
);

CREATE TABLE categories (
    category_id BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    category_key NVARCHAR(255) NOT NULL UNIQUE,
    category_name NVARCHAR(255) NOT NULL,
    listing_url VARCHAR(900) NOT NULL,
    is_active BIT NOT NULL CONSTRAINT DF_categories_is_active DEFAULT 1,
    created_at DATETIME2(6) NOT NULL CONSTRAINT DF_categories_created_at DEFAULT SYSUTCDATETIME()
);

CREATE TABLE jobs (
    job_id BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    canonical_job_url VARCHAR(900) NOT NULL UNIQUE,
    source_host NVARCHAR(255) NOT NULL,
    current_listing_hash CHAR(64) NULL,
    first_seen_at DATETIME2(6) NOT NULL CONSTRAINT DF_jobs_first_seen_at DEFAULT SYSUTCDATETIME(),
    last_seen_at DATETIME2(6) NOT NULL CONSTRAINT DF_jobs_last_seen_at DEFAULT SYSUTCDATETIME(),
    last_detail_fetched_at DATETIME2(6) NULL,
    last_http_status SMALLINT NULL,
    current_snapshot_id BIGINT NULL,
    is_active BIT NOT NULL CONSTRAINT DF_jobs_is_active DEFAULT 1,
    created_at DATETIME2(6) NOT NULL CONSTRAINT DF_jobs_created_at DEFAULT SYSUTCDATETIME(),
    updated_at DATETIME2(6) NOT NULL CONSTRAINT DF_jobs_updated_at DEFAULT SYSUTCDATETIME()
);

CREATE TABLE job_observations (
    job_observation_id BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    scrape_run_id UNIQUEIDENTIFIER NOT NULL,
    job_id BIGINT NOT NULL,
    category_id BIGINT NOT NULL,
    listing_page_url VARCHAR(900) NOT NULL,
    listing_position INT NOT NULL,
    job_url_raw VARCHAR(900) NOT NULL,
    job_title_raw NVARCHAR(MAX) NULL,
    company_name_raw NVARCHAR(255) NULL,
    company_url_raw VARCHAR(900) NULL,
    location_raw NVARCHAR(255) NULL,
    published_raw NVARCHAR(255) NULL,
    banner_image_url_raw VARCHAR(900) NULL,
    footer_image_url_raw VARCHAR(900) NULL,
    listing_hash CHAR(64) NOT NULL,
    observed_at DATETIME2(6) NOT NULL CONSTRAINT DF_job_observations_observed_at DEFAULT SYSUTCDATETIME(),
    CONSTRAINT FK_job_observations_scrape_runs FOREIGN KEY (scrape_run_id) REFERENCES scrape_runs(scrape_run_id) ON DELETE CASCADE,
    CONSTRAINT FK_job_observations_jobs FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE,
    CONSTRAINT FK_job_observations_categories FOREIGN KEY (category_id) REFERENCES categories(category_id),
    CONSTRAINT UQ_job_observations UNIQUE (scrape_run_id, job_id, category_id, listing_page_url, listing_position)
);

CREATE TABLE job_images (
    job_image_id BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    job_id BIGINT NOT NULL,
    image_role NVARCHAR(20) NOT NULL,
    source_url VARCHAR(900) NOT NULL,
    content_type NVARCHAR(255) NULL,
    content_sha256 CHAR(64) NOT NULL,
    image_bytes VARBINARY(MAX) NOT NULL,
    fetched_at DATETIME2(6) NOT NULL CONSTRAINT DF_job_images_fetched_at DEFAULT SYSUTCDATETIME(),
    CONSTRAINT FK_job_images_jobs FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE,
    CONSTRAINT CK_job_images_role CHECK (image_role IN (N'banner', N'footer')),
    CONSTRAINT UQ_job_images UNIQUE (job_id, image_role, content_sha256)
);

CREATE TABLE job_snapshots (
    job_snapshot_id BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    job_id BIGINT NOT NULL,
    extraction_version NVARCHAR(255) NOT NULL,
    listing_hash CHAR(64) NOT NULL,
    detail_html_hash CHAR(64) NOT NULL,
    description_text_hash CHAR(64) NOT NULL,
    job_title_raw NVARCHAR(MAX) NULL,
    job_title_normalized NVARCHAR(255) NOT NULL,
    company_name_raw NVARCHAR(255) NULL,
    company_name_normalized NVARCHAR(255) NULL,
    company_url_raw VARCHAR(900) NULL,
    company_url_normalized VARCHAR(900) NULL,
    location_raw NVARCHAR(255) NULL,
    location_normalized NVARCHAR(255) NULL,
    published_raw NVARCHAR(255) NULL,
    published_utc DATETIME2(6) NULL,
    job_description_raw NVARCHAR(MAX) NULL,
    job_description_clean NVARCHAR(MAX) NULL,
    field_provenance NVARCHAR(MAX) NOT NULL CONSTRAINT DF_job_snapshots_field_provenance DEFAULT N'{}',
    extraction_warnings NVARCHAR(MAX) NOT NULL CONSTRAINT DF_job_snapshots_extraction_warnings DEFAULT N'[]',
    dominant_language NVARCHAR(50) NULL,
    language_confidence FLOAT NULL,
    banner_image_id BIGINT NULL,
    footer_image_id BIGINT NULL,
    created_at DATETIME2(6) NOT NULL CONSTRAINT DF_job_snapshots_created_at DEFAULT SYSUTCDATETIME(),
    CONSTRAINT FK_job_snapshots_jobs FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE,
    CONSTRAINT FK_job_snapshots_banner_image FOREIGN KEY (banner_image_id) REFERENCES job_images(job_image_id),
    CONSTRAINT FK_job_snapshots_footer_image FOREIGN KEY (footer_image_id) REFERENCES job_images(job_image_id),
    CONSTRAINT CK_job_snapshots_field_provenance_json CHECK (ISJSON(field_provenance) = 1),
    CONSTRAINT CK_job_snapshots_extraction_warnings_json CHECK (ISJSON(extraction_warnings) = 1),
    CONSTRAINT UQ_job_snapshots UNIQUE (job_id, extraction_version, detail_html_hash)
);

ALTER TABLE jobs
ADD CONSTRAINT FK_jobs_current_snapshot
FOREIGN KEY (current_snapshot_id)
REFERENCES job_snapshots(job_snapshot_id);

CREATE TABLE job_categories (
    job_id BIGINT NOT NULL,
    category_id BIGINT NOT NULL,
    linked_at DATETIME2(6) NOT NULL CONSTRAINT DF_job_categories_linked_at DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_job_categories PRIMARY KEY (job_id, category_id),
    CONSTRAINT FK_job_categories_jobs FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE,
    CONSTRAINT FK_job_categories_categories FOREIGN KEY (category_id) REFERENCES categories(category_id)
);

CREATE TABLE job_keywords (
    job_keyword_id BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    job_snapshot_id BIGINT NOT NULL,
    keyword NVARCHAR(255) NOT NULL,
    source NVARCHAR(100) NOT NULL,
    confidence_score FLOAT NULL,
    created_at DATETIME2(6) NOT NULL CONSTRAINT DF_job_keywords_created_at DEFAULT SYSUTCDATETIME(),
    CONSTRAINT FK_job_keywords_snapshots FOREIGN KEY (job_snapshot_id) REFERENCES job_snapshots(job_snapshot_id) ON DELETE CASCADE,
    CONSTRAINT UQ_job_keywords UNIQUE (job_snapshot_id, keyword, source)
);

CREATE TABLE scrape_events (
    scrape_event_id BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    scrape_run_id UNIQUEIDENTIFIER NOT NULL,
    stage NVARCHAR(100) NOT NULL,
    event NVARCHAR(100) NOT NULL,
    status NVARCHAR(20) NOT NULL,
    canonical_job_url VARCHAR(900) NULL,
    source_host NVARCHAR(255) NULL,
    details_json NVARCHAR(MAX) NOT NULL CONSTRAINT DF_scrape_events_details_json DEFAULT N'{}',
    created_at DATETIME2(6) NOT NULL CONSTRAINT DF_scrape_events_created_at DEFAULT SYSUTCDATETIME(),
    CONSTRAINT FK_scrape_events_scrape_runs FOREIGN KEY (scrape_run_id) REFERENCES scrape_runs(scrape_run_id) ON DELETE CASCADE,
    CONSTRAINT CK_scrape_events_status CHECK (status IN (N'info', N'warning', N'error')),
    CONSTRAINT CK_scrape_events_details_json CHECK (ISJSON(details_json) = 1)
);

CREATE INDEX idx_jobs_last_seen_at ON jobs (last_seen_at);
CREATE INDEX idx_jobs_is_active ON jobs (is_active);
CREATE INDEX idx_job_observations_job_id ON job_observations (job_id);
CREATE INDEX idx_job_observations_scrape_run_id ON job_observations (scrape_run_id);
CREATE INDEX idx_job_snapshots_job_id_created_at ON job_snapshots (job_id, created_at DESC);
CREATE INDEX idx_job_categories_category_id_job_id ON job_categories (category_id, job_id);
CREATE INDEX idx_job_keywords_snapshot_id ON job_keywords (job_snapshot_id);
CREATE INDEX idx_scrape_events_run_stage ON scrape_events (scrape_run_id, stage);