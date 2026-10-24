# ADR-0006: Anthropic API is the default planner provider; providers are pluggable

Status: accepted · 2026-10-24

## Context
The planner needs an LLM for proposals and for extraction (lab PDFs, pantry photos). The LLM is never trusted on quantities, prices or rules; a deterministic checker validates everything. The household already uses Claude for the manual version of this loop.

## Decision
- `PlannerProvider` is a port. The first implementation is `znacht-llm-anthropic` on the Anthropic Messages API with structured JSON output; a model name is configuration, not code, defaulting to the current mid-tier Claude model at release time.
- Other providers (OpenAI-compatible, Ollama for local models) are separate packages discovered through the `znacht.planner_providers` entry-point group.
- The core ships a deterministic `RuleBasedPlanner` that needs no LLM. It is the test planner, the fallback when the LLM is unreachable, and proof that the pipeline does not depend on any provider.
- API keys come from the environment or the engine's secrets file, never from the household YAML.

## Consequences
- Phase 1 runs the whole pipeline without network access.
- Prompt templates and JSON schemas live in core (`znacht.planner`), providers only transport them.
- Provider cost and latency are isolated from HA.
