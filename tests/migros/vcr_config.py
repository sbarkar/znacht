"""VCR setup for the read-only Migros cassette. Scrubs tokens, cookies and account data."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import vcr

CASSETTE = str(Path(__file__).resolve().parent / "cassettes" / "migros_readonly.yaml")
SEARCH_QUERY = "broccoli"
SECOND_QUERY = "natural yogurt"
KNOWN_PRODUCT_ID = "100025235"  # Migros broccoli, first hit of the recorded search

_LOGIN_HOSTS = ("login.migros.ch", "account.migros.ch")
_DROP_REQUEST_HEADERS = ("authorization", "cookie", "leshopch")
_DROP_RESPONSE_HEADERS = frozenset(
    {
        "set-cookie",
        "cf-ray",
        "cf-cache-status",
        "report-to",
        "nel",
        "x-request-id",
        "x-amz-cf-id",
        "x-amz-cf-pop",
        "via",
        "x-cache",
        "age",
        "date",
        "etag",
        "server-timing",
        "x-correlation-id",
        "correlation-id",
        "traceparent",
    }
)
_SCRUB_KEYS = re.compile(
    rb'"(accessToken|access_token|token|jwt|firstName|lastName|personId|badgeIdentifier|email|'
    rb'userId|customerId|houseKey|streetName|streetNumber|city)"\s*:\s*"[^"]*"'
)


def _scrub_request(request: Any) -> Any | None:
    if any(h in request.uri for h in _LOGIN_HOSTS) or "/oauth/" in request.uri:
        return None
    for header in list(request.headers):
        if header.lower() in _DROP_REQUEST_HEADERS:
            request.headers.pop(header, None)
    return request


def _scrub_response(response: dict[str, Any]) -> dict[str, Any]:
    headers = response.get("headers", {})
    for key in list(headers):
        if key.lower() in _DROP_RESPONSE_HEADERS:
            headers.pop(key)
        elif key.lower() == "leshopch":
            headers[key] = ["replay-guest-token"]  # anonymous, short-lived; value is irrelevant
    body = response.get("body", {})
    if isinstance(body, dict):
        raw = body.get("string")
        if isinstance(raw, bytes):
            body["string"] = _SCRUB_KEYS.sub(rb'"\1":"<scrubbed>"', raw)
        elif isinstance(raw, str):
            body["string"] = _SCRUB_KEYS.sub(rb'"\1":"<scrubbed>"', raw.encode()).decode()
    return response


def cassette(record_mode: str = "none") -> Any:
    return vcr.VCR(
        record_mode=record_mode,
        match_on=["method", "scheme", "host", "path", "query", "body"],
        before_record_request=_scrub_request,
        before_record_response=_scrub_response,
        decode_compressed_response=True,
    ).use_cassette(CASSETTE, allow_playback_repeats=True)
