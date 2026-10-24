from __future__ import annotations

from typing import Literal

from znacht.domain._base import Frozen
from znacht.domain.plan import Meal, Week
from znacht.domain.product import ProductId


class ShoppingListRef(Frozen):
    id: str
    name: str
    kind: Literal["online", "in_store", "other"] = "other"


class ShoppingListLine(Frozen):
    quantity: int = 1
    product_id: ProductId | None = None
    text: str | None = None
    availability: str | None = None  # the store's feedback, e.g. INSUFFICIENT_STOCK

    @property
    def key(self) -> str:
        return f"p:{self.product_id}" if self.product_id is not None else f"t:{self.text}"


class ShoppingList(Frozen):
    id: str
    lines: tuple[ShoppingListLine, ...] = ()

    def as_dict(self) -> dict[str, ShoppingListLine]:
        return {line.key: line for line in self.lines}


class ListLineDiff(Frozen):
    op: Literal["add", "remove", "change"]
    line: ShoppingListLine
    previous_quantity: int | None = None


class ListDiff(Frozen):
    list_id: str
    lines: tuple[ListLineDiff, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.lines

    def inverse(self) -> ListDiff:
        """The diff that undoes this one: adds become removes, removes become adds,
        quantity changes go back to the previous quantity."""
        out: list[ListLineDiff] = []
        for change in self.lines:
            if change.op == "add":
                out.append(
                    ListLineDiff(
                        op="remove", line=change.line, previous_quantity=change.line.quantity
                    )
                )
            elif change.op == "remove":
                out.append(ListLineDiff(op="add", line=change.line))
            else:
                previous = change.previous_quantity if change.previous_quantity is not None else 1
                out.append(
                    ListLineDiff(
                        op="change",
                        line=change.line.model_copy(update={"quantity": previous}),
                        previous_quantity=change.line.quantity,
                    )
                )
        return ListDiff(list_id=self.list_id, lines=tuple(out))


def diff_lists(current: ShoppingList, target: ShoppingList) -> ListDiff:
    """Pure diff between two lists, keyed by product ID or free text."""
    before = current.as_dict()
    after = target.as_dict()
    lines: list[ListLineDiff] = []
    for key, line in after.items():
        if key not in before:
            lines.append(ListLineDiff(op="add", line=line))
        elif before[key].quantity != line.quantity:
            lines.append(
                ListLineDiff(op="change", line=line, previous_quantity=before[key].quantity)
            )
    for key, line in before.items():
        if key not in after:
            lines.append(ListLineDiff(op="remove", line=line, previous_quantity=line.quantity))
    return ListDiff(list_id=target.id, lines=tuple(lines))


class PlanDiff(Frozen):
    week: Week
    add: tuple[Meal, ...] = ()
    remove: tuple[Meal, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.add and not self.remove

    def inverse(self) -> PlanDiff:
        """The diff that undoes this one."""
        return PlanDiff(week=self.week, add=self.remove, remove=self.add)


class ApplyResult(Frozen):
    ok: bool
    message: str = ""
    applied: int = 0
