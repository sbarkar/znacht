# znacht-engine

The service that runs the weekly loop. FastAPI, one household per instance, SQLite for runs and learned facts, a JSON API for the Home Assistant integration, and the **Znacht Brief**: one page per plan with the dinners, the money, every swap with its reason, the online basket, the store run in walking order, and one button to approve.

```bash
ZNACHT_HOUSEHOLD=examples/household.example.yaml ZNACHT_DATA_DIR=/tmp/znacht uv run znacht-engine
# then: curl -X POST localhost:8787/api/plan_week ; open http://localhost:8787/brief
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
| `ZNACHT_HA_URL`, `ZNACHT_HA_TOKEN`, `ZNACHT_HA_NOTIFY` | unset | send actionable notifications through HA (`ZNACHT_HA_NOTIFY=mobile_app_<device>`) |

Plus the adapter variables: `ZNACHT_COOKIDOO_*`, `ZNACHT_MIGROS_*`, `ZNACHT_ANTHROPIC_*`, `ANTHROPIC_API_KEY`.

## API

`GET /api/status` · `POST /api/plan_week {week?}` · `POST /api/optimize_products` · `POST /api/apply?run_id=` · `POST /api/refresh` · `POST /api/pantry {items}` · `GET /api/lists` · `POST /api/lists/{kind}/done` · `POST /api/lists/{kind}/items` · `GET /api/calendar` · `GET /api/runs` · `GET /brief[/{run_id}]`.

Writes to Cookidoo and Migros happen only in `apply`. There is no checkout endpoint and never will be; the Brief links to the store's basket page for you to finish.
