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
                verdict_color = (
                    "bg-emerald-600"
                    if verdict == "VERIFIED"
                    else "bg-red-600"
                    if verdict == "FAILED"
                    else "bg-amber-500"
                )

                # ===== Header =====
                with ui.card().classes("w-full"):
                    with ui.row().classes("items-center justify-between w-full"):
                        ui.label("FinSight — E2E Verification").classes("text-h5")
                        ui.badge(f"OVERALL: {verdict}").classes(
                            "text-lg " + verdict_color + " text-white"
                        )
                    ui.label(
                        "Staging run · commit "
                        + str(report.get("commit_sha", "?"))
                        + " · illustrative values only"
                    ).classes("text-caption text-grey-6")

                # ===== Run summary =====
                with ui.card().classes("w-full"):
                    ui.label("Run summary").classes("text-h6 q-mb-sm")
                    with ui.grid(columns=2).classes("w-full gap-2"):
                        for key in (
                            "run_id",
                            "commit_sha",
                            "image_digest",
                            "migration_revision",
                            "environment",
                            "timestamp",
                        ):
                            val = report.get(key)
                            if val is not None:
                                with ui.row().classes("items-center gap-2"):
                                    ui.label(key).classes("text-bold text-grey-7")
                                    ui.label(str(val)).classes("font-mono text-sm")

                # ===== Stage timeline =====
                with ui.card().classes("w-full"):
                    ui.label("Execution trace (stages)").classes("text-h6 q-mb-sm")
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
                    with ui.column().classes("w-full gap-1"):
                        for name in stage_names:
                            st = stage_map.get(name, {})
                            status = st.get("status", "NOT_RUN")
                            detail = st.get("detail", "")
                            ids = st.get("ids", {})
                            color = (
                                "text-green-600"
                                if status == "PASSED"
                                else "text-red-600"
                                if status == "FAILED"
                                else "text-amber-600"
                            )
                            with ui.row().classes("items-center gap-3 w-full"):
                                ui.badge(status).classes(color)
                                ui.label(name).classes("text-bold w-24")
                                if detail:
                                    ui.label(f"— {detail}").classes(
                                        "text-caption text-grey-6 flex-grow"
                                    )
                            if ids:
                                ui.label(f"  ids: {json.dumps(ids)}").classes(
                                    "text-caption font-mono text-grey-5 q-ml-xl"
                                )

                # ===== Scenarios =====
                scenarios = report.get("scenarios", [])
                with ui.card().classes("w-full"):
                    ui.label("Scenarios").classes("text-h6 q-mb-sm")
                    with ui.row().classes("items-center gap-2 q-mb-md"):
                        passed_count = sum(1 for s in scenarios if s.get("verdict") == "VERIFIED")
                        ui.badge(f"{passed_count}/{len(scenarios)} passed").classes(
                            "bg-emerald-600 text-white"
                            if passed_count == len(scenarios)
                            else "bg-amber-500 text-white"
                        )

                    for sc in scenarios:
                        sc_id = sc.get("scenario_id", "?")
                        sc_verdict = sc.get("verdict", "INCOMPLETE")
                        v_color = (
                            "text-green-600"
                            if sc_verdict == "VERIFIED"
                            else "text-red-600"
                            if sc_verdict == "FAILED"
                            else "text-amber-600"
                        )
                        border_color = (
                            "#10b981"
                            if sc_verdict == "VERIFIED"
                            else "#ef4444"
                            if sc_verdict == "FAILED"
                            else "#f59e0b"
                        )
                        with (
                            ui.card()
                            .classes("w-full q-mb-md")
                            .style("border-left: 4px solid " + border_color)
                        ):
                            with ui.row().classes("items-center gap-2"):
                                ui.label(sc_id).classes("text-subtitle1 text-bold")
                                ui.badge(sc_verdict).classes(v_color)
                            mismatches = sc.get("mismatches", [])
                            if mismatches:
                                ui.label(f"mismatches: {mismatches}").classes(
                                    "text-negative text-caption"
                                )

                            exp = sc.get("expected", {})
                            act = sc.get("actual", {})
                            exp_flat = _flatten(exp)
                            act_flat = _flatten(act)
                            all_keys = sorted(set(exp_flat) | set(act_flat))
                            if all_keys:
                                ui.label("Expected vs actual").classes("text-bold q-mt-sm")
                                columns = [
                                    {
                                        "name": "metric",
                                        "label": "Metric",
                                        "field": "metric",
                                        "align": "left",
                                    },
                                    {
                                        "name": "expected",
                                        "label": "Expected",
                                        "field": "expected",
                                        "align": "right",
                                    },
                                    {
                                        "name": "actual",
                                        "label": "Actual",
                                        "field": "actual",
                                        "align": "right",
                                    },
                                    {
                                        "name": "result",
                                        "label": "Result",
                                        "field": "result",
                                        "align": "center",
                                    },
                                ]
                                rows = []
                                for key in all_keys:
                                    e_val = exp_flat.get(key, "—")
                                    a_val = act_flat.get(key, "—")
                                    match = "Match" if str(e_val) == str(a_val) else "MISMATCH"
                                    rows.append(
                                        {
                                            "metric": key,
                                            "expected": str(e_val),
                                            "actual": str(a_val),
                                            "result": match,
                                        }
                                    )
                                table = ui.table(columns=columns, rows=rows).classes("w-full")
                                table.add_slot(
                                    "body-cell-result",
                                    """
                                    <q-td :props="props">
                                        <q-badge :color="props.value === 'Match' ? 'green' : 'red'">
                                            {{ props.value }}
                                        </q-badge>
                                    </q-td>
                                """,
                                )

                            # Payout flow diagram
                            recon = act.get("reconciliation", act)
                            if isinstance(recon, dict) and "allocated_total" in recon:
                                ui.label("Payout flow").classes("text-bold q-mt-sm")
                                captured = recon.get("captured", recon.get("gross", "?"))
                                fee = recon.get("fee_total", recon.get("fees", "?"))
                                deposit = recon.get("allocated_total", "?")
                                variance = recon.get("open_balance", recon.get("variance", "?"))
                                with ui.row().classes("items-center gap-4 q-mt-xs"):
                                    with ui.card().classes("p-3 text-center"):
                                        ui.label("Stripe charge").classes(
                                            "text-caption text-grey-6"
                                        )
                                        ui.label(str(captured)).classes("text-h6")
                                        ui.label("gross captured").classes(
                                            "text-caption text-grey-5"
                                        )
                                    ui.label("−").classes("text-h5 text-grey-5")
                                    with ui.card().classes("p-3 text-center"):
                                        ui.label("Processing fee").classes(
                                            "text-caption text-grey-6"
                                        )
                                        ui.label(str(fee)).classes("text-h6")
                                    ui.label("=").classes("text-h5 text-grey-5")
                                    with ui.card().classes("p-3 text-center"):
                                        ui.label("Bank deposit").classes("text-caption text-grey-6")
                                        ui.label(str(deposit)).classes("text-h6")
                                        ui.label("net payout").classes("text-caption text-grey-5")
                                ui.label(f"Expected variance: {variance}").classes(
                                    "text-caption q-mt-xs"
                                )

                            # Persisted IDs
                            ids = {}
                            for k in (
                                "run_id",
                                "exception_ids",
                                "investigation_id",
                                "export_id",
                                "trace_id",
                                "provider_request_id",
                                "provider_model",
                            ):
                                v = sc.get(k)
                                if v is not None:
                                    ids[k] = v
                            if ids:
                                ui.label("Persisted IDs").classes("text-caption text-bold q-mt-sm")
                                ui.label(json.dumps(ids, indent=2)).classes(
                                    "font-mono text-caption text-grey-6"
                                )

                # --- LLM evidence panel ---
                prov = report.get("provider")
                tr = report.get("trace")
                if prov or tr:
                    with ui.card().classes("w-full"):
                        ui.label("Investigation evidence (LLM)").classes("text-h6 q-mb-sm")
                        with ui.row().classes("gap-4 q-mb-sm"):
                            ui.chip("Deterministic facts", color="blue").props("outline")
                            ui.chip("LLM explanation", color="purple").props("outline")
                            ui.chip("Human decision", color="green").props("outline")
                        ui.label(
                            "Deterministic facts come from the database and reconciliation engine. "
                            "LLM explanation is generated text, not a verified financial fact. "
                            "Human decision is the authoritative resolution."
                        ).classes("text-caption text-grey-6 q-mb-md")

                        if prov:
                            ui.label("Provider call").classes("text-bold q-mt-sm")
                            with ui.grid(columns=2).classes("gap-2"):
                                for k in (
                                    "provider_name",
                                    "model",
                                    "request_id",
                                    "success",
                                    "latency_ms",
                                ):
                                    v = prov.get(k)
                                    if v is not None:
                                        ui.label(k).classes("text-bold text-grey-7")
                                        ui.label(str(v)).classes("font-mono text-sm")
                        if tr:
                            ui.label("Trace").classes("text-bold q-mt-sm")
                            with ui.grid(columns=2).classes("gap-2"):
                                for k in ("trace_id", "exported", "backend"):
                                    v = tr.get(k)
                                    if v is not None:
                                        ui.label(k).classes("text-bold text-grey-7")
                                        ui.label(str(v)).classes("font-mono text-sm")

                # --- Financial invariants ---
                inv = report.get("financial_invariants", {})
                if inv:
                    with ui.card().classes("w-full"):
                        ui.label("Financial invariants").classes("text-h6 q-mb-sm")
                        for k, v in inv.items():
                            with ui.row().classes("items-center gap-2"):
                                ui.badge("PASS" if v is True else "FAIL").classes(
                                    "bg-green-600" if v is True else "bg-red-600"
                                )
                                color = "text-green-600" if v is True else "text-red-600"
                                ui.label(k).classes(color)

                # --- Re-verify with deterministic verifier ---
                with ui.card().classes("w-full"):
                    ui.label("Verifier re-check").classes("text-h6 q-mb-sm")
                    try:
                        from finance.verification.evidence import E2ERunReport
                        from finance.verification.verifier import verify_run

                        golden = None
                        try:
                            import json as _j
                            from pathlib import Path

                            golden_path = Path(
                                "tests/fixtures/reconciliation/golden_scenarios.json"
                            )
                            if golden_path.exists():
                                golden = _j.loads(golden_path.read_text())
                        except Exception:
                            golden = None
                        rep = E2ERunReport(**report)
                        re_verdict = verify_run(rep, golden)
                        ui.badge(re_verdict.value).classes(
                            "bg-green-600 text-white"
                            if re_verdict.value == "VERIFIED"
                            else "bg-red-600 text-white"
                        )
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

        ui.button("Render", on_click=load).classes("q-mt-md")
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
