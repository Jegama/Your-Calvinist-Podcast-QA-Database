<div align="center">
    <a href="https://calvinistparrotministries.org">
        <img src="./public/LogoForHeader.png" alt="Calvinist Parrot Ministries" height="140" />
    </a>
</div>

# Podcast Q&A API

A FastAPI application that extracts, classifies, and serves timestamped Q&A content from YouTube podcast episodes. Built for [YourCalvinist Podcast](https://www.youtube.com/@ConversationswithaCalvinist) with Keith Foskey.

**Live API**: https://keithfoskey.calvinistparrot.com  
**Interactive Docs**: https://keithfoskey.calvinistparrot.com/docs

## Features

- 🎯 **Automatic Q&A Extraction** - Parses timestamps from video descriptions and slices transcripts into Q&A pairs
- 🏷️ **AI Classification** - Uses Gemini to categorize questions by topic, subcategory, and tags
- 🔍 **Full-Text Search** - PostgreSQL-powered search with relevance ranking
- ⚡ **Serverless Ready** - Designed for Vercel with bounded runtime operations
- 🔄 **Daily Ingestion** - Cron job automatically checks for new videos

## Quick Start for Frontend Developers

### Base URL
```
https://keithfoskey.calvinistparrot.com
```

### Key Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /v1/videos` | List all processed videos |
| `GET /v1/videos/summary` | Videos with aggregated categories, subcategories, and tags |
| `GET /v1/videos/{youtube_id}` | Get a single video with full description |
| `GET /v1/videos/{youtube_id}/questions` | Get Q&A items for a specific video |
| `GET /v1/questions` | **Browse all questions** with category/tag filtering |
| `GET /v1/questions/search?q=...` | Full-text search across all Q&A |
| `GET /v1/questions/{question_id}` | Get a single question with full answer |
| `GET /v1/categories` | List all categories |
| `GET /v1/subcategories` | List all subcategories (filterable by category) |
| `GET /v1/tags` | List all tags by popularity |

### Filtering Examples

**Browse questions by category:**
```bash
curl "https://keithfoskey.calvinistparrot.com/v1/questions?category=Theology"
```

**Browse questions by multiple tags (AND logic):**
```bash
curl "https://keithfoskey.calvinistparrot.com/v1/questions?tags=Calvinism,Election"
```

**Combine filters:**
```bash
curl "https://keithfoskey.calvinistparrot.com/v1/questions?category=Theology&subcategory=Soteriology&tags=Calvinism"
```

**Search with filters:**
```bash
curl "https://keithfoskey.calvinistparrot.com/v1/questions/search?q=grace&category=Theology&tags=Calvinism,Election"
```

### Example: Search for Questions

```bash
curl "https://keithfoskey.calvinistparrot.com/v1/questions/search?q=election&limit=5"
```

Response:
```json
{
  "query": "election",
  "total": 42,
  "results": [
    {
      "id": "abc123",
      "youtube_id": "xyz789",
      "video_title": "YourCalvinist LIVE Q&A",
      "timestamp_text": "23:45",
      "timestamp_seconds": 1425,
      "question": "How do you explain election to someone new to Reformed theology?",
      "answer_preview": "Well, the first thing I'd say is...",
      "category": "Theology",
      "subcategory": "Soteriology",
      "tags": ["Election", "Calvinism", "Reformed"],
      "rank": 0.89
    }
  ]
}
```

### Building YouTube Links

To link directly to a timestamp in the video:
```
https://www.youtube.com/watch?v={youtube_id}&t={timestamp_seconds}
```

### Full API Documentation

Visit the interactive docs at `/docs` to explore all endpoints, try them live, and see full request/response schemas.

---

## Development Setup

### Prerequisites

- Python 3.11+
- PostgreSQL (or Neon account)
- YouTube Data API key
- Gemini API key

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/Jegama/Your-Calvinist-Podcast-QA-Database.git
   cd Your-Calvinist-Podcast-QA-Database
   ```

2. Create a virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Copy the environment template:
   ```bash
   cp .env.example .env
   ```

5. Fill in your `.env` file:
   ```env
   DATABASE_URL=postgresql://user:pass@host/db
   GOOGLE_API_KEY=your_youtube_api_key
   GEMINI_API_KEY=your_gemini_api_key
   ADMIN_API_KEY=your_admin_key
   CRON_SECRET=your_cron_secret
   ```

6. Run the database migrations (see `plan.md` Section 2.5 for schema SQL)

7. Start the development server:
   ```bash
   uvicorn app.main:app --reload
   ```

### Project Structure

```
app/
├── main.py              # FastAPI application entry point
├── settings.py          # Environment configuration
├── schemas.py           # Pydantic models
├── dependencies.py      # FastAPI dependencies (auth, db)
├── db/
│   ├── engine.py        # SQLAlchemy engine setup
│   ├── models.py        # ORM models
│   └── crud.py          # Database operations
├── youtube/
│   ├── metadata.py      # YouTube Data API client
│   ├── timestamps.py    # Description parser
│   ├── transcript.py    # Transcript fetcher
│   └── playlist.py      # Playlist operations
├── qa/
│   ├── answer_slicer.py # Transcript slicing logic
│   └── classify.py      # Gemini classification
├── ingest/
│   ├── pipeline.py      # Main processing pipeline
│   └── jobs.py          # Job queue management
├── routers/
│   ├── public.py        # Public GET endpoints
│   └── ingest.py        # Protected ingestion endpoints
└── cli/
    └── backfill.py      # Bulk processing script
```

### Running the Backfill

To process existing videos locally:

```bash
python -m app.cli.backfill --input playlist_videos.txt --verbose
```

### Cron Configuration

The app is configured with two Vercel Cron jobs (see `vercel.json`):

1. **2:00 AM ET** - Check playlist for new videos
2. **2:05 AM ET** - Process up to 5 pending videos

---

## Architecture

- **Vercel** - Serverless hosting + cron
- **Neon** - Serverless PostgreSQL
- **FastAPI** - Python web framework
- **Gemini 3 Flash** - LLM for classification
- **YouTube Data API** - Video metadata
- **youtube-transcript-api** - Transcript extraction

See `plan.md` for the full implementation plan and design decisions.

---

## License

MIT-0 (No Attribution Required)

This project is open source as part of [Calvinist Parrot Ministries](https://www.calvinistparrotministries.org). Feel free to use, modify, and distribute this code for any purpose - including building similar Q&A systems for other podcasts or video content.

---

## Contributing

Contributions are welcome! This project serves the church by making theological content more accessible and searchable.

---

## Contact
For questions or support, please [reach out](mailto:contact@calvinistparrotministries.org).

---

# Soli Deo Gloria

**"For from Him and through Him and to Him are all things. To Him be the glory forever! Amen."**
- Romans 11:36

<div align="center">
  <a href="https://copy.church/explain/importance/">
    <img src="https://copy.church/badges/lcc_alt_pde.png" alt="Copy.church" height="100" />
  </a>
  <a href="https://sellingJesus.org/free">
    <img src="https://copy.church/badges/sj_standard_pd.png" alt="sellingJesus.org/free" height="100" />
  </a>
</div>