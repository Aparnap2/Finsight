"""Golden dataset loader with built-in evaluation datasets and JSON support.

Scenarios live in ``finance/evaluation/datasets/`` as JSON files.  The
loader reads them at construction time and also provides a small built-in
set for unit tests.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from finance.evaluation.dataset import (
    DatasetInput,
    DatasetMetadata,
    ExecutionExpectation,
    ExpectedBehaviour,
    GoldenDataset,
    OutputExpectation,
    PlanningExpectation,
    ReflectionExpectation,
    VerificationExpectation,
)

_DATASETS_DIR = Path(__file__).resolve().parent / "datasets"


class GoldenDatasetLoader:
    """Loads golden datasets used for evaluation and regression testing.

    Datasets are discovered from two sources:
    1. JSON files in ``finance/evaluation/datasets/``
    2. A small set of built-in datasets (for unit tests)
    """

    def __init__(self) -> None:
        self._datasets: dict[str, GoldenDataset] = {}
        self._load_json_datasets()
        self._datasets.update(self._build_builtins())

    # ── JSON-based datasets ──────────────────────────────────────────────

    def _load_json_datasets(self) -> None:
        if not _DATASETS_DIR.is_dir():
            return
        for path in sorted(_DATASETS_DIR.rglob("*.json")):
            try:
                raw = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            ds = self._parse_json_dataset(raw, path)
            if ds is not None:
                self._datasets[ds.metadata.id] = ds

    @staticmethod
    def _parse_json_dataset(raw: dict[str, Any], path: Path) -> GoldenDataset | None:
        raw_meta = raw.get("metadata", {})
        if not raw_meta.get("id"):
            return None
        metadata = DatasetMetadata(
            id=raw_meta["id"],
            name=raw_meta.get("name", ""),
            category=raw_meta.get("category", "financial_logic"),
            subcategory=raw_meta.get("subcategory", ""),
            description=raw_meta.get("description", ""),
            tags=raw_meta.get("tags", []),
            difficulty=raw_meta.get("difficulty", "basic"),
        )
        raw_input = raw.get("input", {})
        dataset_input = DatasetInput(
            query=raw_input.get("query", ""),
            context=raw_input.get("context", {}),
            spreadsheet_data=raw_input.get("spreadsheet_data", {}),
            variances=raw_input.get("variances", []),
        )
        raw_exp = raw.get("expected", {})
        expected = ExpectedBehaviour(
            planning=PlanningExpectation(**raw_exp.get("planning", {})),
            execution=ExecutionExpectation(**raw_exp.get("execution", {})),
            verification=VerificationExpectation(**raw_exp.get("verification", {})),
            reflection=ReflectionExpectation(**raw_exp.get("reflection", {})),
            output=OutputExpectation(**raw_exp.get("output", {})),
        )
        return GoldenDataset(
            metadata=metadata,
            input=dataset_input,
            expected=expected,
        )

    # ── Built-in datasets (for unit tests) ───────────────────────────────

    @staticmethod
    def _build_builtins() -> dict[str, GoldenDataset]:
        datasets: dict[str, GoldenDataset] = {}

        ds1 = GoldenDataset(
            metadata=DatasetMetadata(
                id="simple_001",
                name="Simple Revenue Check",
                category="financial_logic",
                subcategory="revenue_growth",
                tags=["simple", "revenue"],
            ),
            input=DatasetInput(
                query="Analyse revenue variance for Q1 2026",
                context={"accounts": [{"id": "4010", "actual": 100000, "budget": 95000}]},
            ),
            expected=ExpectedBehaviour(
                output=OutputExpectation(
                    variances=[
                        {"account_id": "4010", "variance_amount": 5000, "variance_pct": 5.26},
                    ],
                    kpis=[{"name": "Revenue Growth", "value": 5.26}],
                    report_sections={"executive_summary": "revenue increased 5.26%"},
                ),
            ),
        )
        datasets[ds1.metadata.id] = ds1

        ds2 = GoldenDataset(
            metadata=DatasetMetadata(
                id="seasonal_001",
                name="Seasonal Pattern",
                category="financial_logic",
                subcategory="seasonality",
                tags=["seasonal"],
            ),
            input=DatasetInput(
                query="Analyse Q1 performance with seasonal patterns",
                context={
                    "accounts": [
                        {"id": "4010", "actual": 120000, "budget": 100000},
                        {"id": "5010", "actual": 50000, "budget": 45000},
                    ],
                },
            ),
            expected=ExpectedBehaviour(
                output=OutputExpectation(
                    variances=[
                        {"account_id": "4010", "variance_amount": 20000, "variance_pct": 20.0},
                        {"account_id": "5010", "variance_amount": 5000, "variance_pct": 11.11},
                    ],
                    kpis=[
                        {"name": "Revenue Growth", "value": 20.0},
                        {"name": "Expense Ratio", "value": 41.67},
                    ],
                    report_sections={
                        "executive_summary": "revenue grew 20%",
                        "details": "expenses increased 11.11%",
                    },
                ),
            ),
        )
        datasets[ds2.metadata.id] = ds2

        return datasets

    # ── Public API ───────────────────────────────────────────────────────

    def load_all(self) -> list[GoldenDataset]:
        return list(self._datasets.values())

    def load(self, dataset_id: str) -> GoldenDataset | None:
        return self._datasets.get(dataset_id)
