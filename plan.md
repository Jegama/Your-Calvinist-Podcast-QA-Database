# Podcast Q&A API, Minimal-Cost Implementation Plan (Vercel + Neon + Local Backfill)

This document is a step-by-step implementation guide for a low-cost architecture that uses only what you already pay for: Vercel (hosting + cron) and Neon (Postgres). Heavy work (backfill of existing videos) runs locally. Ongoing ingestion is triggered daily by a Vercel Cron job.

## 1. Overall Architecture

### Goals
- Extract timestamped questions from YouTube video descriptions.
- Build answers by slicing the transcript between timestamps.
- Persist all Q&A items in Postgres (Neon).
- Provide a stable REST API for your friend’s website to query Q&A.
- Keep operating costs near zero.

### System components

**A) Local backfill runner (your machine)**
- Reads a text file with existing video URLs.
- Extracts Q&A pairs per video.
- Writes to Postgres (Neon) in bulk.

**B) FastAPI app (Vercel)**
- Read endpoints for the website.
- Minimal protected ingestion endpoints.
- OpenAPI docs are automatically available.

**C) Scheduler (Vercel Cron)**
- Calls an API endpoint daily at 2:00 am ET.
- Endpoint checks the channel or playlist for new videos.
- New videos are enqueued and processed in small bounded units.

**D) Neon Postgres**
- Stores videos, Q&A items, tags.
- Optional full-text search index for fast keyword search.

### High-level flow
1) **Backfill**: local script processes all existing videos and inserts into Neon.
2) **Daily cron**: `check_youtube` detects new videos and enqueues them.
3) **Ingestion worker (serverless-friendly)**: processes one pending job per call (bounded time), can be run N times sequentially.
4) Website uses `GET` endpoints to query/search.

### Why this is the cheapest viable approach
- No always-on servers.
- No managed queues, no extra cloud services.
- Serverless endpoints do short work.
- Local machine handles the expensive one-time backfill.

---

## 2. Data Models and Neon Setup

### Recommended schema (minimal but scalable)

#### 2.1. `videos`
Stores one row per YouTube video.

- `id` UUID PK
- `youtube_id` TEXT UNIQUE
- `url` TEXT
- `title` TEXT
- `channel_id` TEXT
- `channel_title` TEXT
- `published_at` TIMESTAMPTZ
- `description` TEXT
- `processed_at` TIMESTAMPTZ
- `status` TEXT (pending | processed | failed)
- `error` TEXT
- `created_at` TIMESTAMPTZ

#### 2.2. `qa_items`
Stores each Q&A unit.

- `id` UUID PK
- `video_id` UUID FK -> videos(id)
- `timestamp_text` TEXT (e.g., "23:45")
- `timestamp_seconds` INT
- `question` TEXT
- `answer` TEXT (full transcript slice)
- `answer_preview` TEXT (first 500 chars, for list views)
- `category` TEXT
- `subcategory` TEXT
- `created_at` TIMESTAMPTZ

**Uniqueness**: `(video_id, timestamp_seconds)` should be unique so re-runs are idempotent.

**Note on `answer_preview`**: For 2+ hour podcasts, some answers can span 10-20 minutes of text. The preview column enables fast list views without loading full content.

#### 2.3. `tags` and `qa_item_tags` (optional but recommended)
- `tags(id uuid pk, name text unique)`
- `qa_item_tags(qa_item_id uuid fk, tag_id uuid fk, primary key (qa_item_id, tag_id))`

#### 2.4. `transcripts` (recommended for 2+ hour podcasts)
Stores raw transcript data separately to keep `videos` table lean and allow re-processing without hitting YouTube again.

- `id` UUID PK
- `video_id` UUID FK -> videos(id) UNIQUE
- `raw_data` JSONB (array of `{start: float, text: string}`)
- `full_text` TEXT (optional, concatenated for backup/export)
- `created_at` TIMESTAMPTZ

**Why store transcripts?**
- 2-hour podcast transcripts are ~50-100KB (very manageable for Postgres)
- Enables re-slicing Q&A if timestamps change without re-fetching from YouTube
- Keeps the `videos` table fast for listing queries
- YouTube transcript API has rate limits; caching avoids repeated calls

#### 2.5. `ingest_jobs` (cheap queue)
This is your queue without extra services.

- `id` UUID PK
- `youtube_id` TEXT
- `status` TEXT (pending | processing | done | failed)
- `attempts` INT
- `locked_at` TIMESTAMPTZ
- `last_error` TEXT
- `created_at` TIMESTAMPTZ


### 2.5. SQL to create tables
Run these statements in Neon SQL editor, or via migrations.

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS videos (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  youtube_id TEXT NOT NULL UNIQUE,
  url TEXT NOT NULL,
  title TEXT,
  channel_id TEXT,
  channel_title TEXT,
  published_at TIMESTAMPTZ,
  description TEXT,
  processed_at TIMESTAMPTZ,
  status TEXT NOT NULL DEFAULT 'pending',
  error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS qa_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  video_id UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
  timestamp_text TEXT,
  timestamp_seconds INT NOT NULL,
  question TEXT NOT NULL,
  answer TEXT,
  answer_preview TEXT,
  category TEXT,
  subcategory TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(video_id, timestamp_seconds)
);

CREATE TABLE IF NOT EXISTS tags (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS qa_item_tags (
  qa_item_id UUID NOT NULL REFERENCES qa_items(id) ON DELETE CASCADE,
  tag_id UUID NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  PRIMARY KEY (qa_item_id, tag_id)
);

CREATE TABLE IF NOT EXISTS transcripts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  video_id UUID NOT NULL UNIQUE REFERENCES videos(id) ON DELETE CASCADE,
  raw_data JSONB,
  full_text TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ingest_jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  youtube_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  attempts INT NOT NULL DEFAULT 0,
  locked_at TIMESTAMPTZ,
  last_error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_qa_video_id ON qa_items(video_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON ingest_jobs(status);
```

### 2.6. Neon project setup checklist
1) Create a new Neon project for this podcast.
2) Create a database, e.g., `podcast_qa`.
3) Create a user for the API (least privilege) and a separate user for admin/migrations.
4) Store connection strings in:
   - Local `.env`
   - Vercel environment variables

**Connection pooling**
- Use Neon's pooled connection string for Vercel.
- Use direct connection string for local migrations and bulk loads.

---

## 3. Optional Full-Text Search (`search_tsv` + GIN)

This enables fast keyword search across question and answer text.

### What is full-text search?

PostgreSQL's full-text search is much faster than `LIKE '%word%'` queries because it:
1. **Tokenizes** text into individual words
2. **Stems** words to their roots (e.g., "baptizing" → "baptiz", "churches" → "church")
3. **Removes stop words** like "the", "and", "is"
4. **Stores as a vector** optimized for fast matching
5. **Uses a GIN index** for sub-millisecond lookups even with thousands of rows

This means searching for "infant baptism" will also match "infants", "baptized", "baptismal", etc.

### 3.1. Add column and index (run FIRST)
```sql
ALTER TABLE qa_items
  ADD COLUMN IF NOT EXISTS search_tsv tsvector;

CREATE INDEX IF NOT EXISTS idx_qa_search_tsv
  ON qa_items USING GIN (search_tsv);
```

### 3.2. Create trigger for automatic updates (run SECOND)

**IMPORTANT**: The trigger must be created BEFORE inserting data, otherwise `search_tsv` will be NULL for those rows.

```sql
CREATE OR REPLACE FUNCTION qa_items_search_tsv_update() RETURNS trigger AS $$
BEGIN
  NEW.search_tsv := to_tsvector('english', coalesce(NEW.question,'') || ' ' || coalesce(NEW.answer,''));
  RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_qa_items_search_tsv ON qa_items;

CREATE TRIGGER trg_qa_items_search_tsv
BEFORE INSERT OR UPDATE OF question, answer ON qa_items
FOR EACH ROW EXECUTE FUNCTION qa_items_search_tsv_update();
```

### 3.3. Backfill existing rows (run if data was inserted before trigger existed)
```sql
UPDATE qa_items
SET search_tsv = to_tsvector('english', coalesce(question,'') || ' ' || coalesce(answer,''))
WHERE search_tsv IS NULL;
```

### 3.4. Query example
```sql
SELECT *
FROM qa_items
WHERE search_tsv @@ plainto_tsquery('english', 'baptism covenant')
ORDER BY ts_rank(search_tsv, plainto_tsquery('english', 'baptism covenant')) DESC
LIMIT 50;
```

**Note**: The FastAPI search endpoint (Phase 3) will use this query pattern.

---

## 4. REST API Design (FastAPI)

### 4.1. Public read endpoints (for the website)
- `GET /v1/videos`
  - Params: `limit`, `offset`, `q` (optional title search)
- `GET /v1/videos/summary`
  - Returns all videos with aggregated categories, subcategories, and tags
  - Useful for frontend filtering/faceting
  - Params: `limit`, `offset`
- `GET /v1/videos/{youtube_id}`
- `GET /v1/videos/{youtube_id}/questions`
  - Params: `category`, `subcategory`, `tag`, `q` (keyword), `limit`, `offset`
- `GET /v1/questions/search`
  - Params: `q`, `category`, `tag`, `limit`, `offset`

### 4.2. Protected ingestion endpoints
- `POST /v1/ingest/check` (cron calls this)
  - checks playlist/channel, enqueues new video IDs
- `POST /v1/ingest/run-one`
  - processes exactly one pending job

### 4.3. Security measures (low-cost standard)

**A) API key for ingestion endpoints**
- Require a header like `X-API-Key: <secret>` for any endpoint that writes/ingests.
- Store the secret in Vercel env vars.

**B) Rate limiting**
- Cheapest: implement a basic in-memory limiter per instance.
- Better: do a simple DB-based limiter using a `request_log` table.
- For a small podcast, API key plus conservative endpoint design is usually sufficient.

**C) CORS**
- Allow only your friend’s website domain.

**D) Input validation**
- Use Pydantic models.
- Validate YouTube ID and URL formats.

**E) Read-only DB role**
- Use a restricted DB user for read endpoints.
- Use a separate user for ingestion endpoints if you want strict separation.

### 4.4. FastAPI docs
- `/docs` Swagger UI
- `/redoc` ReDoc
- `/openapi.json` OpenAPI schema

---

## 5. Refactoring `test.py` into a modular design

The goal is to reuse the same extraction logic for:
- local bulk backfill
- online ingestion for new videos

### 5.1. Recommended project structure

```
app/
  main.py                 # FastAPI app
  settings.py             # env vars, config
  db/
    __init__.py
    engine.py             # SQLAlchemy engine/session
    models.py             # ORM models
    crud.py               # queries/upserts
    migrations/           # Alembic (optional)
  youtube/
    __init__.py
    ids.py                # parse youtube_id from URL
    metadata.py           # fetch title/desc/published_at
    playlist.py           # list videos in playlist/channel
    transcripts.py        # fetch transcript
  qa/
    __init__.py
    timestamp_parser.py   # parse timestamps from description
    answer_slicer.py      # slice transcript into answers by time window
    classify.py           # optional category/tags classification
    normalize.py          # cleanup text
  ingest/
    __init__.py
    pipeline.py           # process_one_video(youtube_id)
    jobs.py               # enqueue, lock, run-one
  cli/
    backfill.py           # local bulk backfill entrypoint
```

### 5.2. Core rule
Create a single function as the “source of truth”:

- `process_video(youtube_id: str) -> ProcessResult`

It should:
1) fetch metadata (title, description, channelId, channelTitle, publishedAt)
2) parse timestamps from description
3) fetch transcript (raw segments with start times)
4) **store raw transcript** in `transcripts` table (JSONB)
5) slice answers by time windows
6) generate `answer_preview` (first 500 chars of each answer)
7) write to DB (upsert videos, qa_items, tags, qa_item_tags)

**Important**: Extend YouTube API call to fetch full snippet:
```python
request = youtube.videos().list(part="snippet", id=video_id)
# Extract: title, description, channelId, channelTitle, publishedAt
```

Then:
- CLI calls this in a loop for backfill.
- API `run-one` locks a job and calls it once.

### 5.3. Transcript slicing (recommended deterministic approach)
If timestamps are the start of each question:
- Convert timestamps to seconds.
- For i-th item:
  - start = ts[i]
  - end = ts[i+1] or video_end
- Concatenate transcript segments within [start, end).

This is stable and re-runnable.

---

## 6. New Videos Ingestion via Polling (Option A)

### 6.1. Polling schedule
You want: **every 24 hours at 2:00 am ET**.

In Vercel Cron, define a schedule that runs at 2:00 am Eastern.
- If your project is configured in UTC, convert accordingly.
- Keep it daily.

### 6.2. What `POST /v1/ingest/check` does
1) Query YouTube API for latest items in the playlist or channel.
2) For each video ID:
   - if not in `videos`, insert `videos(status='pending')` and enqueue `ingest_jobs(pending)`
3) Return counts.

### 6.3. What `POST /v1/ingest/run-one` does
1) Lock one job atomically:
   - set `status='processing'`, set `locked_at=now()`
2) Call `process_video(youtube_id)`
3) On success:
   - mark job `done`
   - mark video `processed`
4) On failure:
   - increment attempts
   - set `last_error`
   - if attempts < N, set back to `pending`, else `failed`

### 6.4. Why “run-one” is serverless-friendly
- bounded runtime
- fewer timeout issues
- easy to retry

You can have the cron call `run-one` multiple times if needed, or have `check` enqueue and also process up to K jobs.

---

## 7. Detailed Implementation Steps

### Phase 1: Database
1) Create Neon project.
2) Run schema SQL (Section 2.5).
3) (Optional) add `search_tsv` + index (Section 3).

### Phase 2: Local extraction and backfill
1) Refactor script into modules (Section 5).
2) Implement `cli/backfill.py`:
   - read URLs from `a.txt`
   - for each URL, derive `youtube_id`
   - call `process_video(youtube_id)`
3) Run locally and validate a handful of records in Neon.

### Phase 3: FastAPI
1) Create `app/main.py` with routers:
   - `routers/public.py` for GETs
   - `routers/ingest.py` for protected endpoints
2) Add Pydantic schemas for:
   - `VideoOut`
   - `VideoSummaryOut` (with aggregated categories, subcategories, tags)
   - `QAItemOut` (with answer_preview for list views)
   - `QAItemDetailOut` (with full answer)
   - `SearchResponse`
   - `IngestCheckResponse`
3) Add middleware:
   - CORS allowlist
   - API key dependency for ingest routes

### Phase 4: Deploy to Vercel
1) Add env vars in Vercel:
   - `DATABASE_URL` (pooled)
   - `ADMIN_API_KEY`
   - YouTube API key or OAuth tokens as required
2) Deploy.
3) Verify:
   - `/docs` loads
   - read endpoints work

### Phase 5: Cron
1) Configure Vercel Cron to call:
   - `POST /v1/ingest/check` at 2:00 am ET daily
2) Optionally add a second cron shortly after to drain jobs:
   - `POST /v1/ingest/run-one` multiple times, or create `POST /v1/ingest/run-batch?max=5`

### Phase 6: Hand-off documentation for your friend
1) Provide base URL.
2) Provide `/docs` link.
3) Provide example queries the frontend can call.

---

## 8. Operational Tips (still low-cost)

- Keep ingestion endpoints secret: require `X-API-Key`.
- Keep logs structured: include `youtube_id` and job id.
- Avoid LLM calls during ingestion unless necessary.
- Make everything idempotent: safe to re-run.

---

## 9. API Contract Examples

### 9.1. Search
`GET /v1/questions/search?q=baptism&limit=20&offset=0`

### 9.2. Questions for a video
`GET /v1/videos/dQw4w9WgXcQ/questions?category=Theology&tag=Covenant`

### 9.3. Videos summary with aggregated metadata
`GET /v1/videos/summary?limit=50`

**Response example:**
```json
[
  {
    "youtube_id": "oGIqIuoBItQ",
    "title": "Episode 42 Q&A",
    "published_at": "2025-12-01T14:00:00Z",
    "qa_count": 15,
    "categories": ["Theology", "Church History"],
    "subcategories": ["Baptism", "Covenant Theology"],
    "tags": ["infant baptism", "reformed", "confession"]
  }
]
```

**SQL for this endpoint:**
```sql
SELECT 
  v.youtube_id,
  v.title,
  v.published_at,
  COUNT(q.id) AS qa_count,
  ARRAY_AGG(DISTINCT q.category) FILTER (WHERE q.category IS NOT NULL) AS categories,
  ARRAY_AGG(DISTINCT q.subcategory) FILTER (WHERE q.subcategory IS NOT NULL) AS subcategories,
  ARRAY_AGG(DISTINCT t.name) FILTER (WHERE t.name IS NOT NULL) AS tags
FROM videos v
LEFT JOIN qa_items q ON q.video_id = v.id
LEFT JOIN qa_item_tags qt ON qt.qa_item_id = q.id
LEFT JOIN tags t ON t.id = qt.tag_id
WHERE v.status = 'processed'
GROUP BY v.id
ORDER BY v.published_at DESC
LIMIT $1 OFFSET $2;
```

### 9.4. Cron check
`POST /v1/ingest/check` with header `X-API-Key`.
