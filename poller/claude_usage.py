#!/usr/bin/env python3
"""Claude Code usage bridge — legge l'utilizzo della finestra a 5 ore (e 7 giorni)
dall'endpoint che usa `claude /usage` e lo espone come JSON compatto sulla LAN.

Nessuna dipendenza esterna. Nessun segreto in chiaro nel codice o nel repo:
il token viene letto a runtime dal file di credenziali di Claude Code
(CLAUDE_CREDENTIALS, default ~/.claude/.credentials.json) e non viene mai
scritto nei log ne' esposto dalle risposte HTTP.

Config: file .env accanto al repo (vedi .env.example). Le variabili d'ambiente
hanno la precedenza sul file.
"""

import json
import os
import pathlib
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
ENV_FILE = ROOT / ".env"


def load_env(path: pathlib.Path = ENV_FILE) -> dict:
    """Parser minimo KEY=VALUE: evita di dipendere da librerie esterne."""
    cfg = {}
    if not path.exists():
        return cfg
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        cfg[key.strip()] = val.strip().strip('"').strip("'")
    return cfg


CFG = load_env()


def setting(key: str, default: str) -> str:
    return os.environ.get(key) or CFG.get(key) or default


CREDENTIALS = pathlib.Path(os.path.expanduser(
    setting("CLAUDE_CREDENTIALS", "~/.claude/.credentials.json")))
TOKEN_OVERRIDE = setting("CLAUDE_OAUTH_TOKEN", "")   # opzionale, solo per test
HOST = setting("HOST", "0.0.0.0")
PORT = int(setting("PORT", "8790"))
POLL_SECONDS = int(setting("POLL_SECONDS", "60"))
STALE_SECONDS = int(setting("STALE_SECONDS", "180"))
USAGE_URL = setting("USAGE_URL", "https://api.anthropic.com/api/oauth/usage")

STATE = {
    "ok": False,
    "pct": None,          # utilizzo finestra 5 ore, in percentuale
    "reset_s": None,      # secondi al prossimo reset della finestra 5 ore
    "pct7": None,         # utilizzo finestra 7 giorni
    "reset7_s": None,
    "fetched_at": 0,      # epoch dell'ultimo dato valido
    "error": "avvio",
}
LOCK = threading.Lock()
log = lambda *a: print("[claude-usage]", *a, file=sys.stderr, flush=True)


def read_token() -> str:
    """Token OAuth di Claude Code. Non viene mai stampato ne' restituito."""
    if TOKEN_OVERRIDE:
        return TOKEN_OVERRIDE
    try:
        raw = json.loads(CREDENTIALS.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise RuntimeError(f"credenziali non trovate: {CREDENTIALS}")
    except json.JSONDecodeError:
        raise RuntimeError(f"credenziali illeggibili: {CREDENTIALS}")
    oauth = raw.get("claudeAiOauth", raw)
    token = oauth.get("accessToken") or oauth.get("access_token")
    if not token:
        raise RuntimeError("nessun accessToken nel file di credenziali")
    expires_at = oauth.get("expiresAt")      # millisecondi
    if expires_at and expires_at / 1000 < time.time():
        raise RuntimeError("token scaduto: usa Claude Code per farlo rinnovare")
    return token


def seconds_to(resets_at):
    if not resets_at:
        return None
    try:
        txt = str(resets_at).replace("Z", "+00:00")
        # Python < 3.11 non digerisce i microsecondi a 6 cifre con offset: li tronco
        if "." in txt:
            head, _, tail = txt.partition(".")
            frac = tail[:6]
            rest = tail[6:]
            txt = f"{head}.{frac}{rest}"
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(txt)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, int(dt.timestamp() - time.time()))
    except Exception as exc:                                  # noqa: BLE001
        log("resets_at non interpretabile:", resets_at, exc)
        return None


def fetch_usage() -> dict:
    token = read_token()
    req = urllib.request.Request(
        USAGE_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": "oauth-2025-04-20",
            "User-Agent": "claude-code/2.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def poll_once() -> None:
    try:
        data = fetch_usage()
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:200]
        except Exception:                                     # noqa: BLE001
            pass
        err = f"HTTP {exc.code}" + (f" {detail}" if detail else "")
        with LOCK:
            STATE["ok"] = False
            STATE["error"] = err
        log("errore upstream:", err)
        return
    except RuntimeError as exc:
        with LOCK:
            STATE["ok"] = False
            STATE["error"] = str(exc)
        log("errore:", exc)
        return
    except Exception as exc:                                  # noqa: BLE001
        with LOCK:
            STATE["ok"] = False
            STATE["error"] = f"{type(exc).__name__}: {exc}"
        log("errore di rete:", exc)
        return

    five = data.get("five_hour") or {}
    week = data.get("seven_day") or {}
    with LOCK:
        STATE.update(
            ok=True,
            pct=five.get("utilization"),
            reset_s=seconds_to(five.get("resets_at")),
            pct7=week.get("utilization"),
            reset7_s=seconds_to(week.get("resets_at")),
            fetched_at=int(time.time()),
            error="",
        )
    log("aggiornato: 5h", STATE["pct"], "% · reset tra", STATE["reset_s"], "s")


def poller_loop() -> None:
    while True:
        poll_once()
        time.sleep(POLL_SECONDS)


def snapshot() -> dict:
    with LOCK:
        state = dict(STATE)
    age = int(time.time() - state["fetched_at"]) if state["fetched_at"] else None
    stale = bool(age is None or age > STALE_SECONDS)
    return {
        # chiavi corte: il payload lo legge un ESP8266, non un browser
        "ok": 1 if (state["ok"] or (state["pct"] is not None and not stale)) else 0,
        "p": state["pct"],
        "r": state["reset_s"],
        "p7": state["pct7"],
        "r7": state["reset7_s"],
        "age": age,
        "stale": 1 if stale else 0,
        "err": state["error"] or "",
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "claude-usage-ring"

    def _send(self, payload: bytes, ctype="application/json", code=200) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:                                 # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/usage"):
            snap = snapshot()
            reset = snap["r"] if snap["r"] is not None else "?"
            body = (
                "Claude Code usage ring\n"
                f"finestra 5h : {snap['p']}%  (reset tra {reset} s)\n"
                f"finestra 7g : {snap['p7']}%\n"
                f"dato di    : {snap['age']} s fa · stale={snap['stale']}\n"
                f"errore     : {snap['err'] or '-'}\n"
                "JSON per il micro: /claude\n"
            ).encode()
            self._send(body, "text/plain; charset=utf-8")
        elif path == "/claude":
            self._send(json.dumps(snapshot(), separators=(",", ":")).encode())
        elif path == "/health":
            snap = snapshot()
            code = 200 if snap["age"] is not None and not snap["stale"] else 503
            self._send(json.dumps({"status": "ok" if code == 200 else "stale",
                                   "age": snap["age"], "error": snap["err"]}
                                  ).encode(), code=code)
        else:
            self._send(b'{"error":"not found"}\n', code=404)

    def log_message(self, fmt, *args):                        # silenzio nei log
        return


def main() -> None:
    log(f"credenziali: {CREDENTIALS} | in ascolto su {HOST}:{PORT} | poll ogni {POLL_SECONDS}s")
    threading.Thread(target=poller_loop, daemon=True).start()
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
