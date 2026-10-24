"""Keyword categoriser shared by adapters whose catalogues carry no usable category.

A hint, not a fact: the household rules are enforced by the checker on recipe tags, and the
health filter only ever compares products within the same category.
"""

from __future__ import annotations

import re
from typing import Final

from znacht.domain.recipe import Category

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


def categorise(name: str) -> Category:
    lowered = name.lower()
    for category, words in _CATEGORY_KEYWORDS:
        if any(w in lowered for w in words):
            return category
    return Category.OTHER


WHOLEGRAIN_WORDS: Final = (
    "wholegrain",
    "whole grain",
    "wholemeal",
    "whole wheat",
    "vollkorn",
    "complet",
    "integrale",
)


def looks_wholegrain(name: str) -> bool:
    lowered = name.lower()
    return any(w in lowered for w in WHOLEGRAIN_WORDS)


STAPLE_WORDS: Final = (
    "salt",
    "salz",
    "pepper",
    "pfeffer",
    "water",
    "wasser",
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
    "baking powder",
    "backpulver",
    "cornflour",
    "cornstarch",
    "maizena",
    "soy sauce",
    "sojasauce",
    "honey",
    "honig",
    "mustard",
    "senf",
    "spice",
    "gewürz",
    "cumin",
    "coriander",
    "paprika",
    "cinnamon",
    "zimt",
    "nutmeg",
    "muskat",
    "oregano",
    "thyme",
    "thymian",
    "curry powder",
    "curry paste",
    "chilli flakes",
    "chili flakes",
    "turmeric",
    "kurkuma",
    "garam masala",
    "cacao",
    "cocoa",
    "kakao",
    "vanilla",
    "vanille",
    "ground ginger",
    "dried oregano",
    "dried thyme",
    "dried chillies",
    "dried chilli",
    "bay leaves",
)
_WORD = re.compile(r"[a-zäöüéèàç]+")


def looks_like_staple(name: str) -> bool:
    """Things a kitchen keeps: seasonings, oils, flour, stock. Not fresh herbs, pulses, dairy."""
    lowered = name.lower()
    if any(
        w in lowered for w in ("fresh", "frisch", "lentil", "linsen", "bean", "bohne", "potato")
    ):
        return False
    words = set(_WORD.findall(lowered))
    for staple in STAPLE_WORDS:
        parts = staple.split()
        if len(parts) == 1 and staple in words:
            return True
        if len(parts) > 1 and staple in lowered:
            return True
    return False
