"""VCR setup shared by the recording script and the replay tests. Scrubs every secret."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

import vcr

HERE = Path(__file__).resolve().parent
CASSETTE_DIR = HERE / "cassettes"
CASSETTE = str(CASSETTE_DIR / "cookidoo_readonly.yaml")
KNOWN_RECIPE_ID = "r769256"  # first hit of the recorded "pasta" search
SEARCH_QUERY = "pasta"
FUTURE_WEEK = date(2027, 3, 1)  # a Monday far enough ahead to be empty

_LOGIN_HOSTS = ("ciam.prod.cookidoo.vorwerk-digital.com", "vorwerk-digital.com")
_TOKEN_RE = re.compile(
    rb'"(access_token|refresh_token|id_token|userId|customerId|email|username)"\s*:\s*"[^"]*"'
)
_DROP_RESPONSE_HEADERS = frozenset(
    {
        "set-cookie",
        "cf-ray",
        "report-to",
        "nel",
        "x-request-id",
        "x-xsrf-token",
        "correlation-id",
        "x-amz-cf-id",
        "x-amz-cf-pop",
        "via",
        "x-cache",
        "age",
        "date",
        "etag",
    }
)


def _scrub_request(request: Any) -> Any | None:
    if any(h in request.uri for h in _LOGIN_HOSTS):
        return None  # the whole login flow is never recorded
    for header in ("Authorization", "Cookie", "authorization", "cookie"):
        request.headers.pop(header, None)
    return request


def _scrub_response(response: dict[str, Any]) -> dict[str, Any]:
    headers = response.get("headers", {})
    for key in list(headers):
        if key.lower() in _DROP_RESPONSE_HEADERS:
            headers.pop(key)
    body = response.get("body", {})
    if isinstance(body, dict):
        raw = body.get("string")
        if isinstance(raw, bytes):
            body["string"] = _TOKEN_RE.sub(rb'"\1":"<scrubbed>"', raw)
        elif isinstance(raw, str):
            body["string"] = _TOKEN_RE.sub(rb'"\1":"<scrubbed>"', raw.encode()).decode()
    return response


def make_vcr(record_mode: str = "none") -> vcr.VCR:
    return vcr.VCR(
        record_mode=record_mode,
        match_on=["method", "scheme", "host", "path", "query"],
        filter_headers=["Authorization", "Cookie"],
        before_record_request=_scrub_request,
        before_record_response=_scrub_response,
        decode_compressed_response=True,
    )


def cassette(record_mode: str = "none") -> Any:
    """The single read-only cassette; repeats allowed so several clients can replay discovery."""
    return make_vcr(record_mode).use_cassette(CASSETTE, allow_playback_repeats=True)
