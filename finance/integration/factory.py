"""Factory that instantiates spreadsheet providers by type name."""

from __future__ import annotations

import importlib
from typing import Any


class ProviderFactory:
    """Creates spreadsheet providers based on a configuration type string.

    Usage::

        factory = ProviderFactory()
        csv_provider = factory.create("csv", path="data.csv")
        mock_provider = factory.create("mock")
        gs_provider  = factory.create("google_sheets", credentials_path="creds.json")
    """

    _PROVIDERS: dict[str, str] = {
        "csv": "finance.integration.csv_provider.CSVProvider",
        "mock": "finance.integration.mock_provider.MockProvider",
        "google_sheets": "finance.integration.google_sheets_provider.GoogleSheetsProvider",
    }

    @property
    def registered_types(self) -> list[str]:
        """Return the list of registered provider type names."""
        return list(self._PROVIDERS.keys())

    @classmethod
    def create(cls, provider_type: str, **kwargs: Any) -> Any:
        """Create a provider instance.

        Parameters
        ----------
        provider_type : str
            One of ``"csv"``, ``"mock"``, or ``"google_sheets"`` (case-insensitive).
        **kwargs
            Forwarded to the provider's constructor.

        Returns
        -------
        An instance of the requested provider class.

        Raises
        ------
        ValueError
            If *provider_type* is not recognised.
        """
        type_lower = provider_type.lower()
        if type_lower not in cls._PROVIDERS:
            raise ValueError(
                f"Unknown provider type: '{provider_type}'. "
                f"Registered types: {list(cls._PROVIDERS)}",
            )
        module_path, class_name = cls._PROVIDERS[type_lower].rsplit(".", 1)
        module = importlib.import_module(module_path)
        klass = getattr(module, class_name)
        return klass(**kwargs)
