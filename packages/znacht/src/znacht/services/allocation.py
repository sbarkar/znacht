"""How much of each ingredient to buy, and on which list (ADR-0016).

Quantities are computed once per ingredient, from the need summed over every recipe and day
(after the pantry), and then split between the lists: the in-store list is bought first, so its
packs count against the later needs too, and the online basket gets only what is still missing.
Nothing is rounded up per list. Moving packs between the lists (a backup bought in store in case
the delivery is late) moves them; it never adds packs on one list without taking them off the other.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal

from znacht.domain.needs import IngredientNeed
from znacht.domain.product import Channel
from znacht.domain.quantity import Quantity, Unit
from znacht.domain.shopping import ProductChoice, ShoppingPlan
from znacht.services.optimiser import shop_amount
from znacht.services.packs import packs_needed

BACKUP_REASON = "backup in store in case the delivery is late"

GroupKey = tuple[str, Unit]  # ingredient name, base unit of its needs


def need_index(plan: ShoppingPlan) -> dict[str, IngredientNeed]:
    return {n.key: n for n in plan.needs}


def summed(quantities: Iterable[Quantity]) -> Quantity | None:
    out: Quantity | None = None
    for q in quantities:
        out = q.to_base() if out is None else out + q
    return out


def needed_for(keys: Iterable[str], index: Mapping[str, IngredientNeed]) -> Quantity | None:
    """The summed need behind ``keys`` (each key once), or ``None`` when none is in the plan."""
    seen: dict[str, Quantity] = {}
    for key in keys:
        if key in index and key not in seen:
            seen[key] = index[key].quantity
    return summed(seen.values())


def line_need(line: ProductChoice, index: Mapping[str, IngredientNeed]) -> Quantity | None:
    return needed_for(line.need_keys, index) or line.need_quantity


def group_key(line: ProductChoice, index: Mapping[str, IngredientNeed]) -> GroupKey | None:
    """Which ingredient a line buys for; ``None`` for household lines and orphans."""
    if not line.need_keys:
        return None
    need = line_need(line, index)
    if need is None:
        return None
    return line.need_name, need.base_unit


def bought_covers(line: ProductChoice, need: Quantity) -> Quantity | None:
    """What the line buys in the need's unit; ``None`` when the units do not bridge
    ("2 onions" against a 1 kg bag), where one pack is taken to cover it (see ``packs_needed``)."""
    return line.bought.to_base() if line.product.pack.compatible(need) else None


def _ordered(lines: Iterable[ProductChoice]) -> list[ProductChoice]:
    """In-store first (it is bought before the delivery), then by when it is needed."""
    return sorted(lines, key=lambda c: (c.channel != Channel.STORE, c.needed_on, c.product.id))


def _merge_same_list(lines: Sequence[ProductChoice]) -> list[ProductChoice]:
    """One line per product per list: two lines for one product on one list are one purchase."""
    out: list[ProductChoice] = []
    for line in lines:
        i = next(
            (
                j
                for j, m in enumerate(out)
                if m.channel == line.channel and m.product.id == line.product.id
            ),
            None,
        )
        if i is None:
            out.append(line)
            continue
        prev = out[i]
        out[i] = prev.model_copy(
            update={
                "need_keys": prev.need_keys
                + tuple(k for k in line.need_keys if k not in prev.need_keys),
                "need_quantity": summed(q for q in (prev.need_quantity, line.need_quantity) if q),
                "needed_on": min(prev.needed_on, line.needed_on),
                "movable": prev.movable and line.movable,
                "split_reason": prev.split_reason or line.split_reason,
            }
        )
    return out


def allocate_group(
    lines: Sequence[ProductChoice], index: Mapping[str, IngredientNeed]
) -> list[ProductChoice]:
    """Packs for one ingredient's lines from the cumulative need: each line buys only what the
    lines before it (in-store first) do not already cover. A line left with nothing to buy is
    dropped and the line that covers it takes over its needs."""
    if not lines:
        return []
    name = lines[0].need_name
    kept: list[ProductChoice] = []
    seen: list[str] = []
    covered = Decimal(0)
    unbounded = False  # a pack whose unit does not bridge covers the ingredient outright
    for line in _merge_same_list(_ordered(lines)):
        seen.extend(k for k in line.need_keys if k not in seen)
        cumulative = needed_for(seen, index) or line.need_quantity
        if cumulative is None:
            kept.append(line)
            continue
        target = shop_amount(name, cumulative)
        if kept and (unbounded or target.base_value <= covered):
            prev = kept[-1]
            kept[-1] = prev.model_copy(
                update={
                    "need_keys": prev.need_keys
                    + tuple(k for k in line.need_keys if k not in prev.need_keys),
                    "need_quantity": summed(
                        q for q in (prev.need_quantity, line.need_quantity) if q
                    ),
                    "reason": f"{prev.reason}; also covers {line.needed_on:%a}",
                }
            )
            continue
        remaining = Quantity(value=target.base_value - covered, unit=target.base_unit)
        packs = packs_needed(remaining, line.product.pack)
        if line.product.pack.compatible(target):
            covered += line.product.pack.base_value * packs
        else:
            unbounded = True
        kept.append(line.model_copy(update={"packs": packs}))
    channels = {c.channel for c in kept}
    if len(channels) > 1:
        in_store = summed(c.bought for c in kept if c.channel == Channel.STORE)
        online = summed(c.bought for c in kept if c.channel == Channel.ONLINE)
        why = (
            f"needed before and after the delivery: {display(in_store)} in store, "
            f"{display(online)} online"
        )
        kept = [c if c.split_reason else c.model_copy(update={"split_reason": why}) for c in kept]
    return kept


def allocate(plan: ShoppingPlan, only: Iterable[GroupKey] | None = None) -> ShoppingPlan:
    """Re-compute packs per ingredient across both lists (all ingredients, or ``only`` these).
    Household lines and lines that trace to no need are left as they are."""
    index = need_index(plan)
    wanted = set(only) if only is not None else None
    groups: dict[GroupKey, list[ProductChoice]] = {}
    passthrough: list[ProductChoice] = []
    for line in plan.lines:
        key = group_key(line, index)
        if key is None or line.manual_reason or (wanted is not None and key not in wanted):
            passthrough.append(line)
            continue
        groups.setdefault(key, []).append(
            line if wanted is None else line.model_copy(update={"split_reason": None})
        )
    result = [*passthrough]
    for key in sorted(groups):
        result.extend(allocate_group(groups[key], index))
    return _rebuild(plan, result)


def _rebuild(plan: ShoppingPlan, lines: Iterable[ProductChoice]) -> ShoppingPlan:
    """Lines back onto their lists, keeping the order the lists had."""
    position = {(c.channel, c.product.id): i for i, c in enumerate(plan.lines)}
    ordered = sorted(lines, key=lambda c: position.get((c.channel, c.product.id), len(position)))
    return plan.model_copy(
        update={
            "online": tuple(c for c in ordered if c.channel == Channel.ONLINE),
            "in_store": tuple(c for c in ordered if c.channel == Channel.STORE),
        }
    )


def add_backup(
    plan: ShoppingPlan, need_name: str, packs: int | None = None, reason: str = BACKUP_REASON
) -> ShoppingPlan:
    """Move ``packs`` of an online line to the in-store list as a backup, in one operation: the
    online quantity goes down by what the in-store list gains. Without ``packs``, all moves."""
    online = next((c for c in plan.online if c.need_name == need_name), None)
    if online is None:
        raise LookupError(f"{need_name} is not on the online basket")
    moving = online.packs if packs is None else packs
    if not 0 < moving <= online.packs:
        raise ValueError(f"can move 1 to {online.packs} packs of {need_name}, not {moving}")
    remaining = online.packs - moving
    backup = online.model_copy(
        update={
            "channel": Channel.STORE,
            "packs": moving,
            "movable": False,
            "split_reason": reason if remaining else None,
            "reason": f"{online.reason}; {reason}"
            if remaining
            else f"{online.reason}; moved to store",
        }
    )
    new_online = [c for c in plan.online if c is not online]
    if remaining:
        new_online.insert(
            plan.online.index(online),
            online.model_copy(update={"packs": remaining, "split_reason": reason}),
        )
    in_store = list(plan.in_store)
    same = next((i for i, c in enumerate(in_store) if c.product.id == online.product.id), None)
    if same is None:
        in_store.append(backup)
    else:
        prev = in_store[same]
        in_store[same] = prev.model_copy(
            update={
                "packs": prev.packs + moving,
                "need_keys": prev.need_keys
                + tuple(k for k in online.need_keys if k not in prev.need_keys),
                "split_reason": backup.split_reason or prev.split_reason,
            }
        )
    return plan.model_copy(update={"online": tuple(new_online), "in_store": tuple(in_store)})


def display(q: Quantity | None, big: bool | None = None) -> str:
    """``1500 g`` as ``1.5 kg``; ``big`` forces (or refuses) kilograms and litres so several
    quantities in one message read in one unit."""
    if q is None:
        return "?"
    base = q.to_base()
    if big is None:
        big = base.base_value >= 1000
    if big and base.unit in (Unit.G, Unit.ML):
        unit = Unit.KG if base.unit == Unit.G else Unit.L
        value = base.base_value / 1000
    else:
        unit, value = base.unit, base.base_value
    text = f"{value.quantize(Decimal('0.001')).normalize():f}"
    if unit == Unit.PIECE:
        return f"{text} piece{'s' if value != 1 else ''}"
    return f"{text} {unit}"
