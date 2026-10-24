import pytest

from znacht import registry
from znacht.config import parse_household
from znacht.domain.money import Money


def test_example_household_loads(household):
    assert household.has_toddler
    assert household.rules.min_tags == {"fish": 2, "legumes": 2, "red_meat": 1}
    assert "dill" in household.rules.banned_ingredients
    assert household.pantry.get("olive oil") is not None
    assert household.store_policy.prefer_store_when_cheaper_by == Money.chf("0.50")
    assert household.make_at_home[0].dish == "hummus"
    assert household.servings == 3


def test_unknown_keys_are_rejected():
    with pytest.raises(ValueError):
        parse_household(
            "id: x\nname: x\nmembers: [{name: a}]\ndelivery: {postcode: '1'}\nbogus: 1\n"
        )


def test_registry_finds_builtin_and_memory_adapters():
    assert "rule_based" in registry.available(registry.PLANNER_PROVIDERS)
    assert "memory" in registry.available(registry.GROCERY_STORES)
    cls = registry.load(registry.GROCERY_STORES, "memory")
    assert getattr(cls, "name", None) == "memory"
    with pytest.raises(LookupError):
        registry.load(registry.GROCERY_STORES, "nope")
