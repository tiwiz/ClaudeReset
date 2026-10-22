"""Token storage: one JSON file with mode 600, written atomically.

Nothing else ever touches the tokens: they are read to call the API, and the file is
replaced as a whole so a crash in the middle cannot leave half a token behind.
"""

from __future__ import annotations

import json
import os
import pathlib
import threading
import time
from typing import Any


class TokenStore:
    def __init__(self, path: pathlib.Path | str):
        self.path = pathlib.Path(path)
        self._lock = threading.Lock()

    def load(self) -> dict[str, Any]:
        with self._lock:
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                return {}

    def save(self, data: dict[str, Any]) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)

    def clear(self) -> None:
        with self._lock:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass

    # -- helpers ---------------------------------------------------------
    def save_token_response(self, resp: dict[str, Any], *, previous: dict[str, Any] | None = None) -> dict[str, Any]:
        """Store a token endpoint response, keeping only what we need plus key names.

        The response shape is not documented: we record the *names* of the fields we did not
        understand (never their values) so the UI can say what the API actually sent.
        """
        previous = previous or {}
        now = int(time.time())
        expires_in = resp.get("expires_in")
        refresh_expires_in = resp.get("refresh_token_expires_in")
        account = resp.get("account") or {}
        organization = resp.get("organization") or {}

        data = {
            "access_token": resp.get("access_token") or previous.get("access_token"),
            "refresh_token": resp.get("refresh_token") or previous.get("refresh_token"),
            "token_type": resp.get("token_type", previous.get("token_type")),
            "scope": resp.get("scope", previous.get("scope")),
            "account": {
                "email": account.get("email_address") or previous.get("account", {}).get("email"),
                "uuid": account.get("uuid") or previous.get("account", {}).get("uuid"),
            },
            "organization": {
                "uuid": organization.get("uuid")
                or previous.get("organization", {}).get("uuid")
            },
            "subscription": resp.get("subscription_type")
            or previous.get("subscription"),
            "access_expires_at": (
                now + int(expires_in) if expires_in else previous.get("access_expires_at")
            ),
            "refresh_expires_at": (
                now + int(refresh_expires_in)
                if refresh_expires_in
                else previous.get("refresh_expires_at")
            ),
            "obtained_at": now,
            "response_keys": sorted(resp.keys()),
        }
        self.save(data)
        return data
