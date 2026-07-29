"""Shared test fixtures for Python Compute Runtime tests."""

import polars as pl
import pytest


@pytest.fixture
def sample_dataframe() -> pl.DataFrame:
    """Standard 5-row financial DataFrame for all pipeline tests."""
    return pl.DataFrame({
        "account_id": ["A100", "A101", "A102", "A103", "A104"],
        "period": ["2026-Q1"] * 5,
        "amount": [1000.0, 2500.0, 0.0, 500.0, 7500.0],
        "department": ["Sales", "Engineering", "Sales", "Marketing", "Engineering"],
        "currency": ["USD", "USD", "EUR", "USD", "USD"],
    })


@pytest.fixture
def sample_csv_path(tmp_path, sample_dataframe) -> str:
    """Write sample_dataframe to a temp CSV and return the path."""
    path = tmp_path / "test_data.csv"
    sample_dataframe.write_csv(path)
    return str(path)
