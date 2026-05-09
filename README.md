# Project Elevate — Step 1: Hospital Need Ingestion

This is the backend for Step 1 of Project Elevate.

**What it does:**
1. A hospital worker submits a free-text pain point via `POST /api/v1/needs`
2. GPT-4o classifies it: department, category, urgency/impact scores, keywords
3. OpenAI embeddings vectorize the raw text
4. Both are stored in Postgres + pgvector
5. `POST /api/v1/needs/search` lets you search the index semantically (the foundation for Step 3's inventor alignment)

---

## Prerequisites

- Python 3.11+
- PostgreSQL 14+ with the **pgvector extension**
- An OpenAI API key

---

## 1. Install PostgreSQL + pgvector

### macOS (Homebrew)
```bash
brew install postgresql@16
brew services start postgresql@16

# Install pgvector
brew install pgvector
```

### Ubuntu / Debian
```bash
sudo apt install postgresql postgresql-contrib
sudo apt install postgresql-16-pgvector   # adjust version as needed
```

### Windows (WSL2 recommended)
Use Ubuntu instructions above inside WSL2, or install Postgres via the official installer + build pgvector from source.

---

## 2. Create the Database

```bash
psql -U postgres

# Inside psql:
CREATE DATABASE project_elevate;
\q
```

The pgvector extension and all tables are created automatically on first startup.

---

## 3. Set Up Python Environment

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate    # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

---

## 4. Configure Environment Variables

```bash
cp .env.example .env
```

Edit `.env`:
```
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/project_elevate
OPENAI_API_KEY=sk-your-key-here
```

---

## 5. Run the Server

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

You should see:
```
✅ Database initialized successfully
INFO:     Uvicorn running on http://127.0.0.1:8000
```

---

## 6. Test It

### Interactive API docs
Open http://localhost:8000/docs — FastAPI auto-generates a full Swagger UI.

### Submit a hospital need (curl)
```bash
curl -X POST http://localhost:8000/api/v1/needs \
  -H "Content-Type: application/json" \
  -d '{
    "raw_text": "During shift handoffs in the ICU, nurses spend 20-30 minutes manually reviewing vitals and transferring notes. Errors happen and patient safety is at risk. We need a better automated handoff summary tool.",
    "hospital_id": "HOSP_001",
    "submitted_by": "Charge Nurse"
  }'
```

Expected response:
```json
{
  "id": 1,
  "raw_text": "During shift handoffs...",
  "department": "ICU",
  "category": "SOFTWARE",
  "subcategory": "Electronic Health Records (EHR/EMR)",
  "urgency_score": 4,
  "patient_impact_score": 5,
  "keywords": ["shift handoff", "vitals", "ICU", "patient safety", "automation"],
  "hospital_id": "HOSP_001",
  "submitted_by": "Charge Nurse",
  "source": "manual",
  "created_at": "2026-02-20T12:00:00Z"
}
```

### Search the needs index (semantic similarity)
```bash
curl -X POST "http://localhost:8000/api/v1/needs/search?top_k=5" \
  -H "Content-Type: application/json" \
  -d '"automated patient handoff tool that reduces nursing errors"'
```

### List all needs
```bash
curl "http://localhost:8000/api/v1/needs?limit=20"

# With filters
curl "http://localhost:8000/api/v1/needs?category=SOFTWARE&min_urgency=4"
```

---

## 7. Run Tests

```bash
cd backend
pytest tests/ -v
```

Tests mock the OpenAI API so they run without a real key.

---

## Project Structure

```
backend/
├── app/
│   ├── main.py                    # FastAPI app + startup
│   ├── core/
│   │   └── config.py              # Settings from .env
│   ├── api/
│   │   └── needs.py               # POST/GET /api/v1/needs routes
│   ├── models/
│   │   └── needs.py               # Pydantic schemas (request/response)
│   ├── services/
│   │   ├── classification_service.py   # GPT-4o classification
│   │   └── embedding_service.py        # OpenAI embeddings
│   └── db/
│       ├── database.py            # Postgres pool + table init
│       └── needs_repository.py    # All SQL operations
├── tests/
│   └── test_step1.py
├── requirements.txt
└── .env.example
```

---

## What's Next

**Step 2 (Week 3):** Add the pgvector index and tune similarity search thresholds once you have real data.

**Step 3 (Week 4):** Build the inventor-facing form + alignment report endpoint. It calls `POST /needs/search` under the hood, then passes the top matches + inventor idea to Claude to generate a structured gap analysis.

**Step 4 (Phase 2):** Add scrapers (Reddit r/nursing, hospital reviews, CMS data) that ingest into the same `hospital_needs` table with `source='scraper'`. The RAG index grows automatically.

---

## Cost Estimates (per hospital need submission)

| Step | Model | Approx. Cost |
|------|-------|-------------|
| Classification | GPT-4o | ~$0.003 |
| Embedding | text-embedding-3-small | ~$0.00002 |
| **Total per submission** | | **~$0.003** |

At 1,000 submissions/month: ~$3.00. At 100,000: ~$300.
# force redeploy Fri May  8 18:14:20 PDT 2026
