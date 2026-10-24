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


if __name__ == "__main__":
    app()
