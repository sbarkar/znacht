"""The add-on's import of an LXC bundle (addon/znacht/import_bundle.py, ADR-0015)."""

from __future__ import annotations

import importlib.util
import io
import json
import sqlite3
import tarfile
from pathlib import Path
from typing import Any

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "import_bundle", Path(__file__).parents[2] / "addon" / "znacht" / "import_bundle.py"
)
assert _SPEC and _SPEC.loader
ib = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ib)

ENV = """# from bundle.sh
ZNACHT_API_TOKEN="lxc-token"
ZNACHT_RECIPE_SOURCE="cookidoo"
ZNACHT_SINK=cookidoo
ZNACHT_STORE='migros'
ZNACHT_PLANNER="anthropic"
ZNACHT_COOKIDOO_EMAIL="cook@example.ch"
ZNACHT_COOKIDOO_PASSWORD=
ZNACHT_MIGROS_EMAIL="shop@example.ch"
ZNACHT_MIGROS_PASSWORD="pa\\"ss"
ANTHROPIC_API_KEY="sk-secret"
ZNACHT_HA_URL="http://192.168.4.81:8123"
ZNACHT_HA_TOKEN="ha-secret"
ZNACHT_HA_NOTIFY="mobile_app_pixel"
ZNACHT_MIGROS_LANGUAGE=de
ZNACHT_SOMETHING_NEW=1
"""
SECRETS = ("lxc-token", "sk-secret", "ha-secret", 'pa"ss')


def _bundle(path: Path, files: dict[str, bytes]) -> Path:
    with tarfile.open(path, "w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(f"./{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path


def _db(rows: int) -> bytes:
    con = sqlite3.connect(":memory:")
    con.execute("create table runs (id integer)")
    con.executemany("insert into runs values (?)", [(i,) for i in range(rows)])
    return con.serialize()


@pytest.fixture
def addon(tmp_path: Path) -> tuple[Path, Path]:
    config, data = tmp_path / "config", tmp_path / "data"
    config.mkdir()
    data.mkdir()
    (data / "options.json").write_text(
        json.dumps({"cookidoo_password": "kept", "cookidoo_country": "ch", "ha_notify": ""})
    )
    (config / "household.yaml").write_text("name: Live test\n")
    (config / "znacht.sqlite-wal").write_bytes(b"old journal")
    return config, data / "options.json"


def test_restores_files_options_and_shreds(addon, tmp_path, capsys) -> None:
    config, options_file = addon
    bundle = _bundle(
        config / "znacht-bundle.tgz",
        {
            "env": ENV.encode(),
            "household.yaml": b"name: Barkar\n",
            "cookidoo-token.json": b'{"access_token": "t"}',
            "znacht.sqlite": _db(3),
        },
    )
    calls: list[tuple[str, str, Any]] = []

    assert ib.import_bundle(bundle, config, options_file, lambda *a: calls.append(a) or {})

    assert not bundle.exists()
    assert (config / "household.yaml").read_text() == "name: Barkar\n"
    assert (config / "household.yaml.before-import").read_text() == "name: Live test\n"
    assert not (config / "znacht.sqlite-wal").exists()
    db = sqlite3.connect(config / "znacht.sqlite")
    assert db.execute("select count(*) from runs").fetchone() == (3,)
    assert (config / "cookidoo-token.json").stat().st_mode & 0o777 == 0o600
    assert (config / "engine.env").read_text() == "ZNACHT_MIGROS_LANGUAGE=de\n"

    options = json.loads(options_file.read_text())
    assert calls == [("POST", "/addons/self/options", {"options": options})]
    assert options["cookidoo_password"] == "kept"  # empty in the env: the option stays
    assert options["migros_password"] == 'pa"ss'
    assert options["ha_notify"] == "mobile_app_pixel"
    assert options["store"] == "migros"
    assert "api_token" not in options  # the add-on keeps its own

    out = capsys.readouterr().out
    assert "ZNACHT_SOMETHING_NEW" in out and "ZNACHT_HA_TOKEN" in out
    for secret in SECRETS:
        assert secret not in out


def test_a_broken_upload_is_removed_and_nothing_changes(addon, capsys) -> None:
    config, options_file = addon
    bundle = config / "znacht-bundle.tgz"
    bundle.write_bytes(b"half an upload")
    before = options_file.read_text()

    assert not ib.import_bundle(bundle, config, options_file, lambda *a: {})

    assert not bundle.exists()
    assert options_file.read_text() == before
    assert (config / "household.yaml").read_text() == "name: Live test\n"
    assert "upload it again" in capsys.readouterr().out


def test_options_that_cannot_be_saved_are_named_not_shown(addon, capsys) -> None:
    config, options_file = addon
    bundle = _bundle(config / "znacht-bundle.tgz", {"env": ENV.encode()})

    def refuse(*_: Any) -> dict[str, Any]:
        raise OSError("supervisor down")

    assert not ib.import_bundle(bundle, config, options_file, refuse)
    out = capsys.readouterr().out
    assert "anthropic_api_key" in out
    for secret in SECRETS:
        assert secret not in out
    assert json.loads(options_file.read_text())["anthropic_api_key"] == "sk-secret"
