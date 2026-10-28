from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from znacht.domain._base import Frozen
from znacht.domain.product import ProductId


class FindingKind(StrEnum):
    SURPLUS = "surplus"  # bought beyond the week's need by more than the threshold
    CROSS_LIST = "cross_list"  # one product on both lists with no reason given
    ORPHAN = "orphan"  # a line that traces to no need and gives no reason


class Finding(Frozen):
    """One thing the reconciliation check found wrong with a shopping plan (ADR-0016).

    ``id`` names the ingredient (and product) and is stable across runs of the check. An
    override covers the finding only while its message reads the same: if the quantities
    change, the finding is open again."""

    id: str
    kind: FindingKind
    need_name: str
    message: str
    product_id: ProductId | None = None
    excess_packs: Decimal | None = None  # how many packs beyond need, in the largest pack


class Override(Frozen):
    """A household's explicit "buy it anyway" for one finding. Logged and kept with the run."""

    finding_id: str
    kind: FindingKind
    message: str  # the finding as it read when it was overridden
    reason: str
    at: datetime
