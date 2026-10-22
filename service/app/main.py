"""Entry point: wire the pieces together and serve.

    python -m app.main            # serve (what the container runs)
    python -m app.main --check    # import/instantiate everything and exit (health of the image)
"""

from __future__ import annotations

import signal
import sys
import threading

from . import config
from .claude import ClaudeClient
from .mdns import Advertisement
from .poller import UsagePoller
from .store import TokenStore
from .web import App, serve

log = lambda *a: print("[claudereset]", *a, file=sys.stderr, flush=True)  # noqa: E731


def build() -> tuple[App, UsagePoller, Advertisement | None]:
    store = TokenStore(config.TOKEN_FILE)
    client = ClaudeClient()
    poller = UsagePoller(client, store)
    advertisement = (
        Advertisement(config.MDNS_SERVICE_TYPE, config.MDNS_NAME, config.PORT)
        if config.MDNS
        else None
    )
    return App(poller, client), poller, advertisement


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    app, poller, advertisement = build()

    if "--check" in argv:
        log(
            "configurazione ok:",
            f"porta={config.PORT}",
            f"intervallo={config.POLL_SECONDS}s",
            f"dati={config.TOKEN_FILE}",
            f"mDNS={'on' if config.MDNS else 'off'}",
        )
        return 0

    thread = threading.Thread(target=poller.run_forever, name="poller", daemon=True)
    thread.start()

    mdns_name = advertisement.start() if advertisement else None
    app.mdns_name = mdns_name

    httpd = serve(app, config.BIND, config.PORT)
    log(f"in ascolto su http://{config.BIND}:{config.PORT} (pagina: /, display: /api/usage)")

    stopping = threading.Event()

    def shutdown(*_: object) -> None:
        if stopping.is_set():
            return
        stopping.set()
        log("arresto in corso")
        if advertisement:
            advertisement.stop()
        poller.stop()
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, shutdown)

    try:
        httpd.serve_forever(poll_interval=0.5)
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
