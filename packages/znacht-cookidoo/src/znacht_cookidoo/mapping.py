"""Map cookidoo-api objects to the Znacht domain.

Cookidoo gives free-text quantities ("500 g", "1 - 2", "2 tbsp") and no categories or
tags, so this module parses what it can and infers the rest from keywords. Everything
inferred is a hint for the planner; the checker still validates against the household's
rules, and the raw notation is kept on the ingredient.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Final

from cookidoo_api import CookidooSearchRecipeHit, CookidooShoppingRecipeDetails
from cookidoo_api.types import CookidooCalendarDay, CookidooCalendarDayRecipe

from znacht.domain.plan import Meal, MealSlot
from znacht.domain.quantity import Quantity, Unit
from znacht.domain.recipe import Category, Ingredient, Recipe, RecipeId, Spiciness, Tag
from znacht_cookidoo.client import CUSTOM_SOURCE, SOURCE

_UNITS: Final[dict[str, Unit]] = {
    "g": Unit.G,
    "gr": Unit.G,
    "gram": Unit.G,
    "grams": Unit.G,
    "gramm": Unit.G,
    "kg": Unit.KG,
    "ml": Unit.ML,
    "l": Unit.L,
    "liter": Unit.L,
    "litre": Unit.L,
    "liters": Unit.L,
    "litres": Unit.L,
    "dl": Unit.ML,
    "cl": Unit.ML,
}
_UNIT_FACTOR: Final[dict[str, Decimal]] = {"dl": Decimal(100), "cl": Decimal(10)}

# Loose count-like units: one of these is one "piece" for shopping purposes.
_PIECE_UNITS: Final = frozenset(
    {
        "",
        "piece",
        "pieces",
        "pc",
        "pcs",
        "stk",
        "stück",
        "x",
        "clove",
        "cloves",
        "slice",
        "slices",
        "can",
        "cans",
        "tin",
        "tins",
        "bunch",
        "sprig",
        "sprigs",
        "stalk",
        "stalks",
        "head",
        "leaf",
        "leaves",
        "sheet",
        "sheets",
        "egg",
        "eggs",
        "pinch",
        "pinches",
        "tbsp",
        "tsp",
        "cup",
        "cups",
        "handful",
        "dash",
        "drop",
        "drops",
        "sachet",
        "packet",
        "pack",
        "zehe",
        "zehen",
        "prise",
        "el",
        "tl",
        "bund",
        "scheibe",
        "scheiben",
        "dose",
        "dosen",
        "blatt",
        "blätter",
        "stängel",
    }
)

_RANGE = re.compile(r"^\s*(?P<a>\d+(?:[.,]\d+)?)\s*-\s*(?P<b>\d+(?:[.,]\d+)?)\s*(?P<unit>.*)$")
_SINGLE = re.compile(r"^\s*(?P<a>\d+(?:[.,]\d+)?)\s*(?P<unit>.*)$")
_FRACTIONS: Final = {"½": "0.5", "¼": "0.25", "¾": "0.75", "⅓": "0.33", "⅔": "0.67"}

_STAPLES: Final = frozenset(
    {
        "salt",
        "pepper",
        "water",
        "sugar",
        "flour",
        "olive oil",
        "oil",
        "vinegar",
        "butter",
        "salz",
        "pfeffer",
        "wasser",
        "zucker",
        "mehl",
        "olivenöl",
        "öl",
        "essig",
    }
)

_CATEGORY_KEYWORDS: Final[tuple[tuple[Category, tuple[str, ...]], ...]] = (
    (
        Category.FISH,
        (
            "salmon",
            "lachs",
            "cod",
            "kabeljau",
            "fish",
            "fisch",
            "tuna",
            "thunfisch",
            "prawn",
            "shrimp",
            "crevette",
            "garnele",
            "trout",
            "forelle",
            "seafood",
            "mussel",
            "squid",
            "calamari",
            "zander",
            "haddock",
            "sea bass",
            "dorade",
        ),
    ),
    (
        Category.POULTRY,
        ("chicken", "poulet", "hähnchen", "huhn", "turkey", "truthahn", "pute", "duck", "ente"),
    ),
    (
        Category.MEAT,
        (
            "beef",
            "rind",
            "pork",
            "schwein",
            "lamb",
            "lamm",
            "veal",
            "kalb",
            "minced",
            "hackfleisch",
            "sausage",
            "wurst",
            "bacon",
            "speck",
            "ham",
            "schinken",
            "steak",
            "pancetta",
            "guanciale",
            "prosciutto",
            "salami",
            "chorizo",
            "lardon",
            "lardons",
            "mince",
        ),
    ),
    (
        Category.TINNED,
        (
            "tinned",
            "canned",
            "dose",
            "coconut milk",
            "kokosmilch",
            "passata",
            "tomato purée",
            "tomatenpüree",
            "pelati",
        ),
    ),
    (Category.YOGURT, ("yogurt", "yoghurt", "joghurt", "jogurt", "quark", "skyr")),
    (
        Category.DAIRY,
        (
            "milk",
            "milch",
            "cream",
            "rahm",
            "sahne",
            "cheese",
            "käse",
            "butter",
            "parmesan",
            "feta",
            "mozzarella",
            "crème fraîche",
            "mascarpone",
            "ricotta",
        ),
    ),
    (Category.MUESLI, ("muesli", "müsli", "granola", "cereal", "oats", "haferflocken")),
    (
        Category.LEGUME,
        ("lentil", "linsen", "chickpea", "kichererbse", "bean", "bohne", "tofu", "edamame"),
    ),
    (
        Category.GRAIN,
        (
            "pasta",
            "spaghetti",
            "penne",
            "fusilli",
            "noodle",
            "nudel",
            "rice",
            "reis",
            "couscous",
            "bulgur",
            "quinoa",
            "polenta",
            "risotto",
            "lasagne",
            "tagliatelle",
        ),
    ),
    (
        Category.BAKERY,
        ("bread", "brot", "bun", "brötchen", "baguette", "pita", "naan", "tortilla", "wrap"),
    ),
    (
        Category.HERB,
        (
            "parsley",
            "petersilie",
            "basil",
            "basilikum",
            "coriander",
            "koriander",
            "dill",
            "chive",
            "schnittlauch",
            "thyme",
            "thymian",
            "rosemary",
            "rosmarin",
            "mint",
            "minze",
            "oregano",
            "sage",
            "salbei",
        ),
    ),
    (Category.FROZEN, ("frozen", "tiefkühl", "tk-")),
    (
        Category.PANTRY,
        (
            "salt",
            "salz",
            "pepper",
            "pfeffer",
            "sugar",
            "zucker",
            "flour",
            "mehl",
            "oil",
            "öl",
            "vinegar",
            "essig",
            "stock",
            "bouillon",
            "brühe",
            "soy sauce",
            "sojasauce",
            "spice",
            "gewürz",
            "paprika powder",
            "cumin",
            "kreuzkümmel",
            "curry powder",
            "cinnamon",
            "zimt",
            "honey",
            "honig",
            "mustard",
            "senf",
            "water",
            "wasser",
        ),
    ),
    (
        Category.PRODUCE,
        (
            "onion",
            "zwiebel",
            "garlic",
            "knoblauch",
            "carrot",
            "karotte",
            "rüebli",
            "potato",
            "kartoffel",
            "tomato",
            "tomate",
            "pepper",
            "peperoni",
            "courgette",
            "zucchini",
            "aubergine",
            "spinach",
            "spinat",
            "broccoli",
            "brokkoli",
            "cauliflower",
            "blumenkohl",
            "lemon",
            "zitrone",
            "lime",
            "limette",
            "apple",
            "apfel",
            "banana",
            "banane",
            "pear",
            "birne",
            "ginger",
            "ingwer",
            "leek",
            "lauch",
            "cucumber",
            "gurke",
            "lettuce",
            "salat",
            "mushroom",
            "pilz",
            "champignon",
            "celery",
            "sellerie",
            "pumpkin",
            "kürbis",
            "avocado",
            "fennel",
            "fenchel",
            "cabbage",
            "kohl",
            "pea",
            "erbse",
            "corn",
            "mais",
            "beetroot",
        ),
    ),
)

_TAG_KEYWORDS: Final[tuple[tuple[Tag, tuple[str, ...]], ...]] = (
    (Tag.FISH, ("fish", "fisch", "seafood", "meeresfrüchte", "poisson", "pesce")),
    (Tag.POULTRY, ("poultry", "geflügel", "chicken", "poulet", "volaille", "pollo")),
    (
        Tag.RED_MEAT,
        ("meat", "fleisch", "beef", "rind", "pork", "schwein", "lamb", "lamm", "viande", "carne"),
    ),
    (
        Tag.LEGUMES,
        ("legume", "hülsenfrüchte", "lentil", "linsen", "chickpea", "kichererbse", "bean", "bohne"),
    ),
    (Tag.VEGETARIAN, ("vegetarian", "vegetarisch", "vegan", "végétarien", "vegetariano")),
    (Tag.FAMILY, ("family", "familie", "kids", "kinder", "famille", "famiglia")),
)

_HOT_WORDS: Final = (
    "spicy",
    "hot ",
    "scharf",
    "piccante",
    "piquant",
    "épicé",
    "fiery",
    "chili con",
)
_MILD_WORDS: Final = (
    "chilli",
    "chili",
    "jalapeño",
    "jalapeno",
    "harissa",
    "curry paste",
    "sriracha",
    "cayenne",
)


def _decimal(text: str) -> Decimal | None:
    try:
        return Decimal(text.replace(",", "."))
    except InvalidOperation:
        return None


def parse_quantity(description: str) -> Quantity | None:
    """``"500 g"`` → 500 g; ``"1 - 2"`` → 2 pieces (buy enough); ``"2 tbsp"`` → 2 pieces.
    Empty or unparseable text → ``None``."""
    text = description.strip()
    for sym, rep in _FRACTIONS.items():
        text = text.replace(sym, rep)
    if not text:
        return None
    match = _RANGE.match(text) or _SINGLE.match(text)
    if not match:
        return None
    value = _decimal(
        match.group("b")
        if "b" in match.groupdict() and match.groupdict().get("b")
        else match.group("a")
    )
    if value is None:
        return None
    unit = match.group("unit").strip().lower()
    if unit in _UNITS:
        factor = _UNIT_FACTOR.get(unit, Decimal(1))
        return Quantity(value=value * factor, unit=_UNITS[unit])
    if unit in _PIECE_UNITS or not unit:
        return Quantity(value=value, unit=Unit.PIECE)
    # unknown unit: count it as pieces but keep the raw text on the ingredient
    return Quantity(value=value, unit=Unit.PIECE)


def categorise(name: str) -> Category:
    lowered = name.lower()
    for category, words in _CATEGORY_KEYWORDS:
        if any(w in lowered for w in words):
            return category
    return Category.OTHER


def infer_tags(
    details: CookidooShoppingRecipeDetails, ingredients: list[Ingredient]
) -> frozenset[str]:
    tags: set[str] = set()
    names = [c.name.lower() for c in details.categories] + [
        c.name.lower() for c in details.collections
    ]
    for tag, words in _TAG_KEYWORDS:
        if any(w in n for n in names for w in words):
            tags.add(tag)
    categories = {i.category for i in ingredients}
    if Category.FISH in categories:
        tags.add(Tag.FISH)
    if Category.MEAT in categories:
        tags.add(Tag.RED_MEAT)
    if Category.POULTRY in categories:
        tags.add(Tag.POULTRY)
    if Category.LEGUME in categories:
        tags.add(Tag.LEGUMES)
    if not categories & {Category.FISH, Category.MEAT, Category.POULTRY}:
        tags.add(Tag.VEGETARIAN)
    else:
        tags.discard(Tag.VEGETARIAN)
    return frozenset(tags)


def infer_spiciness(title: str, ingredients: list[Ingredient]) -> Spiciness:
    lowered = f"{title.lower()} "
    if any(w in lowered for w in _HOT_WORDS):
        return Spiciness.HOT
    if any(w in i.name for i in ingredients for w in _MILD_WORDS):
        return Spiciness.MILD
    return Spiciness.NONE


def ingredient_from(name: str, description: str) -> Ingredient:
    quantity = parse_quantity(description) or Quantity(value=Decimal(1), unit=Unit.PIECE)
    lowered = name.strip().lower()
    return Ingredient(
        name=name,
        quantity=quantity,
        category=categorise(lowered),
        staple=lowered in _STAPLES,
        raw=f"{description} {name}".strip() if description else name,
    )


def recipe_from_details(
    details: CookidooShoppingRecipeDetails, locale: str | None = None
) -> Recipe:
    ingredients = [ingredient_from(i.name, i.description) for i in details.ingredients]
    return Recipe(
        id=RecipeId(source=SOURCE, external_id=details.id),
        title=details.name,
        servings=max(1, details.serving_size),
        ingredients=tuple(ingredients),
        tags=infer_tags(details, ingredients),
        total_minutes=details.total_time // 60 if details.total_time else None,
        active_minutes=details.active_time // 60 if details.active_time else None,
        spiciness=infer_spiciness(details.name, ingredients),
        locale=locale,
        url=details.url or None,
    )


def summary_from_hit(hit: CookidooSearchRecipeHit, locale: str | None = None) -> Recipe:
    """A search hit carries only the title. Ingredients come from ``get``."""
    return Recipe(
        id=RecipeId(source=SOURCE, external_id=hit.id),
        title=hit.name,
        servings=4,
        ingredients=(),
        locale=locale,
        url=hit.url or None,
    )


def day_date(day: CookidooCalendarDay) -> date | None:
    for candidate in (day.id, day.title):
        try:
            return date.fromisoformat(candidate[:10])
        except ValueError:
            continue
    return None


def meal_from(day: date, recipe: CookidooCalendarDayRecipe, servings: int) -> Meal:
    source = CUSTOM_SOURCE if recipe.is_custom else SOURCE
    return Meal(
        date=day,
        slot=MealSlot.DINNER,
        recipe_id=RecipeId(source=source, external_id=recipe.id),
        servings=servings,
    )
