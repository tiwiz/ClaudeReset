"""OAuth request shapes and the mapping from the API payload to our numbers."""

import urllib.parse

from app.claude import ClaudeClient, parse_usage, pkce_pair, split_iso

RESP = {
    "access_token": "at",
    "refresh_token": "rt",
    "expires_in": 28800,
    "account": {"uuid": "u1", "email_address": "me@example.com"},
}


def make_client(calls):
    def post(url, payload, timeout=30):
        calls.append(("POST", url, payload))
        return dict(RESP)

    def get(url, headers, timeout=20):
        calls.append(("GET", url, headers))
        return {
            "five_hour": {"utilization": 12.5, "resets_at": "2026-10-22T17:23:32.298000+00:00"},
            "seven_day": {"utilization": 65.0, "resets_at": "2026-10-25T07:01:36Z"},
        }

    return ClaudeClient(post_json_fn=post, get_json_fn=get), calls


def test_authorize_url_has_the_pkce_parameters():
    client, _ = make_client([])
    url, pending = client.start_login("http://192.168.86.76:8790/callback")
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    assert query["client_id"] == [client.client_id]
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["state"] == [pending.state]
    assert query["redirect_uri"] == ["http://192.168.86.76:8790/callback"]
    assert "code_challenge" in query


def test_pkce_pair_is_urlsafe_and_s256():
    verifier, challenge = pkce_pair()
    assert 43 <= len(verifier) <= 128
    assert "=" not in verifier and "=" not in challenge


def test_exchange_sends_code_verifier_and_state():
    client, calls = make_client([])
    _, pending = client.start_login("http://h/callback")
    client.exchange_code("the-code", pending)
    _, url, payload = calls[-1]
    assert url == client.token_url
    assert payload["grant_type"] == "authorization_code"
    assert payload["code"] == "the-code"
    assert payload["code_verifier"] == pending.verifier
    assert payload["state"] == pending.state
    assert payload["client_id"] == client.client_id


def test_refresh_sends_only_what_is_needed():
    client, calls = make_client([])
    client.refresh("rt")
    _, url, payload = calls[-1]
    assert payload == {"grant_type": "refresh_token", "refresh_token": "rt", "client_id": client.client_id}


def test_usage_request_headers():
    client, calls = make_client([])
    client.fetch_usage("tok")
    _, url, headers = calls[-1]
    assert headers["Authorization"] == "Bearer tok"
    assert headers["anthropic-beta"] == "oauth-2025-04-20"


def test_parse_usage_maps_both_windows():
    out = parse_usage(
        {
            "five_hour": {"utilization": 12.5, "resets_at": "2026-10-22T17:23:32+00:00"},
            "seven_day": {"utilization": 65.0, "resets_at": "2026-10-25T07:01:36+00:00"},
        }
    )
    assert out["p"] == 12.5 and out["p7"] == 65.0
    assert out["r"] < out["r7"]


def test_split_iso_tolerates_microseconds_and_z():
    assert split_iso("2026-10-22T17:23:32.298000+00:00") is not None
    assert split_iso("2026-10-25T07:01:36Z") is not None
    assert split_iso("non-una-data") is None
    assert split_iso(None) is None


def test_parse_usage_survives_a_missing_window():
    out = parse_usage({})
    assert out["p"] is None and out["r"] is None
