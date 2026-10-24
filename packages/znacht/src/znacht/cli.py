"""Command-line interface. ``znacht demo`` runs the whole pipeline on the in-memory fixtures."""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from znacht import registry
from znacht.config import load_household
from znacht.domain.plan import Week
from znacht.services.pipeline import PlanStatus, WeekResult, basket_summary, run_week

app = typer.Typer(help="Znacht: weekly meal planning and grocery splitting. Never checks out.")


@app.command()
def check_config(path: Path) -> None:
    """Validate a household YAML file."""
    household = load_household(path)
    members, pantry = len(household.members), len(household.pantry.items)
    typer.echo(f"ok: {household.name} ({members} members, {pantry} pantry items)")


@app.command()
def adapters() -> None:
    """List installed adapters per port."""
    for group in registry.GROUPS:
        names = registry.available(group)
        typer.echo(f"{group}: {', '.join(sorted(names)) or '-'}")


def _render(result: WeekResult) -> None:
    typer.echo(f"status: {result.status}  ({result.rationale})")
    if result.violations:
        for v in result.violations:
            typer.echo(f"  ! {v}")
    typer.echo("\nmeal plan")
    for meal in result.plan.meals:
        typer.echo(
            f"  {meal.date:%a %d.%m} {meal.slot:<7} {meal.recipe_id.external_id} x{meal.servings}"
        )
    if result.status != PlanStatus.NEEDS_APPROVAL:
        return
    s = result.shopping
    typer.echo(f"\nonline basket ({s.slot.id if s.slot else 'no slot'})")
    for c in s.online:
        flag = " [switched]" if c.switched else " [flag]" if c.flagged else ""
        typer.echo(f"  {c.packs}x {c.product.name:<38} {c.line_total()!s:>10}{flag}  - {c.reason}")
    typer.echo("\nin-store list")
    for c in s.in_store:
        typer.echo(f"  {c.packs}x {c.product.name:<38} {c.line_total()!s:>10}  - {c.reason}")
    for t in s.free_text:
        typer.echo(f"  -  {t}")
    typer.echo("\nsummary")
    for key, value in basket_summary(s).items():
        typer.echo(f"  {key:<16} {value}")
    if result.minimum_order.moved_online:
        typer.echo(
            f"  moved online to reach the minimum: {', '.join(result.minimum_order.moved_online)}"
        )
    for note in result.notes:
        typer.echo(f"  note: {note}")
    if result.new_preferred:
        typer.echo(f"  new preferred products: {result.new_preferred}")


@app.command()
def demo(
    household: Annotated[Path, typer.Option(help="household YAML")],
    week: Annotated[str, typer.Option(help="Monday of the week, YYYY-MM-DD")],
) -> None:
    """Run the pipeline on the in-memory fixture catalogues and print the dry-run result."""
    from znacht.planner import RuleBasedPlanner
    from znacht_memory import MemoryMealPlanSink
    from znacht_memory.fixtures import grocery_store, recipe_source

    hh = load_household(household)
    result = asyncio.run(
        run_week(
            hh,
            Week(start=date.fromisoformat(week)),
            recipes=recipe_source(),
            store=grocery_store(),
            sink=MemoryMealPlanSink(),
            planner=RuleBasedPlanner(),
        )
    )
    _render(result)


@app.command()
def cookidoo_dry_run(
    week: Annotated[str, typer.Option(help="Monday of the week, YYYY-MM-DD")],
    query: Annotated[str, typer.Option(help="a recipe search to try")] = "pasta",
) -> None:
    """Read-only check against the live Cookidoo account: My Week and a search. Writes nothing."""
    from znacht.ports.recipes import RecipeQuery
    from znacht_cookidoo import (
        CookidooMealPlanSink,
        CookidooRecipeSource,
        CookidooSession,
        CookidooSettings,
    )

    settings = CookidooSettings.from_env()

    async def run() -> None:
        async with CookidooSession(settings) as session:
            assert session.client is not None
            plan = await CookidooMealPlanSink(session.client).read_week(
                Week(start=date.fromisoformat(week))
            )
            typer.echo(f"My Week {week}: {len(plan.meals)} planned")
            for meal in plan.meals:
                typer.echo(f"  {meal.date} {meal.recipe_id}")
            source = CookidooRecipeSource(session.client, locale=settings.language)
            for recipe in await source.search(RecipeQuery(text=query, limit=3)):
                tags = ",".join(sorted(recipe.tags))
                n = len(recipe.ingredients)
                typer.echo(f"  {recipe.id.external_id}  {recipe.title}  [{tags}]  {n} ingredients")
        typer.echo("dry run complete; nothing was written")

    asyncio.run(run())


@app.command()
def extract(
    kind: Annotated[
        str, typer.Argument(help="'lab' for a lab-report PDF, 'pantry' for pantry photos")
    ],
    files: Annotated[list[Path], typer.Argument(help="PDF or image files")],
    out: Annotated[
        Path | None, typer.Option(help="write a YAML draft here for you to review")
    ] = None,
) -> None:
    """Extract lab markers or pantry contents with the LLM, and write a draft for you to confirm.

    Nothing is used by the planner until you copy the confirmed lines into the household YAML.
    """
    import mimetypes

    import yaml

    from znacht.domain.household import HealthMarker
    from znacht.planner.schemas import LabReportSchema, PantryPhotoSchema
    from znacht.ports.planner import Document
    from znacht.services.health import rules_from_markers
    from znacht_llm_anthropic import AnthropicPlanner

    planner = AnthropicPlanner()
    schema: type[LabReportSchema] | type[PantryPhotoSchema]
    schema = LabReportSchema if kind == "lab" else PantryPhotoSchema

    async def run() -> dict[str, object]:
        draft: dict[str, object] = {}
        for path in files:
            media = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            doc = Document(name=path.name, media_type=media, content=path.read_bytes())
            result = await planner.extract(doc, schema)
            if isinstance(result, LabReportSchema):
                markers = {
                    m.name: {
                        "value": m.value,
                        "unit": m.unit,
                        "reference": m.reference_range,
                        "flag": m.flag,
                    }
                    for m in result.markers
                }
                rules = rules_from_markers(
                    HealthMarker(name=m.name, value=m.value, unit=m.unit, flag=m.flag)
                    for m in result.markers
                )
                draft.setdefault("health", {"markers": {}, "rules": []})
                health = draft["health"]
                assert isinstance(health, dict)
                health["markers"].update(markers)
                health["rules"] = sorted({*health["rules"], *(r.text for r in rules)})
                if result.notes:
                    health["doctor_notes"] = result.notes
            else:
                pantry = draft.setdefault("pantry", {})
                assert isinstance(pantry, dict)
                for item in result.items:
                    pantry[item.name] = f"{item.quantity:g} {item.unit}"
                if result.unsure:
                    draft["pantry_unsure"] = result.unsure
        return draft

    draft = asyncio.run(run())
    text = yaml.safe_dump(draft, sort_keys=False, allow_unicode=True)
    header = (
        "# Draft from znacht extract. Review every line, then merge into your household YAML.\n"
    )
    if out is not None:
        out.write_text(header + text, encoding="utf-8")
        typer.echo(f"draft written to {out}; nothing is used until you merge it")
    else:
        typer.echo(header + text)


if __name__ == "__main__":
    app()
