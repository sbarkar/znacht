"""Household YAML: one file per household, human-editable, validated with pydantic."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from znacht.domain.household import (
    AgeGroup,
    DeliveryPrefs,
    DietaryRule,
    HealthMarker,
    HealthProfile,
    Household,
    MakeAtHome,
    Member,
    Pantry,
    PantryItem,
    Rules,
    SlotTemplate,
    StoreLists,
    StorePolicy,
)
from znacht.domain.money import Money
from znacht.domain.quantity import Quantity
from znacht.domain.recipe import Category


class _Cfg(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MemberConfig(_Cfg):
    name: str
    age_group: AgeGroup = AgeGroup.ADULT
    dislikes: list[str] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)
    mild_food: bool | None = None


class RulesConfig(_Cfg):
    dinners_per_week: int = 7
    min_per_week: dict[str, int] = Field(default_factory=dict)
    max_per_week: dict[str, int] = Field(default_factory=dict)
    banned_ingredients: list[str] = Field(default_factory=list)
    max_total_minutes_weekday: int | None = None
    max_repeats_per_week: int = 1


class HealthMarkerConfig(_Cfg):
    value: float
    unit: str | None = None
    reference: str | None = None
    flag: str | None = None


class HealthConfig(_Cfg):
    markers: dict[str, HealthMarkerConfig] = Field(default_factory=dict)
    rules: list[str] = Field(default_factory=list)


class SlotTemplateConfig(_Cfg):
    id: str
    weekday: int
    start: str
    end: str


class DeliveryConfig(_Cfg):
    postcode: str
    preferred_slot_id: str | None = None
    slot_templates: list[SlotTemplateConfig] = Field(default_factory=list)


class StoreListsConfig(_Cfg):
    online: str
    in_store: str


class StorePolicyConfig(_Cfg):
    prefer_store_categories: list[Category] = Field(default_factory=list)
    prefer_store_when_cheaper_by: Decimal | None = None
    freezer_box_deposit: Decimal = Decimal(20)


class HouseholdConfig(_Cfg):
    id: str
    name: str
    members: list[MemberConfig]
    rules: RulesConfig = RulesConfig()
    health: HealthConfig = HealthConfig()
    pantry: dict[str, str | int | float] = Field(default_factory=dict)
    delivery: DeliveryConfig
    store_lists: StoreListsConfig | None = None
    store_policy: StorePolicyConfig = StorePolicyConfig()
    make_at_home: dict[str, dict[str, str | int | float]] = Field(default_factory=dict)
    preferred_products: dict[str, str] = Field(default_factory=dict)
    free_text_items: list[str] = Field(default_factory=list)
    default_servings: int | None = None

    def to_household(self) -> Household:
        return Household(
            id=self.id,
            name=self.name,
            members=tuple(
                Member(
                    name=m.name,
                    age_group=m.age_group,
                    dislikes=frozenset(m.dislikes),
                    allergies=frozenset(m.allergies),
                    mild_food=m.mild_food,
                )
                for m in self.members
            ),
            rules=Rules(
                dinners_per_week=self.rules.dinners_per_week,
                min_tags=dict(self.rules.min_per_week),
                max_tags=dict(self.rules.max_per_week),
                banned_ingredients=frozenset(self.rules.banned_ingredients),
                max_total_minutes_weekday=self.rules.max_total_minutes_weekday,
                max_repeats_per_week=self.rules.max_repeats_per_week,
            ),
            health=HealthProfile(
                markers=tuple(
                    HealthMarker(
                        name=k, value=v.value, unit=v.unit, reference=v.reference, flag=v.flag
                    )
                    for k, v in self.health.markers.items()
                ),
                rules=tuple(DietaryRule(text=t) for t in self.health.rules),
            ),
            pantry=Pantry(
                items=tuple(
                    PantryItem(name=k, quantity=Quantity.parse(str(v)))
                    for k, v in self.pantry.items()
                )
            ),
            delivery=DeliveryPrefs(
                postcode=self.delivery.postcode,
                preferred_slot_id=self.delivery.preferred_slot_id,
                slot_templates=tuple(
                    SlotTemplate(id=t.id, weekday=t.weekday, start=t.start, end=t.end)
                    for t in self.delivery.slot_templates
                ),
            ),
            store_lists=(
                StoreLists(online=self.store_lists.online, in_store=self.store_lists.in_store)
                if self.store_lists
                else None
            ),
            store_policy=StorePolicy(
                prefer_store_categories=frozenset(self.store_policy.prefer_store_categories),
                prefer_store_when_cheaper_by=(
                    Money.chf(self.store_policy.prefer_store_when_cheaper_by)
                    if self.store_policy.prefer_store_when_cheaper_by is not None
                    else None
                ),
                freezer_box_deposit=Money.chf(self.store_policy.freezer_box_deposit),
            ),
            make_at_home=tuple(
                MakeAtHome(
                    dish=dish,
                    components=tuple((name, Quantity.parse(str(q))) for name, q in parts.items()),
                )
                for dish, parts in self.make_at_home.items()
            ),
            preferred_products=dict(self.preferred_products),
            free_text_items=tuple(self.free_text_items),
            default_servings=self.default_servings,
        )


def parse_household(text: str) -> Household:
    raw = yaml.safe_load(text)
    if not isinstance(raw, dict):
        raise ValueError("household config must be a mapping")
    return HouseholdConfig.model_validate(raw).to_household()


def load_household(path: str | Path) -> Household:
    return parse_household(Path(path).read_text(encoding="utf-8"))
