# ADR-0008: Migros endpoints, dual-channel offers, and learned availability

Status: accepted · 2026-10-24

## Context
Migros has no public API. The web shop and the mobile apps use a set of `*/public/*` services on `www.migros.ch`. `migros-api-wrapper` and the patched `migros-mcp` document most of them; live read-only probes on 2026-10-24 confirmed the shapes below.

## What we learned
- **Guest token**: `GET /authentication/public/v1/api/guest?authorizationNotRequired=true` returns the token in the `leshopch` response header; anonymous catalogue calls send it back as a `leshopch` request header.
- **Search**: `POST /onesearch-oc-seaapi/public/v5/search` with `{regionId, language, query, ...}` returns `productIds` (integers) in relevance order.
- **Details**: `GET /product-display/public/v2/product-detail?uids=…&warehouseId=1&storeType=ONLINE|OFFLINE&region=national`. **One offer per channel.** The OFFLINE offer is the in-store price and pack; the ONLINE offer is the delivery price and pack, and they differ (broccoli: CHF 4.80 per kg in store, CHF 1.90 per 250–500 g online). `offer.price.effectiveValue < advertisedValue` means a promotion. `productAvailability` is `ONLINE_AND_INSTORE`, `INSTORE_ONLY`, … at product level, not per address. Nutrition sits in `productInformation.nutrientsInformation.nutrientsTableV2` as labelled text rows per 100 g.
- **Account JWT**: silent OAuth with the SSO cookies: `GET /authentication/public/v1/api/oauth/authorize?...` → follow the returned `url` on `login.migros.ch` (302 with `code`/`state`) → `GET /authentication/public/v1/api/oauth/login-success?code&state&redirectUri` → `accessToken` (prefixed "Bearer "). Valid ~30 min; SSO cookies last weeks. Full login is email → password → TOTP on `login.migros.ch` with CSRF form tokens; passkey redirects are forced back to password/authenticator.
- **Lists**: `GET /shopping-list/public/v1/lists/overview` (every list with its ID; a list *is* the basket), `GET /shopping-list/public/v2/list/details?shoppingListId=…` (items with `ecomProductAvailability` and `totals.onlineTotal.{estimatedTotal, minimumOrderValueReached}`), `PUT /shopping-list/public/v3/items` with `{shoppingListId, items:[{id, quantity, type:"PRODUCT"}]}` as upsert-to-target (0 removes).
- **Not found yet**: a delivery-slot endpoint and a per-address deliverability query. Guesses under `/onlineshop`, `/checkout`, `/delivery-slot` return 403.

## Decisions
1. The adapter fetches **both channels** for every product and keeps both prices and packs; the optimiser judges by channel line totals, as the household learned by hand.
2. **Deliverability and stock are learned**: Migros only tells you per item once it is in a list for your address (`INSUFFICIENT_STOCK` and friends). The adapter records that feedback keyed by product ID, exposes it through `deliverability()` and `stock()`, and lets the engine persist it. The product-level flag (`INSTORE_ONLY`) is used first; unknown products are assumed deliverable, and the read-after-apply corrects the plan on the next run.
3. **Delivery slots come from the household's slot templates** until the endpoint is captured (see the package README for how). The pipeline falls back to templates whenever a store returns no slots.
4. The session file keeps the exact shape of `migros-mcp`'s `session.json`, so an existing login can be reused by copying one file. The password and TOTP seed are read only for the first login and never written.
5. Recorded fixtures are read-only (ADR-0007); writes are tested against a respx mock that mirrors the list endpoints' upsert semantics.

## Consequences
- The first live `apply_list` is the moment the free-text item type (`FREE_TEXT`, unverified) and the write path are proven; the diff is shown first and a human approves.
- When Migros changes an endpoint, the replay tests keep passing and `make e2e-dry-run` fails: re-record with `make record-migros`.
