"""Read-only operator console (UI-1) mounted at ``/gui``.

Logic-free by construction: every view renders JSON returned by the
existing ``apps.api.observations`` endpoints, fetched in-process over
ASGI with explicit tenant headers. The console performs no
aggregation, no persistence, no LLM calls, and no database access —
``Browser -> /gui -> observation API -> existing authorization``.

Identity: the page-load request's actor (set by middleware) when
present, else the demo identity from environment
(``OPERATOR_CONSOLE_DEMO_TENANT_ID`` / ``OPERATOR_CONSOLE_DEMO_ROLE`` /
``OPERATOR_CONSOLE_DEMO_USER_ID``). Empty demo settings mean the
console renders an unconfigured notice instead of guessing headers.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from fastapi import FastAPI
from nicegui import context, ui

from shared.config import get_settings

logger = logging.getLogger(__name__)

#: H-4: evaluation-report render cap (bytes). Larger payloads get a
#: bounded representation that says it is truncated.
EVAL_RENDER_CAP_BYTES = 256 * 1024

#: H-3: auto-refresh defaults (seconds). Detail views do not auto-refresh.
LEDGER_REFRESH_SECONDS = 20.0
METRICS_REFRESH_SECONDS = 20.0

_MOUNTED_APPS: set[int] = set()


def render_eval_report(report: dict[str, Any]) -> tuple[str, bool]:
    """Render a report dict to display text, honouring the size cap.

    Returns ``(text, truncated)``. Oversize payloads render a bounded
    summary that explicitly says it is truncated — never a silent cut.
    """
    full = json.dumps(report, indent=2, default=str)
    if len(full.encode("utf-8")) <= EVAL_RENDER_CAP_BYTES:
        return full, False
    summary = {
        "model": report.get("model"),
        "provider": report.get("provider"),
        "summary": report.get("summary"),
        "truncated": True,
        "note": (
            "Report exceeds the 256 KiB render cap; showing model, "
            "provider, and summary only. This view is truncated."
        ),
    }
    text = json.dumps(summary, indent=2, default=str)
    return text, True


def _resolve_identity() -> dict[str, str] | None:
    """Resolve ``{tenant_id, user_id, role}`` for data calls.

    Prefers the page-load request's actor (middleware-set in tests and
    any header-authenticated deployment); falls back to the demo-only
    environment identity. Returns ``None`` when neither is available.
    """
    try:
        actor = getattr(context.client.request.state, "actor", None)
    except Exception:  # noqa: BLE001 - console must degrade, never crash
        actor = None
    if isinstance(actor, dict) and actor.get("tenant_id"):
        return {
            "tenant_id": str(actor.get("tenant_id")),
            "user_id": str(actor.get("user_id", "")),
            "role": str(actor.get("role", "")),
        }
    settings = get_settings()
    if settings.operator_console_demo_tenant_id:
        return {
            "tenant_id": settings.operator_console_demo_tenant_id,
            "user_id": settings.operator_console_demo_user_id,
            "role": settings.operator_console_demo_role,
        }
    return None


async def _fetch(path: str) -> tuple[int, Any]:
    """GET an observation endpoint in-process with explicit headers."""
    identity = _resolve_identity()
    if identity is None:
        return 401, {"detail": "Operator console is not configured"}
    headers = {"X-Tenant-ID": identity["tenant_id"], "X-User-ID": identity["user_id"]}
    if identity["role"]:
        headers["X-Role"] = identity["role"]
    fastapi_app = context.client.request.app
    transport = httpx.ASGITransport(app=fastapi_app)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://console", timeout=5.0
        ) as client:
            response = await client.get(path, headers=headers)
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, {"detail": "Non-JSON response"}
    except Exception as exc:  # noqa: BLE001 - render errors, never crash
        logger.warning("Console fetch %s failed: %s", path, exc)
        return 503, {"detail": "Storage unavailable, retry"}


def _chrome(title: str, tenant: str | None) -> None:
    """Shared header: title + tenant badge."""
    with ui.header():
        ui.label(f"FinSight Operator — {title}")
        ui.badge(tenant or "unconfigured")


def _error_block(status: int, payload: Any) -> None:
    """Render fetch failures with endpoint-faithful wording."""
    detail = payload.get("detail", "Unknown error") if isinstance(payload, dict) else str(payload)
    if status == 401:
        ui.label("Not authorized — console identity is missing or invalid.")
    elif status == 404:
        ui.label("Not found — may be foreign or unknown (no existence oracle).")
    elif status == 503:
        ui.label("Storage unavailable, retry.")
    else:
        ui.label(f"Request failed ({status}): {detail}")


@ui.page("/")
def index() -> None:
    """Console landing: navigation + health strip."""
    _chrome("Console", (_resolve_identity() or {}).get("tenant_id"))

    async def load() -> None:
        strip.clear()
        with strip:
            status, payload = await _fetch("/api/v1/observations/health")
            if status != 200 or not isinstance(payload, dict):
                with strip:
                    _error_block(status, payload)
                return
            db = payload.get("db", {})
            ok = bool(db.get("ok"))
            ui.badge(f"db {'ok' if ok else 'unreachable'}")
            latency = db.get("latency_ms")
            if latency is not None:
                ui.label(f"latency_ms={latency}")
            counts = payload.get("counts")
            if isinstance(counts, dict):
                ui.label(f"counts={json.dumps(counts)}")

    with ui.column():
        ui.link("Executions ledger", "/gui/executions")
        ui.link("Metrics and failures", "/gui/metrics")
        ui.link("Evaluation reports", "/gui/evaluations")
        ui.button("Refresh", on_click=load)
        strip = ui.column()
    ui.timer(METRICS_REFRESH_SECONDS, load)


@ui.page("/executions")
def executions(result: str | None = None) -> None:
    """Execution ledger (View A). ``result`` passes through to the API."""
    identity = _resolve_identity()
    _chrome("Executions", (identity or {}).get("tenant_id"))

    columns = [
        {"name": c, "label": c, "field": c}
        for c in (
            "execution_id",
            "exception_id",
            "proposal_id",
            "idempotency_key",
            "result",
            "post_verify",
            "payload_hash",
            "external_reference",
        )
    ]
    table = ui.table(columns=columns, rows=[], row_key="execution_id")
    if result is None:
        ui.label("Showing all results (no server filter).")
    else:
        ui.label(f"Server filter: result={result}")

    async def load() -> None:
        path = "/api/v1/observations/executions"
        if result:
            path += f"?result={result}"
        status, payload = await _fetch(path)
        if status != 200 or not isinstance(payload, dict):
            _error_block(status, payload)
            return
        rows = payload.get("executions", [])
        table.update_rows(rows)

    ui.button("Refresh", on_click=load)
    ui.timer(LEDGER_REFRESH_SECONDS, load)


@ui.page("/executions/{execution_id}")
def execution_detail(execution_id: str) -> None:
    """Single execution with links to audit and timeline."""
    identity = _resolve_identity()
    _chrome(f"Execution {execution_id}", (identity or {}).get("tenant_id"))
    ui.link("Audit facts", f"/gui/executions/{execution_id}/audit")
    ui.link("Timeline", f"/gui/executions/{execution_id}/timeline")
    ui.link("Back to ledger", "/gui/executions")

    async def load() -> None:
        status, payload = await _fetch(f"/api/v1/observations/executions/{execution_id}")
        if status != 200 or not isinstance(payload, dict):
            _error_block(status, payload)
            return
        ui.json_editor({"content": {"json": payload}})

    ui.button("Refresh", on_click=load)


def _sequenced(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach a client-side sequence key (timestamps are non-unique)."""
    sequenced: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        sequenced.append({"seq": i, **row})
    return sequenced


@ui.page("/executions/{execution_id}/audit")
def execution_audit(execution_id: str) -> None:
    """Stored audit facts with version pins (View B)."""
    identity = _resolve_identity()
    _chrome(f"Audit {execution_id}", (identity or {}).get("tenant_id"))
    ui.label("Stored audit facts (with version pins).")
    columns = [
        {"name": c, "label": c, "field": c}
        for c in (
            "seq",
            "timestamp",
            "actor",
            "previous_state",
            "new_state",
            "operation",
            "reason",
            "expected_version",
            "actual_version",
        )
    ]
    table = ui.table(columns=columns, rows=[], row_key="seq")

    async def load() -> None:
        status, payload = await _fetch(f"/api/v1/observations/executions/{execution_id}/audit")
        if status != 200 or not isinstance(payload, list):
            _error_block(status, payload)
            return
        table.update_rows(_sequenced(payload))

    ui.button("Refresh", on_click=load)


@ui.page("/executions/{execution_id}/timeline")
def execution_timeline(execution_id: str) -> None:
    """Transition-only timeline, no version pins (View C)."""
    identity = _resolve_identity()
    _chrome(f"Timeline {execution_id}", (identity or {}).get("tenant_id"))
    columns = [
        {"name": c, "label": c, "field": c}
        for c in ("seq", "timestamp", "previous_state", "new_state", "actor", "operation", "reason")
    ]
    table = ui.table(columns=columns, rows=[], row_key="seq")

    async def load() -> None:
        status, payload = await _fetch(f"/api/v1/observations/executions/{execution_id}/timeline")
        if status != 200 or not isinstance(payload, list):
            _error_block(status, payload)
            return
        rows = _sequenced(payload)
        for row in rows:
            if row.get("new_state") == "CLOSED":
                row["new_state"] = "CLOSED (terminal)"
        table.update_rows(rows)

    ui.button("Refresh", on_click=load)


@ui.page("/metrics")
def metrics() -> None:
    """Server-computed buckets rendered verbatim (View D)."""
    identity = _resolve_identity()
    _chrome("Metrics", (identity or {}).get("tenant_id"))

    async def load() -> None:
        body.clear()
        with body:
            status, payload = await _fetch("/api/v1/observations/metrics")
            if status != 200 or not isinstance(payload, dict):
                _error_block(status, payload)
                return
            for title, buckets in (
                ("Executions by result", payload.get("executions_by_result", {})),
                ("Exceptions by state", payload.get("exceptions_by_state", {})),
            ):
                ui.label(title)
                if isinstance(buckets, dict) and buckets:
                    ui.echart(
                        {
                            "xAxis": {"type": "category", "data": list(buckets)},
                            "yAxis": {"type": "value"},
                            "series": [{"type": "bar", "data": list(buckets.values())}],
                        }
                    )
                    ui.table(
                        columns=[
                            {"name": "bucket", "label": "bucket", "field": "bucket"},
                            {"name": "count", "label": "count", "field": "count"},
                        ],
                        rows=[{"bucket": k, "count": v} for k, v in buckets.items()],
                        row_key="bucket",
                    )
            ui.label(f"audits={payload.get('audits')}")

    with ui.column():
        ui.button("Refresh", on_click=load)
        body = ui.column()
    ui.timer(METRICS_REFRESH_SECONDS, load)


@ui.page("/evaluations")
def evaluations() -> None:
    """Evaluation run index (View E)."""
    identity = _resolve_identity()
    _chrome("Evaluations", (identity or {}).get("tenant_id"))
    table = ui.table(
        columns=[
            {"name": c, "label": c, "field": c}
            for c in ("run_id", "model", "provider", "total", "passed", "failed")
        ],
        rows=[],
        row_key="run_id",
    )

    async def load() -> None:
        status, payload = await _fetch("/api/v1/observations/evaluations/runs")
        if status != 200 or not isinstance(payload, dict):
            _error_block(status, payload)
            return
        runs = payload.get("runs", [])
        for run in runs:
            for key in ("model", "provider", "total", "passed", "failed"):
                run.setdefault(key, None)
        table.update_rows(runs)

    ui.button("Refresh", on_click=load)


@ui.page("/evaluations/{run_id}")
def evaluation_detail(run_id: str) -> None:
    """Schemaless report detail with the 256 KiB cap (View E)."""
    identity = _resolve_identity()
    _chrome(f"Evaluation {run_id}", (identity or {}).get("tenant_id"))
    ui.link("Back to runs", "/gui/evaluations")

    async def load() -> None:
        status, payload = await _fetch(f"/api/v1/observations/evaluations/runs/{run_id}")
        if status != 200 or not isinstance(payload, dict):
            _error_block(status, payload)
            return
        text, truncated = render_eval_report(payload)
        if truncated:
            ui.label("Report exceeds the 256 KiB render cap — truncated view.")
        ui.json_editor({"content": {"json": json.loads(text)}})

    ui.button("Refresh", on_click=load)


@ui.page("/verification")
def verification(report_path: str | None = None) -> None:
    """Read-only E2E verification viewer (CP6).

    Loads a machine-readable E2E run report (JSON) from ``report_path`` (a
    local file) or from pasted JSON, then renders run metadata, scenario
    results, stage timeline, provider/trace evidence and the overall verdict.
    The viewer never calculates or modifies the verdict; it displays the
    report (and optionally re-runs the deterministic verifier for display).
    """
    _chrome("Verification", (_resolve_identity() or {}).get("tenant_id"))

    with ui.column().classes("w-full"):
        ui.label("E2E Verification Viewer").classes("text-h5")
        ui.label(
            "Read-only. Verdicts come from the deterministic verifier, not this page."
        ).classes("text-caption")

        report_box = ui.textarea(label="Paste E2E report JSON (or provide ?report_path=)").classes(
            "w-full"
        )
        report_box.props("rows=8")

        result_col = ui.column().classes("w-full")

        def _render(report: dict[str, Any]) -> None:
            result_col.clear()
            with result_col:
                verdict = report.get("overall_verdict", "INCOMPLETE")

                # --- Overall status badge ---
                ui.label("FinSight — E2E Verification").classes("text-h4")
                with ui.row():
                    ui.badge(f"OVERALL: {verdict}").classes(
                        "text-h6 " + ("bg-green-700" if verdict == "VERIFIED" else "bg-red-700")
                    )
                ui.label(
                    "Staging run · commit "
                    + str(report.get("commit_sha", "?"))
                    + " · illustrative values only"
                ).classes("text-caption")

                # --- Run summary ---
                ui.label("Run summary").classes("text-h6")
                ui.label(f"run_id: {report.get('run_id')}")
                ui.label(f"commit_sha: {report.get('commit_sha')}")
                ui.label(f"image_digest: {report.get('image_digest')}")
                ui.label(f"migration_revision: {report.get('migration_revision')}")
                ui.label(f"environment: {report.get('environment')}")
                ui.label(f"timestamp: {report.get('timestamp')}")

                # --- Stage timeline ---
                ui.label("Execution trace (stages)").classes("text-h6")
                stage_names = [
                    "import",
                    "validate",
                    "reconcile",
                    "persist",
                    "context",
                    "investigate",
                    "decide",
                    "audit",
                    "export",
                ]
                stage_map = {s.get("stage", "").lower(): s for s in report.get("stages", [])}
                for name in stage_names:
                    st = stage_map.get(name, {})
                    status = st.get("status", "NOT_RUN")
                    detail = st.get("detail", "")
                    ids = st.get("ids", {})
                    with ui.row():
                        ui.badge(status)
                        ui.label(name)
                        if detail:
                            ui.label(f"— {detail}").classes("text-caption")
                    if ids:
                        ui.label(f"  ids: {json.dumps(ids)}").classes("text-caption")

                # --- Scenarios ---
                ui.label("Scenarios").classes("text-h6")
                scenarios = report.get("scenarios", [])
                with ui.row():
                    passed_count = sum(1 for s in scenarios if s.get("verdict") == "VERIFIED")
                    ui.label(f"{passed_count}/{len(scenarios)} passed")

                for sc in scenarios:
                    sc_id = sc.get("scenario_id", "?")
                    sc_verdict = sc.get("verdict", "INCOMPLETE")
                    ui.label(f"{sc_id}: {sc_verdict}").classes("text-subtitle1")
                    mismatches = sc.get("mismatches", [])
                    if mismatches:
                        ui.label(f"  mismatches: {mismatches}").classes("text-negative")

                    exp = sc.get("expected", {})
                    act = sc.get("actual", {})
                    # Flatten expected/actual for comparison table
                    exp_flat = _flatten(exp)
                    act_flat = _flatten(act)
                    all_keys = sorted(set(exp_flat) | set(act_flat))
                    if all_keys:
                        ui.label("Expected vs actual").classes("text-bold")
                        for key in all_keys:
                            e_val = exp_flat.get(key, "—")
                            a_val = act_flat.get(key, "—")
                            match = "Match" if str(e_val) == str(a_val) else "MISMATCH"
                            with ui.row():
                                ui.label(f"  {key}:")
                                ui.label(f"expected={e_val}")
                                ui.label(f"actual={a_val}")
                                ui.badge(match)

                    # Payout flow diagram (if financial data present)
                    recon = act.get("reconciliation", act)
                    if isinstance(recon, dict) and "allocated_total" in recon:
                        ui.label("Payout flow").classes("text-bold")
                        captured = recon.get("captured", recon.get("gross", "?"))
                        fee = recon.get("fee_total", recon.get("fees", "?"))
                        deposit = recon.get("allocated_total", "?")
                        variance = recon.get("open_balance", recon.get("variance", "?"))
                        ui.label(f"  Stripe charge: {captured} (gross captured)")
                        ui.label(f"  − {fee} processing fee")
                        ui.label(f"  Bank deposit: {deposit} (net payout)")
                        ui.label(f"  Expected variance: {variance}")

                    # Persisted IDs
                    ids = {}
                    for k in ("run_id", "exception_ids", "investigation_id", "export_id"):
                        v = sc.get(k)
                        if v is not None:
                            ids[k] = v
                    if ids:
                        ui.label(f"  persisted ids: {json.dumps(ids)}").classes("text-caption")

                # --- LLM evidence panel ---
                prov = report.get("provider")
                tr = report.get("trace")
                if prov or tr:
                    ui.label("Investigation evidence (LLM)").classes("text-h6")
                    ui.label("Deterministic facts: from DB and reconciliation engine.").classes(
                        "text-caption"
                    )
                    ui.label(
                        "LLM explanation: generated text (not a verified financial fact)."
                    ).classes("text-caption")
                    ui.label("Human decision: authoritative resolution.").classes("text-caption")
                    if prov:
                        ui.label(f"provider: {prov.get('provider_name')}")
                        ui.label(f"model: {prov.get('model')}")
                        ui.label(f"request_id: {prov.get('request_id')}")
                        ui.label(f"success: {prov.get('success')}")
                        lat = prov.get("latency_ms")
                        if lat is not None:
                            ui.label(f"latency_ms: {lat}")
                    if tr:
                        ui.label(f"trace_id: {tr.get('trace_id')}")
                        ui.label(f"exported: {tr.get('exported')}")
                        ui.label(f"backend: {tr.get('backend')}")

                # --- Financial invariants ---
                inv = report.get("financial_invariants", {})
                if inv:
                    ui.label("Financial invariants").classes("text-h6")
                    for k, v in inv.items():
                        ui.label(f"{k}: {v}")

                # --- Re-verify with deterministic verifier ---
                try:
                    from finance.verification.evidence import E2ERunReport
                    from finance.verification.verifier import verify_run

                    golden = None
                    try:
                        import json as _j
                        from pathlib import Path

                        golden_path = Path("tests/fixtures/reconciliation/golden_scenarios.json")
                        if golden_path.exists():
                            golden = _j.loads(golden_path.read_text())
                    except Exception:
                        golden = None
                    rep = E2ERunReport(**report)
                    re_verdict = verify_run(rep, golden)
                    ui.label(f"Verifier re-check: {re_verdict.value}").classes("text-bold")
                except Exception as e:
                    ui.label(f"Verifier re-check failed: {e}").classes("text-negative")

        async def load() -> None:
            result_col.clear()
            raw = report_box.value.strip()
            if report_path:
                try:
                    from pathlib import Path

                    raw = Path(report_path).read_text()
                    report_box.value = raw
                except Exception as e:
                    with result_col:
                        ui.label(f"Failed to read report_path: {e}")
                    return
            if not raw:
                with result_col:
                    ui.label("No report provided.")
                return
            try:
                report = json.loads(raw)
            except Exception as e:
                with result_col:
                    ui.label(f"Invalid JSON: {e}")
                return
            _render(report)

        ui.button("Render", on_click=load)
        if report_path:
            ui.timer(0.1, load, once=True)


@ui.page("/reconciliation")
def reconciliation() -> None:
    """Reconciliation workflow: sessions, runs, exceptions."""
    _chrome("Reconciliation", (_resolve_identity() or {}).get("tenant_id"))

    with ui.column():
        ui.label("Reconciliation workflow").classes("text-h6")
        ui.label(
            "The reconciliation workflow is driven through the REST API at "
            "/api/v1/reconciliation/*. This page is a minimal placeholder and "
            "does not implement the workflow."
        )
        ui.label(
            "See docs/release/LOCAL_DEPLOYMENT.md and "
            "tests/integration/test_reconciliation_http.py for the supported flow."
        )


def _flatten(d: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten a nested dict for display."""
    out: dict[str, Any] = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        else:
            out[key] = v
    return out


def mount_console(app: FastAPI) -> None:
    """Mount the console pages at ``/gui`` on the given FastAPI app.

    Idempotent per app instance. The entrypoint module owns the call so
    FastAPI ownership stays in one place.
    """
    if id(app) in _MOUNTED_APPS:
        return
    _MOUNTED_APPS.add(id(app))
    ui.run_with(app, mount_path="/gui", show_welcome_message=False)
