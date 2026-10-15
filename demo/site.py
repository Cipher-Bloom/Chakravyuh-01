"""Meridian Ledger — the application CHAKRAVYUH sits in front of.

This surface is intentionally ordinary. It has a real fingerprint
(``Server: uvicorn``, added by the inner identity middleware) so a scanner
that has not yet crossed the threshold can be classified, and so a scanner
that has crossed it can be shown a different one. Nothing here names the
middleware.
"""
from __future__ import annotations

from fastapi.staticfiles import StaticFiles

import logging

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

logger = logging.getLogger("chakravyuh.origin")

FAVICON = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    '<rect width="32" height="32" rx="3" fill="#1c1915"/>'
    '<path d="M16 5.5c6.2 0 10.5 4.2 10.5 9.2S22.2 22 17.2 22s-5.2-2.2-5.2-4.6'
    ' 1.8-3.2 3.8-3.2 2.2 1.1 2.2 2.1" fill="none" stroke="#c4a574" stroke-width="1.4"/>'
    "</svg>"
)

_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · Meridian Ledger</title>
<link rel="icon" href="/favicon.ico" type="image/svg+xml">
<style>
:root {{ color-scheme: light; }}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; }}
body {{
  font-family: Palatino, "Palatino Linotype", "Iowan Old Style", Georgia, serif;
  background: #f3efe6;
  color: #1c1915;
  min-height: 100vh;
}}
body::before {{
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  background:
    radial-gradient(ellipse at 0% 0%, rgba(140, 58, 47, 0.06), transparent 42%),
    radial-gradient(ellipse at 100% 100%, rgba(90, 70, 40, 0.05), transparent 40%);
}}
.wrap {{ max-width: 760px; margin: 0 auto; padding: 48px 28px 80px; position: relative; }}
header {{ display: flex; justify-content: space-between; align-items: baseline; gap: 16px; }}
.mark {{ letter-spacing: 0.18em; text-transform: uppercase; font-size: 12px; color: #8c3a2f; }}
nav a {{ color: #1c1915; text-decoration: none; margin-left: 18px; font-size: 15px; border-bottom: 1px solid transparent; }}
nav a:hover {{ border-bottom-color: #8c3a2f; }}
/* New styling for the training button to make it pop for the panel */
.training-btn {{ color: #602ff7 !important; font-weight: bold; border-bottom: 1px solid #602ff7 !important; }}
h1 {{ font-weight: normal; font-size: 46px; line-height: 1.05; margin: 36px 0 12px; letter-spacing: -0.02em; }}
.lede {{ font-size: 19px; line-height: 1.5; max-width: 38rem; color: #3a342c; }}
.rule {{ height: 1px; background: #d9d0c2; margin: 28px 0; border: 0; }}
.shelf {{ display: grid; gap: 14px; }}
article {{
  background: rgba(255,252,247,0.72);
  border: 1px solid #e2d8c8;
  padding: 16px 18px;
}}
.sid {{ font-family: ui-monospace, "Cascadia Mono", Menlo, Consolas, monospace; font-size: 12px; letter-spacing: 0.08em; color: #8c3a2f; }}
h2 {{ font-weight: normal; font-size: 22px; margin: 6px 0; }}
p {{ line-height: 1.55; }}
form {{ display: grid; gap: 12px; max-width: 360px; }}
label {{ font-size: 13px; letter-spacing: 0.08em; text-transform: uppercase; color: #6d6458; }}
input {{
  font: inherit; font-size: 16px; padding: 10px 12px;
  border: 1px solid #c9bfb0; background: #fffdf9; color: #1c1915;
}}
button {{
  font: inherit; font-size: 15px; padding: 10px 14px; width: fit-content;
  background: #1c1915; color: #f3efe6; border: 0; cursor: pointer;
}}
.err {{ color: #8c3a2f; }}
footer {{ margin-top: 48px; font-size: 13px; color: #6d6458; display: flex; justify-content: space-between; gap: 12px; }}
footer a {{ color: #8c3a2f; }}
</style>
</head>
<body>
<div class="wrap">
<header>
  <div class="mark">Meridian Ledger</div>
  <nav>
    <a href="/">Index</a>
    <a href="/about">About</a>
    <a href="/login">Sign in</a>
    <a href="/training/index.html" class="training-btn">Cyber Training 🎮</a>{nav}
  </nav>
</header>
{body}
<footer>
  <span>Reading room catalog · not a public archive</span>
  {console}
</footer>
</div>
</body>
</html>
"""


def _page(title: str, body: str, *, console: str, nav_extra: str = "") -> str:
    return _PAGE.format(title=title, body=body, console=console, nav=nav_extra)


def register_demo(app: FastAPI, expose_console_link: bool) -> None:
    console = (
        '<a href="/metrics">Metrics</a>'
        if expose_console_link
        else "<span>Shelf access by appointment</span>"
    )
    nav_extra = (
        '<a href="/metrics">Metrics</a>' if expose_console_link else ""
    )

    @app.get("/", response_class=HTMLResponse)
    async def home() -> HTMLResponse:
        body = """
<h1>The evening index.</h1>
<p class="lede">Meridian Ledger keeps finding aids for a small reading room. Search is closed this week while the shelf marks are checked against the accession book.</p>
<hr class="rule">
<div class="shelf">
  <article>
    <div class="sid">ML-1044</div>
    <h2>River surveys of the upper Ganga</h2>
    <p>Field notes, 1928. Plates stored separately. Ask the desk for the folio.</p>
  </article>
  <article>
    <div class="sid">ML-2210</div>
    <h2>Meerut cantonment water tables</h2>
    <p>Compiled 1956 from municipal returns. Marginalia in pencil is not part of the record.</p>
  </article>
  <article>
    <div class="sid">ML-0881</div>
    <h2>Correspondence on the Eastern Jumna canal</h2>
    <p>Bound letters, 1889–1894. Several leaves are fragile; copies are on the side table.</p>
  </article>
</div>
"""
        return HTMLResponse(_page("Index", body, console=console, nav_extra=nav_extra))

    @app.get("/about", response_class=HTMLResponse)
    async def about() -> HTMLResponse:
        body = """
<h1>About the room.</h1>
<p class="lede">The ledger is an internal catalog. It does not lend, it does not sell, and it does not mirror the stacks onto the public web.</p>
<p>Hours are posted at the desk. Remote readers may request a shelf mark through the duty archivist; the form on this site only confirms that a credential is known to the room.</p>
"""
        return HTMLResponse(_page("About", body, console=console, nav_extra=nav_extra))

    form = """
<h1>Sign in.</h1>
<p class="lede">Staff credentials only. A failed attempt is not a hint.</p>
<form method="post" action="/login" autocomplete="off">
  <label for="username">Name</label>
  <input id="username" name="username" type="text" autocomplete="username">
  <label for="password">Passphrase</label>
  <input id="password" name="password" type="password" autocomplete="current-password">
  <button type="submit">Continue</button>
</form>
"""

    @app.get("/login", response_class=HTMLResponse)
    async def login_form() -> HTMLResponse:
        return HTMLResponse(_page("Sign in", form, console=console, nav_extra=nav_extra))

    @app.post("/login", response_class=HTMLResponse)
    async def login_post(request: Request) -> HTMLResponse:
        # Drain and discard. The passphrase is not logged, stored, or reflected.
        await request.body()
        body = '<p class="err">Those credentials were not recognized.</p>' + form
        return HTMLResponse(_page("Sign in", body, console=console, nav_extra=nav_extra), status_code=401)

    @app.get("/api/health")
    async def api_health() -> JSONResponse:
        return JSONResponse({"status": "ok", "service": "meridian-ledger"})

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @app.get("/api/users")
    async def api_users() -> JSONResponse:
        return JSONResponse(
            {
                "readers": [
                    {"id": "r-14", "role": "desk", "open_requests": 2},
                    {"id": "r-22", "role": "conservator", "open_requests": 0},
                ]
            }
        )

    @app.get("/robots.txt")
    async def robots() -> Response:
        return Response("User-agent: *\nDisallow: /login\n", media_type="text/plain")

    @app.get("/favicon.ico")
    async def favicon() -> Response:
        return Response(FAVICON, media_type="image/svg+xml")

    @app.exception_handler(404)
    async def not_found(request: Request, exc: Exception) -> Response:
        path = request.url.path
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        body = """
<h1>Not in the index.</h1>
<p class="lede">That shelf mark is not in the evening catalog. Check the accession number and try the index.</p>
"""
        return HTMLResponse(_page("Not found", body, console=console, nav_extra=nav_extra), status_code=404)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> HTMLResponse:
        logger.exception("origin failed on %s", request.url.path)
        body = "<h1>The desk is unavailable.</h1><p>The archive could not complete that request.</p>"
        return HTMLResponse(_page("Error", body, console=console, nav_extra=nav_extra), status_code=500)
