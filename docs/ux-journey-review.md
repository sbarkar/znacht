# App UX review against the household's journeys

2026-10-24, overnight session. A written critique of the app (`/app`) at phone width (390 px), done
before any change, against the journeys the household actually has. Each change below points
back to a finding here. The screenshots behind it were taken on the memory adapters (fresh
database, then one run for the week of 26 October).

## The journeys, by how often they happen

| # | Journey | Where | How often | What success looks like |
|---|---|---|---|---|
| J1 | **Glance**: what's for dinner tonight, and the next days? Is the food here? | kitchen, phone or HA tablet | several times a day | answered in five seconds without scrolling or tapping |
| J2 | **Plan the week**: fill the empty days, look at the proposal, change a dinner or two, approve | sofa, Thu–Sun | weekly | one obvious next step at every moment; never wonder "did that go through?" |
| J3 | **Tweak**: swap one dinner, lock one | anywhere | a few times a week | two taps, clear that it's a proposal until approved |
| J4 | **Shop**: finish the Migros order; walk the store run and tick things off | phone in one hand, in the shop | weekly | the list for *this* week, in walking order, large targets |
| J5 | **Adjust the household**: a new dislike, a rule, the pantry | sofa | monthly | edits save without ceremony |

## Findings

Severity: **critical** blocks or misleads a journey, **moderate** slows it, **minor** polish.

### Bugs

| Finding | Severity | Journey |
|---|---|---|
| Week and Groceries overflow sideways at 390 px: rows with a badge *and* an Approve pill are ~500 px wide, the Groceries header pills don't wrap. Everything can be dragged sideways. | critical | all |
| On a pinned run (opened from a week's Approve), ticking an item or adding free text writes to the *latest* run, not the run on screen, so ticks vanish and items land on the wrong week. | critical | J4 |
| A plan that fails in the background (`last_error`) is stored but never shown; the app just stops showing "planning…". | moderate | J2 |
| Connections shows "min." with no amount before the first run. | minor | J5 |
| Household "Every week" steppers jump sideways when one row has "max 1" instead of "no max". | minor | J5 |
| Each proposed day carries a button nested inside a `role="button"` row (nested interactive controls). | minor (a11y) | J2 |

### Week (J1, J2, J3)

| Finding | Severity | Recommendation |
|---|---|---|
| Nothing answers J1 at a glance. Tonight is a row like any other; on a fresh screen the eye lands on three identical orange "Plan the gaps" buttons. | critical | A **Tonight** card at the top: the dinner (or "nothing planned"), minutes, the groceries state, tap to open. Tomorrow on one line under it. |
| Seven "Approve" pills, one per proposed day, all approve the *same* run. It reads as if you approve days one by one. | critical | One proposal banner per week ("Znacht proposes 7 dinners · Review and approve"); days just show the proposal dimmed. |
| Proposed days show "no groceries", which is true but alarming: a proposal brings its groceries when approved. | moderate | No badge on a proposal; the banner says the groceries come with it. |
| Three equal primary buttons on a fresh week. | moderate | Only the first week with gaps gets the filled button; later weeks get an outline one. |
| "Approve" sends you to Groceries, which never shows the dinners you're approving. You approve a list of products. | critical | A **Review** screen per run: dinners (tap to swap), what it removes from My Week, the money, swaps and flags, and one sticky Approve. Groceries stays the shopping list. |
| While a plan runs, only a small grey "planning…" pill shows. | moderate | A banner at the top of Week while busy; when it finishes, the new proposal is announced. |

### Groceries (J4)

| Finding | Severity | Recommendation |
|---|---|---|
| It shows the *latest* run. After planning next week, this week's applied list (the one you're shopping) disappears. | critical | Default to the run you're shopping: the applied run for this week, else the nearest applied run ahead, else the latest. A row of week chips switches between relevant runs. |
| Approve lives at the bottom of a 30-line list. | moderate | Approve moves to Review; Groceries links there while a run is only a proposal and says so at the top. |
| The store run is a flat list, though the Brief already groups it in walking order. | moderate | Group the store run by aisle, same order as the Brief. Ticked lines sink to the end of their group. |
| The move button is an unlabeled double arrow. | minor | Short text label ("to store" / "online"). |
| Ticking products on a proposal that hasn't been approved. | minor | Ticks only once a run is applied; before that the screen says "proposal, not sent yet". |

### Household and Connections (J5)

Mostly fine for a monthly task. The fixes are the two bugs above.

## What works and stays

- The four day states read clearly; dashed for proposed, dashed-grey for empty, dimmed past.
- The swap sheet: pre-checked alternatives, "bends a weekly count" warnings, Surprise me.
- Every write still needs a tap and shows the My Week removals first (ADR-0010, ADR-0011).
- Dark, warm palette, 44 px targets, big type.

## Left for later

- **Planning only the remaining days of this week** (roadmap P0-2). "Plan the gaps" on a Saturday
  still plans the whole ISO week, so past days get dinners and groceries; the app hides them.
  The real fix changes the planner and checker (`dinners_per_week`), which is beyond a UX pass.

## Outcome (same night)

Every finding above is addressed on branch `claude/clever-brown-y1foo9` except the P0-2 item.
An independent code review of the new app found eight more defects. All were fixed:

- editing a member dropped an explicit `mild_food` from the YAML;
- quick household edits overwrote each other;
- pantry chips set by Home Assistant could not be removed;
- grocery lines remounted on every reload, so the tick you pressed lost focus;
- a failed refetch replaced a loaded plan with an error page;
- alternatives could show a stale response;
- swaps were enabled while the engine was busy;
- the day sheet did not take focus.

Driving the journeys also turned up engine bugs, fixed with tests: a store's delivery slot was
used for any week, `plan_week` failed in the background on a non-Monday, and ticks were written
to the wrong run.

Still open:
- Home Assistant's todo lists follow the latest run rather than `shopping_run_id`.
- On the same product needed on two days, ticking one line ticks both (ticks are keyed by
  product).
