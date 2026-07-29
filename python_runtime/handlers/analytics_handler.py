"""Analytics handler — executes DuckDB SQL queries against imported data.

Pipeline: import -> Pandera validate -> DuckDB query -> result Dataset.
"""

from __future__ import annotations

import logging

import duckdb

from python_runtime.importers.factory import ImporterFactory
from python_runtime.importers.protocol import Dataset
from python_runtime.models import ComputeError, Job
from python_runtime.validation.schemas import SCHEMA_REGISTRY
from python_runtime.validation.validator import validate_dataset as _validate_dataset

logger = logging.getLogger(__name__)


class AnalyticsHandler:
    """Executes DuckDB SQL queries against imported data.

    Pipeline: import -> Pandera validate -> DuckDB query -> result Dataset.

    The handler is synchronous — the Dispatcher's ThreadPoolExecutor manages
    concurrency.
    """

    def handle(self, job: Job) -> Dataset:
        """Execute the analytics pipeline for a job.

        Args:
            job: Job with params containing source_type, source_uri, query,
                 and optional validation_schema.

        Returns:
            Result Dataset from the DuckDB query.

        Raises:
            ComputeError: At any stage of the pipeline.
        """
        # 1. Extract params
        source_type = job.params.get("source_type", "csv")
        source_uri = job.params.get("source_uri", "")
        query = job.params.get("query", "")
        schema_name = job.params.get("validation_schema", "financial_dataset")

        if not source_uri:
            raise ComputeError(
                code="IMPORT_ERROR",
                message="Missing 'source_uri' in job params",
                details={"pipeline": job.pipeline},
            )
        if not query:
            raise ComputeError(
                code="ANALYTICS_ERROR",
                message="Missing 'query' in job params",
                details={"pipeline": job.pipeline},
            )

        # 2. Import data
        try:
            importer = ImporterFactory.create(source_type)
            dataset = importer.import_data(source_uri, **job.params.get("import_kwargs", {}))
        except Exception as exc:
            raise ComputeError(
                code="IMPORT_ERROR",
                message=f"Data import failed: {exc}",
                details={"source_type": source_type, "source_uri": source_uri},
            ) from exc

        # 3. Validate dataset (if schema is registered)
        if schema_name in SCHEMA_REGISTRY:
            schema = SCHEMA_REGISTRY[schema_name]
            try:
                _validate_dataset(schema, dataset)
            except ComputeError:
                raise  # re-raise ComputeError as-is
            except Exception as exc:
                raise ComputeError(
                    code="VALIDATION_ERROR",
                    message=f"Dataset validation failed: {exc}",
                    details={"schema": schema_name},
                ) from exc

        # 4. Execute DuckDB query
        conn: duckdb.DuckDBPyConnection | None = None
        try:
            conn = duckdb.connect(":memory:")
            conn.register("data", dataset.data)
            pl_result = conn.execute(query).pl()
        except Exception as exc:
            raise ComputeError(
                code="ANALYTICS_ERROR",
                message=f"DuckDB query failed: {exc}",
                details={"query": query, "source_uri": source_uri},
            ) from exc
        finally:
            if conn:
                conn.close()

        # 5. Wrap result as Dataset

        return Dataset(
            data=pl_result,
            source="duckdb",
            metadata={
                "source_query": query,
                "source_pipeline": job.pipeline,
            },
        )
