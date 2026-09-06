#!/usr/bin/env python
"""Live view of every network connection the backend process holds.

A verification tool for the demo, meant to run in a second visible terminal
beside the app. It is deliberately independent of the application: it reads
the kernel's socket table through psutil rather than trusting any counter
inside the process, so it corroborates /system/network-status instead of
repeating it.

Usage:
    .venv/bin/python scripts/traffic_monitor.py            # refresh forever
    .venv/bin/python scripts/traffic_monitor.py --once     # single snapshot
    .venv/bin/python scripts/traffic_monitor.py --port 8000

On macOS the kernel will not hand a process's socket table to an unprivileged
caller, so this falls back to lsof automatically. Run with sudo for the psutil
path.
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import subprocess
import sys
import time
from dataclasses import dataclass

import psutil

LOCAL_NETS = [
    ipaddress.ip_network(n)
    for n in ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16")
]


@dataclass
class Conn:
    laddr: str
    raddr: str
    status: str
    remote_ip: str


def is_local(ip: str) -> bool:
    if not ip:
        return True
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if address.version == 6:
        return address.is_loopback or address.is_private or address.is_link_local
    return any(address in net for net in LOCAL_NETS)


def find_pid(port: int) -> int | None:
    """The process listening on the backend port."""
    try:
        for conn in psutil.net_connections(kind="inet"):
            if conn.status == psutil.CONN_LISTEN and conn.laddr.port == port:
                return conn.pid
    except (psutil.AccessDenied, PermissionError):
        pass
    # Unprivileged fallback.
    try:
        out = subprocess.run(
            ["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"],
            capture_output=True, text=True, timeout=5,
        ).stdout.split()
        return int(out[0]) if out else None
    except Exception:
        return None


def connections_psutil(pid: int) -> list[Conn] | None:
    try:
        raw = psutil.Process(pid).net_connections(kind="inet")
    except (psutil.AccessDenied, PermissionError):
        return None
    except psutil.NoSuchProcess:
        return []
    out = []
    for c in raw:
        rip = c.raddr.ip if c.raddr else ""
        out.append(Conn(
            f"{c.laddr.ip}:{c.laddr.port}" if c.laddr else "-",
            f"{rip}:{c.raddr.port}" if c.raddr else "-",
            c.status, rip,
        ))
    return out


def connections_lsof(pid: int) -> list[Conn]:
    """Fallback that does not need root for a process we own."""
    try:
        result = subprocess.run(
            ["lsof", "-nP", "-a", "-p", str(pid), "-i", "TCP"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return []
    out = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 9:
            continue
        name, status = parts[8], parts[9].strip("()") if len(parts) > 9 else "LISTEN"
        if "->" in name:
            local, remote = name.split("->", 1)
        else:
            local, remote = name, "-"
        rip = remote.rsplit(":", 1)[0] if remote != "-" else ""
        out.append(Conn(local, remote, status, rip))
    return out


def render(pid: int | None, port: int, source: str, conns: list[Conn]) -> str:
    lines = []
    bar = "─" * 78
    lines.append(bar)
    lines.append(f" DRISHTI WORKBENCH — LIVE NETWORK MONITOR      {time.strftime('%H:%M:%S')}")
    lines.append(f" backend pid {pid}  ·  port {port}  ·  via {source}")
    lines.append(bar)

    if pid is None:
        lines.append("  Backend not running on that port.")
        lines.append(bar)
        return "\n".join(lines)

    external = [c for c in conns if c.remote_ip and not is_local(c.remote_ip)]

    lines.append(f"  {'LOCAL':<26} {'REMOTE':<26} {'STATE':<12} SCOPE")
    if not conns:
        lines.append("  (no sockets)")
    for c in sorted(conns, key=lambda c: (c.raddr == "-", c.raddr)):
        scope = "internal" if is_local(c.remote_ip) else "EXTERNAL"
        mark = "  " if scope == "internal" else "!!"
        lines.append(f"{mark}{c.laddr:<26} {c.raddr:<26} {c.status:<12} {scope}")

    lines.append(bar)
    if external:
        lines.append(f"  ❌  {len(external)} EXTERNAL CONNECTION(S) — the air gap is NOT intact")
        for c in external:
            lines.append(f"      -> {c.raddr}")
    else:
        lines.append("  ✅  0 EXTERNAL CONNECTIONS — all traffic is loopback or private")
    lines.append(bar)
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8000, help="backend port (default 8000)")
    ap.add_argument("--interval", type=float, default=2.0, help="refresh seconds")
    ap.add_argument("--once", action="store_true", help="print one snapshot and exit")
    args = ap.parse_args()

    try:
        while True:
            pid = find_pid(args.port)
            conns: list[Conn] = []
            source = "psutil"
            if pid is not None:
                got = connections_psutil(pid)
                if got is None:
                    # macOS denies the socket table to unprivileged callers.
                    conns, source = connections_lsof(pid), "lsof (psutil needs sudo)"
                else:
                    conns = got

            output = render(pid, args.port, source, conns)
            if args.once:
                print(output)
                return 0
            os.system("clear" if os.name != "nt" else "cls")
            print(output)
            print("\n  Ctrl-C to stop.")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nstopped.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
