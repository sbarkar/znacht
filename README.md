# Znacht

**Znacht** (*ts-NAKHT*) is Swiss German for dinner. It is also a self-hosted engine that runs a household's weekly food loop and plugs into Home Assistant:

1. **Plan** the week's meals within the household's constraints: health targets, people's likes and dislikes, cooking capacity, and what is already in the pantry.
2. **Push** the plan to where the household cooks. For a Thermomix household that is Cookidoo "My Week"; for everyone else, a Home Assistant calendar and a printable week.
3. **Split** the groceries into an online delivery basket and an in-store list, based on what can be delivered and when each ingredient is needed.
4. **Optimise** every product for health first, then value, with every switch explained.
5. **Hand over** to a human. Znacht never checks out, never pays, never places an order. By design, and enforced by a test.

The core knows nothing about any store, recipe platform or appliance. Each one is an adapter behind a typed port, discovered through Python entry points, so a new store or recipe source can ship as its own package.

| Port | First adapter | Later |
|---|---|---|
| `RecipeSource` | Cookidoo | Mealie, Tandoor, web recipes |
| `MealPlanSink` | Cookidoo My Week (Thermomix), HA calendar + Markdown export | Mealie, Tandoor |
| `GroceryStore` | Migros (CH) | Coop, Farmy, Aldi, Lidl |
| `PlannerProvider` | Anthropic API (+ a built-in deterministic planner) | OpenAI-compatible, Ollama |
| `HealthProfileSource` | YAML, lab-report PDF with confirmation | |

## Status

Phase 1: core domain, ports, deterministic planner, in-memory fakes and the golden-week test. No live adapters yet. See [docs/architecture.md](docs/architecture.md) and the [decision log](docs/decisions/).

## Development

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --all-packages
make check        # ruff, mypy --strict, pytest
```

## Licence

Apache-2.0. See [LICENSE](LICENSE).
