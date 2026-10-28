from __future__ import annotations

from datetime import date
from decimal import Decimal

from znacht.domain._base import Frozen
from znacht.domain.delivery import DeliverySlot
from znacht.domain.household import PantryItem
from znacht.domain.money import Money, total
from znacht.domain.needs import IngredientNeed
from znacht.domain.product import Channel, Product, ProductId
from znacht.domain.quantity import Quantity


class ProductChoice(Frozen):
    """One line on a list: a product chosen for a need, with the reason.

    Every line traces back to the ``IngredientNeed`` keys it buys for, or carries a
    ``manual_reason`` (a household item, not a recipe need). A line with neither is an orphan
    and blocks approval (ADR-0016). ``split_reason`` says why the same ingredient is on both
    lists; without one, a product on both lists is a finding."""

    need_name: str
    product: Product
    packs: int
    needed_on: date
    channel: Channel
    reason: str
    baseline_product_id: ProductId | None = None
    switched: bool = False
    flagged: bool = False
    suggested_alternative: Product | None = None
    delta_vs_baseline: Money | None = None
    deliverable: bool | None = None
    movable: bool = False
    need_keys: tuple[str, ...] = ()
    need_quantity: Quantity | None = None  # the summed need the line buys for, before packs
    manual_reason: str | None = None
    split_reason: str | None = None

    @property
    def traceable(self) -> bool:
        return bool(self.need_keys) or bool(self.manual_reason)

    @property
    def bought(self) -> Quantity:
        """What the line puts in the kitchen: packs times pack size."""
        return self.product.pack.scale(Decimal(self.packs))

    def line_total(self, channel: Channel | None = None) -> Money:
        price = self.product.price(channel or self.channel)
        if price is None:
            raise ValueError(f"{self.product.name} has no price in {channel or self.channel}")
        coupons = total([c.discount for c in self.product.coupons], price.currency)
        line = price * self.packs - coupons
        return line if not line.is_negative else Money.zero(price.currency)


class ShoppingPlan(Frozen):
    slot: DeliverySlot | None
    online: tuple[ProductChoice, ...] = ()
    in_store: tuple[ProductChoice, ...] = ()
    free_text: tuple[str, ...] = ()
    pantry_check: tuple[str, ...] = ()  # staples the recipes assume you have; not bought
    minimum_order: Money = Money.zero()
    freezer_box_deposit: Money = Money.chf(20)
    # what reconciliation checks the lists against (ADR-0016): the week's needs after the
    # pantry, the pantry they were reduced by, and how many packs beyond need is a surplus
    needs: tuple[IngredientNeed, ...] = ()
    pantry: tuple[PantryItem, ...] = ()
    surplus_threshold_packs: Decimal = Decimal(1)

    @property
    def lines(self) -> tuple[ProductChoice, ...]:
        return (*self.online, *self.in_store)

    @property
    def online_subtotal(self) -> Money:
        return total([c.line_total() for c in self.online])

    @property
    def deposit(self) -> Money:
        return (
            self.freezer_box_deposit if any(c.product.frozen for c in self.online) else Money.zero()
        )

    @property
    def online_total(self) -> Money:
        return self.online_subtotal + self.deposit

    @property
    def meets_minimum(self) -> bool:
        return self.online_subtotal >= self.minimum_order

    @property
    def shortfall(self) -> Money:
        gap = self.minimum_order - self.online_subtotal
        return gap if not gap.is_negative else Money.zero()

    @property
    def in_store_total(self) -> Money:
        return total([c.line_total() for c in self.in_store])

    @property
    def switches(self) -> list[ProductChoice]:
        return [c for c in (*self.online, *self.in_store) if c.switched]

    @property
    def flags(self) -> list[ProductChoice]:
        return [c for c in (*self.online, *self.in_store) if c.flagged]

    @property
    def savings(self) -> Money:
        return -total(
            [c.delta_vs_baseline for c in self.switches if c.delta_vs_baseline is not None]
        )


class MinimumOrderReport(Frozen):
    moved_online: tuple[str, ...] = ()
    ask_household: Money | None = None
    met: bool = True
