"""Outbound HTTP instrumentation.

Counts every HTTP request this process *attempts*, classified as internal
(loopback or the private Docker network) or external (anything else). The
counter is what makes the air-gap claim checkable at runtime instead of merely
asserted: /system/network-status reports real measurements taken here.

Attempts are counted, not successes. A blocked request still increments the
external counter — which is the point. If the firewall is doing the work and
the application is quietly retrying some cloud endpoint, this surfaces it
rather than reporting a comfortable zero.

Honest boundary: this instruments httpx clients that pass through `attach`,
which is every client the application creates. It is not a kernel-level
packet counter, so it cannot see traffic from a library that opens its own
socket. scripts/traffic_monitor.py exists to check that layer independently,
and the pf rules in scripts/airgap_lockdown.sh are what actually enforce it.
"""

from __future__ import annotations

import ipaddress
import threading
from datetime import datetime, timezone

import httpx

_LOCAL_NAMES = frozenset({"localhost", "0.0.0.0", "::", ""})

_lock = threading.Lock()
_started_at = datetime.now(timezone.utc)
_internal = 0
_external = 0
_last_external_url: str | None = None
_last_external_at: str | None = None


def is_internal_host(host: str) -> bool:
    """Whether a hostname belongs to the machine or the private network.

    Three cases count as internal:

    * the well-known loopback names;
    * any address inside a loopback, private or link-local range, which covers
      Docker's 172.16/12 bridge networks and a plant LAN alike;
    * a single-label hostname such as "ollama" or "backend". A name with no
      dot cannot be a public DNS name, so in practice it is a Docker Compose
      service on the internal network.
    """
    host = host.strip().lower().strip("[]")
    if host in _LOCAL_NAMES:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        # Not a literal address, so judge by name shape.
        return "." not in host or host.endswith((".local", ".internal"))
    return (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_unspecified
    )


def record(url: httpx.URL | str) -> None:
    """Count one attempted request. Safe to call from any thread."""
    global _internal, _external, _last_external_url, _last_external_at

    host = httpx.URL(str(url)).host
    internal = is_internal_host(host)
    with _lock:
        if internal:
            _internal += 1
        else:
            _external += 1
            _last_external_url = str(url)
            _last_external_at = datetime.now(timezone.utc).isoformat()


async def _hook(request: httpx.Request) -> None:
    record(request.url)


def attach(client: httpx.AsyncClient) -> httpx.AsyncClient:
    """Register the counter on a client, preserving any existing hooks."""
    hooks = dict(client.event_hooks)
    hooks["request"] = [*hooks.get("request", []), _hook]
    client.event_hooks = hooks
    return client


def snapshot() -> dict[str, object]:
    """Current counts, for the network-status endpoint."""
    with _lock:
        internal, external = _internal, _external
        last_url, last_at = _last_external_url, _last_external_at

    now = datetime.now(timezone.utc)
    return {
        "external_call_attempts": external,
        "internal_call_count": internal,
        "last_external_attempt": (
            {"url": last_url, "at": last_at} if last_url else None
        ),
        "started_at": _started_at.isoformat(),
        "uptime_seconds": round((now - _started_at).total_seconds(), 1),
        "timestamp": now.isoformat(),
    }


def reset() -> None:
    """Zero the counters. Used by tests, never by the running application."""
    global _internal, _external, _last_external_url, _last_external_at
    with _lock:
        _internal = _external = 0
        _last_external_url = _last_external_at = None
