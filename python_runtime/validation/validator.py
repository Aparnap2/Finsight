"""Dual validation: Pydantic at the request boundary, Pandera at the DataFrame boundary.

Raises ComputeError (not raw exceptions) so the dispatcher can handle all
errors uniformly.
"""

from __future__ import annotations

from typing import Any

import pandera.errors as pa_errors
import pandera.polars as pa
from pydantic import BaseModel, ValidationError

from python_runtime.importers.protocol import Dataset
from python_runtime.models import ComputeError


def validate_request(model: type[BaseModel], data: dict[str, Any]) -> BaseModel:
    """Pydantic validation at the request boundary.

    Args:
        model: Pydantic model class to validate against.
        data: Raw request data dict.

    Returns:
        Validated model instance on success.

    Raises:
        ComputeError: Wrapping Pydantic ValidationError on failure.
    """
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ComputeError(
            code="VALIDATION_ERROR",
            message="Request failed Pydantic validation",
            details={"errors": exc.errors(include_url=False)},
        ) from exc


def validate_dataset(
    schema: type[pa.DataFrameModel],
    dataset: Dataset,
) -> Dataset:
    """Pandera validation at the DataFrame boundary.

    The Dataset is immutable after validation — we only check, we don't modify.

    Args:
        schema: Pandera DataFrameModel class to validate against.
        dataset: Dataset containing the DataFrame to validate.

    Returns:
        The (unchanged) Dataset on success.

    Raises:
        ComputeError: On schema violations, wrapping Pandera SchemaErrors.
    """
    try:
        schema.validate(dataset.data, lazy=True)
    except pa_errors.SchemaErrors as exc:
        raise ComputeError(
            code="DATASET_VALIDATION_ERROR",
            message=f"Dataset failed Pandera validation for {schema.__name__}",
            details={
                "schema": schema.__name__,
                "failure_cases": exc.message,
            },
        ) from exc
    return dataset


class DualValidator:
    """Runs Pydantic validation, then Pandera validation.

    Usage:
        validator = DualValidator(request_model=JobSubmitRequest)
        validated_request = validator.validate_request(raw_data)
        validated_dataset = validator.validate_dataset(FinancialDatasetSchema, dataset)
    """

    def __init__(self, request_model: type[BaseModel] | None = None):
        """Initialize with an optional Pydantic request model.

        Args:
            request_model: Pydantic model for request validation (optional).
        """
        self._request_model = request_model

    def validate_request(self, data: dict[str, Any]) -> BaseModel:
        """Validate request data against the configured Pydantic model.

        Args:
            data: Raw request data dict.

        Returns:
            Validated model instance.

        Raises:
            ValueError: If no request model was configured.
            ComputeError: On validation failure.
        """
        if self._request_model is None:
            raise ValueError("No request model configured")
        return validate_request(self._request_model, data)

    def validate_dataset(
        self,
        schema: type[pa.DataFrameModel],
        dataset: Dataset,
    ) -> Dataset:
        """Validate a Dataset against a Pandera schema.

        Args:
            schema: Pandera DataFrameModel class.
            dataset: Dataset to validate.

        Returns:
            Dataset on success.

        Raises:
            ComputeError: On schema violation.
        """
        return validate_dataset(schema, dataset)
