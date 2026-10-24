"""Login once, persist only the OAuth tokens, refresh transparently."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Self

from aiohttp import ClientSession, CookieJar
from cookidoo_api import (
    Cookidoo,
    CookidooAuthData,
    CookidooConfig,
    CookidooLocalizationConfig,
    get_localization_options,
)

DEFAULT_TOKEN_FILE = Path("~/.config/znacht/cookidoo-token.json")


@dataclass(frozen=True)
class CookidooSettings:
    email: str
    password: str | None = None
    country: str = "ch"
    language: str = "en"
    token_file: Path = field(default_factory=lambda: DEFAULT_TOKEN_FILE.expanduser())

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> CookidooSettings:
        """Read ``ZNACHT_COOKIDOO_*`` variables. The password is optional once a token exists."""
        e = os.environ if env is None else env
        email = e.get("ZNACHT_COOKIDOO_EMAIL")
        if not email:
            raise ValueError("ZNACHT_COOKIDOO_EMAIL is not set")
        token = e.get("ZNACHT_COOKIDOO_TOKEN_FILE")
        return cls(
            email=email,
            password=e.get("ZNACHT_COOKIDOO_PASSWORD") or None,
            country=e.get("ZNACHT_COOKIDOO_COUNTRY", "ch"),
            language=e.get("ZNACHT_COOKIDOO_LANGUAGE", "en"),
            token_file=Path(token).expanduser() if token else DEFAULT_TOKEN_FILE.expanduser(),
        )


async def resolve_localization(country: str, language: str) -> CookidooLocalizationConfig:
    options = await get_localization_options(country=country)
    wanted = language.lower()
    for option in options:
        if option.language.lower() in (wanted, f"{wanted}-{country}".lower()):
            return option
    known = ", ".join(o.language for o in options) or "none"
    raise ValueError(
        f"no Cookidoo localisation {language!r} for country {country!r} (known: {known})"
    )


def _write_token(path: Path) -> Callable[[CookidooAuthData], None]:
    def save(auth: CookidooAuthData) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(vars(auth)), encoding="utf-8")
        tmp.chmod(0o600)
        tmp.replace(path)

    return save


class CookidooSession:
    """Async context manager that yields a logged-in :class:`Cookidoo` client.

    On first use it logs in with email and password and writes the tokens to the token
    file. Later uses load the token file, never the password. Every refresh is written back.
    """

    def __init__(self, settings: CookidooSettings) -> None:
        self._settings = settings
        self._http: ClientSession | None = None
        self.client: Cookidoo | None = None

    async def __aenter__(self) -> Self:
        s = self._settings
        localization = await resolve_localization(s.country, s.language)
        self._http = ClientSession(cookie_jar=CookieJar(unsafe=True))
        cfg = CookidooConfig(localization=localization, email=s.email, password=s.password or "")
        client = Cookidoo(self._http, cfg, on_auth_data_update=_write_token(s.token_file))
        try:
            if s.token_file.exists():
                client.load_token(s.token_file)
            else:
                if not s.password:
                    raise PermissionError(
                        f"no token at {s.token_file} and no password: complete the first login"
                    )
                await client.login()
                client.save_token(s.token_file)
                s.token_file.chmod(0o600)
        except BaseException:
            await self._http.close()
            self._http = None
            raise
        self.client = client
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._http is not None:
            await self._http.close()
        self._http = None
        self.client = None
