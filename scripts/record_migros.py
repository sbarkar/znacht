"""Record the read-only Migros cassette: guest token, two searches with details in both
channels, the lists overview and one list's details. No writes. The session file is the
one migros-mcp maintains (same format), so no password is needed.

Usage:
    uv run python scripts/record_migros.py [--session ~/.config/migros-mcp/session.json]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.migros.vcr_config import KNOWN_PRODUCT_ID, SEARCH_QUERY, SECOND_QUERY, cassette

from znacht.domain.product import ProductId
from znacht_migros import MigrosGroceryStore, MigrosSession, MigrosSettings


async def record(session_file: Path) -> None:
    settings = MigrosSettings(session_file=session_file)
    async with MigrosSession(settings) as session:
        await session.jwt()  # refresh outside the cassette so the oauth hop is never recorded
        store = MigrosGroceryStore(session)
        with cassette("all"):
            hits = await store.search(SEARCH_QUERY, limit=3)
            print(f"search {SEARCH_QUERY!r}: {[h.name for h in hits]}")
            assert hits and hits[0].id == KNOWN_PRODUCT_ID, hits[0].id
            more = await store.search(SECOND_QUERY, limit=3)
            print(f"search {SECOND_QUERY!r}: {[(h.name, str(h.price_online)) for h in more]}")
            await store.product(ProductId(KNOWN_PRODUCT_ID))
            try:
                await store.product(ProductId("1"))
            except LookupError as exc:
                print(f"unknown product -> {exc}")
            refs = await store.lists()
            print(f"lists: {[(r.id, r.kind) for r in refs]}")
            if refs:
                lst = await store.read_list(refs[0].id)
                print(f"list {refs[0].id}: {len(lst.lines)} lines")
            print(f"slots: {await store.delivery_slots('8000')}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--session", type=Path, default=Path("~/.config/migros-mcp/session.json").expanduser()
    )
    args = parser.parse_args()
    asyncio.run(record(args.session))


if __name__ == "__main__":
    main()
