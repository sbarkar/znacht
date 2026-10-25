"""Restore a bundle from deploy/lxc/bundle.sh into the add-on (ADR-0014). Run by run.sh on start.

    python3 /import_bundle.py /config/znacht-bundle.tgz

The household, the Cookidoo token, the Migros session and the database go into the config
folder (what was there is kept as `*.before-import`). The env's account settings go into the
add-on's options through the Supervisor, and into /data/options.json for this start. Engine
settings without an add-on option go to /config/engine.env. The bundle is overwritten and removed
whatever happens. Values never reach the log, only names.
"""

from __future__ import annotations

import json
import os
import sys
import tarfile
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

CONFIG = Path("/config")
OPTIONS_FILE = Path("/data/options.json")
FILES = ("household.yaml", "cookidoo-token.json", "migros-session.json", "znacht.sqlite")
# env name -> add-on option; an empty value in the env leaves the option as it is
TO_OPTION = {
    "ZNACHT_RECIPE_SOURCE": "recipe_source",
    "ZNACHT_SINK": "sink",
    "ZNACHT_STORE": "store",
    "ZNACHT_PLANNER": "planner",
    "ZNACHT_COOKIDOO_EMAIL": "cookidoo_email",
    "ZNACHT_COOKIDOO_PASSWORD": "cookidoo_password",
    "ZNACHT_COOKIDOO_COUNTRY": "cookidoo_country",
    "ZNACHT_COOKIDOO_LANGUAGE": "cookidoo_language",
    "ZNACHT_MIGROS_EMAIL": "migros_email",
    "ZNACHT_MIGROS_PASSWORD": "migros_password",
    "ZNACHT_MIGROS_TOTP_SECRET": "migros_totp_secret",
    "ANTHROPIC_API_KEY": "anthropic_api_key",
    "ZNACHT_ANTHROPIC_MODEL": "anthropic_model",
    "ZNACHT_HA_NOTIFY": "ha_notify",
}
# no add-on option, nothing secret: kept in /config/engine.env, which run.sh exports
EXTRA = (
    "ZNACHT_MIGROS_LANGUAGE",
    "ZNACHT_MIGROS_MINIMUM_ORDER",
    "ZNACHT_ANTHROPIC_EFFORT",
    "ZNACHT_ANTHROPIC_FALLBACKS",
)
# the add-on decides these itself: its own token, the Supervisor as Home Assistant, its own links
IGNORED = (
    "ZNACHT_API_TOKEN",
    "ZNACHT_HA_URL",
    "ZNACHT_HA_TOKEN",
    "ZNACHT_PUBLIC_URL",
    "ZNACHT_HOST",
    "ZNACHT_PORT",
)


def log(message: str) -> None:
    print(f"[znacht] import: {message}", flush=True)


def parse_env(text: str) -> dict[str, str]:
    """A systemd EnvironmentFile: KEY=value, KEY="value" or KEY='value'; # comments."""
    env: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip().removeprefix("export "), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            quote, value = value[0], value[1:-1]
            if quote == '"':
                value = value.replace('\\"', '"').replace("\\\\", "\\")
        env[key] = value
    return env


def read_bundle(path: Path) -> dict[str, bytes]:
    """The known files of the bundle, in memory; nothing is extracted to disk."""
    found: dict[str, bytes] = {}
    with tarfile.open(path, "r:gz") as tar:
        for member in tar.getmembers():
            name = member.name.removeprefix("./")
            if member.isfile() and name in (*FILES, "env"):
                data = tar.extractfile(member)
                assert data is not None
                found[name] = data.read()
    return found


def merge_options(current: dict[str, Any], env: dict[str, str]) -> tuple[dict[str, Any], list[str]]:
    options = dict(current)
    changed = []
    for key, option in TO_OPTION.items():
        value = env.get(key, "").strip()
        if value:
            options[option] = value
            changed.append(option)
    return options, changed


def shred(path: Path) -> None:
    try:
        size = path.stat().st_size
        with path.open("r+b") as f:
            f.write(os.urandom(size))
            f.flush()
            os.fsync(f.fileno())
    except OSError:
        pass
    path.unlink(missing_ok=True)


def supervisor(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    request = urllib.request.Request(
        f"http://supervisor{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {os.environ.get('SUPERVISOR_TOKEN', '')}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        result: dict[str, Any] = json.load(response)
        return result


def restore_files(files: dict[str, bytes], config: Path) -> list[str]:
    restored = []
    for name in FILES:
        if name not in files:
            continue
        target = config / name
        olds = [target]
        if name == "znacht.sqlite":  # a database's journal belongs to the old one
            olds += [config / f"{name}-wal", config / f"{name}-shm"]
        for old in olds:
            if old.exists():
                old.replace(old.with_name(old.name + ".before-import"))
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(files[name])
        restored.append(name)
    return restored


def write_extra(env: dict[str, str], config: Path) -> list[str]:
    extra = {key: env[key] for key in EXTRA if env.get(key, "").strip()}
    path = config / "engine.env"
    if extra:
        path.write_text("".join(f"{key}={value}\n" for key, value in extra.items()))
    return list(extra)


def import_bundle(
    bundle: Path,
    config: Path = CONFIG,
    options_file: Path = OPTIONS_FILE,
    call: Callable[..., dict[str, Any]] = supervisor,
) -> bool:
    """True when everything landed; False with the reason logged. The bundle is gone either way."""
    try:
        files = read_bundle(bundle)
    except (OSError, tarfile.TarError) as exc:
        kind = type(exc).__name__
        log(f"{bundle.name} is not a bundle from deploy/lxc/bundle.sh ({kind}); upload it again")
        return False
    finally:
        shred(bundle)
    if "env" not in files:
        log(f"{bundle.name} has no env file; nothing imported")
        return False

    env = parse_env(files.pop("env").decode())
    restored = restore_files(files, config)
    log(f"restored {', '.join(restored) or 'no files'} (earlier ones kept as *.before-import)")
    extra = write_extra(env, config)
    if extra:
        log(f"engine settings kept in engine.env: {', '.join(extra)}")
    unknown = sorted(set(env) - set(TO_OPTION) - set(EXTRA) - set(IGNORED))
    skipped = sorted(k for k in env if k in IGNORED)
    if skipped:
        log(f"not taken over, the add-on sets these itself: {', '.join(skipped)}")
    if unknown:
        log(f"not taken over, unknown to the add-on: {', '.join(unknown)}")

    current: dict[str, Any] = json.loads(options_file.read_text()) if options_file.exists() else {}
    options, changed = merge_options(current, env)
    # this start uses them right away; the Supervisor keeps them for the next
    fd = os.open(options_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(options, f)
    try:
        call("POST", "/addons/self/options", {"options": options})
    except Exception as exc:
        log(
            f"could not save the options ({type(exc).__name__}); this start uses them, but set "
            f"{', '.join(changed)} on the add-on's Configuration tab before the next restart"
        )
        return False
    log(f"options set from the env: {', '.join(changed) or 'none'}")
    return True


if __name__ == "__main__":
    sys.exit(0 if import_bundle(Path(sys.argv[1])) else 1)
