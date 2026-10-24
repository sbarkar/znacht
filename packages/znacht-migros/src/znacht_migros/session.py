"""Migros auth: guest token for the catalogue, SSO cookies + JWT for the account.

The session file has the same shape as migros-mcp's ``session.json`` so an existing one
can be reused: ``{"cookies": {host: {name: value}}, "jwt": str|null, "jwtExp": int}``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import httpx

from znacht.http import guarded_async_client

WWW = "https://www.migros.ch"
LOGIN = "https://login.migros.ch"
REDIRECT_URI = f"{WWW}/m-login-silent-login-redirect.html"
# Per-host user agents: Akamai on www.migros.ch rejects Chrome UAs; the login origin
# (Cloudflare) accepts them. Same approach as migros-api-wrapper and migros-mcp.
UA_WWW = "Mozilla/5.0 (X11; Linux x86_64; rv:144.0) Gecko/20100101 Firefox/144.0"
UA_LOGIN = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
)
DEFAULT_SESSION_FILE = Path("~/.config/znacht/migros-session.json")


class MigrosAuthError(RuntimeError):
    pass


@dataclass(frozen=True)
class MigrosSettings:
    session_file: Path = field(default_factory=lambda: DEFAULT_SESSION_FILE.expanduser())
    email: str | None = None
    password: str | None = None
    totp_secret: str | None = None
    language: str = "en"
    minimum_order: str = "99"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> MigrosSettings:
        e = os.environ if env is None else env
        sf = e.get("ZNACHT_MIGROS_SESSION_FILE")
        return cls(
            session_file=Path(sf).expanduser() if sf else DEFAULT_SESSION_FILE.expanduser(),
            email=e.get("ZNACHT_MIGROS_EMAIL") or None,
            password=e.get("ZNACHT_MIGROS_PASSWORD") or None,
            totp_secret=e.get("ZNACHT_MIGROS_TOTP_SECRET") or None,
            language=e.get("ZNACHT_MIGROS_LANGUAGE", "en"),
            minimum_order=e.get("ZNACHT_MIGROS_MINIMUM_ORDER", "99"),
        )


def totp_code(secret_base32: str, now: float | None = None, step: int = 30, digits: int = 6) -> str:
    cleaned = re.sub(r"\s+", "", secret_base32).rstrip("=").upper()
    key = base64.b32decode(cleaned + "=" * (-len(cleaned) % 8))
    counter = int((now if now is not None else time.time()) // step)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**digits).zfill(digits)


def jwt_exp(token: str) -> int:
    parts = token.split(".")
    if len(parts) != 3:
        raise MigrosAuthError("malformed JWT")
    payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
    exp = payload.get("exp")
    if not isinstance(exp, int):
        raise MigrosAuthError("JWT has no exp claim")
    return exp


class SessionStore:
    """Cookies per host plus the cached JWT, persisted atomically with mode 0600."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.cookies: dict[str, dict[str, str]] = {}
        self.jwt: str | None = None
        self.jwt_exp = 0
        self.load()

    def load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        self.cookies = {h: dict(c) for h, c in (data.get("cookies") or {}).items()}
        self.jwt = data.get("jwt") or None
        self.jwt_exp = int(data.get("jwtExp") or 0)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(
                {"cookies": self.cookies, "jwt": self.jwt, "jwtExp": self.jwt_exp}, indent=2
            ),
            encoding="utf-8",
        )
        tmp.chmod(0o600)
        tmp.replace(self.path)

    def ingest(self, host: str, response: httpx.Response) -> None:
        for raw in response.headers.get_list("set-cookie"):
            pair = raw.split(";", 1)[0]
            if "=" in pair:
                name, value = pair.split("=", 1)
                if name.strip():
                    self.cookies.setdefault(host, {})[name.strip()] = value.strip()

    def cookie_header(self, host: str) -> str:
        return "; ".join(f"{k}={v}" for k, v in self.cookies.get(host, {}).items())

    @property
    def has_sso_cookies(self) -> bool:
        return bool(self.cookies.get("login.migros.ch"))


def _ua(host: str) -> str:
    return UA_WWW if host == "www.migros.ch" else UA_LOGIN


class MigrosSession:
    """Owns the HTTP client, the guest token and the account JWT."""

    def __init__(self, settings: MigrosSettings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self.store = SessionStore(settings.session_file)
        self._client = client or guarded_async_client(timeout=30.0, follow_redirects=False)
        self._own_client = client is None
        self._guest: str | None = None

    async def __aenter__(self) -> MigrosSession:
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._own_client:
            await self._client.aclose()

    # -- plumbing -------------------------------------------------------------------
    def _headers(
        self, host: str, accept: str, extra: dict[str, str] | None = None
    ) -> dict[str, str]:
        h = {
            "User-Agent": _ua(host),
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
        }
        cookie = self.store.cookie_header(host)
        if cookie:
            h["Cookie"] = cookie
        if extra:
            h.update(extra)
        return h

    async def _request(
        self,
        method: str,
        url: str,
        *,
        accept: str = "application/json, text/plain, */*",
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        host = urlparse(url).netloc
        response = await self._client.request(
            method, url, headers=self._headers(host, accept, headers), **kwargs
        )
        self.store.ingest(host, response)
        return response

    # -- guest token (anonymous catalogue endpoints) ---------------------------------
    async def guest_token(self, *, force: bool = False) -> str:
        if self._guest and not force:
            return self._guest
        r = await self._request(
            "GET",
            f"{WWW}/authentication/public/v1/api/guest",
            params={"authorizationNotRequired": "true"},
        )
        token = r.headers.get("leshopch")
        if r.status_code != 200 or not token:
            raise MigrosAuthError(f"guest token request failed: {r.status_code}")
        self._guest = str(token)
        return self._guest

    async def anonymous(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        token = await self.guest_token()
        r = await self._request(method, f"{WWW}{path}", headers={"leshopch": token}, **kwargs)
        if r.status_code in (401, 403):
            token = await self.guest_token(force=True)
            r = await self._request(method, f"{WWW}{path}", headers={"leshopch": token}, **kwargs)
        return r

    # -- account JWT ------------------------------------------------------------------
    async def jwt(self, buffer_seconds: int = 60) -> str:
        if self.store.jwt and self.store.jwt_exp - int(time.time()) > buffer_seconds:
            return str(self.store.jwt)
        if self.store.has_sso_cookies:
            try:
                return await self.silent_oauth()
            except MigrosAuthError:
                if not (self.settings.email and self.settings.password):
                    raise
        if not (self.settings.email and self.settings.password):
            raise MigrosAuthError(
                f"no Migros session at {self.settings.session_file} and no credentials; "
                "copy migros-mcp's session.json there or set "
                "ZNACHT_MIGROS_EMAIL/PASSWORD/TOTP_SECRET"
            )
        return await self.full_login()

    async def silent_oauth(self) -> str:
        """Mint a JWT from the SSO cookies: authorize → prompt=none login → login-success."""
        q = urlencode(
            {
                "redirectUri": REDIRECT_URI,
                "withLoginPrompt": "false",
                "claimType": "LOGIN",
                "authorizationNotRequired": "true",
            }
        )
        r = await self._request("GET", f"{WWW}/authentication/public/v1/api/oauth/authorize?{q}")
        if r.status_code != 200:
            raise MigrosAuthError(f"oauth/authorize -> {r.status_code}")
        sso_url = r.json().get("url")
        if not sso_url:
            raise MigrosAuthError("oauth/authorize returned no sso url")
        r = await self._request("GET", sso_url, accept="text/html")
        location = r.headers.get("location")
        if not location:
            raise MigrosAuthError("silent SSO did not redirect: login.migros.ch session expired")
        qs = parse_qs(urlparse(location).query)
        code, state = qs.get("code", [None])[0], qs.get("state", [None])[0]
        if not code or not state:
            raise MigrosAuthError("silent SSO redirected without code/state")
        q = urlencode(
            {
                "code": code,
                "state": state,
                "redirectUri": REDIRECT_URI,
                "authorizationNotRequired": "true",
            }
        )
        r = await self._request(
            "GET",
            f"{WWW}/authentication/public/v1/api/oauth/login-success?{q}",
            accept="application/json",
        )
        if r.status_code != 200:
            raise MigrosAuthError(f"oauth/login-success -> {r.status_code}")
        body = r.json()
        token = body.get("accessToken") or body.get("access_token") or body.get("token")
        if not isinstance(token, str):
            raise MigrosAuthError("login-success returned no token")
        token = re.sub(r"^bearer\s+", "", token, flags=re.I)
        self.store.jwt, self.store.jwt_exp = token, jwt_exp(token)
        self.store.save()
        return token

    async def full_login(self) -> str:
        """Email → password → TOTP on login.migros.ch, then silent OAuth. Password never stored."""
        s = self.settings
        assert s.email and s.password

        async def get(url: str) -> httpx.Response:
            return await self._request("GET", url, accept="text/html,application/json")

        async def post_form(url: str, data: dict[str, str]) -> httpx.Response:
            host = urlparse(url).netloc
            return await self._request(
                "POST",
                url,
                accept="text/html",
                data=data,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Origin": f"https://{host}",
                    "Referer": url,
                },
            )

        def csrf(html: str) -> str:
            m = re.search(r'name="_csrf"[^>]*value="([^"]+)"', html)
            if not m:
                raise MigrosAuthError("could not find the CSRF token in the login form")
            return m.group(1)

        def action(html: str, fallback: str) -> str:
            m = re.search(r'<form[^>]+action="([^"]*)"', html)
            return urljoin(fallback, m.group(1)) if m else fallback

        def error(html: str) -> str:
            m = re.search(r"info-message-error[^>]*>[\s\S]*?<div[^>]*>([\s\S]{0,200})<", html)
            return (
                re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1))).strip()
                if m
                else "unknown error"
            )

        r = await get(f"{LOGIN}/login")
        if 300 <= r.status_code < 400 and r.headers.get("location"):
            r = await get(urljoin(LOGIN, r.headers["location"]))
        r = await post_form(
            f"{LOGIN}/login/email",
            {"_csrf": csrf(r.text), "authenticationPayload": "", "email": s.email},
        )
        nxt = r.headers.get("location")
        if not nxt:
            raise MigrosAuthError(f"email step rejected: {error(r.text)}")
        nxt = urljoin(LOGIN, nxt)
        if "/login/passkey" in nxt:
            nxt = f"{LOGIN}/login/password"
        r = await get(nxt)
        r = await post_form(action(r.text, nxt), {"_csrf": csrf(r.text), "password": s.password})
        nxt = r.headers.get("location")
        if not nxt:
            raise MigrosAuthError(f"password step rejected: {error(r.text)}")
        nxt = urljoin(LOGIN, nxt)
        if "/login/passkey" in nxt:
            nxt = f"{LOGIN}/login/authenticator"
        if re.search(r"/login/(authenticator|second|totp|otp)", nxt):
            if not s.totp_secret:
                raise MigrosAuthError("the account requires 2FA but no TOTP seed was provided")
            r = await get(nxt)
            r = await post_form(
                action(r.text, nxt), {"_csrf": csrf(r.text), "code": totp_code(s.totp_secret)}
            )
            nxt = r.headers.get("location")
            if not nxt:
                raise MigrosAuthError(f"OTP step rejected: {error(r.text)}")
            nxt = urljoin(LOGIN, nxt)
        for _ in range(10):
            r = await get(nxt)
            loc = r.headers.get("location")
            if not loc:
                break
            nxt = urljoin(nxt, loc)
        self.store.save()
        return await self.silent_oauth()

    async def api(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Authenticated call against www.migros.ch, retrying once after a silent refresh."""
        token = await self.jwt()
        headers = {
            "Authorization": f"Bearer {token}",
            "migros-language": self.settings.language,
            "accept-language": self.settings.language,
            "peer-id": "website-js-1143.0.0",
            "Origin": WWW,
            "Referer": f"{WWW}/{self.settings.language}",
        }
        r = await self._request(method, f"{WWW}{path}", headers=headers, **kwargs)
        if r.status_code == 401:
            token = await self.silent_oauth()
            headers["Authorization"] = f"Bearer {token}"
            r = await self._request(method, f"{WWW}{path}", headers=headers, **kwargs)
        self.store.save()
        return r
