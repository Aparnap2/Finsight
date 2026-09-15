"""Duplicate invoice detection — hybrid rules + similarity + Isolation Forest.

Deterministic-first hybrid per ``docs/09-platform/mlops.md``: a rule layer
(exact match on vendor/invoice/amount, fuzzy text similarity, amount
proximity) is always present; an optional Isolation Forest layer rejects
rule hits that are statistical outliers (false-positive rejection).

Optional dependencies:
    - ``sklearn.ensemble`` — Isolation Forest outlier rejection.

Degraded mode: without scikit-learn the rule layer still detects exact and
fuzzy duplicates (``degraded=True``); the ML veto is simply skipped.
Embeddings (e.g. TF-IDF) are not required — string similarity is computed
with deterministic token/bigram Jaccard so no heavy dependency is needed.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import polars as pl
from pydantic import BaseModel, Field

from finance.ml.fallback import import_optional
from finance.ml.protocol import ModelMetadata, RiskEvaluation

logger = logging.getLogger(__name__)

#: Upper bound on pairwise comparisons per batch — CPU-first guard.
MAX_PAIRS = 5000


def _clamp01(value: float) -> float:
    """Clamp a value into the closed interval [0.0, 1.0]."""
    return max(0.0, min(1.0, value))


def _token_jaccard(left: str, right: str) -> float:
    """Jaccard index over whitespace token sets (0.0 when both empty)."""
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    union = left_tokens | right_tokens
    if not union:
        return 0.0
    return len(left_tokens & right_tokens) / len(union)


def _bigram_jaccard(left: str, right: str) -> float:
    """Jaccard index over character bigrams (0.0 when either is too short)."""
    if len(left) < 2 or len(right) < 2:
        return 1.0 if left == right else 0.0
    left_grams = {left[i : i + 2] for i in range(len(left) - 1)}
    right_grams = {right[i : i + 2] for i in range(len(right) - 1)}
    union = left_grams | right_grams
    if not union:
        return 0.0
    return len(left_grams & right_grams) / len(union)


def _text_similarity(left: str, right: str) -> float:
    """Deterministic string similarity in [0, 1] (max of token/bigram Jaccard)."""
    left_norm = left.casefold().strip()
    right_norm = right.casefold().strip()
    if left_norm == right_norm:
        return 1.0
    return max(_token_jaccard(left_norm, right_norm), _bigram_jaccard(left_norm, right_norm))


def _amount_similarity(left: Decimal, right: Decimal) -> float:
    """Amount proximity in [0, 1] — Decimal arithmetic, no float drift."""
    scale = max(abs(left), abs(right), Decimal("1"))
    return _clamp01(float(1 - abs(left - right) / scale))


class DuplicatePair(BaseModel):
    """A compared record pair with its duplicate verdict."""

    left_id: str
    right_id: str
    similarity: float  # 0.0 (unrelated) to 1.0 (identical)
    is_duplicate: bool
    confidence: float
    matched_on: list[str] = Field(default_factory=list)


class DuplicateResult(BaseModel):
    """Typed output of the duplicate detector."""

    model_id: str
    version: str
    pairs: list[DuplicatePair] = Field(default_factory=list)
    degraded: bool = False
    degradation_reason: str | None = None


class DuplicateDetectionModel:
    """Hybrid duplicate detector: deterministic rules + optional ML veto."""

    def __init__(
        self,
        *,
        model_id: str = "duplicate_invoice",
        version: str = "1.0.0",
        similarity_threshold: float = 0.85,
        amount_tolerance_pct: Decimal = Decimal("0.01"),
    ) -> None:
        self.model_id = model_id
        self.name = model_id
        self.version = version
        self._similarity_threshold = similarity_threshold
        self._amount_tolerance_pct = amount_tolerance_pct
        # Lazy optional dependency — None when scikit-learn is not installed.
        self._sklearn_ensemble: Any = import_optional("sklearn.ensemble")
        self._iforest: Any = None
        self._id_column: str = "entity_id"
        self._text_columns: tuple[str, ...] = ("vendor_name",)
        self._invoice_column: str = "invoice_number"
        self._amount_column: str = "amount"
        self._reference: list[dict[str, Any]] = []
        self._trained: bool = False
        self._training_rows: int = 0
        self._training_end: datetime | None = None
        self._metrics: dict[str, Any] = {}
        self._pair_sim_features: list[str] = [
            "text_similarity",
            "invoice_similarity",
            "amount_similarity",
        ]

    @property
    def available(self) -> bool:
        """True when the scikit-learn backend is importable."""
        return self._sklearn_ensemble is not None

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train(
        self,
        features: pl.DataFrame,
        *,
        id_column: str = "entity_id",
        text_columns: tuple[str, ...] = ("vendor_name",),
        invoice_column: str = "invoice_number",
        amount_column: str = "amount",
    ) -> DuplicateDetectionModel:
        """Record the reference set and fit the optional outlier-rejection
        layer on the pairwise similarity distribution.

        Returns ``self`` for chaining. Without scikit-learn the rule layer
        alone remains fully operational (degraded mode).
        """
        self._id_column = id_column
        self._text_columns = text_columns
        self._invoice_column = invoice_column
        self._amount_column = amount_column
        self._reference = self._extract_records(features)
        self._training_rows = len(self._reference)
        self._training_end = datetime.now(UTC)
        self._trained = True

        if self._sklearn_ensemble is None:
            self._metrics = {"algorithm": "hybrid_rules"}
            logger.warning(
                "scikit-learn unavailable — %s degraded to rules-only", self.model_id
            )
            return self

        sim_vectors = self._pair_sim_vectors(self._reference, cap=MAX_PAIRS)
        if sim_vectors:
            isolation_forest_cls = self._sklearn_ensemble.IsolationForest
            forest = isolation_forest_cls(n_estimators=50, contamination=0.05, random_state=42)
            forest.fit(sim_vectors)
            self._iforest = forest
        self._metrics = {"algorithm": "hybrid_rules_plus_iforest"}
        return self

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    def predict(self, features: pl.DataFrame) -> DuplicateResult:
        """Compare the batch (and its overlaps with the reference set) and
        emit duplicate verdicts.

        The deterministic rule layer always runs; the Isolation Forest layer
        rejects fuzzy rule hits that are statistical outliers.
        """
        if not self._trained:
            return DuplicateResult(
                model_id=self.model_id,
                version=self.version,
                degraded=True,
                degradation_reason="model not trained",
            )
        candidates = self._extract_records(features)
        # Pairs within the batch plus pairs against the stored reference.
        all_records = list(self._reference) + candidates
        pairs = self._compare_records(candidates, all_records)
        degraded = self._iforest is None
        return DuplicateResult(
            model_id=self.model_id,
            version=self.version,
            pairs=pairs,
            degraded=degraded,
            degradation_reason="scikit-learn unavailable — rules-only (no ML veto)"
            if degraded
            else None,
        )

    # ------------------------------------------------------------------
    # RiskProvider
    # ------------------------------------------------------------------

    def evaluate(self, context: dict[str, Any]) -> RiskEvaluation:
        """Score a single entity's duplicate risk against the reference set.

        A context that matches a reference record within tolerance yields a
        high risk score proportional to similarity.
        """
        entity_id = str(context.get("entity_id", "unknown"))
        record = self._context_to_record(context, entity_id)
        if not self._reference:
            return RiskEvaluation(
                provider_id=self.model_id,
                entity_id=entity_id,
                score=0.0,
                confidence=0.0,
                evidence=[{"detail": "no reference records available"}],
                metadata={"model_version": self.version},
                evaluated_at=datetime.now(UTC),
            )
        best: tuple[float, float, str] | None = None  # (similarity, confidence, matched_id)
        for ref in self._reference:
            pair = self._score_pair(record, ref)
            if pair.is_duplicate and (best is None or pair.similarity > best[0]):
                best = (pair.similarity, pair.confidence, ref["_id"])
        if best is None:
            score = 0.0
            confidence = 0.0
            evidence: list[dict[str, Any]] = [{"detail": "no duplicate match against reference"}]
        else:
            score, confidence, matched_id = best
            evidence = [
                {
                    "matched_reference_id": matched_id,
                    "similarity": score,
                    "degraded": self._iforest is None,
                }
            ]
        return RiskEvaluation(
            provider_id=self.model_id,
            entity_id=entity_id,
            score=score,
            confidence=confidence,
            evidence=evidence,
            metadata={"model_version": self.version, "degraded": self._iforest is None},
            evaluated_at=datetime.now(UTC),
        )

    def metadata(self) -> ModelMetadata:
        """Return model metadata: schema, training window, metrics."""
        return ModelMetadata(
            model_id=self.model_id,
            version=self.version,
            algorithm="hybrid_rules_plus_iforest"
            if self._iforest is not None
            else "hybrid_rules",
            training_end=self._training_end,
            training_rows=self._training_rows,
            feature_count=len(self._pair_sim_features),
            feature_names=list(self._pair_sim_features),
            target_column=self._id_column,
            metrics=dict(self._metrics),
            framework_version=self._framework_version(),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_records(self, features: pl.DataFrame) -> list[dict[str, Any]]:
        """Normalize feature rows into comparable records (Decimal amounts)."""
        records: list[dict[str, Any]] = []
        for row in features.to_dicts():
            record_id = str(row.get(self._id_column, len(records)))
            record: dict[str, Any] = {"_id": record_id}
            for col in self._text_columns:
                record[col] = str(row.get(col, "") or "")
            record["_invoice_number"] = str(row.get(self._invoice_column, "") or "")
            record["_amount"] = self._coerce_amount(row.get(self._amount_column))
            records.append(record)
        return records

    def _context_to_record(self, context: dict[str, Any], entity_id: str) -> dict[str, Any]:
        """Build a single record from an entity context dict."""
        record: dict[str, Any] = {"_id": entity_id}
        for col in self._text_columns:
            record[col] = str(context.get(col, "") or "")
        record["_invoice_number"] = str(context.get(self._invoice_column, "") or "")
        record["_amount"] = self._coerce_amount(context.get(self._amount_column))
        return record

    @staticmethod
    def _coerce_amount(value: Any) -> Decimal:
        """Coerce a monetary value to Decimal at the boundary (rejects float drift)."""
        if value is None:
            return Decimal("0")
        return Decimal(str(value))

    def _pair_sim_vectors(
        self, records: list[dict[str, Any]], *, cap: int
    ) -> list[list[float]]:
        """Pairwise similarity feature vectors for the ML outlier layer."""
        vectors: list[list[float]] = []
        count = 0
        for i in range(len(records)):
            for j in range(i + 1, len(records)):
                if count >= cap:
                    return vectors
                vectors.append(self._sim_vector(records[i], records[j]))
                count += 1
        return vectors

    def _compare_records(
        self, candidates: list[dict[str, Any]], all_records: list[dict[str, Any]]
    ) -> list[DuplicatePair]:
        """Compare candidates against the full set, applying rules then ML veto."""
        pairs: list[DuplicatePair] = []
        count = 0
        for i in range(len(candidates)):
            for j in range(len(all_records)):
                left, right = candidates[i], all_records[j]
                if left["_id"] == right["_id"]:
                    continue  # never compare a record to itself
                if count >= MAX_PAIRS:
                    return pairs
                pair = self._score_pair(left, right)
                if not pair.is_duplicate or self._is_exact_match(pair):
                    pairs.append(pair)
                    count += 1
                    continue
                # Fuzzy rule hit — apply the ML outlier veto when available.
                if self._iforest is not None:
                    decision = float(
                        self._iforest.decision_function([self._sim_vector(left, right)])[0]
                    )
                    if decision < 0.0:
                        pair.is_duplicate = False
                        pair.matched_on.append("ml_rejected")
                        pair.confidence = round(pair.confidence * 0.5, 4)
                pairs.append(pair)
                count += 1
        return pairs

    def _score_pair(self, left: dict[str, Any], right: dict[str, Any]) -> DuplicatePair:
        """Deterministic rule evaluation for one pair."""
        left_id, right_id = left["_id"], right["_id"]
        text_sims = [
            _text_similarity(str(left.get(col, "")), str(right.get(col, "")))
            for col in self._text_columns
        ]
        text_sim = max(text_sims) if text_sims else 0.0
        invoice_sim = self._invoice_similarity(left, right)
        amount_sim = _amount_similarity(left["_amount"], right["_amount"])
        amounts_match = self._amounts_match(left["_amount"], right["_amount"])

        matched_on: list[str] = []
        confidence = 0.0
        similarity = 0.0
        is_duplicate = False

        # Rule 1 — exact match on all text fields + invoice number + amount.
        if (
            text_sim == 1.0
            and invoice_sim == 1.0
            and amounts_match
        ):
            matched_on = ["exact_text", "invoice_number", "amount_proximity"]
            confidence = 0.99
            similarity = 1.0
            is_duplicate = True
        # Rule 2 — same invoice number with amount proximity.
        elif invoice_sim == 1.0 and amounts_match:
            matched_on = ["invoice_number", "amount_proximity"]
            confidence = 0.9
            similarity = _clamp01((text_sim + amount_sim) / 2.0)
            is_duplicate = True
        # Rule 3 — fuzzy text similarity with amount proximity.
        elif (
            text_sim >= self._similarity_threshold
            and amounts_match
            and max(text_sims) > 0.0
        ):
            matched_on = ["fuzzy_text", "amount_proximity"]
            confidence = round(_clamp01(text_sim), 4)
            similarity = _clamp01((text_sim + amount_sim) / 2.0)
            is_duplicate = True

        return DuplicatePair(
            left_id=left_id,
            right_id=right_id,
            similarity=similarity,
            is_duplicate=is_duplicate,
            confidence=confidence,
            matched_on=matched_on,
        )

    @staticmethod
    def _invoice_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
        l_inv = str(left.get("_invoice_number", "")).strip()
        r_inv = str(right.get("_invoice_number", "")).strip()
        if not l_inv or not r_inv:
            return 0.0
        return 1.0 if l_inv == r_inv else 0.0

    def _amounts_match(self, left: Decimal, right: Decimal) -> bool:
        tolerance = max(abs(left), abs(right)) * self._amount_tolerance_pct
        return abs(left - right) <= tolerance

    @staticmethod
    def _is_exact_match(pair: DuplicatePair) -> bool:
        return "exact_text" in pair.matched_on

    def _sim_vector(self, left: dict[str, Any], right: dict[str, Any]) -> list[float]:
        """Feature vector for the ML layer: [text, invoice, amount] similarity."""
        text_sims = [
            _text_similarity(str(left.get(col, "")), str(right.get(col, "")))
            for col in self._text_columns
        ]
        text_sim = max(text_sims) if text_sims else 0.0
        return [
            text_sim,
            self._invoice_similarity(left, right),
            _amount_similarity(left["_amount"], right["_amount"]),
        ]

    def _framework_version(self) -> str:
        if self._sklearn_ensemble is None:
            return "scikit-learn not installed"
        return "scikit-learn installed"
