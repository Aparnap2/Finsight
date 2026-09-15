# ADR-011: LiteLLM Provider Abstraction — Business Code Never Knows Provider Names

**Status:** Accepted  
**Date:** 2026-08-03  
**Deciders:** Architecture Team (decision-maker confirmation of decision D1)  

---

## Context

FinSight's LLM boundary is multi-provider by design. The platform routes LLM calls across Groq, OpenRouter, and Poolside today, with Gemini, Azure OpenAI, and OpenAI on the roadmap. Two designs competed:

1. **Custom OpenAI-compatible router (current code).** `finance/llm/client.py` + `finance/llm/model_router.py` implement an OpenAI-compatible HTTP router with provider failover, cooldown, retry, and telemetry (`docs/09-platform/llmops.md`). `shared/utils/llm_client.py` holds a second provider-switching client (poolside/groq/openrouter). This gives full control but duplicates what a provider-abstraction layer already does, and provider names leak into business-facing code paths.
2. **LiteLLM proxy (plan v3 §4b).** The locked stack (`docs/14-platform/implementation-plan.md` §4b) specifies "AI = LiteLLM + LangGraph". LiteLLM normalises many providers behind one OpenAI-compatible API and handles key management, retries, and cost tracking.

Decision-maker confirmation (D1): **keep LiteLLM as the provider abstraction.** Business code never knows provider names. Preserve the `LLMProvider` interface.

## Decision

Adopt **LiteLLM as the provider abstraction** for the LLM Runtime:

- **Runtime chain:** `LLM Runtime → LiteLLM → Gemini / Groq / OpenRouter / (future) Azure / (future) OpenAI`. The LLM Runtime (routing, structured output, telemetry, failover) sits above LiteLLM; LiteLLM owns provider translation, key management, and the unified API surface.
- **Preserve the `LLMProvider` interface.** The structural contract consumed by agents and the prompt pipeline (`LLMClient.generate(system_prompt, user_prompt, response_model)` returning a validated Pydantic model) is kept. Business code in `agents/` and the prompt pipeline never references a provider name, vendor SDK, or provider-specific configuration.
- **Provider names are configuration, not code.** Provider selection, model names, API keys, and base URLs live in configuration (`shared/config/config.py` already exposes `litellm_proxy_url`), never in business logic.
- **Keep the LLM Runtime capabilities** that already exist — failover/cooldown semantics, structured output with retry, telemetry, cost tracking. They move **on top of** LiteLLM rather than being reimplemented.
- The custom OpenAI-compatible transport (`finance/llm/model_router.py`, `finance/llm/structured_generation.py`) is retired as the transport; its failover and telemetry semantics are preserved in the LLM Runtime layer above LiteLLM.
- Note: plan v3's "LiteLLM + LangGraph" is confirmed **on LiteLLM only**. LangGraph is separately rejected by ADR-012.

## Consequences

### Positive

- **Provider swaps are configuration-only.** Onboarding Azure or OpenAI is a config change, not a code change.
- **Business code stays provider-agnostic.** One contract, one entry point; `agents/` never imports a vendor SDK.
- **Structured-output path preserved.** Every LLM call still passes a Pydantic `response_model` (ADR-004 compliance is unaffected).
- **Single telemetry/cost surface** across all providers via LiteLLM metadata.

### Negative

- **New third-party dependency** (`litellm`) — supply-chain review, version pinning, and maintenance burden.
- **Migration cost.** Current `finance/llm/` router/generation code becomes redundant; tests and telemetry consumers must be re-pointed.
- **LiteLLM API surface can lag vendor SDKs** for brand-new model features; rare escape hatches to a direct provider SDK may be needed.
- **Key/config sprawl risk.** Keys now span LiteLLM plus the existing settings model; secrets management must stay disciplined.

## Compliance

1. No `agents/` or prompt-pipeline module imports a vendor SDK (`openai`, `google-genai`, `groq`, `anthropic`) or names a provider. Enforced by grep in CI and code review.
2. Provider names appear only in configuration, the LLM Runtime, and LiteLLM proxy config.
3. Every LLM call passes a Pydantic `response_model`; structured output compliance is unchanged (ADR-004).
4. Telemetry records provider/model per call (from LiteLLM response metadata), preserving cost/latency tracking.
5. `finance/` still never imports the LLM client (ADR-001/007 boundary rules).

**References:** `docs/09-platform/llmops.md` (LLM Runtime capabilities), `docs/14-platform/implementation-plan.md` §4b (locked stack — superseded on the LiteLLM point only), `shared/config/config.py` (`litellm_proxy_url`), ADR-004 (structured outputs), ADR-008 (hexagonal architecture — LLM infrastructure in `shared/`).
