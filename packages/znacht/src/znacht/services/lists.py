from __future__ import annotations

from collections.abc import Iterable

from znacht.domain.diff import ShoppingList, ShoppingListLine
from znacht.domain.product import ProductId
from znacht.domain.shopping import ProductChoice


def shopping_list_from(
    list_id: str, choices: Iterable[ProductChoice], free_text: Iterable[str] = ()
) -> ShoppingList:
    """Collapse choices into list lines keyed by product, plus free-text lines."""
    packs: dict[str, int] = {}
    order: list[str] = []
    for c in choices:
        if c.product.id not in packs:
            order.append(c.product.id)
        packs[c.product.id] = packs.get(c.product.id, 0) + c.packs
    lines = [ShoppingListLine(product_id=ProductId(c), quantity=packs[c]) for c in order]
    lines += [ShoppingListLine(text=t) for t in free_text]
    return ShoppingList(id=list_id, lines=tuple(lines))
