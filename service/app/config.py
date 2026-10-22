"""Configuration from environment variables. Every knob has a sane default."""

from __future__ import annotations

import os
import pathlib


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off")


DATA_DIR = pathlib.Path(os.environ.get("DATA_DIR", "/data"))
BIND = os.environ.get("BIND", "0.0.0.0")
PORT = _int("PORT", 8790)

# Polling policy. The quotas move slowly: what changes fast is only the countdown,
# which the display computes on its own. 5 minutes upstream is polite and plenty.
POLL_SECONDS = max(60, _int("POLL_SECONDS", 300))
JITTER_SECONDS = max(0, _int("JITTER_SECONDS", 20))
MIN_POLL_SECONDS = max(30, _int("MIN_POLL_SECONDS", 60))
MAX_BACKOFF_SECONDS = max(60, _int("MAX_BACKOFF_SECONDS", 1800))
STALE_SECONDS = max(120, _int("STALE_SECONDS", 900))
REFRESH_MARGIN_SECONDS = max(60, _int("REFRESH_MARGIN_SECONDS", 600))
MANUAL_REFRESH_MIN_INTERVAL = max(0, _int("MANUAL_REFRESH_MIN_INTERVAL", 60))
CACHE_TTL_SECONDS = max(0, _int("CACHE_TTL_SECONDS", 60))

# Claude OAuth (the same client the official CLI and Headroom use; no client secret,
# the flow is PKCE).
CLIENT_ID = os.environ.get("CLIENT_ID", "9d1c250a-e61b-44d9-88ed-5944d1962f5e")
AUTHORIZE_URL = os.environ.get("AUTHORIZE_URL", "https://claude.com/cai/oauth/authorize")
TOKEN_URL = os.environ.get("TOKEN_URL", "https://platform.claude.com/v1/oauth/token")
MANUAL_REDIRECT_URI = os.environ.get(
    "MANUAL_REDIRECT_URI", "https://platform.claude.com/oauth/code/callback"
)
# Narrow by default: we read quota, we do not need to be able to create API keys.
SCOPES = os.environ.get("SCOPES", "user:profile user:sessions:claude_code user:inference")
# What the official CLI asks for, kept as an escape hatch: the dashboard offers it in one click if
# the usage endpoint refuses the narrow set with a 403.
SCOPES_FULL = os.environ.get(
    "SCOPES_FULL",
    "org:create_api_key user:profile user:inference user:sessions:claude_code "
    "user:mcp_servers user:file_upload user:plugins",
)
USAGE_URL = os.environ.get("USAGE_URL", "https://api.anthropic.com/api/oauth/usage")

# mDNS advertisement so the display finds the service without an IP.
MDNS = _bool("MDNS", True)
MDNS_SERVICE_TYPE = os.environ.get("MDNS_SERVICE_TYPE", "_claudereset._tcp.local.")
MDNS_NAME = os.environ.get("MDNS_NAME", "claudereset")

TOKEN_FILE = DATA_DIR / "tokens.json"
