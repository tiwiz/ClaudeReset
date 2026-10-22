"""Token storage: atomic, private, and it must not lose the refresh token on a refresh."""

import json
import os
import stat

from app.store import TokenStore


def test_roundtrip_and_permissions(tmp_path):
    store = TokenStore(tmp_path / "tokens.json")
    store.save({"access_token": "a", "refresh_token": "r"})
    assert store.load()["access_token"] == "a"
    mode = stat.S_IMODE(os.stat(tmp_path / "tokens.json").st_mode)
    assert mode == 0o600


def test_missing_file_is_not_an_error(tmp_path):
    assert TokenStore(tmp_path / "nope.json").load() == {}


def test_unreadable_file_says_what_to_do(tmp_path):
    """The classic Docker mistake: /data owned by root while the container runs as uid 10001."""
    import os

    import pytest

    from app.store import StoreError

    path = tmp_path / "tokens.json"
    path.write_text("{}")
    os.chmod(tmp_path, 0o000)
    try:
        with pytest.raises(StoreError) as err:
            TokenStore(path).load()
        assert "chown 10001:10001" in str(err.value)
    finally:
        os.chmod(tmp_path, 0o700)


def test_token_response_keeps_refresh_token_when_the_api_omits_it(tmp_path):
    store = TokenStore(tmp_path / "tokens.json")
    first = store.save_token_response(
        {
            "access_token": "a1",
            "refresh_token": "r1",
            "expires_in": 28800,
            "account": {"uuid": "u", "email_address": "me@example.com"},
        }
    )
    assert first["access_expires_at"] > 0
    # A refresh that only returns a new access token must not wipe the refresh token.
    second = store.save_token_response({"access_token": "a2", "expires_in": 28800}, previous=first)
    assert second["refresh_token"] == "r1"
    assert second["account"]["email"] == "me@example.com"
    assert second["response_keys"] == ["access_token", "expires_in"]


def test_refresh_expiry_is_recorded_when_the_api_reports_it(tmp_path):
    store = TokenStore(tmp_path / "tokens.json")
    data = store.save_token_response({"access_token": "a", "refresh_token_expires_in": 864000})
    assert data["refresh_expires_at"] > 0


def test_no_token_values_land_in_plain_sight_of_the_response_keys(tmp_path):
    store = TokenStore(tmp_path / "tokens.json")
    store.save_token_response({"access_token": "SECRET", "refresh_token": "SECRET2"})
    raw = (tmp_path / "tokens.json").read_text()
    assert json.loads(raw)["response_keys"] == ["access_token", "refresh_token"]
