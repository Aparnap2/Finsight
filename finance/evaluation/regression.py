"""Regression harness for comparing evaluation results across runs.

Provides a typed pipeline for baseline capture, comparison, and reporting
so that regressions are detected automatically.
"""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from finance.evaluation.metrics import OverallScore
from finance.evaluation.runner import EvaluationReport


class Threshold(BaseModel):
    warn: float = 0.0
    break_: float = 0.0


class RegressionReport(BaseModel):
    """Result of comparing a current run against a stored baseline."""

    baseline_id: str
    current_id: str
    summary: str
    runtime_metrics: dict[str, float]
    business_metrics: dict[str, float]
    deltas: dict[str, float]
    new_failures: list[str]
    resolved_failures: list[str]
    breaking_changes: list[str]
    score: float

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


class Comparator:
    """Compares a current evaluation report list against a stored baseline.

    Thresholds are loaded from YAML files by default but can be injected.
    """

    def __init__(
        self,
        runtime_thresholds: dict[str, Threshold] | None = None,
        business_thresholds: dict[str, Threshold] | None = None,
        thresholds_dir: str | None = None,
    ) -> None:
        if runtime_thresholds is not None:
            self._runtime_thresholds = runtime_thresholds
        else:
            self._runtime_thresholds = self._load_thresholds(
                thresholds_dir, "runtime.yaml"
            )

        if business_thresholds is not None:
            self._business_thresholds = business_thresholds
        else:
            self._business_thresholds = self._load_thresholds(
                thresholds_dir, "business.yaml"
            )

        self._all_thresholds: dict[str, Threshold] = {}
        self._all_thresholds.update(self._runtime_thresholds)
        self._all_thresholds.update(self._business_thresholds)

    @staticmethod
    def _load_thresholds(
        thresholds_dir: str | None,
        filename: str,
    ) -> dict[str, Threshold]:
        """Try to load thresholds from a YAML file; fall back to empty."""
        search_paths: list[str] = []
        if thresholds_dir:
            search_paths.append(os.path.join(thresholds_dir, filename))
        search_paths.append(
            os.path.join(
                os.path.dirname(__file__),
                "thresholds",
                filename,
            )
        )

        for path in search_paths:
            p = Path(path)
            if p.is_file():
                try:
                    text = p.read_text()
                except OSError:
                    continue
                return _parse_yaml_thresholds(text)

        return {}

    def compare(
        self,
        baseline: list[EvaluationReport],
        current: list[EvaluationReport],
    ) -> RegressionReport:
        """Compare *current* reports against *baseline* reports.

        Matching is by ``dataset_id``.  Datasets present only in one side
        are flagged as new/resolved failures.
        """
        baseline_map = {r.dataset_id: r for r in baseline}
        current_map = {r.dataset_id: r for r in current}

        baseline_ids = set(baseline_map)
        current_ids = set(current_map)

        new_failures = sorted(current_ids - baseline_ids)
        resolved_failures = sorted(baseline_ids - current_ids)

        common_ids = baseline_ids & current_ids

        # ── Aggregate metrics ─────────────────────────────────────────
        runtime_keys = _collect_keys(baseline_map, current_map, "runtime_metrics")
        business_keys = _collect_keys(baseline_map, current_map, "business_metrics")

        runtime_keys = _collect_keys(baseline_map, current_map, "runtime_metrics")
        business_keys = _collect_keys(baseline_map, current_map, "business_metrics")

        baseline_runtime = _average_metric(
            baseline_map, common_ids, runtime_keys, "runtime_metrics")
        current_runtime = _average_metric(
            current_map, common_ids, runtime_keys, "runtime_metrics")
        baseline_business = _average_metric(
            baseline_map, common_ids, business_keys, "business_metrics")
        current_business = _average_metric(
            current_map, common_ids, business_keys, "business_metrics")

        # ── Deltas ────────────────────────────────────────────────────
        all_metrics = {**{f"runtime.{k}": v for k, v in baseline_runtime.items()},
                       **{f"business.{k}": v for k, v in baseline_business.items()}}
        current_all = {**{f"runtime.{k}": v for k, v in current_runtime.items()},
                       **{f"business.{k}": v for k, v in current_business.items()}}

        deltas: dict[str, float] = {}
        for key in all_metrics:
            b = all_metrics.get(key, 0.0)
            c = current_all.get(key, 0.0)
            deltas[key] = round(c - b, 10)

        # ── Breaking changes ──────────────────────────────────────────
        breaking_changes: list[str] = []
        for key, delta in deltas.items():
            threshold_key = key.split(".", 1)[1] if "." in key else key
            threshold = self._all_thresholds.get(key) or self._all_thresholds.get(threshold_key)
            if threshold is not None and delta < -threshold.break_:
                breaking_changes.append(key)

        # ── Score ─────────────────────────────────────────────────────
        score = OverallScore.compute(current_all)["overall"]

        # ── Summary ───────────────────────────────────────────────────
        if breaking_changes:
            summary = "REGRESSION_DETECTED"
        elif score >= 0.95:
            summary = "PASS"
        elif score >= 0.80:
            summary = "MINOR_REGRESSION"
        else:
            summary = "REGRESSION_DETECTED"

        return RegressionReport(
            baseline_id=_baseline_id(baseline),
            current_id=_baseline_id(current),
            summary=summary,
            runtime_metrics=current_runtime,
            business_metrics=current_business,
            deltas=deltas,
            new_failures=new_failures,
            resolved_failures=resolved_failures,
            breaking_changes=breaking_changes,
            score=score,
        )


class RegressionRunner:
    """High-level runner that evaluates, compares, and manages baselines."""

    def __init__(self, baseline_dir: str = ".regression_baseline") -> None:
        self._baseline_dir = Path(baseline_dir)
        self._baseline_dir.mkdir(parents=True, exist_ok=True)

    def run_and_compare(
        self,
        reports: list[EvaluationReport],
    ) -> RegressionReport | None:
        """Run evaluation then compare against stored baseline."""
        baseline = self.load_baseline()
        if baseline is None:
            self.save_baseline(reports)
            return None
        comparator = Comparator()
        result = comparator.compare(baseline, reports)
        return result

    def save_baseline(self, reports: list[EvaluationReport]) -> None:
        path = self._baseline_dir / "baseline.json"
        path.write_text(
            json.dumps([r.to_dict() for r in reports], indent=2, default=str)
        )

    def load_baseline(self) -> list[EvaluationReport] | None:
        path = self._baseline_dir / "baseline.json"
        if not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text())
            return [EvaluationReport(**item) for item in raw]
        except (json.JSONDecodeError, OSError, TypeError):
            return None


# ── Internal helpers ────────────────────────────────────────────────────────


def _collect_keys(
    baseline: dict[str, EvaluationReport],
    current: dict[str, EvaluationReport],
    field: str,
) -> list[str]:
    keys: set[str] = set()
    for r in baseline.values():
        keys.update(getattr(r, field, {}).keys())
    for r in current.values():
        keys.update(getattr(r, field, {}).keys())
    return sorted(keys)


def _average_metric(
    reports: dict[str, EvaluationReport],
    ids: set[str],
    keys: list[str],
    field: str,
) -> dict[str, float]:
    result: dict[str, float] = {}
    for key in keys:
        values = []
        for ds_id in ids:
            r = reports.get(ds_id)
            if r is not None:
                val = getattr(r, field, {}).get(key)
                if val is not None:
                    values.append(val)
        result[key] = round(sum(values) / len(values), 10) if values else 0.0
    return result


def _baseline_id(reports: list[EvaluationReport]) -> str:
    """Derive a stable baseline ID from a list of reports."""
    ids = sorted(r.dataset_id for r in reports)
    return f"baseline_{hash(tuple(ids))}" if ids else "empty_baseline"


def _parse_yaml_thresholds(text: str) -> dict[str, Threshold]:
    """Minimal YAML parser for threshold files (no pyyaml dependency)."""
    result: dict[str, Threshold] = {}
    current_key: str | None = None
    current_warn: float = 0.0
    current_break: float = 0.0

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" in stripped and not stripped.startswith("-"):
            parts = stripped.split(":", 1)
            key = parts[0].strip()
            value = parts[1].strip()
            if value == "" and not stripped.endswith(":"):
                continue
            if value and value != "":
                current_key = key
                continue
        if current_key and stripped.startswith("warn:"):
            with contextlib.suppress(ValueError, IndexError):
                current_warn = float(stripped.split(":", 1)[1].strip())
        if current_key and stripped.startswith("break:"):
            with contextlib.suppress(ValueError, IndexError):
                current_break = float(stripped.split(":", 1)[1].strip())
            result[current_key] = Threshold(warn=current_warn, break_=current_break)
            current_key = None
            current_warn = 0.0
            current_break = 0.0

    return result
