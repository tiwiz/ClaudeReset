#!/usr/bin/env python3
"""Container health check.

``/health`` answers 503 while there is no fresh reading yet, which is a legitimate state (nobody
has signed in yet) and not a broken service. ``urllib`` raises on 503 before you can look at the
status code, so the exception is part of the normal path here.
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request

URL = "http://127.0.0.1:8790/health"
ACCEPTED = (200, 503)


def probe(url: str = URL, timeout: int = 4) -> int:
    try:
        code = urllib.request.urlopen(url, timeout=timeout).status
    except urllib.error.HTTPError as exc:
        code = exc.code
    except Exception:  # noqa: BLE001 - unreachable service, DNS, timeout: all "not healthy"
        return 1
    return 0 if code in ACCEPTED else 1


if __name__ == "__main__":
    raise SystemExit(probe())
