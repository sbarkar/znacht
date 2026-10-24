# znacht-migros

Native Python adapter for Migros Online (Switzerland). There is no official API; this talks to the same endpoints the web shop uses, so it can break when Migros changes them. Every request goes through Znacht's request guard: checkout, order and payment paths are refused before they leave the machine.

## What it does

- **Catalogue**: search, product details with **both prices** (the in-store offer and the online offer differ: broccoli was CHF 4.80/kg in store and CHF 1.90 per 250–500 g online), pack size, unit price, promotions (effective vs advertised price), nutrition per 100 g, and the product-level availability flag.
- **Lists by explicit ID**: every list call takes a `shoppingListId`; the app's "active list" is never trusted. Reading a list also yields each item's `ecomProductAvailability` (for example `INSUFFICIENT_STOCK`), which the adapter remembers as deliverability and stock knowledge for that product.
- **Writes**: `apply_list` only, as one batched `PUT` of target quantities (0 removes).
- **Auth**: guest token for anonymous endpoints; for your lists, a session file in the same format as `migros-mcp`'s `session.json` (cookies per host, JWT, expiry). Copy that file to `~/.config/znacht/migros-session.json` to bootstrap, or let the adapter run the full login (email, password, TOTP seed) once. The JWT is refreshed through silent OAuth with the SSO cookies; nothing else is stored.

## Known gaps (help wanted)

- **Delivery slots**: the slot endpoint is not known yet. Until it is captured, slots come from the household YAML (`delivery.slot_templates`). To capture it: open migros.ch, go to checkout, pick a slot with the browser's network tab open, and note the request path; file it in an issue.
- **Deliverability per address** is learned, not queried: Migros only tells you when an item is in a list for your delivery address. The adapter uses the product-level availability flag first and the learned list feedback second.
- **Free-text list items**: the item type for free text is a guess (`FREE_TEXT`) until verified.

## Configuration

| Variable | Meaning |
|---|---|
| `ZNACHT_MIGROS_SESSION_FILE` | default `~/.config/znacht/migros-session.json` |
| `ZNACHT_MIGROS_EMAIL`, `ZNACHT_MIGROS_PASSWORD`, `ZNACHT_MIGROS_TOTP_SECRET` | only for the first login when no session exists; the TOTP value is the base32 seed, not a code |
| `ZNACHT_MIGROS_LANGUAGE` | `en` (default), `de`, `fr`, `it` |
| `ZNACHT_MIGROS_MINIMUM_ORDER` | default `99` |
