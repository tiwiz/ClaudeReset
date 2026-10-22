"""Claude OAuth (PKCE) and the usage endpoint.

The flow is the one the official CLI uses: authorization code + PKCE, no client secret.
Two redirect flavours are supported:

* ``loopback`` — the browser comes back to this service, which needs the UI to be open on an
  address the browser can reach (the LAN address, not ``localhost``);
* ``paste`` — the browser ends on Anthropic's page that shows ``code#state``, which the user
  pastes into the UI. This is the robust one inside a container.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from . import config


class ClaudeError(RuntimeError):
    """Any failure that should end up in front of the user, in plain words."""

    def __init__(self, message: str, status: int | None = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


@dataclass
class PendingLogin:
    verifier: str
    state: str
    redirect_uri: str
    created_at: float = field(default_factory=time.time)


def pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return verifier, challenge


def new_state() -> str:
    return secrets.token_hex(32)


def post_json(url: str, payload: dict[str, Any], timeout: int = 30) -> dict[str, Any]:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "claude-reset/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        text = ""
        try:
            text = exc.read().decode("utf-8", "replace")[:300]
        except Exception:  # noqa: BLE001
            pass
        raise ClaudeError(f"HTTP {exc.code} da {urllib.parse.urlsplit(url).netloc}", exc.code, text) from exc
    except urllib.error.URLError as exc:
        raise ClaudeError(f"rete non raggiungibile ({exc.reason})") from exc


def get_json(url: str, headers: dict[str, str], timeout: int = 20) -> dict[str, Any]:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        text = ""
        try:
            text = exc.read().decode("utf-8", "replace")[:300]
        except Exception:  # noqa: BLE001
            pass
        raise ClaudeError(f"HTTP {exc.code}", exc.code, text) from exc
    except urllib.error.URLError as exc:
        raise ClaudeError(f"rete non raggiungibile ({exc.reason})") from exc


class ClaudeClient:
    def __init__(
        self,
        *,
        client_id: str = config.CLIENT_ID,
        authorize_url: str = config.AUTHORIZE_URL,
        token_url: str = config.TOKEN_URL,
        usage_url: str = config.USAGE_URL,
        scopes: str = config.SCOPES,
        post_json_fn=post_json,
        get_json_fn=get_json,
    ):
        self.client_id = client_id
        self.authorize_url = authorize_url
        self.token_url = token_url
        self.usage_url = usage_url
        self.scopes = scopes
        self._post = post_json_fn
        self._get = get_json_fn

    # -- login -----------------------------------------------------------
    def start_login(self, redirect_uri: str, scopes: str | None = None) -> tuple[str, PendingLogin]:
        verifier, challenge = pkce_pair()
        pending = PendingLogin(verifier=verifier, state=new_state(), redirect_uri=redirect_uri)
        query = urllib.parse.urlencode(
            {
                "code": "true",
                "client_id": self.client_id,
                "response_type": "code",
                "redirect_uri": redirect_uri,
                "scope": scopes or self.scopes,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": pending.state,
            }
        )
        return f"{self.authorize_url}?{query}", pending

    def exchange_code(self, code: str, pending: PendingLogin) -> dict[str, Any]:
        return self._post(
            self.token_url,
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": pending.redirect_uri,
                "client_id": self.client_id,
                "code_verifier": pending.verifier,
                "state": pending.state,
            },
        )

    def refresh(self, refresh_token: str) -> dict[str, Any]:
        return self._post(
            self.token_url,
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self.client_id,
            },
        )

    # -- data ------------------------------------------------------------
    def fetch_usage(self, access_token: str) -> dict[str, Any]:
        return self._get(
            self.usage_url,
            {
                "Authorization": f"Bearer {access_token}",
                "anthropic-beta": "oauth-2025-04-20",
                "User-Agent": "claude-code/2.0",
                "Accept": "application/json",
            },
        )


def split_iso(moment: str | None) -> float | None:
    """ISO timestamp -> epoch seconds, tolerating the shapes the API sends."""
    if not moment:
        return None
    text = str(moment).replace("Z", "+00:00")
    if "." in text:
        head, _, tail = text.partition(".")
        digits = "".join(c for c in tail if c.isdigit())[:6]
        rest = tail[len(digits):] if len(tail) > len(digits) else ""
        # rebuild conservatively: keep only what datetime.fromisoformat accepts
        zone = rest.lstrip("0123456789")
        text = f"{head}.{digits}{zone}"
    try:
        from datetime import datetime

        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            from datetime import timezone

            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def parse_usage(payload: dict[str, Any]) -> dict[str, Any]:
    """The API shape -> the numbers we care about."""
    five = payload.get("five_hour") or {}
    week = payload.get("seven_day") or {}
    return {
        "p": five.get("utilization"),
        "r": split_iso(five.get("resets_at")),
        "r_iso": five.get("resets_at"),
        "p7": week.get("utilization"),
        "r7": split_iso(week.get("resets_at")),
        "r7_iso": week.get("resets_at"),
    }
