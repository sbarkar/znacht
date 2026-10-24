"""Claude as a Znacht planner provider."""

from __future__ import annotations

import base64
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from anthropic import AsyncAnthropic
from pydantic import BaseModel

from znacht.domain.plan import Meal, MealPlan, MealSlot
from znacht.domain.product import Channel, Product, ProductId
from znacht.domain.recipe import RecipeId
from znacht.planner.prompts import (
    EXTRACT_LAB_SYSTEM,
    EXTRACT_PANTRY_SYSTEM,
    MATCH_SYSTEM,
    PLANNER_SYSTEM,
    match_payload,
    planning_payload,
)
from znacht.planner.schemas import (
    LabReportSchema,
    PantryPhotoSchema,
    ProductMatchSchema,
    ProposalSchema,
)
from znacht.ports.planner import Document, PlanningContext, PlanProposal

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"


@dataclass(frozen=True)
class AnthropicSettings:
    model: str = DEFAULT_MODEL
    effort: str = "medium"
    fallbacks: bool = True
    max_tokens: int = 16000

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> AnthropicSettings:
        e = os.environ if env is None else env
        return cls(
            model=e.get("ZNACHT_ANTHROPIC_MODEL", DEFAULT_MODEL),
            effort=e.get("ZNACHT_ANTHROPIC_EFFORT", "medium"),
            fallbacks=e.get("ZNACHT_ANTHROPIC_FALLBACKS", "on").lower()
            not in ("off", "0", "false"),
        )


class ParseClient(Protocol):
    """The one SDK call we use, as a Protocol so tests can fake it."""

    async def parse(self, **kwargs: Any) -> Any: ...


class _SdkParse:
    def __init__(self, client: AsyncAnthropic) -> None:
        self._client = client

    async def parse(self, **kwargs: Any) -> Any:
        return await self._client.beta.messages.parse(**kwargs)


class AnthropicPlanner:
    name = "anthropic"

    def __init__(
        self,
        settings: AnthropicSettings | None = None,
        *,
        client: AsyncAnthropic | None = None,
        parse_client: ParseClient | None = None,
    ) -> None:
        self.settings = settings or AnthropicSettings.from_env()
        self._parse: ParseClient = parse_client or _SdkParse(client or AsyncAnthropic())

    def _request(
        self, system: str, content: list[dict[str, Any]] | str, schema: type[T]
    ) -> dict[str, Any]:
        s = self.settings
        req: dict[str, Any] = {
            "model": s.model,
            "max_tokens": s.max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": content}],
            "output_format": schema,
            "output_config": {"effort": s.effort},
        }
        if s.fallbacks:
            req["betas"] = [FALLBACK_BETA]
            req["fallbacks"] = "default"
        return req

    async def _ask(self, system: str, content: list[dict[str, Any]] | str, schema: type[T]) -> T:
        response = await self._parse.parse(**self._request(system, content, schema))
        if getattr(response, "stop_reason", None) == "refusal":
            details = getattr(response, "stop_details", None)
            raise RuntimeError(
                f"the model declined this request ({getattr(details, 'category', 'unknown')})"
            )
        parsed = getattr(response, "parsed_output", None)
        if parsed is None:
            raise RuntimeError("the model returned no structured output")
        if not isinstance(parsed, schema):
            return schema.model_validate(
                parsed if isinstance(parsed, dict) else parsed.model_dump()
            )
        return parsed

    async def propose(self, context: PlanningContext) -> PlanProposal:
        known = {r.id.key: r for r in context.candidates}
        result = await self._ask(PLANNER_SYSTEM, planning_payload(context), ProposalSchema)
        meals: list[Meal] = []
        dropped: list[str] = []
        for m in result.meals:
            recipe = known.get(m.recipe_id)
            if recipe is None or m.date not in context.week:
                dropped.append(m.recipe_id)
                continue
            meals.append(
                Meal(
                    date=m.date,
                    slot=MealSlot.DINNER,
                    recipe_id=RecipeId(source=recipe.id.source, external_id=recipe.id.external_id),
                    servings=context.household.servings,
                    note=m.why,
                )
            )
        rationale = f"{result.week_theme}: {result.chef_note}"
        if result.reuse:
            rationale += f" Shared across the week: {', '.join(result.reuse)}."
        if dropped:
            rationale += f" (ignored unknown recipe ids: {', '.join(dropped)})"
        return PlanProposal(
            plan=MealPlan(week=context.week, meals=tuple(meals)), rationale=rationale
        )

    async def rank_products(
        self, shortlist: Mapping[str, Sequence[Product]]
    ) -> Mapping[str, ProductId | None]:
        """One call for the whole week: which candidate *is* each ingredient, or none."""
        payload = {
            need: [
                {
                    "product_id": str(p.id),
                    "name": p.name,
                    "pack": str(p.pack),
                    "category": str(p.category),
                    "price_online": str(p.price(Channel.ONLINE))
                    if p.price(Channel.ONLINE)
                    else None,
                }
                for p in candidates
            ]
            for need, candidates in shortlist.items()
        }
        result = await self._ask(MATCH_SYSTEM, match_payload(payload), ProductMatchSchema)
        allowed = {need: {str(p.id) for p in candidates} for need, candidates in shortlist.items()}
        out: dict[str, ProductId | None] = {}
        for m in result.matches:
            if m.need not in allowed:
                continue
            out[m.need] = ProductId(m.product_id) if m.product_id in allowed[m.need] else None
        return out

    async def extract(self, document: Document, schema: type[T]) -> T:
        if schema is LabReportSchema:
            system = EXTRACT_LAB_SYSTEM
            ask = "Transcribe every marker in this report."
        elif schema is PantryPhotoSchema:
            system = EXTRACT_PANTRY_SYSTEM
            ask = "List what you see and how much is left."
        else:
            system = "Extract the requested structure from the document faithfully."
            ask = "Extract."
        return await self._ask(system, [_block(document), {"type": "text", "text": ask}], schema)


def _block(document: Document) -> dict[str, Any]:
    data = base64.standard_b64encode(document.content).decode("ascii")
    if document.media_type == "application/pdf":
        return {
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": data},
        }
    if document.media_type.startswith("image/"):
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": document.media_type, "data": data},
        }
    return {"type": "text", "text": document.content.decode("utf-8", errors="replace")}
