from decimal import Decimal

import pytest

from tests.cookidoo.fake_client import CATALOGUE, details
from znacht.domain.quantity import Unit
from znacht.domain.recipe import Category, Spiciness, Tag
from znacht_cookidoo.mapping import categorise, infer_spiciness, parse_quantity, recipe_from_details


@pytest.mark.parametrize(
    ("text", "value", "unit"),
    [
        ("500 g", Decimal(500), Unit.G),
        ("1.5 kg", Decimal("1.5"), Unit.KG),
        ("400 ml", Decimal(400), Unit.ML),
        ("2.5 dl", Decimal(250), Unit.ML),
        ("1 l", Decimal(1), Unit.L),
        ("1", Decimal(1), Unit.PIECE),
        ("1 - 2", Decimal(2), Unit.PIECE),
        ("2 tbsp", Decimal(2), Unit.PIECE),
        ("½", Decimal("0.5"), Unit.PIECE),
        ("3 cloves", Decimal(3), Unit.PIECE),
        ("1 - 2 sprigs", Decimal(2), Unit.PIECE),
        ("2 Zehen", Decimal(2), Unit.PIECE),
    ],
)
def test_parse_quantity(text, value, unit):
    q = parse_quantity(text)
    assert q is not None
    assert (q.value, q.unit) == (value, unit)


def test_parse_quantity_empty_or_words_is_none():
    assert parse_quantity("") is None
    assert parse_quantity("to taste") is None


@pytest.mark.parametrize(
    ("name", "category"),
    [
        ("salmon fillet", Category.FISH),
        ("Lachsfilet", Category.FISH),
        ("minced beef", Category.MEAT),
        ("chicken breast", Category.POULTRY),
        ("natural yogurt", Category.YOGURT),
        ("parmesan", Category.DAIRY),
        ("red lentils", Category.LEGUME),
        ("coconut milk", Category.TINNED),
        ("spaghetti", Category.GRAIN),
        ("fresh dill", Category.HERB),
        ("olive oil", Category.PANTRY),
        ("onion", Category.PRODUCE),
        ("Zwiebel", Category.PRODUCE),
        ("pancetta", Category.MEAT),
        ("guanciale", Category.MEAT),
        ("mystery powder", Category.OTHER),
    ],
)
def test_categorise(name, category):
    assert categorise(name) == category


def test_recipe_from_details_maps_everything():
    recipe = recipe_from_details(CATALOGUE["r1001"], "en")
    assert recipe.id.key == "cookidoo:r1001"
    assert recipe.servings == 4
    assert recipe.total_minutes == 30
    assert recipe.has_tag(Tag.FISH)
    assert not recipe.has_tag(Tag.VEGETARIAN)
    assert recipe.contains("dill")
    salmon = next(i for i in recipe.ingredients if i.name == "salmon fillet")
    assert salmon.category == Category.FISH
    assert salmon.quantity.value == 500
    assert salmon.raw == "500 g salmon fillet"
    oil = next(i for i in recipe.ingredients if i.name == "olive oil")
    assert oil.staple
    assert oil.quantity.unit == Unit.PIECE  # tbsp counted as pieces, raw notation kept


def test_tags_and_spiciness_are_inferred():
    dal = recipe_from_details(CATALOGUE["r1002"])
    assert {Tag.LEGUMES, Tag.VEGETARIAN, Tag.FAMILY} <= set(dal.tags)
    chilli = recipe_from_details(CATALOGUE["r1003"])
    assert chilli.has_tag(Tag.RED_MEAT) and chilli.has_tag(Tag.LEGUMES)
    assert chilli.spiciness == Spiciness.HOT
    assert infer_spiciness("Beef chilli", chilli.ingredients) == Spiciness.MILD
    plain = details("r9", "Plain soup", [("carrot", "2")])
    assert recipe_from_details(plain).spiciness == Spiciness.NONE
