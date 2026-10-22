"""The JSON the display depends on, plus the LAN-only rule on state-changing calls."""

import http.client
import threading

import pytest

from app.store import TokenStore
from app.web import App, is_lan, serve


class FakePoller:
    def __init__(self, snapshot, status):
        self._snapshot = snapshot
        self._status = status
        self.store = TokenStore("/tmp/does-not-matter.json")
        self.refreshed = 0

    def snapshot(self):
        return self._snapshot

    def status(self):
        return self._status

    def refresh_now(self):
        self.refreshed += 1
        return True


class FakeClient:
    def start_login(self, redirect_uri):
        from app.claude import PendingLogin

        return "https://claude.com/cai/oauth/authorize?x=1", PendingLogin(
            verifier="v", state="s", redirect_uri=redirect_uri
        )

    def exchange_code(self, code, pending):
        return {"access_token": "a", "refresh_token": "r", "expires_in": 100}


SNAPSHOT = {"v": 1, "ok": 1, "p": 12.5, "r": 300, "p7": 65.0, "r7": 900, "age": 20, "stale": 0, "err": ""}
STATUS = {"version": 1, "logged_in": True, "poll_seconds": 300, "usage": {"p7": 65.0}, "account": {}}


@pytest.fixture()
def server():
    app = App(FakePoller(SNAPSHOT, STATUS), FakeClient(), mdns_name="claudereset.local")
    httpd = serve(app, "127.0.0.1", 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd.server_address[1], app
    httpd.shutdown()
    httpd.server_close()


def get(port, path):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", path)
    resp = conn.getresponse()
    body = resp.read().decode()
    conn.close()
    return resp.status, body


def test_usage_contract(server):
    port, _ = server
    status, body = get(port, "/api/usage")
    import json

    assert status == 200
    payload = json.loads(body)
    for key in ("v", "ok", "p", "r", "p7", "r7", "age", "stale", "err"):
        assert key in payload


def test_health_follows_the_reading(server):
    port, _ = server
    assert get(port, "/health")[0] == 200


def test_dashboard_renders_and_never_shows_a_token(server):
    port, _ = server
    status, body = get(port, "/")
    assert status == 200
    assert "Claude" in body
    assert "api/usage" in body


def test_unknown_route_is_404(server):
    port, _ = server
    assert get(port, "/nope")[0] == 404


def test_login_redirects_to_claude(server):
    port, _ = server
    status, _ = get(port, "/login")
    assert status == 302


def test_is_lan_knows_private_ranges():
    assert is_lan("192.168.86.62")
    assert is_lan("10.0.0.5")
    assert is_lan("172.16.4.9")
    assert is_lan("127.0.0.1")
    assert not is_lan("8.8.8.8")
    assert not is_lan("203.0.113.7")
    assert not is_lan("nonsense")
