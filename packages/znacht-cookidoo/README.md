# znacht-cookidoo

Cookidoo adapter for Znacht, built on the unofficial [`cookidoo-api`](https://github.com/miaucl/cookidoo-api) library that Home Assistant's own Cookidoo integration uses.

- `CookidooRecipeSource`: recipe search (optionally across several locales) and recipe details.
- `CookidooMealPlanSink`: reads and writes "My Week", which syncs to the Thermomix. `apply` is the only method that writes.

## Configuration

Environment variables (standalone mode) or the engine's secrets file:

| Variable | Meaning |
|---|---|
| `ZNACHT_COOKIDOO_EMAIL` | Cookidoo account email |
| `ZNACHT_COOKIDOO_PASSWORD` | Only needed for the first login; afterwards the saved session token is used |
| `ZNACHT_COOKIDOO_COUNTRY` | Country code, default `ch` |
| `ZNACHT_COOKIDOO_LANGUAGE` | Language code, default `en` |
| `ZNACHT_COOKIDOO_TOKEN_FILE` | Where the OAuth tokens are persisted, default `~/.config/znacht/cookidoo-token.json` |

Tokens are refreshed transparently and written back to the token file. The password is never written anywhere.

## Tests

- `tests/cookidoo/test_contracts_fake.py`: the port contract suites against a stateful fake client.
- `tests/cookidoo/test_replay.py`: the real `cookidoo-api` client against a scrubbed, read-only cassette.
- Re-record with `make record-cookidoo ENV_FILE=path/to/.env` (reads only; see ADR-0007).

## Mapping notes

Cookidoo gives free-text quantities and no categories, so the adapter parses `"500 g"`, `"1 - 2"`, `"2 tbsp"` and friends, keeps the raw notation on each ingredient, and infers category, tags and spiciness from keywords in English and German. These are hints for the planner; the household rules are still enforced by the checker.
