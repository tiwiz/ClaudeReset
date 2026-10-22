"""The health check must accept 503 as "not ready yet", not as "broken"."""

import http.client
import threading

import pytest

from healthcheck import probe
from app.store import TokenStore
from app.web import App, serve


class FakePoller:
    def __init__(self, snapshot):
        self._snapshot = snapshot
        self.store = TokenStore("/tmp/unused.json")

    def snapshot(self):
        return self._snapshot

    def status(self):
        return {"version": 1}

    def refresh_now(self):
        return True


class FakeClient:
    pass


@pytest.fixture()
def server():
    app = App(FakePoller({"ok": 0, "err": "non autenticato"}), FakeClient())
    httpd = serve(app, "127.0.0.1", 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


def test_503_is_healthy(server):
    assert probe(f"http://127.0.0.1:{server}/health") == 0


def test_unreachable_is_not_healthy():
    assert probe("http://127.0.0.1:1/health", timeout=1) == 1


def test_fresh_reading_is_healthy(server):
    assert probe(f"http://127.0.0.1:{server}/health") == 0
