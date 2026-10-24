# ADR-0007: Recorded HTTP fixtures are read-only; writes are tested on fakes

Status: accepted · 2026-10-24

## Context
Adapter tests need real response shapes, so we record HTTP with VCR.py against the real account and replay it in CI. Recording a *write* (adding a recipe to My Week, changing a basket) would change the household's live data during a test run, and a cassette of it would go stale the moment the account changes.

## Decision
- Recording scripts (`scripts/record_*.py`) perform only reads: discovery, search, details, reading the plan or the lists. They log in with a throwaway token file and never touch the user's real token.
- Cassettes are scrubbed before they are written: the whole login flow is dropped, Authorization and Cookie headers removed, Set-Cookie and tracing headers removed, and account identifiers, tokens and e-mail addresses in bodies replaced with `<scrubbed>`. A grep for known secrets runs before a cassette is committed.
- Write paths (`apply`) are tested against a stateful fake of the vendor client that mirrors the library's method signatures, plus the port contract suite. The first real write of each adapter is done by a human through the normal `apply` gate, which already requires an explicit approval and shows the diff first.
- Replay tests use a dummy token with a far-future expiry so the client never tries to refresh.

## Consequences
- CI never needs credentials and never talks to a vendor.
- A vendor-side change in a write endpoint surfaces at the first human-approved apply, not in CI. The contract suite and `make e2e-dry-run` are the early warning for read endpoints.
- Cassettes must be re-recorded when the vendor changes a read endpoint; the script is one command.
