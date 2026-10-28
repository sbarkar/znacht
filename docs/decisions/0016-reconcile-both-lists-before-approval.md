# ADR-0016: Reconcile both lists against the week's need before a plan can be approved

Status: accepted · 2026-10-28 · builds on ADR-0009 and ADR-0014

## Context
Last week the household bought about 3 kg of carrots for about 0.5 kg of recipe need. 2 kg were on the
online basket and 1 kg was added to the in-store list as a backup in case the delivery came late. Each
list was plausible on its own. Nothing compared the totals across the two lists, and the approval view
(the app's Review, the Brief, the notification) showed the lists but not the surplus.

Three things in the pipeline let this through:

1. **Packs were rounded up per list.** `timing_split` sends a need on or before the delivery day to the
   in-store list and later needs online; `merge_needs` and `packs_needed` then ran once per channel. An
   ingredient needed on the delivery day and later in the week got a full pack on each list, so the
   week bought up to two packs too many with no step that saw both.
2. **A backup added to one list took nothing off the other.** Moving or adding to the store run was a
   separate act from the online quantity.
3. **Lines did not say what they were for.** A `ProductChoice` carried a need name and a date, not the
   needs it covered, so "is this line still needed?" had no answer.

## Decisions
1. **Every line traces to its needs, or says why it is there.** An `IngredientNeed` has a `key`
   (ingredient, day, unit) and a merged need keeps the keys it sums (`merged_from`). A `ProductChoice`
   carries `need_keys`, the summed `need_quantity`, an optional `manual_reason` (a household item, not a
   recipe need) and an optional `split_reason` (why the ingredient is on both lists). A line with no
   need key and no manual reason is an *orphan*: it is not rejected when the model is built, so old runs
   still load and the check can report it, but it is a finding and blocks approval like any other.
2. **Quantities are computed once from the summed need, then split.** The `ShoppingPlan` carries the
   week's needs after the pantry, the pantry and the surplus threshold. `allocate` (in
   `services/allocation.py`) groups the lines of each ingredient across both lists, in-store first
   because it is bought before the delivery, and gives each line only what the lines before it do not
   already cover. Packs are rounded once, against the cumulative need. An online line that the in-store
   packs already cover is dropped and its needs move to the in-store line. When an ingredient really is
   on both lists, both lines get a `split_reason`. `run_week` allocates before the minimum-order step.
3. **A backup moves packs; it never adds them.** `add_backup(plan, need, packs)` takes packs off the
   online line and puts them on the in-store list in one operation (engine:
   `POST /api/runs/{id}/backup`, the app's "backup" button). Moving a whole need keeps going through the
   existing channel override and re-plan, which already computes from the total.
4. **Reconciliation is one deterministic function over the whole plan.** `reconcile(plan)` returns
   findings in a stable order, each with a stable `id` and a message a person can act on:
   - **surplus**: an ingredient whose lines together buy more than `surplus_threshold_packs` packs
     (default 1, in the largest pack on its lines; `store_policy.surplus_threshold_packs` in the household
     YAML) beyond its summed need, for example
     `carrots: 3 kg bought vs 0.5 kg needed (online 2 kg + in-store 1 kg)`. Lines with a manual reason
     and no need are not counted. Where the units do not bridge (a recipe wants "2 onions", the shop sells
     a 1 kg bag), one pack covers the need, as `packs_needed` already assumes, and the check counts packs.
   - **cross-list duplicate**: one product on both lists while any of its lines has neither a split nor a
     manual reason, with the combined quantity.
   - **orphan**: a line that traces to no need of this plan and gives no reason.
   A finding is checked against the plan's own numbers, not against a stored copy, so the same plan
   always gives the same findings.
5. **The gate.** `apply_week` refuses (`UnreconciledPlan`) a `needs_approval` run with open findings:
   such a plan cannot become `applied`. Each finding is either **fixed** or **overridden**. A fix
   (`resolve_findings(fix=…)`) recomputes that ingredient's packs across both lists from its summed need,
   or removes an orphan line, and the list diffs are recomputed. An override needs a non-empty reason.
   It covers a finding only while the finding's message reads the same, so a surplus that grows opens
   again. Overrides are kept on the run (`WeekResult.overrides`), written to the Python log as
   warnings, added to the run's notes, and appended to the engine's `overrides` table, an audit log that
   is never edited.
6. **The household sees it before the savings.** The engine's status and view carry `open_findings` and
   the messages. The plan-ready notification lists the findings first, above the savings, titles itself
   "check the lists" and offers only Review (no Approve button) while any is open. The app's Review and
   Groceries show a findings card with Fix and "Buy anyway…" (which asks for the reason), and the Approve
   button stays disabled, reading "Check N things first", until none is open. The Brief shows the
   findings at the top. `znacht demo` and `make e2e-dry-run` print them first, and again under the
   dry-run diff. `make e2e-dry-run` now prices My Week against the store (Migros with
   `ZNACHT_STORE=migros`, else the fixture catalogue), reading only.
7. **Home Assistant.** `sensor.znacht_open_findings` counts them, with the messages as attributes.
   `znacht.reconcile` runs the check, fixes and overrides, and returns the findings. `znacht.apply_plan`
   while findings are open fails with the engine's reason, not "busy".
8. **A sent plan is checked on the live lists.** On an `applied` run, `reconcile` reads both store lists
   back (`read_listed_plan`), so a backup added by hand in the Migros app after approval shows up as an
   orphan and a cross-list duplicate. It can be overridden but not fixed: only an approved apply writes to
   the lists.
9. **Adapters must agree.** `ReconciliationContract` (in `znacht.testing.contracts`) replays the carrot
   incident in each store's own products: the findings must have the same shape for every adapter
   (surplus of 2.5 packs, a cross-list duplicate, an orphan), and reconciling the lists as written and
   read back must give the same findings as reconciling the plan. The in-memory store and the Migros
   adapter (on its mock server) both run it.

## Consequences
- The golden week reconciles to zero findings, and a Hypothesis property over `run_week` (random needs,
  days, packs, two products per ingredient with different packs, the pantry, the delivery day, backups)
  holds: per ingredient, the lists together buy at least the need and at most one pack beyond it. A
  second property adds lines past the allocation and checks that whatever ends up more than a pack over
  is flagged, refused by `apply_week`, and accepted once overridden.
- Allocating in-store first can drop an online line the household expected, because the in-store pack
  already covers it, and that can take the online basket below the minimum order. The view shows the
  shortfall as before, and the minimum-order step runs after allocation in `run_week`. A fix done
  later in the app does not re-run the minimum-order step.
- Runs saved before this change have lines without need keys. They read as orphans, so a proposal
  from before the upgrade has to be planned again (or overridden) before it can be approved. Applied
  runs are unaffected.
- Free-text items added to the store run in Home Assistant or the app (`todo.extra`) are not product
  lines and are not reconciled. A product added in the Migros app is reconciled, through the live check.
- A backup made with `add_backup` lives on the run. A re-plan of the week (a swap or "plan again")
  computes the lists afresh and does not keep it.
