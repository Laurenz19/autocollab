"""Keeps the agents' browsers away from the server's own network.

An agent reads pages and e-mails written by others; one of them may tell it to open
http://127.0.0.1:..., the office network or the cloud metadata address (169.254.169.254) and
report what it sees. Every request of the agents' browsers (pages, images, scripts, fetch, service
workers) and of "Mes connexions" goes through internal_reason() first, whatever the agent's
allowed sites: internal addresses are refused before anything leaves the browser. The address is
checked after DNS resolution, so a public name pointing to an internal IP is caught too.

A firm that really needs an intranet site lists it in AGENT_ALLOWED_INTERNAL_HOSTS (.env):
host names, IPs or networks, comma separated, e.g. "compta.cabinet.lan, 192.168.10.0/24".
"""

import asyncio
import ipaddress
import os
import socket
import time
from urllib.parse import urlparse

BLOCKED_NAMES = {"localhost", "localhost.localdomain", "metadata", "metadata.google.internal",
                 "instance-data", "instance-data.ec2.internal"}
BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa", ".intranet", ".corp")
NETWORK_SCHEMES = ("http", "https", "ws", "wss")
CACHE_SECONDS = 60

_cache: dict[str, tuple[bool, float]] = {}


def _allow_list() -> tuple[set[str], list]:
    names, networks = set(), []
    for item in os.getenv("AGENT_ALLOWED_INTERNAL_HOSTS", "").split(","):
        item = item.strip().lower()
        if not item:
            continue
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            names.add(item)
    return names, networks


def _internal_ip(value: str) -> bool:
    ip = ipaddress.ip_address(value.split("%")[0])
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    return not ip.is_global or ip.is_multicast


def _allowed(host: str, ips: list[str]) -> bool:
    names, networks = _allow_list()
    if host in names:
        return True
    return bool(ips) and all(any(ipaddress.ip_address(i.split("%")[0]) in n for n in networks) for i in ips)


def allowed_host(host: str) -> bool:
    """For a host typed by someone (Mes connexions): is it on the intranet allow list?"""
    host = host.lower().rstrip(".")
    try:
        return _allowed(host, [str(ipaddress.ip_address(host))])
    except ValueError:
        return _allowed(host, [])


async def _resolve(host: str) -> list[str]:
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, OSError):
        return []  # unknown name: the browser will fail on its own
    return list({info[4][0] for info in infos})


async def internal_reason(url: str) -> str | None:
    """The host when `url` points inside the server's network, else None."""
    parsed = urlparse(url)
    if parsed.scheme not in NETWORK_SCHEMES:
        return None
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        return None
    cached = _cache.get(host)
    if cached and cached[1] > time.monotonic():
        return host if cached[0] else None
    try:
        ips = [str(ipaddress.ip_address(host))]
        named = False
    except ValueError:
        ips, named = [], True
    if named and (host in BLOCKED_NAMES or host.endswith(BLOCKED_SUFFIXES)):
        blocked = not _allowed(host, [])
    else:
        if named:
            ips = await _resolve(host)
        blocked = any(_internal_ip(i) for i in ips) and not _allowed(host, ips)
    _cache[host] = (blocked, time.monotonic() + CACHE_SECONDS)
    return host if blocked else None


async def navigation_error(url: str) -> str | None:
    """Why the agent may not open `url` itself (address bar / new tab), or None."""
    scheme = urlparse(url.strip()).scheme.lower()
    if scheme not in ("http", "https"):
        return (f"Adresse refusée : seules les adresses http(s) peuvent être ouvertes ({scheme or 'sans protocole'}:// interdit). "
                "Les fichiers du serveur et les pages internes du navigateur ne sont pas accessibles.")
    host = await internal_reason(url)
    if host:
        return f"Adresse refusée : {host} est une adresse interne du serveur, inaccessible aux agents."
    return None


def route_guard(on_block=None):
    """A Playwright route handler that refuses internal addresses and lets everything else through."""
    async def guard(route):
        try:
            host = await internal_reason(route.request.url)
            if host:
                if on_block:
                    on_block(host, route.request.url)
                await route.abort("blockedbyclient")
            else:
                await route.continue_()
        except Exception:
            pass  # page closed meanwhile
    return guard
