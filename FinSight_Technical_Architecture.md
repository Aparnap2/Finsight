# FinSight — Technical Architecture & Implementation Plan

## 1. System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Next.js 15 Frontend                          │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌─────────────┐ │
│  │ Variance     │ │ Commentary   │ │ Scenario     │ │ Agent Run   │ │
│  │ Heatmap      │ │ Editor       │ │ Explorer     │ │ Timeline    │ │
│  └──────────────┘ └──────────────┘ └──────────────┘ └─────────────┘ │
│  WebSocket: Real-time agent status + HITL review checkpoints        │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ REST + WebSocket (FastAPI)
┌──────────────────────────▼──────────────────────────────────────────┐
│                         FastAPI Backend (Python 3.12)                │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌─────────────┐ │
│  │ API Routes   │ │ Auth (JWT)   │ │ WebSocket    │ │ Review      │ │
│  │ (Pydantic)   │ │ (OAuth2)     │ │ Hub          │ │ Service     │ │
│  └──────────────┘ └──────────────┘ └──────────────┘ └─────────────┘ │
└──────┬──────────────────┬─────────────────────┬─────────────────────┘
       │                  │                     │
┌──────▼───────┐ ┌───────▼────────┐  ┌────────▼──────────┐
│  LangGraph   │ │  PostgreSQL    │  │  Qdrant (Vector)  │
│  Agent Engine│ │  Financial DB  │  │  Commentary RAG   │
│  + Checkpt   │ │  Agent State   │  │  Variance RAG     │
└──────┬───────┘ └────────────────┘  └───────────────────┘
       │
       │  ┌────────────────┐  ┌───────────────────┐
       │  │  Redis         │  │  Langfuse         │
       │  │  Job Queue     │  │  Observability    │
       │  │  Caching       │  │  LLM Tracing      │
       │  └────────────────┘  └───────────────────┘
       │
       │  ┌──────────────────┐  ┌──────────────────┐
       │  │  Redpanda        │  │  Temporal (v2)     │
       │  │  Event Stream    │  │  Durable Execution │
       │  └──────────────────┘  └──────────────────┘
       │
       ▼
  ┌────────────────────────────────────────────────────────┐
  │              LangGraph StateGraph (Supervisor)         │
  │                                                          │
  │   ┌─────────┐    ┌──────────┐    ┌────────────┐       │
  │   │START    │───▶│Ingestion │───▶│Variance    │       │
  │   └─────────┘    │ Agent    │    │ Detection  │       │
  │                  └──────────┘    └─────┬──────┘       │
  │                                        │               │
  │                              ┌─────────▼────────┐      │
  │                              │ ⏸ HITL Review 1 │      │
  │                              │  (Variance)      │      │
  │                              └─────────┬────────┘      │
  │                                        │               │
  │                              ┌─────────▼────────┐      │
  │                              │ Root-Cause       │      │
  │                              │ Investigation  │      │
  │                              └─────────┬────────┘      │
  │                                        │               │
  │                              ┌─────────▼────────┐      │
  │                              │ ⏸ HITL Review 2 │      │
  │                              │  (Root Cause)    │      │
  │                              └─────────┬────────┘      │
  │                                        │               │
  │                     ┌──────────────────┼────────────────┐│
  │                     │                  │                ││
  │              ┌──────▼─────┐     ┌──────▼──────┐        ││
  │              │Commentary │     │ Scenario    │        ││
  │              │ Agent     │     │ Agent       │        ││
  │              └──────┬─────┘     └──────┬──────┘        ││
  │                     │                  │                ││
  │                     └──────────┬───────┘                ││
  │                                │                        ││
  │                       ┌────────▼────────┐               ││
  │                       │ ⏸ HITL Review 3 │               ││
  │                       │  (Final Output)  │               ││
  │                       └────────┬────────┘               ││
  │                                │                        ││
  │                         ┌──────▼──────┐                ││
  │                         │    END      │                ││
  │                         └─────────────┘                ││
  └────────────────────────────────────────────────────────┘
```

---

## 2. Tech Stack & Justification

| Layer | Technology | Justification |
|-------|-----------|---------------|
| **Agent Orchestration** | LangGraph (StateGraph + Supervisor) | Stateful multi-agent workflows, HITL interrupts, conditional routing. Supervisor pattern is the production-recommended default for LangGraph multi-agent systems |
| **Persistence** | AsyncPostgresSaver (langgraph-checkpoint-postgres) | Production-grade checkpoint persistence. Survives server restarts, enables fault recovery. Creates 4 tables: checkpoints, checkpoint_blobs, checkpoint_writes, checkpoint_migrations |
| **Workflow Durability** | Temporal (Python SDK) — Phase 2 | Durable execution for long-running finance workflows. Resumes exactly where left off after crashes |
| **Backend API** | FastAPI (Python 3.12) | Async, Pydantic-native, great for AI workloads. Lifespan context manager for DB init |
| **Frontend** | Next.js 15 (App Router, TypeScript) | SSR dashboard, real-time updates via WebSocket |
| **Primary DB** | PostgreSQL 16 | ACID for financial data. JSONB for agent state. Row-level security for multi-tenancy (Phase 2) |
| **Vector Store** | Qdrant | Fast similarity search for RAG. LangChain integration via langchain-qdrant |
| **Cache & Queue** | Redis | Job queue, pub/sub for real-time updates, caching |
| **Event Streaming** | Redpanda — Phase 2 | Event-driven inter-agent communication, audit event log |
| **LLM Observability** | Langfuse | Per-feature cost breakdown, LLM-as-Judge quality scoring, span tracing for hallucination detection |
| **LLM Provider** | OpenAI GPT-4o / Anthropic Claude via LiteLLM | Best-in-class reasoning for agent tasks; LiteLLM for provider abstraction and cost tracking |
| **Containerization** | Docker + Docker Compose | Local dev, consistent environments |

---

## 3. Implementation Plan

### Phase 1: MVP (Weeks 1–4)

| Week | Focus | Deliverable |
|------|-------|-------------|
| **Week 1** | Data layer + Ingestion Agent | Synthetic dataset, PostgreSQL schema, mock ERP API, Ingestion Agent with validation |
| **Week 2** | Variance + Root-Cause Agents | Variance detection (deterministic + LLM classification), Root-Cause Agent with ReAct + tools, HITL checkpoint 1 & 2 |
| **Week 3** | Commentary + Scenario Agents | Commentary Agent with RAG, Scenario Agent (LLM picks scenarios, deterministic models compute numbers), HITL checkpoint 3 |
| **Week 4** | Frontend + Observability | Next.js dashboard, WebSocket real-time updates, Langfuse integration, Docker Compose, demo scenarios |

### Phase 2: Production Hardening (Weeks 5–6)

| Week | Focus | Deliverable |
|------|-------|-------------|
| **Week 5** | Temporal + Redpanda | Temporal workflow wrapping, Redpanda event streaming, fault recovery |
| **Week 6** | Evaluation + Deployment | Automated evaluation pipeline, Azure AKS deployment, multi-entity support |

---

## 4. Core Implementation

### 4.1 Project Structure

```
finsight/
├── backend/
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── orchestrator.py          # Supervisor StateGraph
│   │   ├── ingestion_agent.py
│   │   ├── variance_agent.py
│   │   ├── root_cause_agent.py
│   │   ├── commentary_agent.py
│   │   └── scenario_agent.py
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── gl_tools.py              # GL detail, trial balance
│   │   ├── headcount_tools.py
│   │   ├── vendor_tools.py
│   │   ├── pipeline_tools.py
│   │   └── rag_tools.py             # Qdrant search
│   ├── models/
│   │   ├── __init__.py
│   │   ├── state.py                 # PipelineState Pydantic
│   │   ├── financial.py             # Variance, RootCause, etc.
│   │   └── database.py              # SQLAlchemy models
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes.py                # FastAPI routes
│   │   └── websocket.py             # WebSocket hub
│   ├── services/
│   │   ├── __init__.py
│   │   ├── review_service.py        # HITL review management
│   │   └── graph_service.py         # LangGraph compilation
│   ├── data/
│   │   ├── seed.py                  # Synthetic dataset generator
│   │   └── mock_erp.py              # Mock ERP server
│   ├── config.py                    # Settings
│   └── main.py                      # FastAPI app
├── frontend/
│   ├── app/
│   │   ├── page.tsx
│   │   ├── variance/
│   │   ├── commentary/
│   │   ├── scenario/
│   │   └── runs/
│   └── components/
├── docker-compose.yml
└── pyproject.toml
```

### 4.2 Configuration (config.py)

```python
# backend/config.py
from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    # Database
    postgres_uri: str = "postgresql://finsight:finsight@localhost:5432/finsight"

    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # LLM
    openai_api_key: str
    litellm_proxy_url: str | None = None
    default_llm_model: str = "gpt-4o"

    # Langfuse
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "https://cloud.langfuse.com"

    # App
    app_env: str = "development"
    log_level: str = "INFO"

    class Config:
        env_file = ".env"

@lru_cache()
def get_settings() -> Settings:
    return Settings()
```

### 4.3 Pydantic State Models (models/state.py)

```python
# backend/models/state.py
from pydantic import BaseModel, Field
from typing import Annotated, Sequence
from typing_extensions import TypedDict
import operator

class Variance(BaseModel):
    account_id: str
    account_name: str
    department: str
    actual_amount: float
    budget_amount: float
    variance_amount: float
    variance_pct: float
    is_material: bool = False
    classification: str | None = None
    confidence_score: float = 0.0

class RootCauseFinding(BaseModel):
    variance_id: str
    summary: str
    evidence: list[dict] = []
    confidence_score: float
    recommended_action: str | None = None
    similar_historical_case: str | None = None

class CommentarySection(BaseModel):
    section_type: str
    content: str
    cited_data_points: list[str] = []

class CommentaryDraft(BaseModel):
    sections: list[CommentarySection]
    generated_at: str
    version: int = 1
    status: str = "draft"

class Scenario(BaseModel):
    name: str
    description: str
    assumptions: dict
    revenue_impact: float
    ebitda_impact: float
    cash_impact: float
    probability_assessment: str

class PipelineState(TypedDict):
    period: str
    entity_id: str
    actuals: dict
    budget: dict
    forecast: dict
    variances: Annotated[list[Variance], operator.add]
    root_causes: Annotated[list[RootCauseFinding], operator.add]
    commentary_draft: CommentaryDraft | None
    scenarios: Annotated[list[Scenario], operator.add]
    review_decisions: Annotated[list[dict], operator.add]
    error: str | None
    current_step: str

class ReviewCheckpoint(BaseModel):
    id: str
    agent_run_id: str
    checkpoint_name: str
    status: str
    reviewer_notes: str | None = None
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    data_snapshot: dict
```

### 4.4 Database Setup with AsyncPostgresSaver (main.py)

```python
# backend/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from backend.config import get_settings
from backend.api.routes import router
from backend.api.websocket import websocket_router
from backend.services.graph_service import get_compiled_graph

settings = get_settings()

# Global connection pool
pool: AsyncConnectionPool | None = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: init DB pool, setup LangGraph checkpointer tables."""
    global pool

    # Create connection pool with required settings
    pool = AsyncConnectionPool(
        conninfo=settings.postgres_uri,
        min_size=5,
        max_size=20,
        kwargs={"autocommit": True, "row_factory": dict_row}
    )

    # Setup LangGraph checkpointer tables
    async with pool.connection() as conn:
        checkpointer = AsyncPostgresSaver(conn)
        await checkpointer.setup()

    # Compile the graph with checkpointer
    app.state.graph = await get_compiled_graph(pool)
    app.state.pool = pool

    yield

    # Cleanup
    await pool.close()

app = FastAPI(
    title="FinSight API",
    version="1.0.0",
    lifespan=lifespan
)

app.include_router(router, prefix="/api/v1")
app.include_router(websocket_router, prefix="/ws")

@app.get("/health")
async def health_check():
    return {"status": "healthy"}
```

