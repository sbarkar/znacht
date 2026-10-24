from datetime import date
from decimal import Decimal

from znacht.domain.plan import Meal, MealPlan, MealSlot, Week
from znacht.services.checker import check_plan
from znacht.services.needs import explode_needs
from znacht_memory.fixtures import recipes, rid

WEEK = Week(start=date(2026, 10, 26))
RECIPES = {r.id.key: r for r in recipes()}


def _plan(*ids: str, servings: int = 3) -> MealPlan:
    return MealPlan(
        week=WEEK,
        meals=tuple(
            Meal(date=day, slot=MealSlot.DINNER, recipe_id=rid(i), servings=servings)
            for day, i in zip(WEEK.days(), ids, strict=False)
        ),
    )


def test_needs_scale_aggregate_and_deduct_pantry(household):
    plan = _plan("beef-ragu")
    needs = {n.name: n for n in explode_needs(plan, RECIPES, household)}
    # 500 g pasta scaled to 3/4 servings = 375 g, pantry has 250 g -> 125 g
    assert needs["pasta"].quantity.to_base().value == 125
    assert needs["minced beef"].quantity.to_base().value == 375
    assert "rice" not in needs  # not in the recipe
    assert needs["pasta"].needed_on == WEEK.start


def test_pantry_covers_earliest_needs_first(household):
    plan = _plan("fish-curry", "chicken-rice", "lentil-dal", "thai-curry")  # 4 x 225 g rice
    needs = [n for n in explode_needs(plan, RECIPES, household) if n.name == "rice"]
    # pantry 1 kg covers 4 x 225 g = 900 g entirely
    assert needs == []


def test_make_at_home_replaces_the_dish(household):
    needs = {n.name for n in explode_needs(_plan("hummus-bowls"), RECIPES, household)}
    assert "hummus" not in needs
    assert {"chickpeas", "tahini", "lemon"} <= needs


def test_checker_counts_tags_and_bans(household):
    good = _plan(
        "salmon-tray",
        "fish-curry",
        "beef-ragu",
        "lentil-dal",
        "chickpea-stew",
        "chicken-rice",
        "hummus-bowls",
    )
    assert check_plan(good, RECIPES, household) == []

    bad = _plan(
        "dill-salmon",
        "thai-curry",
        "beef-ragu",
        "pork-schnitzel",
        "lentil-dal",
        "chickpea-stew",
        "omelette",
    )
    codes = {v.code for v in check_plan(bad, RECIPES, household)}
    assert {"banned_ingredient", "dislike", "not_mild", "max_tag", "min_tag"} <= codes


def test_checker_flags_count_and_repeats(household):
    short = _plan("salmon-tray", "salmon-tray")
    codes = [v.code for v in check_plan(short, RECIPES, household)]
    assert "dinner_count" in codes
    assert "repeat" in codes


def test_merge_needs_sums_and_keeps_earliest_date(household):
    plan = _plan("beef-ragu", "fish-curry", "lentil-dal")  # onion on three days
    from znacht.services.needs import merge_needs

    merged = {n.name: n for n in merge_needs(explode_needs(plan, RECIPES, household))}
    assert merged["onion"].quantity.value == Decimal("2.25")  # 3 x 0.75
    assert merged["onion"].needed_on == WEEK.start
    assert len(merged["onion"].recipes) == 3
