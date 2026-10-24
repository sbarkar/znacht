from __future__ import annotations

import re
from decimal import Decimal
from enum import StrEnum

from pydantic import field_validator

from znacht.domain._base import Frozen


class Unit(StrEnum):
    G = "g"
    KG = "kg"
    ML = "ml"
    L = "l"
    PIECE = "piece"


_BASE: dict[Unit, tuple[Unit, Decimal]] = {
    Unit.G: (Unit.G, Decimal(1)),
    Unit.KG: (Unit.G, Decimal(1000)),
    Unit.ML: (Unit.ML, Decimal(1)),
    Unit.L: (Unit.ML, Decimal(1000)),
    Unit.PIECE: (Unit.PIECE, Decimal(1)),
}

_ALIASES: dict[str, Unit] = {
    "g": Unit.G,
    "gram": Unit.G,
    "grams": Unit.G,
    "kg": Unit.KG,
    "ml": Unit.ML,
    "l": Unit.L,
    "liter": Unit.L,
    "litre": Unit.L,
    "piece": Unit.PIECE,
    "pieces": Unit.PIECE,
    "pc": Unit.PIECE,
    "pcs": Unit.PIECE,
    "stk": Unit.PIECE,
    "x": Unit.PIECE,
}

_PATTERN = re.compile(r"^\s*(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>[a-zA-Z]+)?\s*$")


class Quantity(Frozen):
    """A non-negative amount with a unit. Mass and volume convert within their family."""

    value: Decimal
    unit: Unit

    @field_validator("value", mode="before")
    @classmethod
    def _coerce(cls, value: object) -> Decimal:
        result = Decimal(str(value))
        if result < 0:
            raise ValueError("quantity cannot be negative")
        return result

    @classmethod
    def of(cls, value: Decimal | int | float | str, unit: Unit | str) -> Quantity:
        return cls(value=Decimal(str(value)), unit=Unit(unit))

    @classmethod
    def parse(cls, text: str) -> Quantity:
        """Parse strings such as ``"500 g"``, ``"1.5kg"``, ``"2"`` (pieces), ``"3 pcs"``."""
        match = _PATTERN.match(text)
        if not match:
            raise ValueError(f"cannot parse quantity: {text!r}")
        value = Decimal(match.group("value").replace(",", "."))
        raw_unit = (match.group("unit") or "piece").lower()
        if raw_unit not in _ALIASES:
            raise ValueError(f"unknown unit in quantity: {text!r}")
        return cls(value=value, unit=_ALIASES[raw_unit])

    @property
    def base_unit(self) -> Unit:
        return _BASE[self.unit][0]

    @property
    def base_value(self) -> Decimal:
        unit, factor = _BASE[self.unit]
        del unit
        return self.value * factor

    def to_base(self) -> Quantity:
        return Quantity(value=self.base_value, unit=self.base_unit)

    def compatible(self, other: Quantity) -> bool:
        return self.base_unit == other.base_unit

    def _require_compatible(self, other: Quantity) -> None:
        if not self.compatible(other):
            raise ValueError(f"incompatible units: {self.unit} vs {other.unit}")

    def __add__(self, other: Quantity) -> Quantity:
        self._require_compatible(other)
        return Quantity(value=self.base_value + other.base_value, unit=self.base_unit)

    def minus(self, other: Quantity) -> Quantity:
        """Subtract, flooring at zero."""
        self._require_compatible(other)
        return Quantity(
            value=max(Decimal(0), self.base_value - other.base_value), unit=self.base_unit
        )

    def scale(self, factor: Decimal) -> Quantity:
        return Quantity(value=self.value * factor, unit=self.unit)

    def ratio(self, other: Quantity) -> Decimal:
        """How many ``other`` fit into ``self``."""
        self._require_compatible(other)
        if other.base_value == 0:
            raise ZeroDivisionError("ratio with a zero quantity")
        return self.base_value / other.base_value

    @property
    def is_zero(self) -> bool:
        return self.value == 0

    def __str__(self) -> str:
        return f"{self.value.normalize():f} {self.unit}"
