"""Each user's list of sites for "Mes connexions" (Gmail, their bank, a client portal...)."""

import re
import uuid
from datetime import datetime
from urllib.parse import urlparse

from .db import connect

MAX_SITES_PER_USER = 30

# Offered when adding a connection; the user can type anything else.
SUGGESTIONS = [
    {"name": "Gmail", "url": "https://mail.google.com"},
    {"name": "Outlook", "url": "https://outlook.office.com/mail/"},
    {"name": "Pennylane", "url": "https://app.pennylane.com"},
    {"name": "Google Drive", "url": "https://drive.google.com"},
    {"name": "impots.gouv (pro)", "url": "https://cfspro.impots.gouv.fr"},
    {"name": "Qonto", "url": "https://app.qonto.com"},
    {"name": "URSSAF", "url": "https://www.urssaf.fr"},
    {"name": "net-entreprises", "url": "https://www.net-entreprises.fr"},
]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def list_for(owner: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM sites WHERE owner = ? ORDER BY name COLLATE NOCASE", (owner,)).fetchall()
    return [dict(r) for r in rows]


def get(site_id: str, owner: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM sites WHERE id = ? AND owner = ?", (site_id, owner)).fetchone()
    return dict(row) if row else None


def create(owner: str, name: str, url: str) -> dict:
    with connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM sites WHERE owner = ?", (owner,)).fetchone()[0]
        if count >= MAX_SITES_PER_USER:
            raise ValueError(f"{MAX_SITES_PER_USER} connexions au maximum.")
        site = {"id": uuid.uuid4().hex[:12], "owner": owner, "name": name, "url": url, "created_at": _now(), "last_opened_at": None}
        conn.execute("INSERT INTO sites (id, owner, name, url, created_at, last_opened_at)"
                     " VALUES (:id, :owner, :name, :url, :created_at, :last_opened_at)", site)
    return site


def update(site_id: str, owner: str, name: str, url: str) -> dict | None:
    with connect() as conn:
        conn.execute("UPDATE sites SET name = ?, url = ? WHERE id = ? AND owner = ?", (name, url, site_id, owner))
    return get(site_id, owner)


def delete(site_id: str, owner: str) -> bool:
    with connect() as conn:
        return conn.execute("DELETE FROM sites WHERE id = ? AND owner = ?", (site_id, owner)).rowcount > 0


# Pages that mean "not signed in": a login address, or a shared login site.
_LOGIN_PATH = re.compile(r"(log-?in|sign-?in|sign_in|connexion|authenticat|/auth\b|/sso\b|/oauth|/session/new|/identifier)", re.I)
_LOGIN_HOSTS = ("accounts.google.com", "login.microsoftonline.com", "login.live.com", "auth.qonto.com", "login.pennylane.com")


def _base(host: str) -> str:
    parts = host.split(".")
    return host if host.replace(".", "").isdigit() else ".".join(parts[-2:])


def _same_site(site_host: str, page_host: str) -> bool:
    return page_host == site_host or page_host.endswith("." + site_host) or site_host.endswith("." + page_host)


def record_page(owner: str, url: str, has_password: bool, opened_site_id: str | None = None) -> None:
    """Update the "Connecté / Non connecté" state of the sites a page belongs to.

    Signed in: on the site itself, no login address and no password field. Not signed in: a login
    page of the site, or the shared login site of its provider (accounts.google.com for Gmail...).
    """
    page = urlparse(url or "")
    page_host = (page.hostname or "").lower()
    if not page_host or page.scheme not in ("http", "https"):
        return
    login_host = page_host in _LOGIN_HOSTS
    on_login = login_host or has_password or bool(_LOGIN_PATH.search(page.path + "?" + page.query))
    now = _now()
    with connect() as conn:
        for site in conn.execute("SELECT id, url FROM sites WHERE owner = ?", (owner,)).fetchall():
            site_host = (urlparse(site["url"]).hostname or "").lower()
            if _same_site(site_host, page_host):
                state = 0 if on_login else 1
            elif (login_host and _base(site_host) == _base(page_host)) or (site["id"] == opened_site_id and on_login):
                state = 0  # redirected to the provider's login page
            else:
                continue
            conn.execute("UPDATE sites SET signed_in = ?, checked_at = ? WHERE id = ?", (state, now, site["id"]))


def mark_opened(site_id: str, owner: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE sites SET last_opened_at = ? WHERE id = ? AND owner = ?", (_now(), site_id, owner))
