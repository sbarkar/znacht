# ADR-0003: Native Python Migros adapter instead of wrapping the Node MCP server

Status: accepted · 2026-10-24

## Context
The working Migros client today is a locally patched `lewpgs/migros-mcp` (TypeScript) on top of `migros-api-wrapper`. It exposes one "basket", no explicit list IDs, no delivery slots, no deliverability per postcode, no minimum order, and no online/in-store price distinction. Those are exactly the data the split and optimisation rules need. The login chain (email → password → TOTP → OAuth PKCE → JWT) is documented in a scrubbed trace captured on 2026-10-18.

## Decision
Write `znacht-migros` natively in Python (`httpx`, pydantic models), porting the login chain and the endpoints: `onesearch-oc-seaapi/public/v5`, `product-display/public/v4`, `shopping-list/public/v1`, `marketablestock/public/v2`, `store-availability/public/v2`, plus the delivery-slot and deliverability endpoints to be captured from the web shop. Keep `curl_cffi` as an optional transport if Cloudflare rejects `httpx`'s TLS fingerprint. Keep the patched MCP as a reference and for cross-checks in `e2e-dry-run`. Time-box the login port to Phase 3's first week; if it stalls, fall back temporarily to an MCP-client adapter behind the same `GroceryStore` port.

## Consequences
- No Node runtime in the LXC or the add-on.
- Recorded-fixture tests with respx; the login trace becomes the first cassette.
- We carry the breakage risk of unofficial endpoints ourselves; the contract suite and `e2e-dry-run` are the early-warning system.
