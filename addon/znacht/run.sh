#!/usr/bin/env bash
# Map add-on options to the engine's environment. Secrets never touch the log.
set -euo pipefail
OPTS=/data/options.json
opt() { jq -r --arg k "$1" '.[$k] // empty' "$OPTS"; }
supervisor() { curl -fsS --max-time 10 -H "Authorization: Bearer ${SUPERVISOR_TOKEN:-}" "$@"; }

export ZNACHT_RECIPE_SOURCE="$(opt recipe_source)" ZNACHT_SINK="$(opt sink)" ZNACHT_STORE="$(opt store)" ZNACHT_PLANNER="$(opt planner)"
export ZNACHT_COOKIDOO_EMAIL="$(opt cookidoo_email)" ZNACHT_COOKIDOO_PASSWORD="$(opt cookidoo_password)"
export ZNACHT_COOKIDOO_COUNTRY="$(opt cookidoo_country)" ZNACHT_COOKIDOO_LANGUAGE="$(opt cookidoo_language)"
export ZNACHT_COOKIDOO_TOKEN_FILE=/config/cookidoo-token.json ZNACHT_MIGROS_SESSION_FILE=/config/migros-session.json
export ZNACHT_MIGROS_EMAIL="$(opt migros_email)" ZNACHT_MIGROS_PASSWORD="$(opt migros_password)" ZNACHT_MIGROS_TOTP_SECRET="$(opt migros_totp_secret)"
export ANTHROPIC_API_KEY="$(opt anthropic_api_key)" ZNACHT_ANTHROPIC_MODEL="$(opt anthropic_model)"
# Inside an add-on, the Supervisor proxy is Home Assistant.
export ZNACHT_HA_URL="http://supervisor/core" ZNACHT_HA_TOKEN="${SUPERVISOR_TOKEN:-}" ZNACHT_HA_NOTIFY="$(opt ha_notify)"
# Trust Home Assistant's ingress gateway and serve the app under its path (ADR-0012).
export ZNACHT_INGRESS=1

# An empty api_token option means: make one once and keep it with the add-on's data.
TOKEN="$(opt api_token)"
if [ -z "$TOKEN" ]; then
  if [ ! -s /config/.api_token ]; then
    (umask 077 && head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' > /config/.api_token)
  fi
  TOKEN="$(cat /config/.api_token)"
fi
export ZNACHT_API_TOKEN="$TOKEN"

SELF="$(supervisor http://supervisor/addons/self/info 2>/dev/null || echo '{}')"
ADDON_HOST="$(jq -r '.data.hostname // empty' <<<"$SELF")"
ADDON_SLUG="$(jq -r '.data.slug // empty' <<<"$SELF")"

# Notification links: the public URL when there is one, else the add-on's panel inside Home Assistant.
PUBLIC_URL="$(opt public_url)"
if [ -n "$PUBLIC_URL" ]; then
  export ZNACHT_PUBLIC_URL="$PUBLIC_URL"
elif [ -n "$ADDON_SLUG" ]; then
  export ZNACHT_NOTIFY_LINK="/$ADDON_SLUG"
fi

if [ ! -f /config/household.yaml ]; then
  cp /app/household.example.yaml /config/household.yaml
  echo "[znacht] wrote an example household.yaml to the add-on config folder; edit it and restart"
fi

# Tell Home Assistant where the engine is, so the integration sets itself up with one click.
if [ -n "$ADDON_HOST" ]; then
  if jq -n --arg url "http://$ADDON_HOST:8787" --arg token "$TOKEN" \
      '{service: "znacht", config: {url: $url, token: $token}}' \
      | supervisor -X POST -H "Content-Type: application/json" -d @- http://supervisor/discovery >/dev/null; then
    echo "[znacht] announced to Home Assistant; confirm the Znacht integration under Settings > Devices & services"
  else
    echo "[znacht] could not announce to Home Assistant; add the Znacht integration by hand (see the Documentation tab)"
  fi
fi

exec znacht-engine
