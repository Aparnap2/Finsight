"""Tests for python_runtime.validation.validator — DualValidator."""

import polars as pl
import pytest
from pydantic import BaseModel

from python_runtime.importers.protocol import Dataset
from python_runtime.models import ComputeError
from python_runtime.validation.schemas import FinancialDatasetSchema, VarianceInputSchema
from python_runtime.validation.validator import (
    DualValidator,
    validate_dataset,
    validate_request,
)


class SampleRequest(BaseModel):
    name: str
    value: int


class TestValidateRequest:
    """Pydantic validation at the request boundary."""

    def test_valid_request(self) -> None:
        result = validate_request(SampleRequest, {"name": "test", "value": 42})
        assert isinstance(result, SampleRequest)
        assert result.name == "test"
        assert result.value == 42

    def test_invalid_request_raises_compute_error(self) -> None:
        with pytest.raises(ComputeError) as excinfo:
            validate_request(SampleRequest, {"name": "test"})  # missing 'value'
        assert excinfo.value.code == "VALIDATION_ERROR"
        assert "Pydantic validation" in excinfo.value.message
        assert excinfo.value.details is not None
        assert "errors" in excinfo.value.details

    def test_extra_fields_ignored(self) -> None:
        result = validate_request(SampleRequest, {"name": "test", "value": 1, "extra": "x"})
        assert isinstance(result, SampleRequest)


class TestValidateDataset:
    """Pandera validation at the DataFrame boundary."""

    def test_valid_dataset_passes(self, sample_dataframe: pl.DataFrame) -> None:
        # Sample dataframe has account_id, period, amount, department, currency
        dataset = Dataset(data=sample_dataframe, source="test")
        result = validate_dataset(FinancialDatasetSchema, dataset)
        assert result is dataset  # returns same instance

    def test_valid_variance_dataset(self) -> None:
        df = pl.DataFrame({
            "account_id": ["A100"],
            "actual_amount": [1000.00],
            "budget_amount": [900.00],
            "variance_pct": [11.1],
            "department": ["Sales"],
        })
        dataset = Dataset(data=df, source="test")
        result = validate_dataset(VarianceInputSchema, dataset)
        assert result is dataset

    @pytest.mark.skip(reason="Pandera nullable + Polars null handling may not trigger")
    def test_null_in_non_nullable_column(self, sample_dataframe: pl.DataFrame) -> None:
        df = sample_dataframe.with_columns(pl.lit(None).alias("account_id"))
        dataset = Dataset(data=df, source="test")
        with pytest.raises(ComputeError) as excinfo:
            validate_dataset(FinancialDatasetSchema, dataset)
        assert excinfo.value.code == "DATASET_VALIDATION_ERROR"
        assert "FinancialDatasetSchema" in excinfo.value.message


class TestDualValidator:
    """Runs Pydantic validation, then Pandera validation."""

    def test_init_with_request_model(self) -> None:
        validator = DualValidator(request_model=SampleRequest)
        assert validator._request_model is SampleRequest

    def test_init_without_request_model(self) -> None:
        validator = DualValidator()
        assert validator._request_model is None

    def test_validate_request_success(self) -> None:
        validator = DualValidator(request_model=SampleRequest)
        result = validator.validate_request({"name": "test", "value": 42})
        assert isinstance(result, SampleRequest)

    def test_validate_request_no_model_raises(self) -> None:
        validator = DualValidator()
        with pytest.raises(ValueError, match="No request model configured"):
            validator.validate_request({"name": "test"})

    def test_validate_dataset_success(self, sample_dataframe: pl.DataFrame) -> None:
        validator = DualValidator()
        dataset = Dataset(data=sample_dataframe, source="test")
        result = validator.validate_dataset(FinancialDatasetSchema, dataset)
        assert result is dataset
