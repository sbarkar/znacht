"""Edit the household YAML from the app, keeping the human's comments and order.

The YAML stays the source of truth (it is what the household reads and versions); the app
applies small, validated patches through ruamel's round-trip loader.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from znacht.config import parse_household


def _yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=4, offset=2)
    y.width = 100
    return y


def apply_patch(path: Path, patch: dict[str, Any]) -> dict[str, Any]:
    """Apply a partial update and write the file atomically. Returns the applied patch.

    Supported keys: members (list of {name, age_group?, dislikes?, allergies?, mild_food?},
    replaces the list), rules ({min_per_week, max_per_week, banned_ingredients,
    max_total_minutes_weekday, dinners_per_week}, merged), pantry ({name: quantity}, merged;
    "0" or "" removes), make_at_home ({dish: {component: qty}}, merged; null removes),
    free_text_items (list, replaces), default_servings, delivery ({postcode,
    preferred_slot_id}), store_lists ({online, in_store}), health ({rules: [...]}).
    """
    yaml = _yaml()
    data = yaml.load(path.read_text(encoding="utf-8")) or {}
    for key, value in patch.items():
        if key == "members":
            data["members"] = [_clean_member(m) for m in value]
        elif key == "rules":
            rules = data.setdefault("rules", {})
            for rk, rv in value.items():
                if rk in ("min_per_week", "max_per_week"):
                    bucket = rules.setdefault(rk, {})
                    for tag, n in rv.items():
                        if n is None or int(n) <= 0:
                            bucket.pop(tag, None)
                        else:
                            bucket[tag] = int(n)
                elif rk == "banned_ingredients":
                    rules[rk] = [str(x) for x in rv]
                elif rv is None:
                    rules.pop(rk, None)
                else:
                    rules[rk] = rv
        elif key == "pantry":
            pantry = data.setdefault("pantry", {})
            for name, qty in value.items():
                if qty in (None, "", "0", 0):
                    pantry.pop(name, None)
                else:
                    pantry[name] = str(qty)
        elif key == "make_at_home":
            mah = data.setdefault("make_at_home", {})
            for dish, parts in value.items():
                if parts is None:
                    mah.pop(dish, None)
                else:
                    mah[dish] = {k: str(v) for k, v in parts.items()}
        elif key == "health":
            health = data.setdefault("health", {})
            if "rules" in value:
                health["rules"] = [str(x) for x in value["rules"]]
        elif key in (
            "free_text_items",
            "default_servings",
            "delivery",
            "store_lists",
            "store_policy",
        ):
            if isinstance(value, dict) and isinstance(data.get(key), dict):
                data[key].update(value)
            else:
                data[key] = value
        else:
            raise ValueError(f"unknown household field {key!r}")
    buf = io.StringIO()
    yaml.dump(data, buf)
    text = buf.getvalue()
    parse_household(text)  # validate before touching the file
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return patch


def _clean_member(m: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"name": str(m["name"]), "age_group": str(m.get("age_group", "adult"))}
    if m.get("dislikes"):
        out["dislikes"] = [str(x) for x in m["dislikes"]]
    if m.get("allergies"):
        out["allergies"] = [str(x) for x in m["allergies"]]
    if m.get("mild_food") is not None:
        out["mild_food"] = bool(m["mild_food"])
    return out
