"""Edit the household YAML from the app, keeping the human's comments and order.

The YAML stays the source of truth (it is what the household reads and versions); the app
applies small, validated patches through ruamel's round-trip loader.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import DoubleQuotedScalarString

from znacht.config import parse_household

EXAMPLE_HOUSEHOLD_ID = "example"  # the shipped example; while it is in place, the app offers setup
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


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
        elif key == "delivery":
            delivery = data.setdefault("delivery", {})
            for dk, dv in value.items():
                delivery[dk] = _slots(dv) if dk == "slot_templates" else dv
        elif key in (
            "free_text_items",
            "default_servings",
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


def write_new_household(path: Path, answers: dict[str, Any]) -> None:
    """Write a household file from the Welcome wizard's answers, validated, atomically.

    answers: name, members [{name, age_group?, dislikes?, allergies?}], rules {dinners_per_week?,
    max_total_minutes_weekday?, min_per_week?, max_per_week?}, delivery {postcode, weekday?,
    start?, end?}, store_lists {online, in_store}?
    """
    name = str(answers.get("name") or "").strip() or "Our household"
    members = [
        _clean_member(m) for m in answers.get("members") or [] if str(m.get("name", "")).strip()
    ]
    if not members:
        raise ValueError("add at least one person")
    rules_in = answers.get("rules") or {}
    rules: dict[str, Any] = {"dinners_per_week": int(rules_in.get("dinners_per_week") or 7)}
    if rules_in.get("max_total_minutes_weekday"):
        rules["max_total_minutes_weekday"] = int(rules_in["max_total_minutes_weekday"])
    for bucket in ("min_per_week", "max_per_week"):
        counts = {
            str(k): int(v) for k, v in (rules_in.get(bucket) or {}).items() if v and int(v) > 0
        }
        if counts:
            rules[bucket] = counts
    d = answers.get("delivery") or {}
    postcode = str(d.get("postcode") or "").strip()
    if not postcode:
        raise ValueError("the delivery postcode is missing")
    delivery: dict[str, Any] = {"postcode": postcode}
    if d.get("weekday") is not None and d.get("start") and d.get("end"):
        weekday = int(d["weekday"])
        slot_id = f"{WEEKDAYS[weekday]}-{str(d['start'])[:2]}-{str(d['end'])[:2]}"
        delivery["preferred_slot_id"] = slot_id
        delivery["slot_templates"] = _slots(
            [{"id": slot_id, "weekday": weekday, "start": d["start"], "end": d["end"]}]
        )
    data: dict[str, Any] = {
        "id": _slug(name),
        "name": name,
        "members": members,
        "rules": rules,
        "pantry": {},
        "delivery": delivery,
    }
    lists = answers.get("store_lists") or {}
    if lists.get("online") and lists.get("in_store"):
        data["store_lists"] = {"online": str(lists["online"]), "in_store": str(lists["in_store"])}
    yaml = _yaml()
    buf = io.StringIO()
    buf.write("# Made by the Znacht setup. Edit it here or in the app's Household screen.\n")
    yaml.dump(data, buf)
    text = buf.getvalue()
    parse_household(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _slots(templates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Quote the times: YAML 1.1 would read an unquoted 18:00 as the number 1080."""
    return [
        {
            "id": str(t["id"]),
            "weekday": int(t["weekday"]),
            "start": DoubleQuotedScalarString(str(t["start"])),
            "end": DoubleQuotedScalarString(str(t["end"])),
        }
        for t in templates
    ]


def _slug(name: str) -> str:
    slug = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")
    slug = "-".join(p for p in slug.split("-") if p) or "home"
    return "home" if slug == EXAMPLE_HOUSEHOLD_ID else slug


def _clean_member(m: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"name": str(m["name"]), "age_group": str(m.get("age_group", "adult"))}
    if m.get("dislikes"):
        out["dislikes"] = [str(x) for x in m["dislikes"]]
    if m.get("allergies"):
        out["allergies"] = [str(x) for x in m["allergies"]]
    if m.get("mild_food") is not None:
        out["mild_food"] = bool(m["mild_food"])
    return out
