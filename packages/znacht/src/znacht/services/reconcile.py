"""Reconciliation: compare what both lists buy with what the week needs (ADR-0016).

``reconcile`` is a pure, deterministic function of a ``ShoppingPlan`` (both lists, the needs
after the pantry, the pantry): the same plan always gives the same findings in the same order.
A plan with open findings cannot be applied; each finding is fixed (quantities adjusted) or
overridden with a reason, and overrides are logged.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal

from znacht.domain.diff import ShoppingList
from znacht.domain.product import Channel, Product, ProductId
from znacht.domain.quantity import Quantity
from znacht.domain.reconcile import Finding, FindingKind, Override
from znacht.domain.shopping import ProductChoice, ShoppingPlan
from znacht.ports.stores import GroceryStore
from znacht.services.allocation import (
    GroupKey,
    allocate,
    bought_covers,
    display,
    group_key,
    need_index,
    summed,
)
from znacht.services.optimiser import shop_amount

log = logging.getLogger(__name__)

_WHERE = {Channel.ONLINE: "online", Channel.STORE: "in-store"}


class UnreconciledPlan(ValueError):
    """The plan still has findings that were neither fixed nor overridden."""

    def __init__(self, findings: Sequence[Finding]) -> None:
        self.findings = tuple(findings)
        listed = "; ".join(f.message for f in self.findings)
        super().__init__(
            f"{len(self.findings)} open reconciliation finding"
            f"{'s' if len(self.findings) != 1 else ''}: {listed}. "
            "Fix each one or override it with a reason before approving."
        )


def reconcile(plan: ShoppingPlan) -> list[Finding]:
    """Surplus, cross-list duplicate and orphan findings, in a stable order."""
    index = need_index(plan)
    findings: list[Finding] = []

    # surplus: per ingredient, everything both lists buy for it against its summed need
    needs_by_group: dict[GroupKey, list[Quantity]] = {}
    for need in plan.needs:
        needs_by_group.setdefault((need.name, need.quantity.base_unit), []).append(need.quantity)
    lines_by_group: dict[GroupKey, list[ProductChoice]] = {}
    for line in plan.lines:
        key = group_key(line, index)
        if key is not None and not line.manual_reason:
            lines_by_group.setdefault(key, []).append(line)
    pantry = {p.name: p.quantity for p in plan.pantry}
    for key in sorted(lines_by_group):
        surplus = _surplus(
            key,
            lines_by_group[key],
            needs_by_group.get(key, []),
            pantry,
            plan.surplus_threshold_packs,
        )
        if surplus is not None:
            findings.append(surplus)

    # cross-list duplicate: one product on both lists, unless every such line says why
    on_both = sorted({c.product.id for c in plan.online} & {c.product.id for c in plan.in_store})
    for pid in on_both:
        lines = [c for c in plan.lines if c.product.id == pid]
        if all(c.split_reason or c.manual_reason for c in lines):
            continue
        product = lines[0].product
        online = summed(c.bought for c in lines if c.channel == Channel.ONLINE)
        in_store = summed(c.bought for c in lines if c.channel == Channel.STORE)
        combined = summed(c.bought for c in lines)
        big = combined is not None and combined.base_value >= 1000
        findings.append(
            Finding(
                id=f"{FindingKind.CROSS_LIST}:{pid}",
                kind=FindingKind.CROSS_LIST,
                need_name=lines[0].need_name,
                product_id=pid,
                message=(
                    f"{lines[0].need_name}: {product.name} is on both lists with no reason, "
                    f"{display(combined, big)} combined "
                    f"(online {display(online, big)} + in-store {display(in_store, big)})"
                ),
            )
        )

    # orphan: a line that traces to no need of this plan and gives no reason
    for line in plan.lines:
        if line.manual_reason:
            continue
        if line.need_keys and any(k in index for k in line.need_keys):
            continue
        dangling = " (its needs are not in this plan)" if line.need_keys else ""
        findings.append(
            Finding(
                id=f"{FindingKind.ORPHAN}:{line.channel}:{line.product.id}",
                kind=FindingKind.ORPHAN,
                need_name=line.need_name,
                product_id=line.product.id,
                message=(
                    f"{line.need_name}: {line.packs} × {line.product.name} on the "
                    f"{_WHERE[line.channel]} list traces to no recipe need and gives no "
                    f"reason{dangling}"
                ),
            )
        )
    return findings


def _surplus(
    key: GroupKey,
    lines: Sequence[ProductChoice],
    needs: Sequence[Quantity],
    pantry: Mapping[str, Quantity],
    threshold: Decimal,
) -> Finding | None:
    name = key[0]
    raw = summed(needs)
    need = shop_amount(name, raw) if raw is not None else None
    biggest = max(lines, key=lambda c: c.product.pack.base_value).product.pack
    bridged = need is not None and all(bought_covers(c, need) is not None for c in lines)
    if need is not None and bridged:
        bought = summed(c.bought for c in lines)
        assert bought is not None
        excess = bought.base_value - need.base_value
        if biggest.base_value == 0 or excess <= 0:
            return None
        excess_packs = excess / biggest.base_value
        big = max(bought.base_value, need.base_value) >= 1000
        split = " + ".join(
            f"{_WHERE[ch]} {display(summed(c.bought for c in lines if c.channel == ch), big)}"
            for ch in (Channel.ONLINE, Channel.STORE)
            if any(c.channel == ch for c in lines)
        )
        detail = f"{display(bought, big)} bought vs {display(need, big)} needed ({split})"
    else:
        # the units do not bridge ("2 onions" against a 1 kg bag): one pack covers the need
        packs = sum(c.packs for c in lines)
        excess_packs = Decimal(packs - (1 if need is not None else 0))
        split = " + ".join(
            f"{_WHERE[ch]} {sum(c.packs for c in lines if c.channel == ch)} × {biggest}"
            for ch in (Channel.ONLINE, Channel.STORE)
            if any(c.channel == ch for c in lines)
        )
        detail = f"{packs} packs bought for {display(need)} needed ({split})"
    if excess_packs <= threshold:
        return None
    if name in pantry:
        detail += f"; {display(pantry[name])} in the pantry already counted"
    return Finding(
        id=f"{FindingKind.SURPLUS}:{name}",
        kind=FindingKind.SURPLUS,
        need_name=name,
        message=f"{name}: {detail}",
        excess_packs=excess_packs.quantize(Decimal("0.01")).normalize(),
    )


def open_findings(findings: Iterable[Finding], overrides: Iterable[Override]) -> list[Finding]:
    """Findings no override covers. An override covers a finding while it reads the same."""
    covered = {(o.finding_id, o.message) for o in overrides}
    return [f for f in findings if (f.id, f.message) not in covered]


def fix_findings(plan: ShoppingPlan, findings: Iterable[Finding]) -> ShoppingPlan:
    """Adjust quantities so the findings go away: surplus and cross-list findings re-compute
    that ingredient's packs across both lists from its summed need; an orphan line is removed."""
    index = need_index(plan)
    regroup: set[GroupKey] = set()
    drop: set[tuple[Channel, ProductId]] = set()
    for f in findings:
        if f.kind == FindingKind.ORPHAN:
            channel = Channel(f.id.split(":")[1])
            drop.add((channel, ProductId(str(f.product_id))))
            continue
        for line in plan.lines:
            matches = (
                line.need_name == f.need_name
                if f.kind == FindingKind.SURPLUS
                else line.product.id == f.product_id
            )
            key = group_key(line, index) if matches else None
            if key is not None:
                regroup.add(key)
    if drop:
        plan = plan.model_copy(
            update={
                "online": tuple(c for c in plan.online if (c.channel, c.product.id) not in drop),
                "in_store": tuple(
                    c for c in plan.in_store if (c.channel, c.product.id) not in drop
                ),
            }
        )
    return allocate(plan, only=regroup) if regroup else plan


def override(finding: Finding, reason: str, at: datetime) -> Override:
    reason = reason.strip()
    if not reason:
        raise ValueError(f"an override of {finding.id} needs a reason")
    log.warning("reconciliation override: %s; reason: %s", finding.message, reason)
    return Override(
        finding_id=finding.id, kind=finding.kind, message=finding.message, reason=reason, at=at
    )


def plan_as_listed(
    plan: ShoppingPlan,
    online: ShoppingList,
    in_store: ShoppingList,
    products: Mapping[ProductId, Product],
) -> ShoppingPlan:
    """The plan as the store's lists actually hold it: each plan line takes the quantity its list
    shows, plan lines missing from a list are gone, and products the plan did not put there (a
    backup added by hand in the store's app) become lines that trace to no need."""
    fallback_day = min((n.needed_on for n in plan.needs), default=None) or (
        plan.slot.delivery_day if plan.slot else date.min
    )
    out: dict[Channel, list[ProductChoice]] = {Channel.ONLINE: [], Channel.STORE: []}
    texts: list[str] = []
    for channel, listed, ours in (
        (Channel.ONLINE, online, plan.online),
        (Channel.STORE, in_store, plan.in_store),
    ):
        for line in listed.lines:
            if line.product_id is None:
                if line.text:
                    texts.append(line.text)
                continue
            mine = [c for c in ours if c.product.id == line.product_id]
            if mine:
                first = mine[0]
                keys = tuple(dict.fromkeys(k for c in mine for k in c.need_keys))
                out[channel].append(
                    first.model_copy(update={"packs": line.quantity, "need_keys": keys})
                )
                continue
            product = products.get(line.product_id)
            if product is None:
                raise LookupError(f"product {line.product_id} on list {listed.id} is unknown")
            out[channel].append(
                ProductChoice(
                    need_name=product.name,
                    product=product,
                    packs=line.quantity,
                    needed_on=fallback_day,
                    channel=channel,
                    reason="on the list, not from the plan",
                )
            )
    return plan.model_copy(
        update={
            "online": tuple(out[Channel.ONLINE]),
            "in_store": tuple(out[Channel.STORE]),
            "free_text": tuple(texts),
        }
    )


async def read_listed_plan(
    plan: ShoppingPlan, store: GroceryStore, online_id: str, in_store_id: str
) -> ShoppingPlan:
    """``plan_as_listed`` on the store's live lists. Reads only."""
    online = await store.read_list(online_id)
    in_store = await store.read_list(in_store_id)
    products: dict[ProductId, Product] = {c.product.id: c.product for c in plan.lines}
    for line in (*online.lines, *in_store.lines):
        pid = line.product_id
        if pid is not None and pid not in products:
            products[pid] = await store.product(pid)
    return plan_as_listed(plan, online, in_store, products)
