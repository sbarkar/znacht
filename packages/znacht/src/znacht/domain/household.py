from __future__ import annotations

from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from znacht.domain._base import Frozen
from znacht.domain.money import Money
from znacht.domain.quantity import Quantity
from znacht.domain.recipe import Category, normalise_name


class AgeGroup(StrEnum):
    ADULT = "adult"
    CHILD = "child"
    TODDLER = "toddler"


class Member(Frozen):
    name: str
    age_group: AgeGroup = AgeGroup.ADULT
    dislikes: frozenset[str] = frozenset()
    allergies: frozenset[str] = frozenset()
    mild_food: bool | None = None

    @field_validator("dislikes", "allergies", mode="before")
    @classmethod
    def _normalise(cls, value: object) -> frozenset[str]:
        if value is None:
            return frozenset()
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list | set | frozenset | tuple):
            raise TypeError("expected a list of names")
        return frozenset(normalise_name(str(v)) for v in value)

    @property
    def needs_mild_food(self) -> bool:
        if self.mild_food is not None:
            return self.mild_food
        return self.age_group == AgeGroup.TODDLER


class Rules(Frozen):
    """The weekly template. Counts apply to dinners unless stated otherwise."""

    dinners_per_week: int = 7
    min_tags: dict[str, int] = Field(default_factory=dict)
    max_tags: dict[str, int] = Field(default_factory=dict)
    banned_ingredients: frozenset[str] = frozenset()
    max_total_minutes_weekday: int | None = None
    max_repeats_per_week: int = 1

    @field_validator("banned_ingredients", mode="before")
    @classmethod
    def _normalise(cls, value: object) -> frozenset[str]:
        if value is None:
            return frozenset()
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list | set | frozenset | tuple):
            raise TypeError("expected a list of names")
        return frozenset(normalise_name(str(v)) for v in value)


class PantryItem(Frozen):
    name: str
    quantity: Quantity

    @field_validator("name")
    @classmethod
    def _normalise(cls, value: str) -> str:
        return normalise_name(value)


class Pantry(Frozen):
    items: tuple[PantryItem, ...] = ()

    def get(self, name: str) -> Quantity | None:
        needle = normalise_name(name)
        for item in self.items:
            if item.name == needle:
                return item.quantity
        return None

    def as_dict(self) -> dict[str, Quantity]:
        return {i.name: i.quantity for i in self.items}


class HealthMarker(Frozen):
    name: str
    value: float
    unit: str | None = None
    reference: str | None = None
    flag: str | None = None


class DietaryRule(Frozen):
    text: str
    tags: frozenset[str] = frozenset()


class HealthProfile(Frozen):
    markers: tuple[HealthMarker, ...] = ()
    rules: tuple[DietaryRule, ...] = ()
    confirmed: bool = True


class MakeAtHome(Frozen):
    """A dish the household makes rather than buys. Its need is replaced by the components."""

    dish: str
    components: tuple[tuple[str, Quantity], ...]

    @field_validator("dish")
    @classmethod
    def _normalise(cls, value: str) -> str:
        return normalise_name(value)


class StoreLists(Frozen):
    """Explicit list IDs. The store's "active list" changes whenever someone opens the app,
    so every call addresses a list by ID."""

    online: str
    in_store: str


class StorePolicy(Frozen):
    prefer_store_categories: frozenset[Category] = frozenset()
    prefer_store_when_cheaper_by: Money | None = None
    freezer_box_deposit: Money = Money.chf(20)


class DeliveryPrefs(Frozen):
    postcode: str
    preferred_slot_id: str | None = None


class Household(Frozen):
    id: str
    name: str
    members: tuple[Member, ...]
    rules: Rules = Rules()
    health: HealthProfile = HealthProfile()
    pantry: Pantry = Pantry()
    delivery: DeliveryPrefs
    store_lists: StoreLists | None = None
    store_policy: StorePolicy = StorePolicy()
    make_at_home: tuple[MakeAtHome, ...] = ()
    preferred_products: dict[str, str] = Field(default_factory=dict)
    free_text_items: tuple[str, ...] = ()
    default_servings: int | None = None

    @model_validator(mode="after")
    def _members(self) -> Household:
        if not self.members:
            raise ValueError("a household needs at least one member")
        return self

    @property
    def has_toddler(self) -> bool:
        return any(m.age_group == AgeGroup.TODDLER for m in self.members)

    @property
    def needs_mild_food(self) -> bool:
        return any(m.needs_mild_food for m in self.members)

    @property
    def allergies(self) -> frozenset[str]:
        return frozenset().union(*(m.allergies for m in self.members))

    @property
    def dislikes(self) -> frozenset[str]:
        return frozenset().union(*(m.dislikes for m in self.members))

    @property
    def servings(self) -> int:
        if self.default_servings is not None:
            return self.default_servings
        return len(self.members)
