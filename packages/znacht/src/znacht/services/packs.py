from __future__ import annotations

import math

from znacht.domain.quantity import Quantity


def packs_needed(need: Quantity, pack: Quantity) -> int:
    """Smallest number of packs covering ``need``. Zero need means zero packs.

    When the units do not bridge (a recipe wants "2 onions", the shop sells "1 kg"), one pack
    is assumed to cover it; the Brief shows the raw notation so the household can judge.
    """
    if need.is_zero:
        return 0
    if not need.compatible(pack):
        return 1
    return max(1, math.ceil(need.ratio(pack)))
