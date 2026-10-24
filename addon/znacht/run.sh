#!/usr/bin/env bash
# Map add-on options to the engine's environment. Secrets never touch the log.
set -euo pipefail
OPTS=/data/options.json
opt() { jq -r --arg k "$1" '.[$k] // empty' "$OPTS"; }
export ZNACHT_RECIPE_SOURCE="$(opt recipe_source)" ZNACHT_SINK="$(opt sink)" ZNACHT_STORE="$(opt store)" ZNACHT_PLANNER="$(opt planner)"
export ZNACHT_API_TOKEN="$(opt api_token)" ZNACHT_PUBLIC_URL="$(opt public_url)"
export ZNACHT_COOKIDOO_EMAIL="$(opt cookidoo_email)" ZNACHT_COOKIDOO_PASSWORD="$(opt cookidoo_password)"
export ZNACHT_COOKIDOO_COUNTRY="$(opt cookidoo_country)" ZNACHT_COOKIDOO_LANGUAGE="$(opt cookidoo_language)"
export ZNACHT_COOKIDOO_TOKEN_FILE=/config/cookidoo-token.json ZNACHT_MIGROS_SESSION_FILE=/config/migros-session.json
export ZNACHT_MIGROS_EMAIL="$(opt migros_email)" ZNACHT_MIGROS_PASSWORD="$(opt migros_password)" ZNACHT_MIGROS_TOTP_SECRET="$(opt migros_totp_secret)"
export ANTHROPIC_API_KEY="$(opt anthropic_api_key)" ZNACHT_ANTHROPIC_MODEL="$(opt anthropic_model)"
# Inside an add-on, the Supervisor proxy is Home Assistant.
export ZNACHT_HA_URL="http://supervisor/core" ZNACHT_HA_TOKEN="${SUPERVISOR_TOKEN:-}" ZNACHT_HA_NOTIFY="$(opt ha_notify)"
if [ ! -f /config/household.yaml ]; then
  cp /app/household.example.yaml /config/household.yaml
  echo "[znacht] wrote an example household.yaml to the add-on config folder; edit it and restart"
fi
exec znacht-engine
