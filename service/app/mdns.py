"""mDNS advertisement so a display can find the service without being told an IP.

Requires host networking: the container publishes on the host's interfaces.
If `zeroconf` is missing or the network refuses multicast, the service keeps working and
just says so: discovery is a convenience, not a requirement.
"""

from __future__ import annotations

import logging
import socket
import sys

log = lambda *a: print("[mdns]", *a, file=sys.stderr, flush=True)  # noqa: E731


def local_ipv4_addresses() -> list[str]:
    """Private IPv4 addresses of this host, without sending any traffic."""
    found: list[str] = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addr = info[4][0]
            if addr.startswith("127.") or addr in found:
                continue
            parts = [int(p) for p in addr.split(".")]
            private = (
                parts[0] == 10
                or (parts[0] == 192 and parts[1] == 168)
                or (parts[0] == 172 and 16 <= parts[1] <= 31)
            )
            if private:
                found.append(addr)
    except socket.gaierror:
        pass
    if not found:
        # Fall back to the route table: no packet is actually sent on a UDP connect.
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("192.0.2.1", 9))
            found.append(probe.getsockname()[0])
        except OSError:
            pass
        finally:
            probe.close()
    return found


class Advertisement:
    def __init__(self, service_type: str, name: str, port: int, path: str = "/api/usage"):
        self.service_type = service_type
        self.name = name
        self.port = port
        self.path = path
        self._zeroconf = None
        self._info = None

    def start(self) -> str | None:
        addresses = local_ipv4_addresses()
        if not addresses:
            log("nessun indirizzo privato trovato: annuncio saltato")
            return None
        try:
            from zeroconf import ServiceInfo, Zeroconf
        except ImportError:
            log("libreria zeroconf assente: annuncio saltato")
            return None
        try:
            self._zeroconf = Zeroconf()
            self._info = ServiceInfo(
                type_=self.service_type,
                name=f"{self.name}.{self.service_type}",
                addresses=[socket.inet_aton(a) for a in addresses],
                port=self.port,
                properties={"path": self.path, "v": "1"},
                server=f"{self.name}.local.",
            )
            self._zeroconf.register_service(self._info)
        except Exception as exc:  # noqa: BLE001
            log("annuncio non registrato:", exc)
            self._zeroconf = None
            return None
        log(f"annunciato {self.name} {self.service_type} su {', '.join(addresses)}:{self.port}")
        return f"{self.name}.local"

    def stop(self) -> None:
        if self._zeroconf is None:
            return
        try:
            if self._info is not None:
                self._zeroconf.unregister_service(self._info)
            self._zeroconf.close()
        except Exception:  # noqa: BLE001
            pass
