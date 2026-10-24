# ADR-0004: Project name "Znacht"

Status: accepted · 2026-10-24

## Context
"Mealwise" is used by several unrelated apps. "Tischlein" (from *Tischlein deck dich*) is the name of a Swiss food-rescue charity. "Provender" was free everywhere but felt too abstract for a project that wants a community. A second round checked PyPI, GitHub, `.dev`/`.ch`/`.app` registrations and existing products for ~35 candidates. "Scran" fell to a 2025 UK trademark for meal-planning software; "Weeknight", "Dishup" and "Stocked" are crowded; "Nosh", "Hearth", "Potluck", "Galley", "Simmer" are taken on PyPI. The clean finalists were Mealtide, Speis, Znacht, Suppertime and Cookweek.

## Decision
**Znacht** (pronounced *ts-NAKHT*), Swiss German for dinner, the evening meal.

- PyPI distribution and package `znacht`, HA integration domain `znacht`, GitHub `sbarkar/znacht`, adapter packages `znacht-<adapter>`.
- Domains: `znacht.dev` and `znacht.app` were free on 2026-10-24. `znacht.ch` has been a dormant GoDaddy registration since 2001 with no website; worth a polite offer, not a blocker.
- Spelling is always plain lowercase `znacht` in code and package names; no `Z'Nacht` or `zNacht` variants.
- The README's first line explains the word and its pronunciation, as Zustand does.

## Why a Swiss German word is fine
Non-English project names are common and do not hinder adoption: Zustand and Immer (German), Vite (French), Hono and Jotai (Japanese), Ubuntu (Zulu), Kubernetes (Greek). A unique word is far more searchable than a descriptive English compound. The name also tells the origin story: a project born on Migros and Cookidoo in a Swiss household. Dinner is the centre of gravity of the weekly plan, so the meaning is accurate, not just cute.

## Consequences
- Register the PyPI name and create the GitHub repo before any code is pushed.
- Draft folder renamed to `~/code/znacht` on 2026-10-24.
- Alternatives if ever needed: Mealtide, Speis.
