"""Genuine application fingerprint, applied only on the pass-through path.

Distorted requests never reach this middleware, so a scanner that has
crossed the threshold cannot observe the real Server token. Uvicorn itself
must be started with ``server_header=False`` or it will append a second
Server header and undo the mutation.
"""

from __future__ import annotations


class RealIdentityMiddleware:
    def __init__(self, app, server_header: str = "uvicorn", skip_prefixes: tuple[str, ...] = ("/chakravyuh-dashboard", "/metrics")) -> None:
        self.app = app
        self.server_header = server_header.encode("latin-1")
        self.skip_prefixes = skip_prefixes

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path") or ""
        if any(path.startswith(prefix) for prefix in self.skip_prefixes):
            await self.app(scope, receive, send)
            return

        async def send_wrap(message):
            if message["type"] == "http.response.start":
                headers = [
                    (key, value)
                    for key, value in (message.get("headers") or [])
                    if key.lower() != b"server"
                ]
                headers.append((b"server", self.server_header))
                message = dict(message)
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrap)
