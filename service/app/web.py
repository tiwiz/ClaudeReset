"""HTTP surface: a small dashboard for the human, a tiny JSON API for the display.

Security posture: the JSON API is read-only, and every endpoint that changes state (login,
logout, refresh) is refused unless the caller is on a private or loopback address.
"""

from __future__ import annotations

import html
import ipaddress
import json
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from . import config
from .claude import PendingLogin
from .poller import UsagePoller

PENDING_TTL_SECONDS = 600
PENDING_MAX = 16


# Explicitly, because `ipaddress.is_private` also covers documentation ranges like
# 203.0.113.0/24 — fine for arithmetic, misleading for "is this caller on my LAN".
LAN_NETWORKS = tuple(
    ipaddress.ip_network(cidr)
    for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "fc00::/7")
)


def is_lan(address: str) -> bool:
    """True for loopback and private/link-local sources: the only ones allowed to change state."""
    try:
        ip = ipaddress.ip_address(address.split("%")[0].strip())
    except ValueError:
        return False
    if ip.is_loopback:
        return True
    return any(ip in network for network in LAN_NETWORKS if network.version == ip.version)


def _fmt_time(epoch: float | None) -> str:
    if not epoch:
        return "—"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(epoch))


def _fmt_in(epoch: float | None, now: float) -> str:
    if not epoch:
        return ""
    delta = epoch - now
    if delta <= 0:
        return "adesso"
    hours, rem = divmod(int(delta), 3600)
    minutes = rem // 60
    if hours >= 24:
        return f"fra {hours // 24}g {hours % 24}h"
    if hours:
        return f"fra {hours}h {minutes:02d}m"
    return f"fra {minutes}m"


def _bar(value: Any, ceiling: float = 100.0) -> str:
    try:
        pct = max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return '<div class="bar"><span style="width:0%"></span></div>'
    return f'<div class="bar"><span style="width:{pct:.1f}%"></span></div>'


def render_page(status: dict[str, Any], *, host: str, mdns_name: str | None) -> str:
    now = time.time()
    usage = status.get("usage") or {}
    account = status.get("account") or {}
    logged = status.get("logged_in")

    reset_in = None
    if usage.get("r7"):
        reset_in = usage["r7"] - now
    reset_5h_in = None
    if usage.get("r"):
        reset_5h_in = usage["r"] - now

    refresh_expires = status.get("refresh_expires_at")
    refresh_known = status.get("refresh_expiry_known")
    if refresh_known and refresh_expires:
        days_left = (refresh_expires - now) / 86400
        if days_left < 2:
            refresh_line = (
                f'<span class="warn">{_fmt_time(refresh_expires)} '
                f"({_fmt_in(refresh_expires, now)}) — riaccedi prima che scada</span>"
            )
        else:
            refresh_line = f"{_fmt_time(refresh_expires)} ({_fmt_in(refresh_expires, now)})"
    else:
        refresh_line = '<span class="dim">non comunicata dall\'API (si scopre al primo refresh)</span>'

    scope_hint = ""
    if "403" in str(status.get("error") or ""):
        scope_hint = """  <p class="warn small">L'endpoint delle quote ha risposto 403: sono gli scope richiesti a
     essere troppo stretti, non l'accesso a essere sbagliato. Riprova concedendo quelli completi
     (gli stessi che chiede il CLI di Claude).</p>
  <form method="get" action="/login">
    <input type="hidden" name="mode" value="paste">
    <input type="hidden" name="scope" value="full">
    <button class="primary" type="submit">Riprova con gli scope completi</button>
  </form>
"""

    if not logged:
        auth_card = f"""<section class="card">
  <h2>Accesso</h2>
  <p>Serve una volta sola: poi il servizio rinnova da s&eacute;. Il token resta qui dentro e non
     viene mai mandato al display.</p>
  <ol class="small">
    <li>Premi il pulsante: si apre la pagina di Anthropic.</li>
    <li>Autorizza: la pagina ti mostra una riga tipo <code>codice#stato</code>.</li>
    <li>Copia <b>tutta</b> la riga e incollala qui sotto.</li>
  </ol>
  <div class="row">
    <form method="get" action="/login">
      <input type="hidden" name="mode" value="paste">
      <button class="primary" type="submit">Accedi con Claude</button>
    </form>
  </div>
  <form method="post" action="/paste">
    <input name="code" placeholder="codice#stato" autocomplete="off" spellcheck="false">
    <button type="submit">Invia il codice</button>
  </form>
{scope_hint}  <details>
    <summary>Perch&eacute; non torna indietro da solo?</summary>
    <p class="small">Il client di Claude accetta come ritorno automatico solo
       <code>http://localhost:&lt;porta&gt;/callback</code>, non l'indirizzo di rete di questo servizio:
       da un telefono o da un altro computer quel ritorno finirebbe sul dispositivo sbagliato. Il codice
       invece funziona da qualunque dispositivo &mdash; ed &egrave; quello che fa
       <code>claude setup-token</code>.</p>
    <p class="small">Vuoi comunque il ritorno automatico? Apri un tunnel verso la macchina dove gira il
       servizio (<code>ssh -L 8790:localhost:8790 root@{html.escape(host)}</code>), poi visita
       <code>http://localhost:8790/</code> e usa questo pulsante:</p>
    <form method="get" action="/login">
      <input type="hidden" name="mode" value="loopback">
      <button type="submit">Accesso con ritorno automatico</button>
    </form>
  </details>
</section>"""
    else:
        auth_card = f"""<section class="card">
  <h2>Accesso</h2>
  <table>
    <tr><th>Account</th><td>{html.escape(account.get("email") or "—")}</td></tr>
    <tr><th>Abbonamento</th><td>{html.escape(str(status.get("subscription") or "—"))}</td></tr>
    <tr><th>Token di accesso</th><td>{_fmt_time(status.get("access_expires_at"))}
        <span class="dim">({_fmt_in(status.get("access_expires_at"), now)})</span></td></tr>
    <tr><th>Token di refresh</th><td>{refresh_line}</td></tr>
    <tr><th>Ultimo refresh token</th><td>{_fmt_time(status.get("last_token_refresh_at")) or "mai"}</td></tr>
  </table>
  <div class="row">
    <form method="post" action="/refresh"><button type="submit">Aggiorna adesso</button></form>
    <form method="post" action="/logout"><button class="danger" type="submit">Disconnetti</button></form>
  </div>
</section>"""

    if status.get("error"):
        state = f'<span class="warn">{html.escape(status["error"])}</span>'
    elif not logged:
        state = '<span class="dim">in attesa dell\'accesso</span>'
    elif status.get("stale"):
        state = '<span class="warn">dato vecchio</span>'
    else:
        state = '<span class="ok">aggiornato</span>'

    age = status.get("age")
    next_in = status.get("next_fetch_in")

    data_card = f"""<section class="card">
  <h2>Quote</h2>
  <table>
    <tr><th>Finestra 7 giorni</th>
        <td><b>{usage.get("p7", "—")}%</b> {_bar(usage.get("p7"))}
            <span class="dim">reset {_fmt_time(usage.get("r7"))} ({_fmt_in(usage.get("r7"), now)})</span></td></tr>
    <tr><th>Finestra 5 ore</th>
        <td><b>{usage.get("p", "—")}%</b> {_bar(usage.get("p"))}
            <span class="dim">reset {_fmt_time(usage.get("r"))} ({_fmt_in(usage.get("r"), now)})</span></td></tr>
  </table>
  <p class="small">Stato: {state} · ultimo dato {age} s fa · prossimo controllo {next_in} s
     · intervallo {status.get("poll_seconds")} s</p>
</section>"""

    mdns_line = (
        f"annuncio mDNS attivo come <code>{html.escape(mdns_name)}</code>"
        if mdns_name
        else '<span class="dim">mDNS spento</span>'
    )
    display_card = f"""<section class="card">
  <h2>Per il display</h2>
  <table>
    <tr><th>JSON</th><td><code>http://{html.escape(host)}/api/usage</code></td></tr>
    <tr><th>Stato completo</th><td><code>http://{html.escape(host)}/api/status</code></td></tr>
    <tr><th>Salute</th><td><code>http://{html.escape(host)}/health</code></td></tr>
  </table>
  <p class="small">Il display scopre il servizio da solo via {mdns_line}.
     Interroga l'API, che risponde <b>sempre dalla cache</b>: nessuna richiesta in pi&ugrave; verso Anthropic.</p>
</section>"""

    return f"""<!doctype html>
<html lang="it"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="30">
<title>ClaudeReset</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; padding: 24px 16px 48px; background: #0b1120; color: #e2e8f0;
         font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
  .wrap {{ max-width: 720px; margin: 0 auto; }}
  h1 {{ font-size: 22px; margin: 0 0 2px; letter-spacing: -0.2px; }}
  h1 span {{ color: #d97757; }}
  .sub {{ color: #94a3b8; font-size: 13px; margin-bottom: 22px; }}
  .card {{ background: rgba(30,41,59,.35); border: 1px solid #334155; border-radius: 14px;
           padding: 18px 20px; margin-bottom: 16px; }}
  h2 {{ font-size: 12px; text-transform: uppercase; letter-spacing: 1.2px; color: #cbd5e1;
        margin: 0 0 12px; font-weight: 600; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th {{ text-align: left; font-weight: 500; color: #94a3b8; padding: 5px 12px 5px 0;
        white-space: nowrap; vertical-align: top; width: 34%; }}
  td {{ padding: 5px 0; vertical-align: top; }}
  code {{ background: #0f172a; border: 1px solid #334155; border-radius: 6px;
          padding: 1px 6px; font-size: 13px; }}
  .bar {{ display: inline-block; width: 120px; height: 7px; background: #2b2b33;
          border-radius: 4px; overflow: hidden; vertical-align: middle; margin: 0 8px; }}
  .bar span {{ display: block; height: 100%; background: #d97757; }}
  button {{ font: inherit; padding: 8px 14px; border-radius: 9px; cursor: pointer;
            background: #1e293b; color: #e2e8f0; border: 1px solid #334155; }}
  button.primary {{ background: #d97757; border-color: #d97757; color: #1a0f0a; font-weight: 600; }}
  button.danger {{ background: transparent; border-color: #7f1d1d; color: #fca5a5; }}
  input[type=text], input:not([type]) {{ font: inherit; padding: 8px 10px; border-radius: 9px;
            background: #0f172a; border: 1px solid #334155; color: #e2e8f0; min-width: 220px; }}
  .row {{ display: flex; gap: 10px; margin-top: 14px; flex-wrap: wrap; align-items: center; }}
  ol {{ margin: 10px 0; padding-left: 22px; }} ol li {{ margin-bottom: 3px; }}
  form {{ display: inline; }}
  .dim {{ color: #94a3b8; }} .small {{ font-size: 13px; }}
  .ok {{ color: #86efac; }} .warn {{ color: #fbbf24; }}
  details {{ margin-top: 14px; }} summary {{ cursor: pointer; color: #94a3b8; font-size: 13px; }}
  .foot {{ color: #64748b; font-size: 12px; text-align: center; margin-top: 28px; }}
</style></head>
<body><div class="wrap">
  <h1>Claude<span>Reset</span></h1>
  <div class="sub">Servizio di rete: accesso a Claude, refresh dei token, cache del dato per il display.</div>
  {auth_card}
  {data_card}
  {display_card}
  <div class="foot">pagina aggiornata ogni 30 s · versione {status.get("version")}</div>
</div></body></html>"""


class App:
    """Small container for what the handlers need. Keeps the handler stateless."""

    def __init__(self, poller: UsagePoller, client, mdns_name: str | None = None):
        self.poller = poller
        self.client = client
        self.mdns_name = mdns_name
        self.pending: dict[str, PendingLogin] = {}

    def remember(self, pending: PendingLogin) -> None:
        now = time.time()
        self.pending = {
            state: item
            for state, item in self.pending.items()
            if now - item.created_at < PENDING_TTL_SECONDS
        }
        while len(self.pending) >= PENDING_MAX:
            self.pending.pop(next(iter(self.pending)))
        self.pending[pending.state] = pending

    def take(self, state: str) -> PendingLogin | None:
        return self.pending.pop(state, None)


def make_handler(app: App, *, dashboard_host: str = "localhost"):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ClaudeReset/1.0"
        protocol_version = "HTTP/1.1"

        # -- helpers ----------------------------------------------------
        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj: dict, code: int = 200) -> None:
            self._send(code, json.dumps(obj).encode(), "application/json; charset=utf-8")

        def _html(self, text: str, code: int = 200) -> None:
            self._send(code, text.encode(), "text/html; charset=utf-8")

        def _redirect(self, url: str) -> None:
            self.send_response(302)
            self.send_header("Location", url)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _host(self) -> str:
            header = self.headers.get("Host") or dashboard_host
            return header.split(":")[0]

        def _lan_only(self) -> bool:
            if is_lan(self.client_address[0]):
                return True
            self._json({"error": "solo dalla rete locale"}, 403)
            return False

        def log_message(self, fmt: str, *args) -> None:  # quiet by default
            return

        # -- routes -----------------------------------------------------
        def do_GET(self) -> None:  # noqa: N802
            path = urllib.parse.urlsplit(self.path)
            query = urllib.parse.parse_qs(path.query)
            route = path.path.rstrip("/") or "/"

            if route == "/":
                status = app.poller.status()
                return self._html(
                    render_page(status, host=self._host(), mdns_name=app.mdns_name)
                )
            if route == "/api/usage":
                return self._json(app.poller.snapshot())
            if route == "/api/status":
                return self._json(app.poller.status())
            if route == "/health":
                snap = app.poller.snapshot()
                ok = snap.get("ok")
                return self._json(
                    {"ok": ok, "age": snap.get("age"), "err": snap.get("err", "")},
                    200 if ok else 503,
                )
            if route == "/login":
                if not self._lan_only():
                    return
                mode = (query.get("mode") or ["paste"])[0]
                full = (query.get("scope") or [""])[0] == "full"
                scopes = config.SCOPES_FULL if full else None
                if mode == "loopback":
                    # The Claude client only accepts a localhost redirect: this works when the
                    # browser runs on the same machine as the service, or through an SSH tunnel.
                    redirect_uri = f"http://localhost:{config.PORT}/callback"
                else:
                    redirect_uri = config.MANUAL_REDIRECT_URI
                url, pending = app.client.start_login(redirect_uri, scopes=scopes)
                app.remember(pending)
                return self._redirect(url)
            if route == "/callback":
                return self._finish(query.get("code", [""])[0], query.get("state", [""])[0])
            return self._json({"error": "not found"}, 404)

        def do_POST(self) -> None:  # noqa: N802
            route = urllib.parse.urlsplit(self.path).path.rstrip("/")
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length).decode("utf-8", "replace") if length else ""
            form = urllib.parse.parse_qs(body)

            if not self._lan_only():
                return
            if route == "/refresh":
                changed = app.poller.refresh_now()
                return self._json({"refreshed": changed})
            if route == "/logout":
                app.poller.store.clear()
                return self._redirect("/")
            if route == "/paste":
                raw = (form.get("code") or [""])[0].strip()
                code, _, state = raw.partition("#")
                return self._finish(code.strip(), state.strip(), redirect_uri=config.MANUAL_REDIRECT_URI)
            return self._json({"error": "not found"}, 404)

        def _finish(self, code: str, state: str, redirect_uri: str | None = None) -> None:
            if not code or not state:
                return self._html("<p>Accesso annullato o incompleto.</p>", 400)
            pending = app.take(state)
            if pending is None:
                return self._html("<p>Richiesta di accesso scaduta: riprova dalla pagina.</p>", 400)
            if redirect_uri:
                pending = PendingLogin(
                    verifier=pending.verifier, state=pending.state, redirect_uri=redirect_uri
                )
            try:
                resp = app.client.exchange_code(code, pending)
            except Exception as exc:  # noqa: BLE001
                return self._html(f"<p>Accesso non riuscito: {html.escape(str(exc))}</p>", 502)
            app.poller.store.save_token_response(resp)
            app.poller.fetch_once()
            self.send_response(302)
            self.send_header("Location", "/")
            self.send_header("Content-Length", "0")
            self.end_headers()

    return Handler


def serve(app: App, host: str, port: int) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), make_handler(app))
    httpd.daemon_threads = True
    return httpd
