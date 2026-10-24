from __future__ import annotations

from typing import Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

from znacht.domain._base import Frozen
from znacht.domain.household import Household
from znacht.domain.plan import MealPlan, Week
from znacht.domain.recipe import Recipe
from znacht.domain.violations import Violation

T = TypeVar("T", bound=BaseModel)


class Document(Frozen):
    name: str
    media_type: str
    content: bytes


class PlanningContext(Frozen):
    household: Household
    week: Week
    candidates: tuple[Recipe, ...]
    violations: tuple[Violation, ...] = ()
    previous: MealPlan | None = None


class PlanProposal(Frozen):
    plan: MealPlan
    rationale: str = ""


@runtime_checkable
class PlannerProvider(Protocol):
    """Proposes plans and extracts structure from documents. Never trusted: the
    deterministic checker validates every proposal and the user confirms every extraction."""

    name: str

    async def propose(self, context: PlanningContext) -> PlanProposal: ...

    async def extract(self, document: Document, schema: type[T]) -> T: ...

    # Optional: ``async def rank_products(self, shortlist: Mapping[str, Sequence[Product]])
    # -> Mapping[str, ProductId | None]`` picks the product that *is* the ingredient for each
    # need (or None). The pipeline uses it when present; the health/price optimiser still runs.
