"""Structured-output schemas the planner providers must return.

These are the only shapes the LLM is allowed to speak in. Everything in them is a
proposal or a guess: the checker validates plans, and the household confirms extractions.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class ProposedMeal(BaseModel):
    date: date
    recipe_id: str = Field(
        description="exactly as given in the candidates list, e.g. 'cookidoo:r123'"
    )
    servings: int = Field(ge=1, le=12)
    why: str = Field(description="one short sentence for the household")


class ProposalSchema(BaseModel):
    week_theme: str = Field(
        description="a playful 2-5 word name for the week, e.g. 'Mediterranean Mondays'"
    )
    meals: list[ProposedMeal]
    chef_note: str = Field(
        description="2-3 sentences: how the week hangs together, what to prep ahead, what to watch"
    )
    reuse: list[str] = Field(
        default_factory=list,
        description="ingredients deliberately shared across dinners to avoid waste",
    )


class LabMarkerGuess(BaseModel):
    name: str = Field(
        description=(
            "canonical English name, e.g. 'triglycerides', 'ldl cholesterol', 'hba1c', "
            "'ferritin', 'vitamin d'"
        )
    )
    value: float
    unit: str | None = None
    reference_range: str | None = Field(default=None, description="as printed, e.g. '< 1.7'")
    flag: str | None = Field(
        default=None, description="'high', 'low' or null, as the lab marked it"
    )
    page: int | None = None


class LabReportSchema(BaseModel):
    report_date: date | None = None
    markers: list[LabMarkerGuess]
    notes: list[str] = Field(
        default_factory=list, description="doctor's written recommendations, verbatim and short"
    )


class PantryItemGuess(BaseModel):
    name: str = Field(
        description=(
            "lowercase ingredient name as a cook would say it, e.g. 'olive oil', 'red lentils'"
        )
    )
    quantity: float
    unit: str = Field(description="g, kg, ml, l or piece")
    confidence: float = Field(ge=0, le=1)


class PantryPhotoSchema(BaseModel):
    items: list[PantryItemGuess]
    unsure: list[str] = Field(default_factory=list, description="things seen but not identified")


class ProductMatch(BaseModel):
    need: str
    product_id: str | None = Field(
        description="the candidate that IS this ingredient, or null if none is"
    )
    reason: str


class ProductMatchSchema(BaseModel):
    matches: list[ProductMatch]
