"""Record the read-only Cookidoo cassettes used by the adapter tests.

Runs a real login with the credentials from an env file (never committed), performs only
read calls, and writes ``tests/cookidoo/cassettes/*.yaml`` with every secret scrubbed:
the whole login flow is dropped, Authorization and Cookie headers are removed, and
Set-Cookie headers are stripped from responses.

Usage:
    uv run python scripts/record_cookidoo.py --env-file ~/.config/cookidoo-mcp.env

The env file may use the ZNACHT_COOKIDOO_* names or the cookidoo-mcp COOKIDOO_* names.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
from pathlib import Path

from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.cookidoo.vcr_config import FUTURE_WEEK, SEARCH_QUERY, cassette

from znacht_cookidoo.session import CookidooSession, CookidooSettings


def settings_from(env_file: Path) -> CookidooSettings:
    raw = {k: v for k, v in dotenv_values(env_file).items() if v}
    env = {
        "ZNACHT_COOKIDOO_EMAIL": raw.get("ZNACHT_COOKIDOO_EMAIL") or raw.get("COOKIDOO_EMAIL", ""),
        "ZNACHT_COOKIDOO_PASSWORD": raw.get("ZNACHT_COOKIDOO_PASSWORD")
        or raw.get("COOKIDOO_PASSWORD", ""),
        "ZNACHT_COOKIDOO_COUNTRY": raw.get("ZNACHT_COOKIDOO_COUNTRY")
        or raw.get("COOKIDOO_COUNTRY", "ch"),
        "ZNACHT_COOKIDOO_LANGUAGE": raw.get("ZNACHT_COOKIDOO_LANGUAGE")
        or raw.get("COOKIDOO_LANGUAGE", "en"),
        # a throwaway token file: the recording never touches the user's real token
        "ZNACHT_COOKIDOO_TOKEN_FILE": os.path.join(
            tempfile.mkdtemp(prefix="znacht-rec-"), "token.json"
        ),
    }
    return CookidooSettings.from_env(env)


async def record(settings: CookidooSettings) -> str:
    async with CookidooSession(settings) as session:
        client = session.client
        assert client is not None
        with cassette("all"):
            result = await client.search_recipes(
                SEARCH_QUERY, locale=settings.language, languages=[settings.language], page_size=5
            )
            print(f"search: {len(result.recipes)} hits of {result.total}")
            first = result.recipes[0].id
            excluded = await client.search_recipes(
                SEARCH_QUERY,
                locale=settings.language,
                languages=[settings.language],
                exclude_ingredients=["cheese"],
                page_size=5,
            )
            print(f"search excluding cheese: {len(excluded.recipes)} hits")
            details = await client.get_recipe_details(first)
            print(f"details: {details.name} ({len(details.ingredients)} ingredients)")
            try:
                await client.get_recipe_details("r000000")
            except Exception as exc:
                print(f"unknown recipe -> {type(exc).__name__}")
            days = await client.get_recipes_in_calendar_week(
                FUTURE_WEEK, resolve_custom_recipes=True
            )
            print(f"week {FUTURE_WEEK}: {sum(len(d.recipes) for d in days)} planned recipes")
    return first


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    args = parser.parse_args()
    settings = settings_from(args.env_file)
    first = asyncio.run(record(settings))
    Path(settings.token_file).unlink(missing_ok=True)
    print(f"first recipe id (set KNOWN_RECIPE_ID in vcr_config.py): {first}")


if __name__ == "__main__":
    main()
