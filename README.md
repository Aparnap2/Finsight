# FinSight — Agentic FP&A Operations Platform

> The AI FP&A analyst that runs your month-end close — detects what changed, figures out why, writes the board commentary, and re-forecasts — all before your morning standup.

## What's Built

| Layer | Status | Details |
|-------|--------|---------|
| **DB** | ✅ | 15 tables, seeded CloudForge Inc. dataset (18 GL accounts, 18 months) |
| **Backend Agents** | ✅ | Ingestion, Variance, Root-Cause, Commentary — real DB + real LLM |
| **Claim Validator** | ✅ | Extracts $-claims from commentary, verifies against DB facts (5% tolerance) |
| **Evidence Graph** | ✅ | Root-cause findings linked to source DB records via EvidenceItem |
| **API** | ✅ | 6 endpoints: health, run, status, results, review, import/csv |
| **Frontend** | ✅ | 5 pages wired to real API: dashboard, variance, commentary, scenario, runs |
| **Mock ERP** | ✅ | CSV import endpoint for actuals + budget data |
| **LLM Integration** | ✅ | OpenRouter (google/gemma-4-26b-a4b-it:free) with structured prompts |

## Quick Start

### Prerequisites

- Python 3.12+
- Node.js 22+
- Docker & Docker Compose
- uv (Python package manager)

### 1. Start Infrastructure

```bash
docker compose up -d
```

Services (2.8GB total):
- PostgreSQL: `localhost:5432`
- Redis: `localhost:6380`
- Qdrant: `localhost:6333`
- Temporal: `localhost:7233`
- Jaeger: `localhost:16686`

### 2. Setup Backend

```bash
uv sync
alembic upgrade head
uv run python -c "from backend.data.seed import seed_database; from sqlalchemy import create_engine; from sqlalchemy.orm import Session; from backend.models.database import Base; e = create_engine('postgresql://finsight:finsight@localhost:5432/finsight'); Base.metadata.create_all(e); Session(e).execute('select 1')"
```

### 3. Seed Database

```bash
uv run python -c "
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from backend.models.database import Base
from backend.data.seed import seed_database
engine = create_engine('postgresql://finsight:finsight@localhost:5432/finsight')
Base.metadata.drop_all(engine)
Base.metadata.create_all(engine)
with Session(engine) as session:
    seed_database(session)
print('Database seeded')
"
```

### 4. Run Full Pipeline

```bash
curl -X POST http://localhost:8000/api/v1/pipeline/run \
  -H "Content-Type: application/json" \
  -d '{"period": "2026-06", "entity_id": "CF001", "run_sync": true}'
```

### 5. Setup Frontend

```bash
cd frontend && pnpm install && pnpm dev
```

### 6. Run Tests

```bash
uv run pytest tests/ -v
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/health` | Health check |
| POST | `/api/v1/pipeline/run` | Run pipeline (`run_sync: true` for sync) |
| GET | `/api/v1/pipeline/{run_id}/status` | Check run status |
| GET | `/api/v1/pipeline/{run_id}/results` | Get completed run results |
| POST | `/api/v1/pipeline/{run_id}/review` | Submit HITL review (approve/reject) |
| POST | `/api/v1/import/csv` | Import CSV data (actuals + budget) |

## Agent Pipeline

```
Phase 1: Data Ingestion (deterministic)
  └── Fetch actuals + budget from PostgreSQL

Phase 2: Variance Detection (deterministic)
  ├── Compute actual vs budget
  ├── Apply materiality (>5% AND >$5K)
  └── Return 18 variances, 2 material

Phase 3: Root-Cause Investigation (LLM)
  ├── Analyze material variances
  ├── Return structured findings + confidence
  └── EvidenceItem links to DB records

Phase 4: Commentary Generation (LLM)
  ├── Generate 6 sections: exec summary, revenue, cost, cash, risks, actions
  └── Claim Validator blocks hallucinated numbers

Phase 5: HITL Review (deterministic)
  └── Approve/reject at each checkpoint
```

## Project Structure

```
finsight/
├── backend/
│   ├── agents/              # LangGraph agent nodes
│   │   ├── orchestrator.py  # StateGraph with conditional routing
│   │   ├── ingestion_agent.py  # Real PostgreSQL queries
│   │   ├── variance_agent.py   # Deterministic variance engine
│   │   ├── root_cause_agent.py # LLM + EvidenceItem output
│   │   ├── commentary_agent.py # LLM + structured sections
│   │   └── scenario_agent.py
│   ├── validators/
│   │   └── claim_validator.py  # Hallucination detection
│   ├── models/
│   │   ├── state.py         # PipelineState, Variance, EvidenceItem
│   │   └── database.py      # 15 SQLAlchemy tables
│   ├── api/
│   │   ├── routes.py        # 6 REST endpoints
│   │   └── schemas.py       # Pydantic request/response models
│   ├── tools/               # Agent tool functions
│   ├── data/
│   │   └── seed.py          # CloudForge Inc. synthetic dataset
│   ├── config.py            # GROQ/OPENROUTER env vars
│   └── main.py
├── frontend/
│   └── src/
│       ├── app/             # Next.js App Router (5 pages)
│       └── components/      # VarianceHeatmap, CommentaryEditor, etc.
├── tests/                   # 78 tests (unit + integration + real LLM)
├── docker-compose.yml       # Memory-limited (2.8GB)
├── litellm-config.yaml      # Groq + OpenRouter routing
├── IMPLEMENTATION_PLAN.md   # Phased task breakdown
└── FinSight_PRD.md          # Product requirements
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Agent Orchestration | LangGraph (StateGraph) |
| LLM | OpenRouter (gemma-4-26b, free tier) |
| Backend | FastAPI (Python 3.12) |
| Frontend | Next.js 15 (App Router, TypeScript) |
| Database | PostgreSQL 15 |
| Vector Store | Qdrant |
| Cache | Redis |
| Workflow | Temporal (ready) |
| Observability | Jaeger (ready) |
| Containerization | Docker Compose (2.8GB) |

## Demo Data

Seeded CloudForge Inc. with 2 material variances for 2026-06:

| Account | Actual | Budget | Variance | % |
|---------|--------|--------|----------|---|
| Revenue - Product Y | $426,328 | $484,464 | -$58,136 | -12.0% |
| Cloud Infrastructure | $225,529 | $167,058 | +$58,470 | +35.0% |

## Tests

```bash
# Run all tests
uv run pytest tests/ -v

# Run only real LLM tests
uv run pytest tests/ -k "real_llm" -v

# Run claim validator tests
uv run pytest tests/backend/validators/ -v
```

78 tests covering:
- Database models and seed data
- Variance engine (deterministic)
- Ingestion agent (real PostgreSQL)
- Commentary agent (real LLM)
- Root-cause agent (real LLM)
- Claim validator (hallucination detection)
- API endpoints (all 6)
- Evidence model

## License

MIT
