from __future__ import annotations

from znacht.domain.money import Money
from znacht.domain.product import Channel
from znacht.domain.shopping import MinimumOrderReport, ProductChoice, ShoppingPlan


def ensure_minimum_order(plan: ShoppingPlan) -> tuple[ShoppingPlan, MinimumOrderReport]:
    """Reach the minimum order by moving movable in-store lines online, cheapest penalty first.

    Never adds anything. Never pads with pantry staples. If still short, asks the household.
    """
    if plan.meets_minimum or plan.slot is None:
        return plan, MinimumOrderReport(met=plan.meets_minimum)

    def penalty(c: ProductChoice) -> Money:
        return c.line_total(Channel.ONLINE) - c.line_total(Channel.STORE)

    movable = sorted(
        (
            c
            for c in plan.in_store
            if c.movable and c.product.price_online is not None and c.deliverable is not False
        ),
        key=lambda c: (penalty(c).amount, c.need_name),
    )
    online = list(plan.online)
    in_store = list(plan.in_store)
    moved: list[str] = []
    current = plan
    for candidate in movable:
        if current.meets_minimum:
            break
        in_store.remove(candidate)
        online.append(
            candidate.model_copy(
                update={
                    "channel": Channel.ONLINE,
                    "movable": False,
                    "reason": candidate.reason + "; moved online to reach the minimum order",
                }
            )
        )
        moved.append(candidate.need_name)
        current = plan.model_copy(update={"online": tuple(online), "in_store": tuple(in_store)})

    report = MinimumOrderReport(
        moved_online=tuple(moved),
        ask_household=None if current.meets_minimum else current.shortfall,
        met=current.meets_minimum,
    )
    return current, report
