# ADR-0014: A release pins the add-on's engine image; the add-on is the household's production

Status: accepted · 2026-10-25 · builds on ADR-0012 and ADR-0013

## Context
The add-on's Dockerfile built `FROM ghcr.io/sbarkar/znacht:latest`, and `latest` follows `main`. The
Supervisor builds an add-on on install and on every update, and the add-on store reads the repository's
`main`, so an add-on released as 0.1.0 and rebuilt a week later ran whatever `main` was by then: code
nobody had released, under a version number that said otherwise. That is fine for a test add-on and not
for the one a household plans its dinners with.

The household that runs Znacht moves from the LXC (ADR-0002) to the add-on, and brings its run history,
savings, learned Migros availability, tokens and sessions with it.

## Decision
1. **The add-on builds on the engine image of its own version.** `addon/znacht/Dockerfile` names the tag
   (`FROM ghcr.io/sbarkar/znacht:0.2.0`), without a `BUILD_FROM` argument the Supervisor could override.
   `scripts/check_versions.py` requires it to equal `manifest.json` and `config.yaml`, in CI and for the
   tag, and `release.yml` publishes that image tag when the tag is pushed.
2. **A release candidate is a version of its own.** `v0.2.0-rc.1` needs `0.2.0-rc.1` in all three files:
   the Supervisor offers an add-on update only when `config.yaml`'s version changes, so an rc carrying
   `0.2.0` would hide the final release. Each rc and each release is one small version PR followed by its
   tag.
3. **The LXC hands over with a bundle.** `deploy/lxc/bundle.sh`, run in the LXC, packs its env, household,
   tokens, session and a consistent copy of the database. The add-on restores a `znacht-bundle.tgz` it
   finds in its config folder on start, moves the env's account settings into its options, and shreds the
   bundle. The LXC is stopped before the bundle is made (two engines on one Cookidoo or Migros account
   rotate each other's sessions out) and kept, stopped, as the way back.
4. **Notifications are set where the accounts are.** The integration's Configure form picks the phone
   from the `notify.mobile_app_*` services; nobody needs the add-on's options tab.

## Consequences
- A version on Home Assistant means the same code on every rebuild.
- Between merging a version PR and pushing its tag, the add-on store can offer a version whose image does
  not exist yet; an update in that window fails to build and leaves the old version running. Tag right
  after merging (the image takes a few minutes).
- `main` between releases is tested on Home Assistant by building the add-on as a local add-on with the
  Dockerfile's `FROM` pointed at `latest` (or a `sha-…` tag), not by changing the release pin.
- The LXC scripts stay for households that run the engine outside Home Assistant.
