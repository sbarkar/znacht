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
| `ci.yml` | every PR, pushes to `main` | `make check` on 3.12 and 3.13, `make test-ha`, builds and smoke-tests the image |
| `release.yml` | pushes to `main`, `v*` tags | builds amd64 + arm64, pushes to GHCR with build provenance |

Images: `latest` follows `main`, `sha-<commit>` pins one build, and a `v1.2.3` tag also gives `1.2.3` and `1.2`.

Deploying to the LXC is pull-based on purpose (no self-hosted runner on a public repo, no inbound access to the
LAN): run `install.sh` in the container to update, as in `deploy/lxc/README.md`.

## Pull requests from forks

Workflows on fork PRs run with a read-only token and no secrets, and wait for a maintainer's approval before they
run. Workflows use `pull_request`, never `pull_request_target`, and actions are pinned to commit SHAs (Dependabot
keeps them current).
