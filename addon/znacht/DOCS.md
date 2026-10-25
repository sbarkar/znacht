# Znacht add-on

The same engine image as the LXC and Compose deployments (`ghcr.io/sbarkar/znacht`), with an entrypoint
that reads the add-on options. The [Proxmox LXC](https://github.com/sbarkar/znacht/blob/main/deploy/lxc/README.md)
is the tested path; the add-on is newer and has the limitations listed below.

## Install

1. Settings → Add-ons → Add-on store → ⋮ → Repositories, add `https://github.com/sbarkar/znacht`.
2. Install **Znacht**, fill in the options (below), start it.
3. On first start it writes an example `household.yaml` to the add-on's config folder
   (`/addon_configs/<hostname>/household.yaml`, reachable with the File editor or Samba add-on). Edit it
   for your household and restart the add-on. The example explains every option.
4. Install the **Znacht** integration from HACS, then Settings → Devices & services → Add integration →
   Znacht, with the URL `http://<add-on hostname>:8787` (the hostname is on the add-on's Info page) and
   the `api_token` from the options.

## Options

| Option | Meaning |
|---|---|
| `recipe_source`, `sink` | `cookidoo` for real recipes and My Week; `memory` for the sample catalogue |
| `store` | `migros`, or `memory` for the sample store |
| `planner` | `anthropic` (Claude, recommended) or `rule_based` (no key needed, plainer weeks, no pantry by photo) |
| `api_token` | any long random string; the integration and the app present it |
| `public_url` | the address used in notification links, e.g. your HTTPS URL for the engine |
| `cookidoo_email`, `cookidoo_password` | the password is used for the first login; a token file is kept after that |
| `cookidoo_country`, `cookidoo_language` | e.g. `ch` and `en` |
| `migros_email`, `migros_password`, `migros_totp_secret` | used for the first login and whenever the Migros sign-on expires; only the session is stored |
| `anthropic_api_key`, `anthropic_model` | for the Claude planner |
| `ha_notify` | your phone's notify service without `notify.`, e.g. `mobile_app_pixel`; the add-on reaches Home Assistant by itself |

## Data and backups

The database, the household file, the Cookidoo token and the Migros session live in the add-on's
config folder and are part of Home Assistant backups.

## Limitations

- The add-on publishes no port on the host, only to Home Assistant's internal network. Home Assistant
  reaches it by its hostname; your browser and phone do not.
- So the Znacht app (sidebar panel, Review and Groceries screens) and the links in notifications do not
  load yet with the add-on, and neither does the add-on's own "Open web UI" panel: the app does not yet
  support running under ingress. The entities, the to-do lists, the calendar and the actions work.

Until that is fixed, run the engine in an LXC or a container if you want the app.
