"""The golden-week fixture: a small recipe catalogue and a small store catalogue.

Swiss-flavoured prices, deliberately shaped to exercise every rule: non-deliverable
fresh items, online vs in-store prices, pack sizes, a frozen item (box deposit), a
sugary vs natural yogurt (switch), white vs wholegrain pasta (flag), whole vs skimmed milk
(toddler fat-level guard), a dill recipe (banned) and a hot curry (toddler-mild).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from znacht.domain.delivery import DeliverySlot
from znacht.domain.diff import ShoppingListRef
from znacht.domain.money import Money
from znacht.domain.product import Nutrition, Product, ProductId, Promotion
from znacht.domain.quantity import Quantity
from znacht.domain.recipe import Category, Ingredient, Recipe, RecipeId, Spiciness, Tag
from znacht_memory.recipes import MemoryRecipeSource
from znacht_memory.store import MemoryGroceryStore

SOURCE = "memory"
STORE = "memory"
POSTCODE = "8000"
ONLINE_LIST = "list-online"
IN_STORE_LIST = "list-store"
GOLDEN_WEEK_START = date(2026, 10, 26)  # a Monday


def rid(external_id: str) -> RecipeId:
    return RecipeId(source=SOURCE, external_id=external_id)


def _i(
    name: str, qty: str, category: Category = Category.OTHER, *, staple: bool = False
) -> Ingredient:
    return Ingredient(name=name, quantity=Quantity.parse(qty), category=category, staple=staple)


C = Category


def recipes() -> list[Recipe]:
    return [
        Recipe(
            id=rid("salmon-tray"),
            title="Salmon tray bake",
            servings=4,
            ingredients=(
                _i("salmon", "500 g", C.FISH),
                _i("potatoes", "800 g", C.PRODUCE),
                _i("broccoli", "400 g", C.PRODUCE),
                _i("cherry tomatoes", "250 g", C.PRODUCE),
                _i("feta", "150 g", C.DAIRY),
                _i("lemon", "1", C.PRODUCE),
                _i("olive oil", "30 ml", C.PANTRY, staple=True),
            ),
            tags=frozenset({Tag.FISH, Tag.FAMILY}),
            total_minutes=35,
            rating=4.6,
        ),
        Recipe(
            id=rid("fish-curry"),
            title="Mild fish curry",
            servings=4,
            ingredients=(
                _i("white fish", "500 g", C.FISH),
                _i("coconut milk", "400 ml", C.TINNED),
                _i("rice", "300 g", C.GRAIN, staple=True),
                _i("spinach", "200 g", C.PRODUCE),
                _i("ginger", "20 g", C.PRODUCE),
                _i("onion", "1", C.PRODUCE),
            ),
            tags=frozenset({Tag.FISH}),
            total_minutes=40,
            rating=4.3,
            spiciness=Spiciness.MILD,
        ),
        Recipe(
            id=rid("beef-ragu"),
            title="Beef ragù",
            servings=4,
            ingredients=(
                _i("minced beef", "500 g", C.MEAT),
                _i("pasta", "500 g", C.GRAIN),
                _i("tinned tomatoes", "800 g", C.TINNED),
                _i("red wine", "200 ml", C.OTHER),
                _i("onion", "1", C.PRODUCE),
                _i("carrot", "2", C.PRODUCE),
                _i("parmesan", "50 g", C.DAIRY),
            ),
            tags=frozenset({Tag.RED_MEAT}),
            total_minutes=60,
            rating=4.7,
        ),
        Recipe(
            id=rid("lentil-dal"),
            title="Red lentil dal",
            servings=4,
            ingredients=(
                _i("red lentils", "300 g", C.LEGUME),
                _i("coconut milk", "400 ml", C.TINNED),
                _i("tinned tomatoes", "400 g", C.TINNED),
                _i("peas", "200 g", C.FROZEN),
                _i("rice", "300 g", C.GRAIN, staple=True),
                _i("onion", "1", C.PRODUCE),
                _i("ginger", "20 g", C.PRODUCE),
            ),
            tags=frozenset({Tag.LEGUMES, Tag.VEGETARIAN, Tag.FAMILY}),
            total_minutes=35,
            rating=4.4,
            spiciness=Spiciness.MILD,
        ),
        Recipe(
            id=rid("chickpea-stew"),
            title="Chickpea and spinach stew",
            servings=4,
            ingredients=(
                _i("chickpeas", "800 g", C.TINNED),
                _i("tinned tomatoes", "400 g", C.TINNED),
                _i("spinach", "200 g", C.PRODUCE),
                _i("feta", "150 g", C.DAIRY),
                _i("bread", "1", C.BAKERY),
                _i("yogurt", "200 g", C.YOGURT),
            ),
            tags=frozenset({Tag.LEGUMES, Tag.VEGETARIAN}),
            total_minutes=30,
            rating=4.2,
        ),
        Recipe(
            id=rid("chicken-rice"),
            title="Chicken with rice and broccoli",
            servings=4,
            ingredients=(
                _i("chicken breast", "600 g", C.POULTRY),
                _i("rice", "300 g", C.GRAIN, staple=True),
                _i("broccoli", "400 g", C.PRODUCE),
                _i("milk", "100 ml", C.DAIRY),
                _i("soy sauce", "30 ml", C.PANTRY, staple=True),
            ),
            tags=frozenset({Tag.POULTRY, Tag.FAMILY}),
            total_minutes=40,
            rating=4.5,
        ),
        Recipe(
            id=rid("hummus-bowls"),
            title="Hummus bowls",
            servings=4,
            ingredients=(
                _i("hummus", "400 g", C.OTHER),
                _i("bread", "2", C.BAKERY),
                _i("cucumber", "1", C.PRODUCE),
                _i("carrot", "2", C.PRODUCE),
                _i("yogurt", "200 g", C.YOGURT),
            ),
            tags=frozenset({Tag.LEGUMES, Tag.VEGETARIAN, Tag.FAMILY}),
            total_minutes=25,
            rating=4.6,
        ),
        Recipe(
            id=rid("veg-pasta"),
            title="Pasta with pesto and tomatoes",
            servings=4,
            ingredients=(
                _i("pasta", "500 g", C.GRAIN),
                _i("pesto", "150 g", C.OTHER),
                _i("cherry tomatoes", "250 g", C.PRODUCE),
                _i("parmesan", "50 g", C.DAIRY),
            ),
            tags=frozenset({Tag.VEGETARIAN, Tag.FAMILY}),
            total_minutes=20,
            rating=4.1,
        ),
        Recipe(
            id=rid("mushroom-risotto"),
            title="Mushroom risotto",
            servings=4,
            ingredients=(
                _i("risotto rice", "300 g", C.GRAIN),
                _i("mushrooms", "400 g", C.PRODUCE),
                _i("parmesan", "60 g", C.DAIRY),
                _i("butter", "50 g", C.DAIRY),
                _i("onion", "1", C.PRODUCE),
            ),
            tags=frozenset({Tag.VEGETARIAN}),
            total_minutes=45,
            rating=4.3,
        ),
        Recipe(
            id=rid("omelette"),
            title="Omelette with salad",
            servings=4,
            ingredients=(
                _i("eggs", "8", C.OTHER),
                _i("milk", "100 ml", C.DAIRY),
                _i("lettuce", "1", C.PRODUCE),
                _i("bread", "1", C.BAKERY),
            ),
            tags=frozenset({Tag.VEGETARIAN}),
            total_minutes=15,
            rating=3.8,
        ),
        Recipe(
            id=rid("pork-schnitzel"),
            title="Pork schnitzel",
            servings=4,
            ingredients=(
                _i("pork escalope", "600 g", C.MEAT),
                _i("breadcrumbs", "100 g", C.PANTRY, staple=True),
                _i("eggs", "2", C.OTHER),
                _i("potatoes", "800 g", C.PRODUCE),
            ),
            tags=frozenset({Tag.RED_MEAT}),
            total_minutes=35,
            rating=4.5,
        ),
        Recipe(
            id=rid("dill-salmon"),
            title="Salmon with dill sauce",
            servings=4,
            ingredients=(
                _i("salmon", "500 g", C.FISH),
                _i("dill", "20 g", C.HERB),
                _i("cream", "200 ml", C.DAIRY),
                _i("potatoes", "800 g", C.PRODUCE),
            ),
            tags=frozenset({Tag.FISH}),
            total_minutes=30,
            rating=4.8,
        ),
        Recipe(
            id=rid("thai-curry"),
            title="Thai red chicken curry",
            servings=4,
            ingredients=(
                _i("chicken breast", "600 g", C.POULTRY),
                _i("red curry paste", "60 g", C.OTHER),
                _i("coconut milk", "400 ml", C.TINNED),
                _i("rice", "300 g", C.GRAIN, staple=True),
            ),
            tags=frozenset({Tag.POULTRY}),
            total_minutes=30,
            rating=4.9,
            spiciness=Spiciness.HOT,
        ),
    ]


def _p(
    pid: str,
    name: str,
    category: Category,
    pack: str,
    *,
    online: str | None,
    store: str | None,
    nutrition: Nutrition | None = None,
    wholegrain: bool | None = None,
    frozen: bool = False,
    staple: bool = False,
    promotions: tuple[Promotion, ...] = (),
) -> Product:
    return Product(
        id=ProductId(pid),
        name=name,
        store=STORE,
        category=category,
        pack=Quantity.parse(pack),
        price_online=Money.chf(online) if online is not None else None,
        price_store=Money.chf(store) if store is not None else None,
        nutrition=nutrition,
        wholegrain=wholegrain,
        frozen=frozen,
        staple=staple,
        promotions=promotions,
    )


def _n(**kwargs: str) -> Nutrition:
    return Nutrition(**{k: Decimal(v) for k, v in kwargs.items()})


def products() -> list[Product]:
    return [
        # fish: online in ~225 g packs, in-store per 100 g at the counter
        _p("p-salmon-pack", "Salmon fillet 225 g", C.FISH, "225 g", online="9.90", store=None),
        _p("p-salmon-counter", "Salmon fillet counter", C.FISH, "100 g", online=None, store="3.90"),
        _p("p-whitefish", "White fish fillets MSC", C.FISH, "300 g", online="8.50", store="8.50"),
        # meat: two fat levels; lean is healthier but pricier
        _p(
            "p-beef-15",
            "Minced beef 15% fat",
            C.MEAT,
            "370 g",
            online="6.90",
            store="6.90",
            nutrition=_n(fat_g="15", saturated_fat_g="6.5"),
        ),
        _p(
            "p-beef-5",
            "Minced beef lean 5% fat",
            C.MEAT,
            "370 g",
            online="7.90",
            store="7.90",
            nutrition=_n(fat_g="5", saturated_fat_g="2.1"),
        ),
        _p(
            "p-pork",
            "Pork escalope",
            C.MEAT,
            "600 g",
            online="12.50",
            store="12.50",
            nutrition=_n(saturated_fat_g="2.0"),
        ),
        _p(
            "p-chicken",
            "Chicken breast",
            C.POULTRY,
            "600 g",
            online="11.90",
            store="11.90",
            nutrition=_n(saturated_fat_g="0.5"),
        ),
        # dairy and yogurt
        _p(
            "p-milk-whole",
            "Milk whole 1 l",
            C.DAIRY,
            "1 l",
            online="1.75",
            store="1.75",
            nutrition=_n(fat_g="3.5", saturated_fat_g="2.3"),
        ),
        _p(
            "p-milk-skim",
            "Milk skimmed 1 l",
            C.DAIRY,
            "1 l",
            online="1.55",
            store="1.55",
            nutrition=_n(fat_g="0.1", saturated_fat_g="0.1"),
        ),
        _p(
            "p-feta",
            "Feta 150 g",
            C.DAIRY,
            "150 g",
            online="3.50",
            store="3.50",
            nutrition=_n(fat_g="22", saturated_fat_g="15"),
        ),
        _p(
            "p-parmesan",
            "Parmesan grated 100 g",
            C.DAIRY,
            "100 g",
            online="5.90",
            store="5.90",
            nutrition=_n(fat_g="28", saturated_fat_g="19"),
        ),
        _p(
            "p-butter",
            "Butter 200 g",
            C.DAIRY,
            "200 g",
            online="3.20",
            store="3.20",
            nutrition=_n(fat_g="82", saturated_fat_g="52"),
        ),
        _p(
            "p-cream",
            "Cream 200 ml",
            C.DAIRY,
            "200 ml",
            online="2.40",
            store="2.40",
            nutrition=_n(fat_g="35", saturated_fat_g="23"),
        ),
        _p(
            "p-yog-sweet",
            "Yogurt strawberry 180 g",
            C.YOGURT,
            "180 g",
            online="2.20",
            store="2.20",
            nutrition=_n(fat_g="3.0", sugar_g="12.5"),
        ),
        _p(
            "p-yog-natural",
            "Yogurt natural 3.5% 180 g",
            C.YOGURT,
            "180 g",
            online="1.80",
            store="1.80",
            nutrition=_n(fat_g="3.5", sugar_g="4.5"),
        ),
        # grains: white pasta is CHF 1.20 in-store and 2.40 online; wholegrain is pricier
        _p(
            "p-pasta-white",
            "Pasta spaghetti 500 g",
            C.GRAIN,
            "500 g",
            online="2.40",
            store="1.20",
            wholegrain=False,
        ),
        _p(
            "p-pasta-wg",
            "Pasta wholegrain spaghetti 500 g",
            C.GRAIN,
            "500 g",
            online="2.90",
            store="1.60",
            wholegrain=True,
        ),
        _p(
            "p-rice",
            "Rice basmati 1 kg",
            C.GRAIN,
            "1 kg",
            online="4.50",
            store="4.50",
            wholegrain=False,
            staple=True,
        ),
        _p(
            "p-risotto",
            "Risotto rice 1 kg",
            C.GRAIN,
            "1 kg",
            online="4.90",
            store="4.90",
            wholegrain=False,
        ),
        # tins: salt levels
        _p(
            "p-tom-chopped",
            "Tinned tomatoes chopped 400 g",
            C.TINNED,
            "400 g",
            online="1.60",
            store="1.20",
            nutrition=_n(salt_g="0.5"),
        ),
        _p(
            "p-tom-nosalt",
            "Tinned tomatoes no added salt 400 g",
            C.TINNED,
            "400 g",
            online="1.70",
            store="1.40",
            nutrition=_n(salt_g="0.1"),
        ),
        _p(
            "p-coconut",
            "Coconut milk 400 ml",
            C.TINNED,
            "400 ml",
            online="2.20",
            store="2.20",
            nutrition=_n(salt_g="0.1"),
        ),
        _p(
            "p-chickpeas-salt",
            "Chickpeas tinned 400 g",
            C.TINNED,
            "400 g",
            online="1.30",
            store="1.30",
            nutrition=_n(salt_g="0.9"),
        ),
        _p(
            "p-chickpeas-nosalt",
            "Chickpeas tinned no added salt 400 g",
            C.TINNED,
            "400 g",
            online="1.50",
            store="1.50",
            nutrition=_n(salt_g="0.2"),
        ),
        # legumes and pantry
        _p("p-lentils", "Red lentils 500 g", C.LEGUME, "500 g", online="3.20", store="3.20"),
        _p("p-tahini", "Tahini 250 g", C.OTHER, "250 g", online="5.50", store="5.50"),
        _p("p-hummus", "Hummus 200 g", C.OTHER, "200 g", online="2.90", store="2.90"),
        _p("p-pesto", "Pesto genovese 190 g", C.OTHER, "190 g", online="3.90", store="3.90"),
        _p(
            "p-soy",
            "Soy sauce 150 ml",
            C.PANTRY,
            "150 ml",
            online="2.80",
            store="2.80",
            staple=True,
        ),
        _p(
            "p-oil",
            "Olive oil 500 ml",
            C.PANTRY,
            "500 ml",
            online="8.90",
            store="8.90",
            staple=True,
        ),
        _p("p-wine", "Red wine cooking 750 ml", C.OTHER, "750 ml", online="6.90", store="6.90"),
        _p("p-eggs", "Eggs free range 10", C.OTHER, "10", online="5.20", store="5.20"),
        _p("p-curry", "Red curry paste 100 g", C.OTHER, "100 g", online="3.40", store="3.40"),
        # produce: several are not deliverable to this postcode
        _p("p-potatoes", "Potatoes 1 kg", C.PRODUCE, "1 kg", online="2.90", store="2.90"),
        _p("p-broccoli", "Broccoli 500 g", C.PRODUCE, "500 g", online="3.40", store="3.40"),
        _p("p-lemon", "Lemon", C.PRODUCE, "1", online="0.90", store="0.90"),
        _p("p-ginger", "Ginger root 100 g", C.PRODUCE, "100 g", online="1.60", store="1.60"),
        _p("p-spinach", "Spinach fresh 200 g", C.PRODUCE, "200 g", online="3.20", store="3.20"),
        _p("p-cherry", "Cherry tomatoes 250 g", C.PRODUCE, "250 g", online="4.50", store="4.50"),
        _p("p-onion", "Onions 1 kg", C.PRODUCE, "8", online="2.50", store="2.50"),
        _p("p-carrot", "Carrots 1 kg", C.PRODUCE, "10", online="2.20", store="2.20"),
        _p("p-cucumber", "Cucumber", C.PRODUCE, "1", online="1.50", store="1.50"),
        _p("p-mushrooms", "Mushrooms 250 g", C.PRODUCE, "250 g", online="3.60", store="3.60"),
        _p("p-lettuce", "Lettuce", C.PRODUCE, "1", online="2.20", store="2.20"),
        _p("p-bread", "Bread sourdough", C.BAKERY, "1", online="4.20", store="4.20"),
        _p("p-dill", "Dill fresh", C.HERB, "20 g", online="2.50", store="2.50"),
        _p(
            "p-peas",
            "Peas frozen 750 g",
            C.FROZEN,
            "750 g",
            online="3.20",
            store="3.20",
            frozen=True,
        ),
    ]


NON_DELIVERABLE: dict[str, list[ProductId]] = {
    POSTCODE: [
        ProductId(p)
        for p in (
            "p-potatoes",
            "p-broccoli",
            "p-lemon",
            "p-ginger",
            "p-bread",
            "p-dill",
            "p-spinach",
        )
    ]
}


def slots() -> dict[str, list[DeliverySlot]]:
    monday = GOLDEN_WEEK_START
    return {
        POSTCODE: [
            DeliverySlot(
                id="mon-19-21",
                start=datetime(monday.year, monday.month, monday.day, 19, 0),
                end=datetime(monday.year, monday.month, monday.day, 21, 0),
                cutoff=datetime(monday.year, monday.month, monday.day, 0, 0),
                price=Money.chf("9.90"),
            ),
            DeliverySlot(
                id="wed-08-10",
                start=datetime(monday.year, monday.month, monday.day + 2, 8, 0),
                end=datetime(monday.year, monday.month, monday.day + 2, 10, 0),
            ),
        ]
    }


def recipe_source() -> MemoryRecipeSource:
    return MemoryRecipeSource(recipes())


def grocery_store() -> MemoryGroceryStore:
    return MemoryGroceryStore(
        products(),
        lists=[
            ShoppingListRef(id=ONLINE_LIST, name="Online basket", kind="online"),
            ShoppingListRef(id=IN_STORE_LIST, name="In store", kind="in_store"),
        ],
        slots=slots(),
        minimum_order=Money.chf(99),
        non_deliverable=NON_DELIVERABLE,
        search_terms={
            ProductId("p-tom-chopped"): ["tinned tomatoes"],
            ProductId("p-tom-nosalt"): ["tinned tomatoes"],
            ProductId("p-onion"): ["onion"],
            ProductId("p-carrot"): ["carrot"],
            ProductId("p-whitefish"): ["white fish"],
        },
    )
