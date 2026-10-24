from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import NewType

from znacht.domain._base import Frozen
from znacht.domain.money import Money
from znacht.domain.quantity import Quantity
from znacht.domain.recipe import Category

ProductId = NewType("ProductId", str)


class Channel(StrEnum):
    ONLINE = "online"
    STORE = "store"


class StockStatus(StrEnum):
    IN_STOCK = "in_stock"
    LOW = "low"
    OUT = "out"
    UNKNOWN = "unknown"


class Nutrition(Frozen):
    """Per 100 g or 100 ml. Missing values stay ``None``; they are never estimated."""

    energy_kcal: Decimal | None = None
    fat_g: Decimal | None = None
    saturated_fat_g: Decimal | None = None
    carbs_g: Decimal | None = None
    sugar_g: Decimal | None = None
    protein_g: Decimal | None = None
    salt_g: Decimal | None = None
    fibre_g: Decimal | None = None


class Promotion(Frozen):
    description: str
    price: Money
    valid_until: date | None = None


class Coupon(Frozen):
    id: str
    description: str
    discount: Money


class Deliverability(Frozen):
    product_id: ProductId
    deliverable: bool
    reason: str | None = None


class Product(Frozen):
    id: ProductId
    name: str
    store: str
    category: Category
    pack: Quantity
    brand: str | None = None
    price_online: Money | None = None
    price_store: Money | None = None
    nutrition: Nutrition | None = None
    wholegrain: bool | None = None
    frozen: bool = False
    staple: bool = False
    promotions: tuple[Promotion, ...] = ()
    coupons: tuple[Coupon, ...] = ()
    url: str | None = None

    def list_price(self, channel: Channel) -> Money | None:
        return self.price_online if channel == Channel.ONLINE else self.price_store

    def price(self, channel: Channel) -> Money | None:
        """Effective pack price in a channel: list price or best promotion, whichever is lower.
        A product with no offer in the asked channel is priced from the other one (an estimate:
        the Migros online assortment is sold in its shops too, usually cheaper)."""
        base = self.list_price(channel)
        if base is None:
            other = Channel.STORE if channel == Channel.ONLINE else Channel.ONLINE
            base = self.list_price(other)
        if base is None:
            return None
        promo = min((p.price for p in self.promotions), default=None)
        return promo if promo is not None and promo < base else base

    def unit_price(self, channel: Channel) -> Money | None:
        """Price per 100 g / 100 ml / 1 piece in a channel."""
        price = self.price(channel)
        if price is None or self.pack.base_value == 0:
            return None
        per = Decimal(100) if self.pack.base_unit != "piece" else Decimal(1)
        return Money(amount=price.amount * per / self.pack.base_value, currency=price.currency)
