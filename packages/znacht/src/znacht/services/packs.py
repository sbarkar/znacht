from __future__ import annotations

import math

from znacht.domain.quantity import Quantity


def packs_needed(need: Quantity, pack: Quantity) -> int:
    """Smallest number of packs covering ``need``. Zero need means zero packs."""
    if need.is_zero:
        return 0
    return max(1, math.ceil(need.ratio(pack)))
