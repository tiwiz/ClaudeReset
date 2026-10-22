# ClaudeReset service

A small service that signs in to Claude **on its own** (no Claude Code CLI, no credentials file),
refreshes the OAuth token for you, caches the quota numbers and serves them on the LAN so a display
can show them. It is also the one place that can tell you *when* your sign-in will expire: the
refresh token has a lifetime, and nobody else surfaces it.

```
ClaudeReset service (Docker)          display (D1 mini + GC9A01)
  login + refresh token   ──── LAN ────▶  GET /api/usage  every 60 s
  poll Anthropic every 5 min                     (answers from cache, instantly)
  announce itself over mDNS
```

## Run it

```bash
mkdir -p data && chmod 700 data
docker compose up -d --build
```

Then open `http://<host-lan-address>:8790/` **from the LAN address you will keep using** (not
`localhost`, unless the container runs on the machine you are browsing from), and click
*Accedi con Claude*. If the browser cannot come back to the container, use the paste flow: the code
page shows `code#state`, and you paste it into the box.

`network_mode: host` is not optional: mDNS is link-local multicast and Docker's bridge does not
forward it, so the display would never find the service. With host networking the container
advertises `_claudereset._tcp` on the host's interfaces.

## Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /` | dashboard: sign-in state, quotas, token expiries, last error |
| `GET /api/usage` | compact JSON for the display, always served from cache |
| `GET /api/status` | everything the dashboard shows, as JSON |
| `GET /health` | 200 when the last reading is fresh, 503 when it is stale |
| `GET /login`, `GET /callback`, `POST /paste` | OAuth (PKCE, no client secret) |
| `POST /refresh`, `POST /logout` | manual refresh, sign out |

The JSON the display consumes:

```json
{"v":1,"ok":1,"p":14.0,"r":9206,"p7":65.0,"r7":14006,"age":21,"stale":0,"err":""}
```

`p`/`r` are the 5-hour window (used %, seconds to reset), `p7`/`r7` the 7-day one, `age` the age of
the reading in seconds, `stale` 1 when it is older than `STALE_SECONDS`.

## Polling policy

Anthropic is asked once every **5 minutes** (±20 s of jitter, so many instances never sync up),
plus one fetch immediately after a window resets, which is the only moment the numbers move. Ten
displays asking every minute cause zero extra upstream calls: the cache answers them. On errors the
service backs off 1 → 2 → 5 → 10 → 30 minutes and never hammers. The access token is refreshed only
when it is about to expire, or once after a 401.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `8790` | HTTP port |
| `POLL_SECONDS` | `300` | upstream interval (never below `MIN_POLL_SECONDS`) |
| `MIN_POLL_SECONDS` | `60` | the floor people cannot go below |
| `JITTER_SECONDS` | `20` | ± randomness on the interval |
| `STALE_SECONDS` | `900` | after this the reading is reported as stale |
| `CACHE_TTL_SECONDS` | `60` | how long the display's copy is considered fresh |
| `REFRESH_MARGIN_SECONDS` | `600` | refresh the access token this early |
| `MDNS`, `MDNS_NAME`, `MDNS_SERVICE_TYPE` | `1`, `claudereset`, `_claudereset._tcp.local.` | discovery |
| `SCOPES` | `user:profile user:sessions:claude_code user:inference` | widen if the usage endpoint answers 403 |
| `DATA_DIR` | `/data` | token file lives here (volume), mode 600 |

## Security

- The tokens live in one file with mode 600 inside the volume, written atomically. They are never
  logged, never sent to the display and never returned by any endpoint.
- Every endpoint that changes state (login, paste, logout, refresh) refuses callers that are not on
  a private or loopback address.
- The display's endpoint is read-only and exposes quota numbers only.
- Do not publish this service on the internet. It belongs on your LAN.

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest -q          # policy, storage, OAuth request shapes, API contract
python -m app.main --check   # instantiate everything and exit
DATA_DIR=./data python -m app.main   # run it locally without Docker
```
