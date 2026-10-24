"""The Anthropic provider against a fake parse client: request shape, mapping, guards."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from znacht.domain.plan import Week
from znacht.planner.schemas import LabReportSchema, PantryPhotoSchema, ProposalSchema, ProposedMeal
from znacht.ports.planner import Document, PlanningContext
from znacht.services.checker import check_plan
from znacht.testing.contracts import PlannerProviderContract
from znacht_llm_anthropic import AnthropicPlanner, AnthropicSettings
from znacht_memory.fixtures import GOLDEN_WEEK_START, recipes

RECIPES = {r.id.key: r for r in recipes()}
WEEK = Week(start=GOLDEN_WEEK_START)


class FakeParse:
    def __init__(self, parsed, stop_reason="end_turn"):
        self.parsed = parsed
        self.stop_reason = stop_reason
        self.requests: list[dict] = []

    async def parse(self, **kwargs):
        self.requests.append(kwargs)
        return SimpleNamespace(
            parsed_output=self.parsed, stop_reason=self.stop_reason, stop_details=None
        )


def good_proposal() -> ProposalSchema:
    ids = [
        "chicken-rice",
        "salmon-tray",
        "lentil-dal",
        "chickpea-stew",
        "hummus-bowls",
        "beef-ragu",
        "fish-curry",
    ]
    return ProposalSchema(
        week_theme="Cosy Autumn Week",
        meals=[
            ProposedMeal(date=d, recipe_id=f"memory:{rid}", servings=3, why="fits")
            for d, rid in zip(WEEK.days(), ids, strict=True)
        ],
        chef_note="Ragù on Saturday, fish twice, lentils midweek.",
        reuse=["onion", "coconut milk"],
    )


@pytest.fixture
def context(household):
    return PlanningContext(household=household, week=WEEK, candidates=tuple(recipes()))


class TestAnthropicPlannerContract(PlannerProviderContract):
    @pytest.fixture
    def planner(self):
        return AnthropicPlanner(AnthropicSettings(), parse_client=FakeParse(good_proposal()))

    @pytest.fixture
    def context(self, household):
        return PlanningContext(household=household, week=WEEK, candidates=tuple(recipes()))


async def test_request_shape_uses_structured_output_effort_and_fallbacks(context):
    fake = FakeParse(good_proposal())
    planner = AnthropicPlanner(
        AnthropicSettings(model="claude-opus-5-5", effort="high"), parse_client=fake
    )
    await planner.propose(context)
    req = fake.requests[0]
    assert req["model"] == "claude-opus-5-5"
    assert req["output_format"] is ProposalSchema
    assert req["output_config"] == {"effort": "high"}
    assert req["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in req["betas"]
    assert "thinking" not in req  # adaptive by default on this model
    payload = json.loads(req["messages"][0]["content"])
    assert payload["household"]["min_per_week"] == {"fish": 2, "legumes": 2, "red_meat": 1}
    assert "dill" in payload["household"]["banned_ingredients"]
    assert any(c["recipe_id"] == "memory:beef-ragu" for c in payload["candidates"])
    assert "spicy" not in req["system"].lower() or "mild" in req["system"].lower()


async def test_proposal_maps_to_a_plan_the_checker_accepts(context, household):
    planner = AnthropicPlanner(parse_client=FakeParse(good_proposal()))
    proposal = await planner.propose(context)
    assert len(proposal.plan.meals) == 7
    assert check_plan(proposal.plan, RECIPES, household) == []
    assert proposal.rationale.startswith("Cosy Autumn Week")
    assert proposal.plan.meals[0].note == "fits"
    assert all(m.servings == household.servings for m in proposal.plan.meals)


async def test_unknown_recipe_ids_are_dropped_not_trusted(context):
    bad = good_proposal().model_copy(
        update={
            "meals": good_proposal().meals[:6]
            + [ProposedMeal(date=WEEK.end, recipe_id="memory:made-up", servings=3, why="x")]
        }
    )
    planner = AnthropicPlanner(parse_client=FakeParse(bad))
    proposal = await planner.propose(context)
    assert len(proposal.plan.meals) == 6
    assert "made-up" in proposal.rationale


async def test_violations_and_previous_plan_are_fed_back(context, household):
    from znacht.domain.violations import Violation

    fake = FakeParse(good_proposal())
    ctx = context.model_copy(
        update={
            "violations": (Violation(code="min_tag", message="fish: 1 dinners, need at least 2"),)
        }
    )
    await AnthropicPlanner(parse_client=fake).propose(ctx)
    payload = json.loads(fake.requests[0]["messages"][0]["content"])
    assert payload["previous_attempt_violations"] == ["[min_tag] fish: 1 dinners, need at least 2"]


async def test_refusal_is_an_error_not_a_plan(context):
    planner = AnthropicPlanner(parse_client=FakeParse(None, stop_reason="refusal"))
    with pytest.raises(RuntimeError):
        await planner.propose(context)


async def test_extract_sends_pdf_as_document_block_and_image_as_image_block():
    lab = LabReportSchema(markers=[])
    fake = FakeParse(lab)
    planner = AnthropicPlanner(parse_client=fake)
    out = await planner.extract(
        Document(name="lab.pdf", media_type="application/pdf", content=b"%PDF-1.4"), LabReportSchema
    )
    assert out is lab
    blocks = fake.requests[0]["messages"][0]["content"]
    assert (
        blocks[0]["type"] == "document" and blocks[0]["source"]["media_type"] == "application/pdf"
    )
    assert "transcribe" in fake.requests[0]["system"].lower()

    fake2 = FakeParse(PantryPhotoSchema(items=[]))
    await AnthropicPlanner(parse_client=fake2).extract(
        Document(name="p.jpg", media_type="image/jpeg", content=b"\xff\xd8"), PantryPhotoSchema
    )
    assert fake2.requests[0]["messages"][0]["content"][0]["type"] == "image"
