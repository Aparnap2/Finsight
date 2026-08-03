"""Composable DataFrame transformation pipeline.

Provides TransformStep (single operation) and TransformPipeline (sequence
of steps) with ComputeError wrapping at each step.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import polars as pl

from python_runtime.models import ComputeError

logger = logging.getLogger(__name__)

# Type alias for a transform function
TransformFn = Callable[[pl.DataFrame], pl.DataFrame]


class TransformStep:
    """A single step in the transform pipeline.

    Attributes:
        name: Identifier for this step (used in error messages).
        fn: The transform function.
        description: Optional human-readable description.
    """

    def __init__(
        self,
        name: str,
        fn: TransformFn,
        description: str = "",
    ):
        """Initialize a transform step.

        Args:
            name: Identifier for this step.
            fn: Pure function DataFrame -> DataFrame.
            description: Optional description.
        """
        self.name = name
        self.fn = fn
        self.description = description

    def apply(self, data: pl.DataFrame) -> pl.DataFrame:
        """Apply the transform. Wraps errors as ComputeError.

        Args:
            data: Input DataFrame.

        Returns:
            Transformed DataFrame.

        Raises:
            ComputeError: If the transform function raises any exception.
        """
        try:
            return self.fn(data)
        except Exception as exc:
            raise ComputeError(
                code="TRANSFORM_ERROR",
                message=f"Transform step '{self.name}' failed: {exc}",
                details={"step": self.name, "error": str(exc)},
            ) from exc


class TransformPipeline:
    """A sequence of transform steps applied in order.

    Usage:
        pipeline = TransformPipeline()
        pipeline.add_step(step1).add_step(step2)
        result = pipeline.apply(data)
    """

    def __init__(self, steps: list[TransformStep] | None = None):
        """Initialize with an optional list of steps.

        Args:
            steps: Initial list of transform steps.
        """
        self._steps = steps or []

    def add_step(self, step: TransformStep) -> TransformPipeline:
        """Append a step and return self for fluent API.

        Args:
            step: TransformStep to append.

        Returns:
            Self for chaining.
        """
        self._steps.append(step)
        return self

    def apply(self, data: pl.DataFrame) -> pl.DataFrame:
        """Apply each step in sequence. Each step is a pure function.

        Args:
            data: Input DataFrame.

        Returns:
            Transformed DataFrame after all steps.

        Raises:
            ComputeError: If any step fails.
        """
        result = data
        for step in self._steps:
            logger.debug("Applying transform step: %s", step.name)
            result = step.apply(result)
        return result

    @property
    def steps(self) -> list[TransformStep]:
        """Return a copy of the step list."""
        return list(self._steps)
