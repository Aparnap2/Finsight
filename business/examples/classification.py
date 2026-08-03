"""Example classification catalog for the Example Library.

Classifies curated example sets into the four plan categories per
aggregate (``docs/14-platform/implementation-plan.md`` Phase 0):

* ``good`` — happy-path, fully valid data (e.g. invoice_good).
* ``bad`` — data that fails domain validation (e.g. unbalanced trial
  balance, missing vendor).
* ``edge`` — boundary conditions that must not crash logic (zero
  budget, negative amount, future date).
* ``malicious`` — adversarial input (cross-tenant references,
  tampered rows, injection-shaped strings).

The classification is a separate registry layer over the existing
tag-based ExampleSets so docs, tests, demos, and evaluations can all
select the same curated inputs without coupling to tag spellings.
"""

from __future__ import annotations

from enum import StrEnum

from business.examples.models import ExampleSet


class ExampleClassification(StrEnum):
    """Category of a curated example set."""

    GOOD = "good"
    BAD = "bad"
    EDGE = "edge"
    MALICIOUS = "malicious"


#: Classification of each known example set id by aggregate.
#: Aggregates mirror the domain values used by the example library
#: (invoices, trial_balance, variance, forecast, headcount).
_CLASSIFICATION: dict[str, dict[str, ExampleClassification]] = {
    "invoices": {
        "invoice_good": ExampleClassification.GOOD,
        "invoice_duplicate": ExampleClassification.BAD,
        "invoice_missing_vendor": ExampleClassification.BAD,
        "invoice_negative_amount": ExampleClassification.EDGE,
        "cross_currency_invoices": ExampleClassification.BAD,
        "future_dated_invoices": ExampleClassification.EDGE,
        "invoice_cross_tenant": ExampleClassification.MALICIOUS,
        "invoice_tampered": ExampleClassification.MALICIOUS,
    },
    "trial_balance": {
        "trial_balance_balanced": ExampleClassification.GOOD,
        "trial_balance_unbalanced": ExampleClassification.BAD,
    },
    "variance": {
        "budget_variance_normal": ExampleClassification.GOOD,
        "budget_variance_high": ExampleClassification.EDGE,
        "zero_budget_variance": ExampleClassification.EDGE,
        "negative_budget": ExampleClassification.EDGE,
        "missing_department_codes": ExampleClassification.EDGE,
        "multi_period_budget_revisions": ExampleClassification.EDGE,
        "period_with_no_actuals": ExampleClassification.EDGE,
        "cross_tenant_variance": ExampleClassification.MALICIOUS,
    },
    "forecast": {
        "forecast_vs_actual": ExampleClassification.GOOD,
    },
    "headcount": {
        "headcount_data": ExampleClassification.GOOD,
    },
}


class ExampleCatalog:
    """Registry over classified example sets.

    Provides aggregate and classification-aware lookup so callers can
    select curated inputs by category without knowing tag spellings.

    Attributes:
        sets_by_id: Mapping of example_id → ExampleSet.
    """

    def __init__(self, example_sets: list[ExampleSet]) -> None:
        """Build the catalog from a flat list of example sets.

        Args:
            example_sets: Example sets to classify.
        """
        self.sets_by_id: dict[str, ExampleSet] = {ex.example_id: ex for ex in example_sets}
        self.classification_by_id: dict[str, ExampleClassification] = {}
        for _, mapping in _CLASSIFICATION.items():
            for example_id, classification in mapping.items():
                if example_id in self.sets_by_id:
                    self.classification_by_id[example_id] = classification

    def classify(self, example_id: str) -> ExampleClassification:
        """Return the classification of an example set.

        Args:
            example_id: The example set identifier.

        Returns:
            The classification, or ``GOOD`` as the default for
            unclassified sets.
        """
        return self.classification_by_id.get(example_id, ExampleClassification.GOOD)

    def by_classification(
        self,
        classification: ExampleClassification,
    ) -> list[ExampleSet]:
        """Return all example sets in the given classification.

        Args:
            classification: The category to select.

        Returns:
            List of matching example sets.
        """
        return [
            self.sets_by_id[eid]
            for eid, cat in self.classification_by_id.items()
            if cat == classification
        ]

    def by_aggregate(self, aggregate: str) -> list[ExampleSet]:
        """Return example sets classified under the given aggregate.

        Args:
            aggregate: Aggregate domain (e.g. ``invoices``).

        Returns:
            List of example sets classified under that aggregate.
        """
        mapping = _CLASSIFICATION.get(aggregate, {})
        return [self.sets_by_id[eid] for eid in mapping if eid in self.sets_by_id]

    def __len__(self) -> int:
        """Return the number of classified example sets."""
        return len(self.classification_by_id)


__all__ = ["ExampleCatalog", "ExampleClassification"]
