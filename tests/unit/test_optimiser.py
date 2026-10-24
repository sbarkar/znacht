from datetime import date

from znacht.domain.needs import IngredientNeed
from znacht.domain.product import Channel
from znacht.domain.quantity import Quantity
from znacht.domain.recipe import Category
from znacht.services.optimiser import choose_product, health_rank
from znacht_memory.fixtures import products

P = {p.id: p for p in products()}
DAY = date(2026, 10, 28)


def _need(name: str, qty: str, category: Category) -> IngredientNeed:
    return IngredientNeed(name=name, quantity=Quantity.parse(qty), needed_on=DAY, category=category)


def test_health_rank_uses_the_category_metric():
    assert health_rank(P["p-yog-natural"]) < health_rank(P["p-yog-sweet"])  # sugar
    assert health_rank(P["p-beef-5"]) < health_rank(P["p-beef-15"])  # saturated fat
    assert health_rank(P["p-pasta-wg"]) < health_rank(P["p-pasta-white"])  # wholegrain
    assert health_rank(P["p-tom-nosalt"]) < health_rank(P["p-tom-chopped"])  # salt


def test_switch_when_healthier_or_equal_and_cheaper(household):
    choice = choose_product(
        _need("yogurt", "150 g", Category.YOGURT),
        [P["p-yog-sweet"], P["p-yog-natural"]],
        household,
        Channel.ONLINE,
        baseline=P["p-yog-sweet"],
    )
    assert choice is not None
    assert choice.product.id == "p-yog-natural"
    assert choice.switched
    assert choice.delta_vs_baseline is not None and choice.delta_vs_baseline.is_negative


def test_flag_but_keep_when_healthier_is_pricier(household):
    choice = choose_product(
        _need("pasta", "125 g", Category.GRAIN),
        [P["p-pasta-white"], P["p-pasta-wg"]],
        household,
        Channel.ONLINE,
        baseline=P["p-pasta-white"],
    )
    assert choice is not None
    assert choice.product.id == "p-pasta-white"
    assert not choice.switched
    assert choice.flagged
    assert choice.suggested_alternative is not None
    assert choice.suggested_alternative.id == "p-pasta-wg"
    assert str(choice.delta_vs_baseline) == "CHF 0.50"


def test_toddler_dairy_keeps_the_fat_level(household):
    assert household.has_toddler
    choice = choose_product(
        _need("milk", "100 ml", Category.DAIRY),
        [P["p-milk-whole"], P["p-milk-skim"]],
        household,
        Channel.STORE,
        baseline=P["p-milk-whole"],
    )
    assert choice is not None
    assert choice.product.id == "p-milk-whole"
    assert not choice.switched
    assert not choice.flagged


def test_without_baseline_pick_healthiest_then_cheapest(household):
    choice = choose_product(
        _need("tinned tomatoes", "600 g", Category.TINNED),
        [P["p-tom-chopped"], P["p-tom-nosalt"]],
        household,
        Channel.ONLINE,
    )
    assert choice is not None
    assert choice.product.id == "p-tom-nosalt"
    assert choice.packs == 2


def test_judged_by_line_total_not_pack_count(household):
    # 375 g of salmon: 2 x 225 g packs online
    choice = choose_product(
        _need("salmon", "375 g", Category.FISH), [P["p-salmon-pack"]], household, Channel.ONLINE
    )
    assert choice is not None
    assert choice.packs == 2
    assert str(choice.line_total()) == "CHF 19.80"


def test_cloves_are_counted_as_bulbs(household):
    from znacht.domain.money import Money
    from znacht.domain.product import Product, ProductId

    garlic = Product(
        id=ProductId("g"),
        name="Migros Garlic",
        store="memory",
        category=Category.PRODUCE,
        pack=Quantity.parse("1"),
        price_online=Money.chf("0.50"),
    )
    choice = choose_product(
        _need("garlic cloves", "12", Category.PRODUCE), [garlic], household, Channel.ONLINE
    )
    assert choice is not None and choice.packs == 2  # 12 cloves -> 2 bulbs, not 12
