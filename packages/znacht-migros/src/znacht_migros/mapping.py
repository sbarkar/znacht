"""Map Migros product-display JSON to the Znacht domain.

Each product has one *offer* per channel: ``storeType=OFFLINE`` is the in-store price,
``storeType=ONLINE`` the delivery price, often with a different pack size. The adapter
fetches both and keeps both on the product.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from znacht.domain.money import Money
from znacht.domain.product import Nutrition, Product, ProductId, Promotion
from znacht.domain.quantity import Quantity, Unit
from znacht.domain.recipe import Category
from znacht.services.categorise import categorise, looks_wholegrain

STORE = "migros"

_UNITS: Final[dict[str, tuple[Unit, Decimal]]] = {
    "g": (Unit.G, Decimal(1)),
    "kg": (Unit.KG, Decimal(1)),
    "ml": (Unit.ML, Decimal(1)),
    "cl": (Unit.ML, Decimal(10)),
    "dl": (Unit.ML, Decimal(100)),
    "l": (Unit.L, Decimal(1)),
}
_PACK = re.compile(
    r"^\s*(?:ca\.?\s*|approx\.?\s*|~\s*)?(?:(?P<mult>\d+)\s*[x×]\s*)?"
    r"(?P<a>\d+(?:[.,]\d+)?)(?:\s*[–\-]\s*(?P<b>\d+(?:[.,]\d+)?))?\s*(?P<unit>[a-zA-Zü]+)?\.?\s*$"
)
_BREADCRUMB: Final[tuple[tuple[str, Category], ...]] = (
    ("frozen", Category.FROZEN),
    ("tiefkühl", Category.FROZEN),
    ("surgel", Category.FROZEN),
    ("fruits & vegetables", Category.PRODUCE),
    ("früchte & gemüse", Category.PRODUCE),
    ("bread", Category.BAKERY),
    ("brot", Category.BAKERY),
    ("pasta", Category.GRAIN),
    ("rice", Category.GRAIN),
    ("cereal", Category.MUESLI),
    ("müesli", Category.MUESLI),
    ("canned", Category.TINNED),
    ("tinned", Category.TINNED),
    ("konserven", Category.TINNED),
)
_NUTRIENT_LABELS: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("saturated_fat_g", ("saturates", "saturated", "gesättigte", "saturés", "saturi")),
    ("sugar_g", ("sugars", "sugar", "zucker", "sucres", "zuccheri")),
    ("fat_g", ("fat", "fett", "matières grasses", "grassi")),
    ("carbs_g", ("carbohydrate", "kohlenhydrate", "glucides", "carboidrati")),
    ("protein_g", ("protein", "eiweiss", "eiweiß", "protéines", "proteine")),
    ("salt_g", ("salt", "salz", "sel", "sale")),
    ("fibre_g", ("fibre", "fiber", "ballaststoffe", "fibres", "fibre")),
    ("energy_kcal", ("energy", "energie", "énergie", "energia")),
)
_NUMBER = re.compile(r"(\d+(?:[.,]\d+)?)")


def _decimal(text: str) -> Decimal | None:
    try:
        return Decimal(text.replace(",", "."))
    except InvalidOperation:
        return None


def parse_pack(text: str | None) -> Quantity:
    """``"360 g"`` → 360 g; ``"6 x 125 g"`` → 750 g; ``"250–500 g"`` → 250 g (buy enough);
    ``"1 piece"`` / ``"2 Stück"`` → pieces; anything else → 1 piece."""
    if not text:
        return Quantity(value=Decimal(1), unit=Unit.PIECE)
    m = _PACK.match(text.strip())
    if not m:
        return Quantity(value=Decimal(1), unit=Unit.PIECE)
    value = _decimal(m.group("a"))
    if value is None:
        return Quantity(value=Decimal(1), unit=Unit.PIECE)
    if m.group("mult"):
        value *= Decimal(m.group("mult"))
    unit = (m.group("unit") or "").lower()
    if unit in _UNITS:
        u, factor = _UNITS[unit]
        return Quantity(value=value * factor, unit=u)
    return Quantity(value=value, unit=Unit.PIECE)


def parse_nutrition(info: Mapping[str, Any] | None) -> Nutrition | None:
    """Read the per-100 g nutrient table. Unknown rows are ignored; nothing is estimated."""
    if not info:
        return None
    table = info.get("nutrientsTableV2") or info.get("nutrientsTable") or {}
    rows = table.get("rows") or []
    values: dict[str, Decimal] = {}
    for row in rows:
        label = str(row.get("label", "")).lower()
        raw_values = row.get("values") or []
        if not raw_values:
            continue
        text = str(raw_values[0])
        for field, words in _NUTRIENT_LABELS:
            if field in values or not any(w in label for w in words):
                continue
            if field == "energy_kcal":
                m = re.search(r"(\d+(?:[.,]\d+)?)\s*kcal", text)
            else:
                m = _NUMBER.search(text)
            if m:
                number = _decimal(m.group(1))
                if number is not None:
                    values[field] = number
            break
    return Nutrition(**values) if values else None


def _price(offer: Mapping[str, Any] | None) -> tuple[Money | None, Promotion | None]:
    if not offer:
        return None, None
    price = offer.get("price") or {}
    advertised = price.get("advertisedValue")
    effective = price.get("effectiveValue")
    if effective is None and advertised is None:
        return None, None
    list_price = Money.chf(str(advertised if advertised is not None else effective))
    promo = None
    if (
        advertised is not None
        and effective is not None
        and Decimal(str(effective)) < Decimal(str(advertised))
    ):
        promo = Promotion(
            description=str(offer.get("type") or "promotion"), price=Money.chf(str(effective))
        )
    return list_price, promo


def _category(detail: Mapping[str, Any], name: str) -> Category:
    crumbs = " / ".join(str(c.get("name", "")) for c in detail.get("breadcrumb") or []).lower()
    by_name = categorise(name)
    if by_name != Category.OTHER:
        return by_name
    for needle, category in _BREADCRUMB:
        if needle in crumbs:
            return category
    return Category.OTHER


def availability_flag(detail: Mapping[str, Any]) -> str | None:
    value = detail.get("productAvailability")
    return str(value) if value else None


def product_from(online: Mapping[str, Any] | None, store: Mapping[str, Any] | None) -> Product:
    base = online or store
    if base is None:
        raise ValueError("no product detail in either channel")
    name = str(base.get("name") or base.get("title") or "")
    brand = base.get("brand")
    full_name = f"{brand} {name}".strip() if brand and brand.lower() not in name.lower() else name
    online_price, online_promo = _price((online or {}).get("offer"))
    store_price, store_promo = _price((store or {}).get("offer"))
    pack_text = ((online or {}).get("offer") or {}).get("quantity") or (
        (store or {}).get("offer") or {}
    ).get("quantity")
    info = base.get("productInformation") or {}
    category = _category(base, full_name)
    crumbs = " ".join(str(c.get("name", "")) for c in base.get("breadcrumb") or []).lower()
    promotions = tuple(p for p in (online_promo, store_promo) if p is not None)
    return Product(
        id=ProductId(str(base.get("uid"))),
        name=full_name,
        store=STORE,
        category=category,
        pack=parse_pack(pack_text),
        brand=str(brand) if brand else None,
        price_online=online_price,
        price_store=store_price,
        nutrition=parse_nutrition(info.get("nutrientsInformation")),
        wholegrain=looks_wholegrain(full_name) if category == Category.GRAIN else None,
        frozen=category == Category.FROZEN or "frozen" in crumbs or "tiefkühl" in crumbs,
        staple=category == Category.PANTRY,
        promotions=promotions,
        url=str(base.get("productUrls")) if base.get("productUrls") else None,
    )
