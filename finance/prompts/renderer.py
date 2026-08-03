"""Prompt template renderer.

Injects variable values into template strings by replacing
``{variable_name}`` placeholders.
"""

from __future__ import annotations

import re
from typing import Any


class PromptRenderer:
    """Renders prompt templates by substituting ``{variable}`` placeholders.

    Examples::

        renderer = PromptRenderer()
        result = renderer.render(
            template="Analyze {account} in {period}.",
            variables={"account": "4010", "period": "2026-07"},
        )
    """

    _VARIABLE_PATTERN = re.compile(r"\{(\w+)\}")

    def render(self, template: str, variables: dict[str, Any]) -> str:
        """Render a template by substituting variables.

        Args:
            template: Template string with ``{variable}`` placeholders.
            variables: Mapping of variable names to values.

        Returns:
            Rendered string with all placeholders replaced.

        Raises:
            ValueError: If a placeholder in the template has no
                corresponding value in *variables*.
        """
        placeholders = self._VARIABLE_PATTERN.findall(template)
        missing = [p for p in placeholders if p not in variables]
        if missing:
            raise ValueError(
                f"Missing variable(s) in template: {', '.join(sorted(missing))}"
            )

        def _replace(match: re.Match[str]) -> str:
            key = match.group(1)
            return str(variables[key])

        return self._VARIABLE_PATTERN.sub(_replace, template)
