# ADR-0012: The add-on is a first-class deployment; the engine stays out of Home Assistant's process

Status: accepted · 2026-10-25 · amends ADR-0002

## Context
ADR-0002 made the LXC the primary deployment and the add-on "packaging later". The add-on as shipped in
0.1.0 starts the engine, but a household on Home Assistant OS cannot use the app: the add-on publishes
no host port, the app calls absolute `/api/...` paths that break under ingress, setting up the
integration needs the add-on's internal hostname and a hand-copied token, and notification links point
at a LAN address. "Fully self-contained in Home Assistant" was weighed in two forms:

- **A.** Make the add-on first-class: everything runs on the Home Assistant box, as the add-on plus the
  integration, with ingress, discovery and no typing.
- **B.** Run the engine inside the integration, so HACS alone installs everything.

B is one to two weeks of work plus a cost on every Home Assistant release. Home Assistant core pins its
own `cookidoo-api` and `anthropic` versions for its built-in integrations, and a custom integration
needing other versions would break those or be broken by them. Planning makes long LLM, Cookidoo and
Migros calls that ADR-0002 kept out of Home Assistant's event loop on purpose, and the household's HAOS VM
runs close to its memory limit. A gives Home Assistant OS households most of B's benefit for a fraction of
the cost, while the engine's API is still changing.

## Decision
1. **A now, B not now.** The add-on is a supported deployment next to the LXC and Compose. The engine stays
   a separate process with the same image everywhere.
2. **Ingress.** The app and the Brief build every URL from a base path: the `X-Ingress-Path` header when
   the request comes through Home Assistant's ingress gateway, empty otherwise. `/` redirects to the app.
   The add-on's own sidebar entry is the app.
3. **Ingress is authenticated by Home Assistant.** With `ZNACHT_INGRESS=1` (set only by the add-on), the
   engine accepts requests from the Supervisor's ingress gateway (`172.30.32.2`) without the API token;
   Home Assistant has already checked the user. Every other request still needs the token.
4. **Discovery.** The add-on generates an API token if none is set, keeps it in its config folder, and
   announces `{url, token}` to Home Assistant through Supervisor discovery (service `znacht`). The
   integration offers a one-click setup from that announcement. An entry created this way does not add
   the integration's iframe panel, since the add-on's ingress panel is the app.
5. **Notification links** from the add-on open the add-on's sidebar panel (`/<slug>`, a path inside Home
   Assistant), unless `public_url` is set.
6. **A host port is optional.** `8787/tcp` is declared but unpublished by default; publish it for direct
   access from other machines.

## Consequences
- Home Assistant OS households need no other hardware and type no URL or token.
- The engine knows one environment-specific fact (the ingress gateway), behind a flag only the add-on
  sets.
- B stays possible: FastAPI is confined to `app.py`, and `service.py` has no web code. Revisit B when
  outside households ask for a single HACS install and the API has settled; it needs the packages on PyPI
  and an answer to the dependency pins first.
- Supervisor discovery for a custom integration and the ingress paths must be checked on a real Home
  Assistant OS install; until then the manual setup (URL and token) keeps working as before.
