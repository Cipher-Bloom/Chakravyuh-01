# CHAKRAVYUH

Session-scoped HTTP middleware that detects automated reconnaissance and degrades it. Two mechanisms, both applied **before** the request reaches the origin:

1. **Coherent stack mutation.** A detected client sees one consistent fake profile for the whole session (IIS/ASP.NET, nginx/PHP, or Apache Coyote/Tomcat): `Server`, `X-Powered-By`, session cookie, and a plausible HTML body. Contradictory fingerprints are not used. They are themselves a signal.
2. **Adaptive HTTP tarpitting.** Phase 1 sends `200` and the first 512 bytes immediately, so the client commits a read. Phase 2 sends 8–16 byte slices of the same document every 2–2.5 seconds, up to 30 seconds. The ASGI server frames the chunks. The middleware does not.

The suspicion score is the published a priori formula, clamped to [0, 1]:

```
S = 0.35·R̂ + 0.35·D + 0.20·H − 0.10·C
```

| Term | Meaning |
|---|---|
| R̂ | Requests in a 5-second window, divided by 20, capped at 1 |
| D | Decayed 404 count / decayed request count. Both counters are multiplied by 0.9 before each observation |
| H | Fraction of `User-Agent`, `Accept`, `Accept-Language` that are missing |
| C | 1 only after reverse DNS and forward confirmation of a known crawler. A User-Agent string is not enough |

`S ≥ 0.70` closes the gate. It stays closed until `S < 0.30` (or a crawler is reverse-DNS verified). The release band is gate policy, not a change to the formula: tarpitting drives the rate term toward zero, and a literal reopen at 0.69 would hand the next request to the origin and publish the real stack. Below the band, the origin answers, and the real `Server: uvicorn` token is added only on that path.

This is a research prototype (0.2.0) of the design by Anushka Rawat. It is not a WAF, not a honeypot, and not a blocker. It does not inspect exploit payloads. Deploy it only on systems you operate.

## Run

From this directory, after `pip install -r requirements.txt`:

```sh
python main.py
```

That process binds `0.0.0.0:8000` and forces the flags tarpitting actually needs:

- `--workers 1` — session memory and the tarpit counter are process-local. A second worker is a second, half-blind gate.
- `--loop uvloop --http httptools` — when those packages are installed (they come with `uvicorn[standard]`).
- `--no-server-header` — otherwise Uvicorn appends `server: uvicorn` beside the fake profile and the mutation is visible.
- `--no-proxy-headers` — Uvicorn's default rewrites `scope["client"]` from `X-Forwarded-For` before middleware runs, which bypasses the trusted-peer check. CHAKRAVYUH parses XFF itself.
- `--limit-concurrency` starts at 2048 and is clamped to `ulimit -n` minus 64. A 2048 cap on a process whose soft nofile limit is 1024 does not protect anything; the process hits `EMFILE` first. Startup logs the nofile limit, the tarpit cap, and the headroom. If the soft limit is under twice the tarpit cap, that log line is a warning.
- `--timeout-keep-alive 5` — idle keep-alive only. It does not cut an active tarpit stream.
- `--timeout-graceful-shutdown 35` — long enough for a 30-second hold to close cleanly.

The equivalent Uvicorn command, if you are not using `python main.py`:

```sh
uvicorn main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 1 \
  --loop uvloop \
  --http httptools \
  --no-server-header \
  --no-proxy-headers \
  --forwarded-allow-ips "" \
  --timeout-keep-alive 5 \
  --limit-concurrency 960 \
  --backlog 2048 \
  --timeout-graceful-shutdown 35
```

`python main.py` asks for 2048 and clamps it. The command above already shows the clamp from this box (`ulimit -n` 1024 → 960). Copying 2048 onto that box hits `EMFILE` before the cap means anything. Do not export `WEB_CONCURRENCY` above 1. Do not export `FORWARDED_ALLOW_IPS=*`.

- Protected application: `http://127.0.0.1:8000/`
- Metrics: `http://127.0.0.1:8000/metrics`

`/metrics` and `/chakravyuh-dashboard/api/snapshot` are exempt from scoring. Both are unauthenticated unless `CHAKRAVYUH_DASHBOARD_TOKEN` is set. Set the token before either is reachable beyond loopback. Prometheus sends it as `Authorization: Bearer`. The snapshot also accepts `?token=`.

Behind a TLS terminator, set `CHAKRAVYUH_TRUSTED_PROXIES` to that proxy's IP or CIDR and only that. XFF from any other peer is ignored. The chain is walked from the right so a client cannot prepend a spoofed address.

## Layout

```
main.py                 application factory and the launch command
core/config.py          knobs, including the a priori weights
core/scoring.py         S, decay, TTL session store
core/identity.py        session key and trusted-peer XFF
core/crawlers.py        reverse-DNS crawler credit, fail closed
core/profiles.py        coherent fake stacks and the HTML stream
core/metrics.py         bounded counters the scrape renders
middleware/middleware.py  pure ASGI gate (not BaseHTTPMiddleware)
middleware/identity.py  real Server token, pass-through only
observability/          Prometheus text, Grafana dashboard, study snapshot
demo/site.py            Meridian Ledger, the origin being protected
tests/                  formula, streaming, XFF, caps, fail-open
scripts/simulate_clients.py
scripts/smoke_eval.py
```

## What the gate does

```
request → identity → score → gate
                         │
           S < 0.70 and not held
              │          │      S ≥ 0.70, or already held and S ≥ 0.30
              ▼          │         │
           origin        │         ▼
                         │    concurrency cap? → 429, fake headers, origin not called
                         │    session budget spent? → short fake response, origin not called
                         │    else → mutate headers and tarpit
```

Identity, by default, is `SHA-256(IP + User-Agent + Accept-Language)`, falling back to the IP when both headers are absent. Cookie-primary keying is opt-in (`CHAKRAVYUH_TRUST_SESSION_COOKIE=1`) and is a score-reset bypass if the cookie is forgeable. Leave it off.

Unknown paths are counted as probes immediately, including on the distortion path. That is deliberate: once a scanner is being tarpitted the origin is not asked, and if those requests stopped counting, D would decay and the scanner would fall back through the gate. Pass-through corrects the guess from the real status code.

Hard caps, so the defense cannot become the outage:

- 10,000 sessions, 300 seconds of inactivity, TTL cache.
- 500 concurrent tarpits, then `429` with the session's fake profile. Not the origin.
- 30 seconds per distorted response, 300 seconds of hold time per session, then a short fake response. The real stack is still not served.

Headers are decoded with `utf-8` and `errors="replace"`. A non-UTF-8 scanner header does not take the process down. A fault during planning fails open once, calls the origin, and increments `chakravyuh_fail_open_total`. It does not call the origin a second time.

## Operator surface

`/metrics` is Prometheus text. Grafana is the time-series UI. The dashboard JSON is `observability/grafana/dashboards/chakravyuh.json`. It has request rate, decisions by action, score quantiles with the 0.40 and 0.70 lines, session count, open tarpits against the cap, tarpit-seconds, and the shed / budget-close rates. It does not have a per-client series. An IP label would be a second access log and a cardinality problem at 10,000 sessions.

```sh
docker compose -f observability/docker-compose.yml up
```

Grafana is then at `http://127.0.0.1:3000/d/chakravyuh`. The compose file is a lab: anonymous view, admin password `admin`, and a scrape of `host.docker.internal:8000`. It is not a production deploy. The app is not in that compose file. It stays one process, started with `python main.py`, because the session store is process-local.

`/chakravyuh-dashboard` is a table page: sessions, the last decisions, open tarpits. It polls `/chakravyuh-dashboard/api/snapshot` every 3 seconds. That snapshot is the JSON document the score study polled. It still returns at most eighteen sessions, ranked by score, and forty feed events. That cap is the study contract. The page does not invent a client when the store is empty.

v0.2 measurements in `BENCHMARKS.md` and the thesis used a different page at this path. That page is gone. The snapshot path those runs read is unchanged. The weights are unchanged.

## Checks

```sh
pytest
pytest -m slow
```

`pytest` skips the production-interval test. `pytest -m slow` is the one that proves the drip is 2.0–2.5 seconds, not the 50 ms used by the rest of the suite. Run it before any benchmark. It takes about seven seconds.

Measured runs, including the Uvicorn chunk gaps and the gobuster and Nikto numbers, are in `BENCHMARKS.md`. The write-up — related work, threat model, and the Chromium score-separation study — is `thesis/CHAKRAVYUH.pdf`. Those files are the only figures this tree claims.

Stream a distorted response with curl. A single request will not cross 0.70; a burst will. `--raw` shows that Uvicorn, not the middleware, is framing the body:

```sh
# quiet client — real stack
curl -sD - -o /dev/null -A 'Mozilla/5.0' -H 'Accept: text/html' -H 'Accept-Language: en' http://127.0.0.1:8000/

# after a burst, this should be a fake Server token and a slow HTML body
curl -N --raw --max-time 8 -A 'Nikto/2.5.0' -H 'X-Forwarded-For: 203.0.113.10' http://127.0.0.1:8000/.env
```

The second command only shows the fake stack if that client has already crossed the gate, and only shows the forwarded address if `127.0.0.1` is a trusted proxy. For a local demo:

```sh
CHAKRAVYUH_TRUSTED_PROXIES=127.0.0.1 python main.py
python scripts/simulate_clients.py
python scripts/smoke_eval.py
```

`CHAKRAVYUH_EXPOSE_CONSOLE_LINK=1` puts a `/metrics` link on the origin. Leave it off. `simulate_clients.py` only talks to localhost and only displays RFC 5737 documentation addresses.

External tools, when you have them, are the evaluation from the design digest. Record whatever they actually do, including a miss:

```sh
gobuster dir -u http://127.0.0.1:8000 -w /usr/share/wordlists/dirb/common.txt --threads 50
gobuster dir -u http://127.0.0.1:8000 -w /usr/share/wordlists/dirb/common.txt --threads 50 --timeout 2s
```

The second command is the adversarial case. A scanner whose timeout is a total response deadline, not an idle deadline, abandons the hold. That is a limit of tarpitting.

## Configuration

See `.env.example`. Weights are not fitted. If you move the threshold, write down the false-positive trade and do not pretend the new number was in the original design.

`CHAKRAVYUH_DISTORT_STATUS=404` streams the profile's error page instead of the loading page. The default is `200`, which is what the pipeline specifies. Either way the origin is not called.

## Limits, stated plainly

- Not effective against a person at browser speed, or a scanner sending one request every several seconds. S stays under the gate. That is the threat model, not a missed case.
- On this box `ulimit -n` is 1024. Startup clamps concurrency from 2048 to 960 and logs `headroom_after_tarpits=524`. A full tarpit of 500 plus ordinary traffic can still exhaust descriptors before the HTTP cap matters.
- Carrier-grade NAT can put many people on one public IP. The fingerprint includes User-Agent and Accept-Language. It can still collide.
- Rotating User-Agent every request resets the fingerprint. An IP-only score would punish the NAT. The formula was not changed to chase that bypass.
- Crawler credit requires public reverse DNS. Private addresses, timeouts, a saturated lookup queue, and `CHAKRAVYUH_CRAWLER_DNS_ENABLED=0` all fail closed (C = 0). A spoofed Googlebot that is actually scanning is tarpitted.
- That lookup is one outbound DNS query per new public `(IP, family)` until the 10-minute cache hits. A botnet spraying a Googlebot User-Agent from thousands of addresses can amplify into thousands of lookups. The semaphore (8) fails closed instead of queueing, which stops the event loop from piling up waits. It does not stop the queries that do get a slot. Turn DNS off if this process must not originate queries.
- HTTP/2 is not supported by this deployment. `h2load` negotiated h2c and the only request failed: 0 status codes, 175 bytes, 726 µs. That is not an unverified flow-control question. The same binary over HTTP/1.1 got a 200. HTTP/3 was not attempted. See `BENCHMARKS.md`.
- In-memory state does not survive another worker, another host, or a restart. A shared store (Redis is the obvious next step) is not in this prototype.
- `/metrics` has no client address, path, or User-Agent label. The snapshot does. Treat the snapshot as an admin surface.
- A client that abandons the body is not held for the full 30 seconds. It is still not free. On the measured wordlist, `gobuster --timeout 2s` took 16.0 s and recorded no paths, including the four that exist. See `BENCHMARKS.md`.
- The numbers in `BENCHMARKS.md` are the v0.2 baseline. The finding is not a slowdown ratio. A 10 s gobuster timeout produced about 45 hits, all the same 206-byte page. A 2 s timeout produced none. Neither recovered the origin. Do not promote 1137× beyond that wordlist.

## Tests cover

- The formula, including the 0.70 boundary and the crawler credit.
- Decay of 0.9 and the 5-second rate window.
- XFF ignored from an untrusted peer; walked from the right when the peer is trusted.
- Cookie rotation does not split a session unless that bypass is explicitly enabled.
- Malformed header bytes do not raise.
- Distorted bodies start with HTML, contain no middleware name, are not manually chunk-framed, commit 512 bytes, then drip 8–16 byte slices, and take real time.
- A verified crawler at the same heat stays under the gate. An unverified one does not.
- The concurrency cap and the session budget both refuse without calling the origin.
- Client disconnect during a hold does not raise.
- A planning fault fails open once.
- `/metrics` and the snapshot path are not scored, and the scrape does not label by client address.
