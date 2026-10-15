"""Client identity and trusted-proxy X-Forwarded-For handling.

X-Forwarded-For is attacker-controlled unless the immediate TCP peer is a
reverse proxy you operate. This module ignores XFF unless that peer is in
the configured allowlist, then walks the chain from the right and skips
other trusted hops. That is the opposite of "trust the leftmost value",
which a client can spoof with a single header.
"""

from __future__ import annotations

import hashlib
import ipaddress
from typing import Mapping

from core.config import ChakravyuhConfig

_Network = ipaddress.IPv4Network | ipaddress.IPv6Network


def normalize_ip(value: str) -> str:
    addr = ipaddress.ip_address(value.strip())
    mapped = getattr(addr, "ipv4_mapped", None)
    if mapped is not None:
        return str(mapped)
    return str(addr)


def parse_ip_token(token: str) -> str | None:
    """Parse one XFF list element. Returns a normalized IP or None."""
    token = token.strip().strip('"').strip("'")
    if not token or token.lower() == "unknown":
        return None
    if token.startswith("["):
        end = token.find("]")
        if end == -1:
            return None
        inner = token[1:end]
        try:
            return normalize_ip(inner)
        except ValueError:
            return None
    try:
        return normalize_ip(token)
    except ValueError:
        pass
    # IPv4:port only. Bare IPv6 has more than one colon and was already tried.
    if token.count(":") == 1:
        host, port = token.rsplit(":", 1)
        if port.isdigit():
            try:
                return normalize_ip(host)
            except ValueError:
                return None
    return None


def is_trusted(ip: str, networks: tuple[_Network, ...]) -> bool:
    if not networks:
        return False
    try:
        addr = ipaddress.ip_address(normalize_ip(ip))
    except ValueError:
        return False
    return any(addr in net for net in networks)


def resolve_client_ip(
    peer: str | None,
    xff: str | None,
    trusted: tuple[_Network, ...],
) -> tuple[str, str]:
    """Return ``(client_ip, source)`` where source is ``peer`` or ``xff``."""
    peer_ip = "0.0.0.0"
    if peer:
        try:
            peer_ip = normalize_ip(peer)
        except ValueError:
            peer_ip = "0.0.0.0"
    if not xff or not is_trusted(peer_ip, trusted):
        return peer_ip, "peer"
    parts = [parsed for parsed in (parse_ip_token(p) for p in xff.split(",")) if parsed]
    if not parts:
        return peer_ip, "peer"
    for ip in reversed(parts):
        if not is_trusted(ip, trusted):
            return ip, "xff"
    return parts[0], "xff"


def decode_header_value(value: bytes | str) -> str:
    """Never raise on scanner garbage. Invalid UTF-8 becomes U+FFFD."""
    if isinstance(value, str):
        return value
    return value.decode("utf-8", errors="replace")


def headers_as_dict(raw_headers: list[tuple[bytes, bytes]] | None) -> dict[str, str]:
    """Lower-case header map. Repeated headers are joined, cookies with '; '."""
    out: dict[str, str] = {}
    for key, value in raw_headers or []:
        try:
            name = decode_header_value(key).lower().strip()
        except Exception:
            continue
        if not name:
            continue
        decoded = decode_header_value(value)
        if name in out:
            sep = "; " if name == "cookie" else ", "
            out[name] = out[name] + sep + decoded
        else:
            out[name] = decoded
    return out


def parse_cookies(cookie_header: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    if not cookie_header:
        return cookies
    for part in cookie_header.split(";"):
        if "=" not in part:
            continue
        name, _, value = part.partition("=")
        name = name.strip()
        if name and name not in cookies:
            cookies[name] = value.strip()
    return cookies


def session_key(
    ip: str,
    headers: Mapping[str, str],
    config: ChakravyuhConfig,
) -> tuple[str, str]:
    """Return ``(key, method)``.

    Default method is ``fingerprint``: SHA-256 of IP + User-Agent +
    Accept-Language. Raw IP is the fallback when both headers are absent
    (so a headerless scanner cannot mint a new key by omission alone — all
    such clients on one IP share a bucket).

    Cookie keying is opt-in. A scanner that sends a fresh cookie on every
    request would otherwise zero its history. Do not enable it unless the
    application session id is authenticated and unforgeable.
    """
    if config.trust_session_cookie:
        sid = parse_cookies(headers.get("cookie", "")).get(config.session_cookie_name, "")
        if sid:
            digest = hashlib.sha256(sid.encode("utf-8", errors="replace")).hexdigest()
            return f"cookie:{digest}", "cookie"
    ua = headers.get("user-agent", "").strip()
    lang = headers.get("accept-language", "").strip()
    if ua or lang:
        material = f"{ip}|{ua}|{lang}".encode("utf-8", errors="replace")
        digest = hashlib.sha256(material).hexdigest()
        return f"fp:{digest}", "fingerprint"
    return f"ip:{ip}", "ip"


def is_known_path(path: str, config: ChakravyuhConfig) -> bool:
    """True when the path belongs to the real application surface.

    Used only to estimate 404s on the distortion path, where the real app
    is never called. Pass-through corrects this guess from the real status.
    """
    if not path:
        path = "/"
    candidates = {path}
    if path != "/" and path.endswith("/"):
        candidates.add(path[:-1])
    elif path != "/":
        candidates.add(path + "/")
    if candidates & set(config.known_paths):
        return True
    for prefix in config.known_prefixes:
        if prefix and path.startswith(prefix):
            return True
    return False


def peer_ip_from_scope(scope: dict) -> str | None:
    client = scope.get("client")
    if not client:
        return None
    host = client[0]
    if isinstance(host, bytes):
        host = decode_header_value(host)
    return str(host)
