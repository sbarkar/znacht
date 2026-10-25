# Contributing

## Branches

`main` is always deployable: the LXC install (`deploy/lxc/install.sh`) pulls it, and every push to it publishes
`ghcr.io/sbarkar/znacht:latest`. So nothing lands on `main` except through a pull request:

- Work on a branch, open a PR against `main`.
- The `ci` check must pass. It is the one required check and waits on every CI job (lint, types, tests on 3.12 and
  3.13, the Home Assistant tests, and a build plus smoke test of the image).
- Squash or rebase merge only; history stays linear. Open review threads must be resolved.
- No force pushes to `main`, no deleting it. Admins can merge a PR whose checks are stuck, but cannot push directly.
- `v*` tags are release tags; only admins can create them (`release tags`), and nobody can move or delete them
  (`release tags immutable`, no bypass; disable that ruleset in the settings if a tag ever truly has to go).

The rules live in `.github/rulesets/` and are applied with:

```bash
gh api -X POST repos/sbarkar/znacht/rulesets --input .github/rulesets/main.json
```

(`PUT repos/sbarkar/znacht/rulesets/<id>` to update an existing one; `gh api repos/sbarkar/znacht/rulesets` lists the ids.)

## CI and releases

| workflow | runs on | does |
|---|---|---|
| `ci.yml` | every PR, pushes to `main` | `make check` on 3.12 and 3.13, `make test-ha`, the version check, builds and smoke-tests the image |
| `release.yml` | pushes to `main`, `v*` tags | builds amd64 + arm64, pushes to GHCR with build provenance; for a tag, checks the versions first and creates the GitHub release |

Images: `latest` follows `main`, `sha-<commit>` pins one build, and a `v1.2.3` tag also gives `1.2.3` and `1.2`.

### Cutting a release

HACS offers GitHub releases once there is one (until then it offers every commit on `main`), and the add-on
updates only when its `version` changes. So a release is:

1. A PR that sets the same version in `custom_components/znacht/manifest.json`, `addon/znacht/config.yaml` and
   the `FROM ghcr.io/sbarkar/znacht:<version>` line of `addon/znacht/Dockerfile` (CI fails if they differ),
   and adds `docs/releases/v<version>.md` (a release candidate uses its final version's notes). Merge it.
2. Right away, tag the merge commit and push the tag (admins only). Until the tag's image is published (a few
   minutes), the add-on store may already offer the new version and its build fails (ADR-0015):

   ```bash
   git tag v0.2.0 origin/main && git push origin v0.2.0
   ```

3. `release.yml` checks the tag against the three files, publishes the image, and creates the GitHub release
   with `docs/releases/v<version>.md` followed by GitHub's generated notes. A tag with a hyphen (`v0.2.0-rc.1`)
   becomes a pre-release, which HACS shows only to those who opt into beta versions. A release candidate is a
   version of its own (`0.2.0-rc.1` in all three files), because the add-on updates only when its version
   changes; the final release is a second version PR and tag.

Tags cannot be moved or deleted. If a tag's version check fails nothing is published; fix the versions and
release the next patch version.

Deploying to the LXC is pull-based on purpose (no self-hosted runner on a public repo, no inbound access to the
LAN): run `install.sh` in the container to update, as in `deploy/lxc/README.md`.

## Pull requests from forks

Workflows on fork PRs run with a read-only token and no secrets, and wait for a maintainer's approval before they
run. Workflows use `pull_request`, never `pull_request_target`, and actions are pinned to commit SHAs (Dependabot
keeps them current).
