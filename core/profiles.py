"""Coherent fake technology profiles.

A contradictory fingerprint (IIS headers on an nginx error page) is itself
a signal: scanners flag the target as anomalous and a human looks closer.
Each profile therefore agrees with itself across Server, X-Powered-By,
session cookie, and — when a 404 body is requested — the error page.

Bodies are plausible HTML. They never contain the middleware name, the
word "tarpit", or filler like ``00000000``.
"""

from __future__ import annotations

import base64
import hashlib
import random
from dataclasses import dataclass


def _expand(seed: str, nbytes: int) -> bytes:
    material = hashlib.sha256(seed.encode("utf-8")).digest()
    buf = b""
    counter = 0
    while len(buf) < nbytes:
        buf += hashlib.sha256(material + counter.to_bytes(2, "big")).digest()
        counter += 1
    return buf[:nbytes]


def _b64(seed: str, nbytes: int) -> str:
    return base64.b64encode(_expand(seed, nbytes)).decode("ascii")


def _php_sid(seed: str) -> str:
    # 26 lowercase alphanumerics, the common PHP session id shape.
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
    raw = _expand(seed, 26)
    return "".join(alphabet[b % len(alphabet)] for b in raw)


def _asp_sid(seed: str) -> str:
    return _expand(seed, 12).hex()  # 24 hex chars


def _jsession(seed: str) -> str:
    return _expand(seed, 16).hex().upper()


@dataclass(frozen=True)
class StackProfile:
    profile_id: str
    server: str
    powered_by: str | None
    extra_headers: tuple[tuple[str, str], ...]
    cookie_name: str

    def cookie_value(self, session_key: str) -> str:
        if self.cookie_name == "ASP.NET_SessionId":
            return _asp_sid(session_key + ":asp")
        if self.cookie_name == "PHPSESSID":
            return _php_sid(session_key + ":php")
        return _jsession(session_key + ":j")

    def header_pairs(self, session_key: str) -> list[tuple[str, str]]:
        pairs = [
            ("server", self.server),
            ("content-type", "text/html; charset=utf-8"),
            ("cache-control", "no-store, no-cache, must-revalidate"),
            ("pragma", "no-cache"),
            ("x-content-type-options", "nosniff"),
        ]
        if self.powered_by:
            pairs.append(("x-powered-by", self.powered_by))
        pairs.extend(self.extra_headers)
        cookie = f"{self.cookie_name}={self.cookie_value(session_key)}; path=/; HttpOnly"
        pairs.append(("set-cookie", cookie))
        return pairs

    def asgi_headers(self, session_key: str, *, close: bool = False) -> list[tuple[bytes, bytes]]:
        pairs = self.header_pairs(session_key)
        if close:
            pairs.append(("connection", "close"))
        encoded: list[tuple[bytes, bytes]] = []
        for key, value in pairs:
            encoded.append((key.encode("latin-1"), value.encode("latin-1")))
        return encoded

    def document(self, session_key: str, *, status: int) -> bytes:
        raw = self.error_page(session_key) if status == 404 else self.loading_page(session_key)
        # Pad inside the body so a short error page still has a phase-2 tail.
        # The commitment chunk is ~512 bytes; without padding, a 150-byte
        # nginx error page would end immediately and the hold would not hold.
        return pad_document(raw, 1600)

    def loading_page(self, session_key: str) -> bytes:
        hidden = ""
        if self.profile_id == "iis":
            view = _b64(session_key + ":view", 96)
            gen = _expand(session_key + ":gen", 4).hex().upper()
            event = _b64(session_key + ":event", 24)
            hidden = (
                f'<input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE" value="{view}">'
                f'<input type="hidden" name="__VIEWSTATEGENERATOR" id="__VIEWSTATEGENERATOR" value="{gen}">'
                f'<input type="hidden" name="__EVENTVALIDATION" id="__EVENTVALIDATION" value="{event}">'
            )
        # Several kilobytes of ordinary prose so a slow slice still looks like HTML
        # when concatenated. No trademark of this middleware, no zero-runs.
        paragraphs = [
            "The requested document is being prepared for display. Please keep this window open.",
            "Catalog records are read from the primary shelf and checked against the evening index.",
            "If the page appears to pause, the transfer is still in progress and has not failed.",
            "Large finding aids are sent in order so that the first heading remains readable.",
            "You may leave this request running. Closing it will abandon the transfer.",
            "Margins, plate numbers, and accession notes are included when the record has them.",
            "A short delay here is the cost of reading a cold volume rather than a cached card.",
            "The reading room does not refresh this view automatically. The bytes continue on their own.",
            "Should the connection be interrupted, request the same shelf mark again from the index.",
            "Nothing on this page requires a script, a plugin, or a second host.",
        ]
        body = "".join(f"<p>{line}</p>" for line in paragraphs)
        # Repeat so phase-2 slicing still has real markup after thirty seconds
        # of 8–16 byte chunks. ~4 bytes/s * 30s is only ~120 bytes; the extra
        # copy is for shorter test intervals and for clients that read ahead.
        body = body + body
        html = (
            "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            "<title>Loading</title>"
            "<style>body{font-family:Georgia,serif;background:#f4f1ea;color:#222;margin:2rem}"
            "h1{font-weight:normal;font-size:1.5rem}p{line-height:1.55;max-width:38rem}</style>"
            "</head><body>"
            "<h1>Please wait</h1>"
            "<p>The requested resource is being prepared. This page will continue loading.</p>"
            f"{hidden}{body}</body></html>"
        )
        return html.encode("utf-8")

    def error_page(self, session_key: str) -> bytes:
        if self.profile_id == "iis":
            html = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>404 - File or directory not found.</title>
<style>
body{margin:0;font-family:"Segoe UI",Tahoma,sans-serif;background:#fff;color:#222}
.bar{background:#5c87b2;color:#fff;padding:14px 22px;font-size:1.35rem}
.wrap{padding:22px}
h2{font-size:1.15rem;margin:0 0 8px}
h3{font-size:1rem;font-weight:normal;color:#333}
</style>
</head>
<body>
<div class="bar">Server Error</div>
<div class="wrap">
<h2>404.0 - Not Found</h2>
<h3>The resource you are looking for has been removed, had its name changed, or is temporarily unavailable.</h3>
</div>
</body>
</html>
"""
            return html.encode("utf-8")
        if self.profile_id == "nginx":
            html = """<html>
<head><title>404 Not Found</title></head>
<body>
<center><h1>404 Not Found</h1></center>
<hr><center>nginx/1.18.0 (Ubuntu)</center>
</body>
</html>
"""
            return html.encode("utf-8")
        html = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>404 Not Found</title></head>
<body>
<h1>Not Found</h1>
<p>The requested URL was not found on this server.</p>
<hr>
<address>Apache/2.4.41 (Ubuntu) Server</address>
</body></html>
"""
        return html.encode("utf-8")

    def short_message(self, title: str, detail: str) -> bytes:
        if self.profile_id == "iis":
            html = (
                "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
                f"<title>{title}</title></head><body>"
                "<div style=\"background:#5c87b2;color:#fff;padding:12px 18px;font-family:Segoe UI,Tahoma,sans-serif\">"
                f"{title}</div><div style=\"padding:18px;font-family:Segoe UI,Tahoma,sans-serif\">"
                f"<h2>{detail}</h2></div></body></html>"
            )
        elif self.profile_id == "nginx":
            html = (
                "<html><head><title>"
                f"{title}</title></head><body><center><h1>{title}</h1></center>"
                f"<center><p>{detail}</p></center><hr><center>nginx/1.18.0 (Ubuntu)</center></body></html>"
            )
        else:
            html = (
                "<!DOCTYPE html><html><head><meta charset=\"utf-8\"><title>"
                f"{title}</title></head><body><h1>{title}</h1><p>{detail}</p>"
                "<hr><address>Apache/2.4.41 (Ubuntu) Server</address></body></html>"
            )
        return html.encode("utf-8")


IIS = StackProfile(
    profile_id="iis",
    server="Microsoft-IIS/10.0",
    powered_by="ASP.NET",
    extra_headers=(("x-aspnet-version", "4.0.30319"),),
    cookie_name="ASP.NET_SessionId",
)

NGINX = StackProfile(
    profile_id="nginx",
    server="nginx/1.18.0 (Ubuntu)",
    powered_by="PHP/8.1.2",
    extra_headers=(),
    cookie_name="PHPSESSID",
)

TOMCAT = StackProfile(
    profile_id="tomcat",
    server="Apache-Coyote/1.1",
    powered_by=None,
    extra_headers=(),
    cookie_name="JSESSIONID",
)

# Tomcat often emits X-Powered-By only when explicitly configured. The cookie
# and Coyote server token are the coherent pair; an extra PHP/ASP header would
# break the profile. Leave powered_by unset.
PROFILES: tuple[StackProfile, ...] = (IIS, NGINX, TOMCAT)


def select_profile(session_key: str) -> StackProfile:
    """Stable for the life of a session key. Not stable across key rotation."""
    digest = hashlib.sha256(session_key.encode("utf-8")).digest()
    return PROFILES[digest[0] % len(PROFILES)]


def pad_document(payload: bytes, minimum: int) -> bytes:
    if len(payload) >= minimum:
        return payload
    paragraph = (
        b"<p>The requested document is still being read from the shelf. "
        b"Please keep this window open.</p>"
    )
    repeats = ((minimum - len(payload)) // len(paragraph)) + 2
    block = paragraph * repeats
    idx = payload.lower().rfind(b"</body>")
    if idx == -1:
        return payload + block
    return payload[:idx] + block + payload[idx:]


def split_document(payload: bytes) -> tuple[bytes, bytes]:
    """Separate the closing tags so later filler stays inside the body."""
    idx = payload.lower().rfind(b"</body>")
    if idx == -1:
        return payload, b""
    return payload[:idx], payload[idx:]


_FILLER = (
    b"<p>Still reading. The transfer remains open and has not failed.</p>"
    b"<p>Shelf marks are checked in order. Please keep this window open.</p>"
) * 12


def take_filler(rng: random.Random, size_range: tuple[int, int], cursor: list[int]) -> bytes:
    """Next 8–16 byte slice of ordinary markup. Concatenation stays HTML."""
    lo, hi = size_range
    n = rng.randint(lo, hi)
    start = cursor[0]
    if start + n > len(_FILLER):
        start = 0
    cursor[0] = start + n
    return _FILLER[start : start + n]


def iter_stream_chunks(
    payload: bytes,
    preamble: int,
    size_range: tuple[int, int],
    rng: random.Random,
) -> list[bytes]:
    """Split a document into a fast commitment chunk plus 8–16 byte slices.

    The ASGI server frames these. Callers must send the bytes raw.
    """
    if not payload:
        return [b""]
    cut = min(preamble, len(payload))
    # Keep the cut on a character boundary for the utf-8 we generate (ASCII).
    chunks = [payload[:cut]]
    rest = payload[cut:]
    lo, hi = size_range
    index = 0
    while index < len(rest):
        remaining = len(rest) - index
        # A random cut can leave a 1-byte tail. That tail is not an 8–16 byte
        # slice, and a test that requires the lower bound will flake. If the
        # remainder fits in one legal slice, emit it. Otherwise refuse to
        # leave a tail shorter than `lo`.
        if remaining <= hi:
            chunks.append(rest[index:])
            break
        n = rng.randint(lo, hi)
        if remaining - n < lo:
            n = remaining - lo
            if n > hi:
                n = hi
            if n < lo:
                n = lo
        chunks.append(rest[index : index + n])
        index += n
    return chunks
