from __future__ import annotations

import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

from tests.migros.mock_server import MockMigros
from znacht_migros import MigrosGroceryStore, MigrosSession, MigrosSettings


@pytest.fixture
def mock() -> Iterator[MockMigros]:
    m = MockMigros()
    with m.router:
        yield m


@pytest.fixture
async def session(tmp_path: Path, mock: MockMigros) -> AsyncIterator[MigrosSession]:
    settings = MigrosSettings(session_file=tmp_path / "session.json")
    s = MigrosSession(settings)
    s.store.jwt, s.store.jwt_exp = "test-jwt", int(time.time()) + 3600
    async with s:
        yield s


@pytest.fixture
async def store(session: MigrosSession) -> MigrosGroceryStore:
    return MigrosGroceryStore(session)
