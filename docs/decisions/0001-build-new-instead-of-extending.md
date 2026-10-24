# ADR-0001: Build a new project rather than extend an existing one

Status: accepted · 2026-10-24

## Context
See `docs/discovery.md` §1. Mealie, Tandoor and KitchenOwl are recipe managers with HA integrations; myMeal and MealMCP are small solo projects with an LLM planner but no store or appliance adapters, no health rules, and a monolithic Flask core.

## Decision
Start a new project. Treat Mealie, Tandoor and KitchenOwl as future `RecipeSource` / `MealPlanSink` adapters, not as the base.

## Consequences
- We own the domain model, the constraint checker and the store/appliance adapters, which is the part nobody has built.
- We reuse `cookidoo-api` unchanged and the endpoint knowledge in `migros-api-wrapper` / the patched `migros-mcp`.
- We do not build a recipe editor or a recipe database; households that want one point Znacht at Mealie or Tandoor later.
