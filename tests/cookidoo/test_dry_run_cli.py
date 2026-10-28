"""``make e2e-dry-run`` (``znacht cookidoo-dry-run``) on the fake Cookidoo client: it prices
My Week, prints the dry-run diff with the reconciliation findings (ADR-0016), writes nothing."""

from __future__ import annotations

from datetime import date

from typer.testing import CliRunner

import znacht_cookidoo
from tests.cookidoo.fake_client import FakeCookidoo
from znacht.cli import app

MONDAY = date(2026, 10, 26)


class _FakeSession:
    def __init__(self, fake: FakeCookidoo) -> None:
        self.client = fake

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


def test_e2e_dry_run_prints_findings_and_writes_nothing(monkeypatch):
    fake = FakeCookidoo()
    fake.calendar[MONDAY] = [("r1001", False), ("r1002", False)]
    before = {day: list(items) for day, items in fake.calendar.items()}
    monkeypatch.setenv("ZNACHT_COOKIDOO_EMAIL", "household@example.test")
    monkeypatch.delenv("ZNACHT_STORE", raising=False)
    monkeypatch.setattr(znacht_cookidoo, "CookidooSession", lambda settings: _FakeSession(fake))

    out = CliRunner().invoke(app, ["cookidoo-dry-run", "--week", MONDAY.isoformat()])

    assert out.exit_code == 0, out.output
    text = out.output
    assert "My Week 2026-10-26: 2 planned" in text
    assert "store: in-memory fixture catalogue" in text
    assert "reconciliation: " in text
    assert text.index("reconciliation: ") < text.index("meal plan")  # findings first
    assert "dry-run diff (nothing written)" in text
    assert text.rstrip().endswith("dry run complete; nothing was written")
    assert {day: list(items) for day, items in fake.calendar.items()} == before
