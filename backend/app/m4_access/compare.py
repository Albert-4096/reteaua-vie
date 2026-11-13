"""v1 compare: two closures side by side (CONTRACT GET /api/compare?a=&b=).

Each side is m1-core's Impact of a stored, analyzed closure (decisions applied).
The frontend draws the difference; nothing is computed here beyond the two impacts.
"""

from __future__ import annotations

from app.common.errors import invalid
from app.m1_disruption.impact import compute_impact
from app.models.v1 import Compare


def compare_closures(a: str, b: str) -> Compare:
    if not a or not b:
        raise invalid("Give two closure ids: ?a=…&b=….")
    return Compare(a=compute_impact(a), b=compute_impact(b))
