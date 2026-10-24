from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from pydantic import field_validator

from znacht.domain._base import Frozen

_CENT = Decimal("0.01")


class Money(Frozen):
    """An amount in one currency, rounded to cents. Arithmetic refuses to mix currencies."""

    amount: Decimal
    currency: str = "CHF"

    @field_validator("amount", mode="before")
    @classmethod
    def _quantize(cls, value: object) -> Decimal:
        return Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP)

    @classmethod
    def chf(cls, value: Decimal | int | float | str) -> Money:
        return cls(amount=Decimal(str(value)), currency="CHF")

    @classmethod
    def zero(cls, currency: str = "CHF") -> Money:
        return cls(amount=Decimal(0), currency=currency)

    def _check(self, other: Money) -> None:
        if other.currency != self.currency:
            raise ValueError(f"currency mismatch: {self.currency} vs {other.currency}")

    def __add__(self, other: Money) -> Money:
        self._check(other)
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def __sub__(self, other: Money) -> Money:
        self._check(other)
        return Money(amount=self.amount - other.amount, currency=self.currency)

    def __mul__(self, factor: int | Decimal) -> Money:
        return Money(amount=self.amount * Decimal(factor), currency=self.currency)

    def __neg__(self) -> Money:
        return Money(amount=-self.amount, currency=self.currency)

    def __lt__(self, other: Money) -> bool:
        self._check(other)
        return self.amount < other.amount

    def __le__(self, other: Money) -> bool:
        self._check(other)
        return self.amount <= other.amount

    def __gt__(self, other: Money) -> bool:
        self._check(other)
        return self.amount > other.amount

    def __ge__(self, other: Money) -> bool:
        self._check(other)
        return self.amount >= other.amount

    @property
    def is_zero(self) -> bool:
        return self.amount == 0

    @property
    def is_negative(self) -> bool:
        return self.amount < 0

    def __str__(self) -> str:
        return f"{self.currency} {self.amount:.2f}"


def total(amounts: list[Money] | tuple[Money, ...], currency: str = "CHF") -> Money:
    result = Money.zero(currency)
    for amount in amounts:
        result = result + amount
    return result
