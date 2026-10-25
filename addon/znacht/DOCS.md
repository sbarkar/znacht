# Znacht add-on

The Znacht engine on your Home Assistant OS box: no other hardware, nothing to type twice. It is the
same engine image as the LXC and Compose deployments (`ghcr.io/sbarkar/znacht`), started from the
add-on options (ADR-0012).

## Install

The easiest way is not to install the add-on by hand at all: install the **Znacht** integration from
HACS and choose **Run Znacht here in Home Assistant**. It adds this repository, installs and starts the
add-on, asks for your accounts and connects to it. The steps below are the same thing by hand.

1. Settings → Add-ons → Add-on store → ⋮ → Repositories, add `https://github.com/sbarkar/znacht`.
2. Install **Znacht**, fill in the options (below) and start it. Leave `api_token` empty: the add-on makes
   one and keeps it.
3. On first start it writes an example `household.yaml` to the add-on's config folder. You don't need to
   edit it: the app's Welcome replaces it with your household the first time you open Znacht.
4. Install the **Znacht** integration from HACS and restart Home Assistant. Settings → Devices & services
   then shows **Znacht** as discovered: press Configure and Submit. No URL, no token.
5. Open **Znacht** from the sidebar. That entry is the app; the first time, it walks you through your
   household.

If the integration is not offered as discovered, add it by hand with `http://<hostname>:8787` (the
hostname is on the add-on's Info page) and the token from `.api_token` in the add-on's config folder.

## Options

| Option | Meaning |
|---|---|
| `recipe_source`, `sink` | `cookidoo` for real recipes and My Week; `memory` for the sample catalogue |
| `store` | `migros`, or `memory` for the sample store |
| `planner` | `anthropic` (Claude, recommended) or `rule_based` (no key needed, plainer weeks, no pantry by photo) |
| `api_token` | leave empty to have one made; set it to use your own |
| `public_url` | only if the engine is also reachable from outside Home Assistant (a published port or a reverse proxy); notification links then open the Brief there |
| `cookidoo_email`, `cookidoo_password` | the password is used for the first login; a token file is kept after that |
| `cookidoo_country`, `cookidoo_language` | e.g. `ch` and `en` |
| `migros_email`, `migros_password`, `migros_totp_secret` | used for the first login and whenever the Migros sign-on expires; only the session is stored |
| `anthropic_api_key`, `anthropic_model` | for the Claude planner |
| `ha_notify` | your phone's notify service without `notify.`, e.g. `mobile_app_pixel`; easier from the integration's Configure, which lists your phones |

## How it fits together

- **The app** runs behind Home Assistant's ingress: Home Assistant signs you in, and the engine accepts
  requests from its ingress gateway without the token. Everything else still needs the token.
- **Notifications** reach Home Assistant through the Supervisor. Their links open the Znacht panel in the
  Home Assistant app (or the Brief at `public_url`, when set).
- **No port is published by default.** Under Network you can publish `8787/tcp` for direct access from
  other machines, for example to put a reverse proxy in front.

## Data and backups

The database, the household file, the generated token, the Cookidoo token and the Migros session live
in the add-on's config folder and are part of Home Assistant backups.

## Updating

Updates appear in the add-on store. Update the integration in HACS to the same release. Each release builds
on the engine image of the same version, so rebuilding an add-on never picks up unreleased code.
