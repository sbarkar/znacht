# ADR-0014: Edit the whole schedule; lock what was ordered

Status: accepted · 2026-10-25 · builds on ADR-0010 and ADR-0011

## Context
After ADR-0011 the Week screen shows what is really in Cookidoo My Week, but only a proposal can be
changed: a dinner already in My Week, whether Znacht sent it or the household put it there by hand, is
view-only, and the app sends people to Cookidoo to change it. For the add-on to be the app the household
runs its week from, any dinner that is not yet bought for must be swappable, movable or removable from
the Week screen, and an empty day must take a dinner, with the same confirm-and-undo safety every other
write has. Once the groceries for a day are ordered, changing that day from Znacht would leave food
nobody cooks, so those days must be locked, and the app must say why. Znacht cannot yet read placed
Migros orders (roadmap P0-3), so it does not know what was ordered unless the household tells it.

## Decisions
1. **An edit is a small run.** Each edit (swap, add, remove, move) is saved as a run like any other:
   `needs_approval` while it is a preview, `applied` once confirmed, `reverted` after an undo. The
   existing apply writes it and the existing revert undoes it. What makes it an edit (its kind, the run
   it builds on, the dates it touches, the change in words) is kept next to the run in the engine's
   key/value store (`edit.<run id>`); the core `WeekResult` is unchanged.
2. **The My Week diff covers only the edited days.** The diff is built from a fresh read of My Week for
   those dates: the day's dinner as read is removed (so a hand-made dinner is removed exactly), the new
   one is added. Breakfasts and the other recipes of the day, and all other days, are never part of it.
   A move removes on one day and adds on the other; moving onto a day that has a dinner swaps the two.
   A move stays inside one ISO week.
3. **The lists follow by delta, rebased on the live lists.** The edit's groceries are the week's latest
   applied plan (none if nothing was applied) with the change made, priced by the usual pipeline with the
   applied run's candidate pool and delivery slot. The change to each list is the new lines minus the
   applied lines, applied to what is on the list right now (`target = live − before + after`, removed at
   zero), and written as an ordinary list diff. The household's own items and quantities on products the
   edit does not touch stay as they are, and the confirm lists only the lines the edit changes. A
   hand-made dinner has no groceries: swapping it adds the new dinner's groceries and removes nothing.
4. **Ordered is recorded, and locks days.** The engine keeps an `orders` table (run, the dates the order
   covers, when, `source`). Until Migros orders can be read, the household records an order in Groceries
   ("I placed the order"), picking the days it covers; the default is the run's dinners after the
   delivery day (what the online basket feeds), else all its days from today. It can be taken back ("not
   ordered after all"). When P0-3 reads real orders they arrive with `source = migros` and confirm or add
   to these records; the API shape (`ordered`, `lock_reason`, coverage `ordered`) does not change.
5. **The lock is enforced by the engine.** Previewing or confirming an edit, applying any run and
   reverting any run are refused with the reason when their My Week diff touches an ordered date. The
   app shows ordered days with a lock and the reason and offers no edit there.
6. **Znacht never fights My Week.** Confirming an edit re-reads My Week and refuses if the edited days
   no longer hold what the preview showed. Applying a proposal compares its stored diff with a fresh one
   and refuses if My Week changed since it was planned, rather than writing a stale diff over a change
   made in Cookidoo or in an edit. Full control stays in the Thermomix and Cookidoo apps.
7. **Provenance.** A dinner an edit put in My Week reads "changed in Znacht"; the other days keep the
   run that sent them. Edit runs are never the week's proposal awaiting approval.
8. **Home Assistant** reads the same timeline and calendar, so it follows edits and order locks on its
   next refresh; calendar events say when a day is ordered. `znacht.mark_ordered` records an order (it
   writes only the engine's database). There is no `swap_dinner` action: a service call would skip the
   confirm step every write to Cookidoo or Migros must go through.

## Consequences
- Every dinner in the horizon that is not past and not ordered can be changed from the Week screen in
  three taps (day, recipe, confirm), and undone from the toast or the day sheet.
- An edit prices the whole applied week again (the swap in a proposal already did), so a confirm takes
  as long as a swap; product picks for untouched days are steered by the preferred products learned on
  apply and only differences reach the confirm.
- A proposal planned before an edit cannot be approved until it is planned again; the refusal says so.
- "Ordered" is the household's word until P0-3; forgetting to record it leaves days editable, and the
  Groceries screen asks for it next to "Finish the order in Migros".
