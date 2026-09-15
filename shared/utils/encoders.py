"""Custom JSON encoders for FinSight.

Ensures Decimal values are serialized as strings in JSON output
to avoid precision loss.
"""

import json
from decimal import Decimal
from typing import Any


class DecimalEncoder(json.JSONEncoder):
    """JSON encoder that serializes Decimal values as strings.

    Non-money floats (confidence scores, etc.) are left unchanged
    by the default JSON encoder.
    """

    def default(self, obj: Any) -> Any:
        if isinstance(obj, Decimal):
            return str(obj)
        return super().default(obj)


def dumps(obj: Any, **kwargs: Any) -> str:
    """Convenience wrapper around json.dumps that uses DecimalEncoder."""
    return json.dumps(obj, cls=DecimalEncoder, **kwargs)
