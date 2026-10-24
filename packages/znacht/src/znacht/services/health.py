"""Deterministic mapping from lab markers to dietary rules.

The LLM extracts markers; the household confirms them; *this* table turns them into rules
the planner sees and the household can read. It is deliberately conservative and
editable: nothing here is medical advice, it is the household's own policy written down.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

from znacht.domain.household import DietaryRule, HealthMarker
from znacht.domain.recipe import Tag

# marker name fragment -> (direction that triggers, rule text, tags to nudge)
_TABLE: Final[tuple[tuple[str, str, str, tuple[str, ...]], ...]] = (
    (
        "triglycerid",
        "high",
        "limit added sugar and refined carbs; fish twice a week; wholegrain over white",
        (Tag.FISH,),
    ),
    (
        "ldl",
        "high",
        "limit saturated fat: lean meat, low-fat dairy for adults, olive oil over butter",
        (Tag.FISH, Tag.LEGUMES),
    ),
    (
        "cholesterol",
        "high",
        "limit saturated fat; more legumes, oats and fish",
        (Tag.FISH, Tag.LEGUMES),
    ),
    (
        "hba1c",
        "high",
        "limit added sugar and refined carbs; legumes and wholegrains for slow carbs",
        (Tag.LEGUMES,),
    ),
    ("glucose", "high", "limit added sugar and refined carbs", (Tag.LEGUMES,)),
    (
        "ferritin",
        "low",
        "iron-rich dinners: red meat once, legumes, dark greens with vitamin C",
        (Tag.LEGUMES,),
    ),
    (
        "haemoglobin",
        "low",
        "iron-rich dinners: red meat once, legumes, dark greens with vitamin C",
        (Tag.LEGUMES,),
    ),
    (
        "hemoglobin",
        "low",
        "iron-rich dinners: red meat once, legumes, dark greens with vitamin C",
        (Tag.LEGUMES,),
    ),
    ("vitamin d", "low", "oily fish twice a week; eggs and fortified dairy", (Tag.FISH,)),
    (
        "uric",
        "high",
        "limit red meat and offal; more plant protein; plenty of water",
        (Tag.LEGUMES,),
    ),
    ("blood pressure", "high", "limit salt: low-salt tins, no added salt at the table", ()),
    ("sodium", "high", "limit salt: low-salt tins, no added salt at the table", ()),
    ("b12", "low", "fish, eggs and dairy regularly", (Tag.FISH,)),
)


def rules_from_markers(markers: Iterable[HealthMarker]) -> list[DietaryRule]:
    """Only flagged markers produce rules; an unflagged value is not interpreted."""
    out: list[DietaryRule] = []
    seen: set[str] = set()
    for marker in markers:
        flag = (marker.flag or "").lower()
        if flag not in ("high", "low"):
            continue
        name = marker.name.lower()
        for fragment, direction, text, tags in _TABLE:
            if fragment in name and direction == flag and text not in seen:
                seen.add(text)
                out.append(DietaryRule(text=text, tags=frozenset(tags)))
    return out
