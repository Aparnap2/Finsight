## ADDED Requirements

### Requirement: Agent Trajectory Harness — Deterministic Record and Replay

The system SHALL provide a deterministic agent trajectory harness capable of recording and replaying, per exception case, the full journal `input context → model output → verifier result → selected capability → capability arguments → capability result → next model output → final candidate`. The harness SHALL support byte-stable record/replay diffs, and replay SHALL reproduce the deterministic verdict plus capability behavior without LLM variation.

#### Scenario: Record and replay are byte-stable for deterministic segments

- **WHEN** the harness records a trajectory through FakeLLM plus real verifier plus real deterministic capabilities
- **THEN** replaying that trajectory without a live model yields the same verifier result, same capability selection, and same capability result

### Requirement: Four-Mode Harness

The harness SHALL support four modes: (1) Fake mode — `FakeLLM`, fake capabilities, fake evidence; (2) Replay mode — recorded LLM outputs plus real deterministic capabilities, real verifier; (3) Live mode — real Groq provider, real local capabilities, real RAG/evidence, real guardrails; (4) E2E mode — real external/local integration boundaries plus real PostgreSQL, with infrastructure emulators only where an actual production AWS seam exists. Mode (4) SHALL use `docker-compose.test.yml` with a healthcheck gate and never start a server inside test code.

#### Scenario: Fake before replay before live

- **WHEN** the harness is exercised in sequence
- **THEN** Fake mode passes with no network, Replay mode passes with only recorded fixtures and real verifier/capabilities, and only Live mode requires a live Groq call; E2E mode requires the `docker-compose.test.yml` healthcheck gate

### Requirement: Gated Live Tests

Every live test (Live mode and E2E mode that touches Groq) SHALL be explicitly gated behind the `live_llm` pytest marker and the `LIVE_LLM=1` environment opt-in. The default `pytest -m "not live_llm"` command SHALL remain zero-network and zero-cost. CI SHALL NOT execute live tests in the fast `lint/typecheck/unit+contract` job.

#### Scenario: Default test run never hits a live model

- **WHEN** `pytest -m "not live_llm"` is executed on a clean checkout with no `LIVE_LLM` env
- **THEN** the entire suite passes with no outbound network and no LLM cost

### Requirement: MiniStack / SQS Gate

The harness MUST NOT introduce `MiniStack` (LocalStack), `boto3`, or any queue abstraction as a default dependency. A queue seam (`QueuePort`) SHALL be introduced only when a failing/insufficient test demonstrates that `p99 latency requires async acknowledgement/reconciliation OR crash-after-commit leaves RECEIVED permanently OR poison messages require DLQ/redrive`. Until that gate fires, `NO QueuePort / NO boto3 / NO MiniStack`.

#### Scenario: Queue dependency absent until gated

- **WHEN** the P5 test suite is executed without a demonstrated queue-requiring failing test
- **THEN** no `boto3`/`QueuePort`/MiniStack appears in `pyproject.toml` or the codebase and `docker-compose.test.yml` is the only compose used for test orchestration
