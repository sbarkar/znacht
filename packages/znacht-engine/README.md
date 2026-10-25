# znacht-engine

The service that runs the weekly loop. FastAPI, one household per instance, SQLite for runs and learned facts, a JSON API for the Home Assistant integration, the **Znacht app** at `/app` (Week, Review, Groceries, Household, Connections; vendored htm + preact, no build step), and the **Znacht Brief**: one page per plan with the dinners, the money, every swap with its reason, the online basket, the store run in walking order, and one button to approve.

```bash
ZNACHT_HOUSEHOLD=examples/household.example.yaml ZNACHT_DATA_DIR=/tmp/znacht uv run znacht-engine
# then open http://localhost:8787/app, or: curl -X POST localhost:8787/api/plan_week ; open http://localhost:8787/brief
```

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `ZNACHT_HOUSEHOLD` | `$ZNACHT_DATA_DIR/household.yaml` | the household YAML |
| `ZNACHT_DATA_DIR` | `~/.local/share/znacht` | SQLite database and caches |
| `ZNACHT_RECIPE_SOURCE` | `memory` | `cookidoo` for the real thing |
| `ZNACHT_SINK` | `memory` | `cookidoo` writes My Week |
| `ZNACHT_STORE` | `memory` | `migros` |
| `ZNACHT_PLANNER` | `rule_based` | `anthropic` |
| `ZNACHT_API_TOKEN` | unset (open) | bearer token for `/api/*`; also accepted as `?token=` on the Brief |
| `ZNACHT_PUBLIC_URL` | `http://localhost:8787` | used in notification links |
| `ZNACHT_HA_URL`, `ZNACHT_HA_TOKEN`, `ZNACHT_HA_NOTIFY` | unset | send actionable notifications through HA (`ZNACHT_HA_NOTIFY=mobile_app_<device>`) and fire `znacht_plan_ready` / `znacht_needs_input` events |
| `ZNACHT_HOST`, `ZNACHT_PORT` | `0.0.0.0`, `8787` | where the engine listens |

Adapter variables:

| Variable | Meaning |
|---|---|
| `ZNACHT_COOKIDOO_EMAIL`, `ZNACHT_COOKIDOO_PASSWORD` | the password is only needed for the first login |
| `ZNACHT_COOKIDOO_COUNTRY`, `ZNACHT_COOKIDOO_LANGUAGE` | e.g. `ch`, `en` |
| `ZNACHT_COOKIDOO_TOKEN_FILE` | default `~/.config/znacht/cookidoo-token.json` |
| `ZNACHT_MIGROS_EMAIL`, `ZNACHT_MIGROS_PASSWORD`, `ZNACHT_MIGROS_TOTP_SECRET` | full login when there is no usable session |
| `ZNACHT_MIGROS_SESSION_FILE` | default `~/.config/znacht/migros-session.json` |
| `ZNACHT_MIGROS_LANGUAGE`, `ZNACHT_MIGROS_MINIMUM_ORDER` | language; delivery minimum in CHF (default `99`) |
| `ANTHROPIC_API_KEY`, `ZNACHT_ANTHROPIC_MODEL`, `ZNACHT_ANTHROPIC_EFFORT`, `ZNACHT_ANTHROPIC_FALLBACKS` | the Claude planner; effort defaults to `medium`, refusal fallback is `on` (set `off` to disable) |

## API

Everything except `/healthz` takes the bearer token (`Authorization: Bearer …`, or `?token=` once on the Brief and the app).

| Area | Endpoints |
|---|---|
| Health and status | `GET /healthz` · `GET /api/status` |
| Planning | `POST /api/plan_week {week?, locked_dates?}` (any date names its week; runs in the background, `409` while busy) · `POST /api/optimize_products` |
| Days and runs | `GET /api/timeline?from=&days=` · `GET /api/calendar` · `GET /api/runs` · `GET /api/view` · `GET /api/runs/{id}/view` |
| Changing a proposal | `GET /api/runs/{id}/alternatives` · `POST /api/runs/{id}/swap` · `/lock` · `/move` · `/replan` |
| Approving | `POST /api/apply?run_id=` · `POST /api/runs/{id}/revert` · `POST /brief/{id}/apply` · `POST /brief/{id}/replan` |
| Lists | `GET /api/lists` · `POST /api/lists/{kind}/done` · `POST /api/lists/{kind}/items` · `POST /api/refresh` |
| Household | `GET /api/household` · `PATCH /api/household` · `POST /api/pantry {items}` · `POST /api/pantry/photo` |
| Pages | `GET /app` · `GET /brief[/{run_id}]` |

Writes to Cookidoo and Migros happen only in `apply`. There is no checkout endpoint and never will be; the Brief links to the store's basket page for you to finish.
