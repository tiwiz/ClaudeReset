"""An expired refresh token is not a network error: it is a login, and the user must be told so.

The refresh token has an absolute lifetime that refreshing never extends. The old code only
refreshed when the *access* token was about to expire, so it kept polling with a dead refresh
token and ended up showing the raw "HTTP 400 da platform.claude.com" on a 16-character display.
"""

from app.claude import ClaudeError
from app.poller import SESSION_EXPIRED, UsagePoller
from app.store import TokenStore
from app.web import render_page

NOW = 1_800_000_000


class FakeClient:
    def __init__(self, error=None):
        self.refresh_calls = 0
        self.usage_calls = 0
        self.error = error

    def refresh(self, refresh_token):
        self.refresh_calls += 1
        if self.error:
            raise self.error
        return {"access_token": "new", "expires_in": 28800}

    def fetch_usage(self, access_token):
        self.usage_calls += 1
        return {"p": 10.0, "r": NOW + 3600, "p7": 20.0, "r7": NOW + 86400}


def make(tmp_path, tokens, client=None):
    store = TokenStore(tmp_path / "tokens.json")
    store.save(tokens)
    client = client or FakeClient()
    poller = UsagePoller(client, store, clock=lambda: NOW)
    return poller, client, store


def test_dead_refresh_token_does_not_hammer_the_token_endpoint(tmp_path):
    poller, client, _ = make(
        tmp_path,
        {
            "access_token": "old",
            "refresh_token": "dead",
            "access_expires_at": NOW + 120,  # inside the refresh margin
            "refresh_expires_at": NOW - 10,  # already gone
        },
    )
    assert poller.fetch_once() is False
    assert poller.error == SESSION_EXPIRED
    assert client.refresh_calls == 0
    assert client.usage_calls == 0


def test_invalid_grant_becomes_a_login_request(tmp_path):
    client = FakeClient(ClaudeError("HTTP 400 da platform.claude.com", 400, '{"error": "invalid_grant"}'))
    poller, _, _ = make(
        tmp_path,
        {
            "access_token": "old",
            "refresh_token": "stale",
            "access_expires_at": NOW - 1,
            "refresh_expires_at": NOW + 86400,
        },
        client,
    )
    assert poller.fetch_once() is False
    assert poller.error == SESSION_EXPIRED
    assert client.refresh_calls == 1


def test_a_network_failure_still_says_what_it_is(tmp_path):
    client = FakeClient(ClaudeError("rete non raggiungibile (timeout)"))
    poller, _, _ = make(
        tmp_path,
        {"access_token": "old", "refresh_token": "r", "access_expires_at": NOW - 1},
        client,
    )
    assert poller.fetch_once() is False
    assert poller.error == "rete non raggiungibile (timeout)"


def test_the_display_only_shows_the_first_16_characters(tmp_path):
    """The firmware cuts err at 16 chars: the useful part must be at the start."""
    assert SESSION_EXPIRED[:16] == "sessione scaduta"


def test_snapshot_flags_a_dead_session_even_with_fresh_numbers(tmp_path):
    poller, _, _ = make(
        tmp_path,
        {
            "access_token": "still-valid",
            "refresh_token": "dead",
            "access_expires_at": NOW + 3600,
            "refresh_expires_at": NOW - 10,
        },
    )
    poller.data = {"p": 10.0, "r": NOW + 600, "p7": 20.0, "r7": NOW + 86400}
    poller.fetched_at = NOW
    snap = poller.snapshot()
    assert snap["stale"] == 0
    assert snap["ok"] == 0
    assert snap["err"] == SESSION_EXPIRED


def test_dashboard_offers_the_login_form_when_the_session_is_dead():
    status = {
        "logged_in": True,
        "account": {"email": "me@example.com"},
        "access_expires_at": NOW + 3600,
        "refresh_expires_at": NOW - 10,
        "refresh_expiry_known": True,
        "error": SESSION_EXPIRED,
        "usage": {},
        "poll_seconds": 300,
    }
    page = render_page(status, host="192.168.86.42:8790", mdns_name="claudereset.local")
    assert 'action="/paste"' in page
    assert "Riaccedi qui sotto" in page


def test_dashboard_keeps_the_login_form_hidden_while_the_session_lives():
    status = {
        "logged_in": True,
        "account": {"email": "me@example.com"},
        "access_expires_at": NOW + 3600,
        "refresh_expires_at": NOW + 20 * 86400,
        "refresh_expiry_known": True,
        "error": "",
        "usage": {"p": 1.0, "r": NOW + 600, "p7": 2.0, "r7": NOW + 900},
        "poll_seconds": 300,
    }
    page = render_page(status, host="192.168.86.42:8790", mdns_name="claudereset.local")
    assert 'action="/paste"' not in page
