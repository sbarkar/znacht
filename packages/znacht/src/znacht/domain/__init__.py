"""Core domain model. Every type here is an immutable pydantic model."""

from znacht.domain.delivery import DeliverySlot
from znacht.domain.diff import (
    ApplyResult,
    ListDiff,
    ListLineDiff,
    PlanDiff,
    ShoppingList,
    ShoppingListLine,
    ShoppingListRef,
)
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
from znacht.domain.needs import IngredientNeed
from znacht.domain.plan import Meal, MealPlan, MealSlot, Week
from znacht.domain.product import (
    Channel,
    Coupon,
    Deliverability,
    Nutrition,
    Product,
    ProductId,
    Promotion,
    StockStatus,
)
from znacht.domain.quantity import Quantity, Unit
from znacht.domain.recipe import Category, Ingredient, Recipe, RecipeId, Spiciness, Tag
from znacht.domain.reconcile import Finding, FindingKind, Override
from znacht.domain.shopping import MinimumOrderReport, ProductChoice, ShoppingPlan
from znacht.domain.violations import Violation

__all__ = [
    "AgeGroup",
    "ApplyResult",
    "Category",
    "Channel",
    "Coupon",
    "Deliverability",
    "DeliveryPrefs",
    "DeliverySlot",
    "DietaryRule",
    "Finding",
    "FindingKind",
    "HealthMarker",
    "HealthProfile",
    "Household",
    "Ingredient",
    "IngredientNeed",
    "ListDiff",
    "ListLineDiff",
    "MakeAtHome",
    "Meal",
    "MealPlan",
    "MealSlot",
    "Member",
    "MinimumOrderReport",
    "Money",
    "Nutrition",
    "Override",
    "Pantry",
    "PantryItem",
    "PlanDiff",
    "Product",
    "ProductChoice",
    "ProductId",
    "Promotion",
    "Quantity",
    "Recipe",
    "RecipeId",
    "Rules",
    "ShoppingList",
    "ShoppingListLine",
    "ShoppingListRef",
    "ShoppingPlan",
    "SlotTemplate",
    "Spiciness",
    "StockStatus",
    "StoreLists",
    "StorePolicy",
    "Tag",
    "Unit",
    "Violation",
    "Week",
]
