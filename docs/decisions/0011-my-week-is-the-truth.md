# ADR-0011: My Week is the truth, runs are proposals

Status: accepted · 2026-10-24

## Context
The Week screen showed the latest run's week. At the fridge that answers none of the questions that
matter: what is actually for dinner over the coming days, which days have nothing yet, and is the
food for each day on its way. Dinners the household put into Cookidoo My Week by hand were invisible,
and an apply once replaced a hand-made week and had to be reverted. Groceries were a per-run basket,
not a per-day answer.

## Decisions
1. **Cookidoo My Week is the only truth about what gets cooked.** A Znacht run is a proposal until
   it is applied, and even an applied run is only the *source* of what is in My Week, never a
   substitute for reading it. The engine reads My Week for every ISO week in view (cached for three
   minutes, dropped after every write) and never infers the plan from its own runs when it can read.
   If My Week cannot be read, the applied run stands in and the view says so.
2. **Four day states**, each with its own look in the app and its own meaning in the API:
   - `planned`: a dinner is in My Week. Its *source* is the run id when the latest applied run for
     that week *added* that recipe on that date (it is in the run's applied diff), else `manual`
     ("yours"): hand-made dinners, and dinners a run kept as locked. A hand-made change to a day a
     run had filled turns that day into `manual`.
   - `proposed`: nothing in My Week, but the week's newest run, which still needs approval or
     input, has a dinner there. A planned day can additionally carry a `proposal` when that run
     wants a different recipe; the day stays `planned`.
   - `empty`: nothing anywhere.
   - `past`: before today, whatever it holds, collapsed.
   The run awaiting approval for a week is its newest run while that run's status is
   `needs_approval` or `needs_input`; an applied or reverted newest run means nothing is pending.
3. **Groceries coverage per day, first heuristic.** In this order:
   1. A planned dinner that the latest applied run's plan contains (added by it or kept as
      locked) is covered by that run's lists, because its needs were exploded with the rest. With a
      delivery slot, days after the delivery day are `arriving <weekday hh:mm>`; the delivery day
      itself and earlier days are a `store_run` (the split rule already put anything needed on or
      before the delivery day in store). Without a slot everything is a store run.
   2. A proposed dinner is `online_list` or `store_run` when the run's products for that day are
      already on the store's lists (listed, not ordered), otherwise `none`.
   3. A hand-made dinner is `none`: nothing links it to a list yet.
   "Arriving" is therefore an inference from an applied run's slot, not a fact. Roadmap item P0-3
   (orders read from Migros) replaces step 1 with placed orders and their slots; per-day needs
   explosion refines steps 2 and 3. The API shape (`coverage`, `label`, `slot`, `run_id`) is the
   seam and does not change.
4. **Plan the gaps.** `POST /api/plan_week` takes `locked_dates`; the app sends every date of the
   week that has a dinner in My Week. The engine locks My Week's dinner for each of those dates
   (the base run's only fills in where My Week has nothing), tells the planner about them through
   `PlanningContext.locked_meals` so they count towards the weekly rules, and the run's diff then
   only adds. The rule-based planner plans the free days around the locks; the Claude prompt lists
   the locked dinners and asks for the other days.
5. **Home Assistant** sees the same model: `sensor.znacht_unplanned_days` counts days in the
   horizon with nothing in My Week (`empty` plus `proposed`, both listed as attributes with the
   week summaries); the calendar carries manual dinners with their source and marks proposals.
6. **Horizon.** Default today plus 13 days (`days=14`), a query parameter on the API and a constant
   in the app until Sergej decides otherwise.

## Consequences
- The app's Week screen is a timeline grouped by ISO week with a summary line per week; the
  run-centred view is gone. Approve, swap, lock and move still act on runs, and every approval
  still shows the My Week removals first.
- A run for "this week" still plans the whole ISO week, so days already past can receive a
  proposal and groceries; the app hides proposals on past days. Partial ranges are roadmap P0-2.
- A failing My Week read never blocks planning: the locks fall back to the base run's dinners and
  the timeline shows a warning for that week.
- Reading My Week and the two store lists for a 14-day view costs at most two Cookidoo calls and
  two Migros calls every three minutes; recipe titles for hand-made dinners are fetched once and
  cached in the repo like every other recipe.
