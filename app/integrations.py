"""Applications connected through MCP (Gmail, Google Drive, Slack...), per user.

An administrator registers the firm's OAuth apps once (Google, Slack) and chooses which
applications are offered. Each user then connects their own account; their tokens are kept
encrypted in the database and only ever used server side, by their own agents.

During a run, the agent gets the tools of the user's active connections as one extra action,
next to the browser (see runner.py).
"""

import base64
import hashlib
import json
import secrets
import threading
import time
import uuid
from datetime import datetime
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken

from . import auth, config, settings, vault
from .db import connect
from .mcp_client import MCPClient

MAX_PER_USER = 20
STATE_TTL_SECONDS = 600

GOOGLE = "https://www.googleapis.com/auth/"
SLACK_READ = ["search:read.public", "search:read.private", "search:read.mpim", "search:read.im", "search:read.files",
              "search:read.users", "files:read", "channels:history", "groups:history", "mpim:history", "im:history",
              "channels:read", "groups:read", "im:read", "mpim:read", "users:read", "users:read.email", "canvases:read",
              "reactions:read"]
SLACK_WRITE = ["chat:write", "files:write", "canvases:write", "reactions:write"]

# Official remote MCP servers. "read" scopes are always asked; "write" ones only without read-only.
CATALOG = {
    "gmail": {"name": "Gmail", "provider": "google", "url": "https://gmailmcp.googleapis.com/mcp/v1",
              "read": [GOOGLE + "gmail.readonly"], "write": [GOOGLE + "gmail.compose"],
              "description": "Chercher et lire les e-mails ; préparer des brouillons."},
    "drive": {"name": "Google Drive", "provider": "google", "url": "https://drivemcp.googleapis.com/mcp/v1",
              "read": [GOOGLE + "drive.readonly"], "write": [GOOGLE + "drive.file"],
              "description": "Chercher et lire les fichiers ; en créer."},
    "docs": {"name": "Google Docs", "provider": "google", "url": "https://docsmcp.googleapis.com/mcp/v1",
             "read": [GOOGLE + "drive.readonly", GOOGLE + "documents.readonly"], "write": [GOOGLE + "drive.file", GOOGLE + "documents"],
             "description": "Lire et rédiger des documents."},
    "sheets": {"name": "Google Sheets", "provider": "google", "url": "https://sheetsmcp.googleapis.com/mcp/v1",
               "read": [GOOGLE + "drive.readonly", GOOGLE + "spreadsheets.readonly"], "write": [GOOGLE + "drive.file", GOOGLE + "spreadsheets"],
               "description": "Lire et remplir des tableurs."},
    "calendar": {"name": "Google Agenda", "provider": "google", "url": "https://calendarmcp.googleapis.com/mcp/v1",
                 "read": [GOOGLE + "calendar.calendarlist.readonly", GOOGLE + "calendar.events.freebusy", GOOGLE + "calendar.events.readonly"],
                 "write": [], "description": "Consulter les agendas et les disponibilités."},
    "slack": {"name": "Slack", "provider": "slack", "url": "https://mcp.slack.com/mcp",
              "read": SLACK_READ, "write": SLACK_WRITE,
              "description": "Chercher et lire les messages ; en envoyer."},
}

OAUTH = {
    "google": {"label": "Google", "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
               "token": "https://oauth2.googleapis.com/token", "revoke": "https://oauth2.googleapis.com/revoke",
               "scope_sep": " ", "console": "https://console.cloud.google.com/apis/credentials"},
    "slack": {"label": "Slack", "authorize": "https://slack.com/oauth/v2_user/authorize",
              "token": "https://slack.com/api/oauth.v2.user.access", "revoke": "https://slack.com/api/auth.revoke",
              "scope_sep": ",", "console": "https://api.slack.com/apps"},
}

CALLBACK_PATH = "/api/integrations/callback"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# --- administrator settings (data/settings.json, key "integrations") -------------------


def admin_config() -> dict:
    data = settings.load().get("integrations") or {}
    return {
        "oauth": {p: {"client_id": (data.get("oauth") or {}).get(p, {}).get("client_id", ""),
                      "client_secret": (data.get("oauth") or {}).get(p, {}).get("client_secret", "")} for p in OAUTH},
        "enabled": [k for k in data.get("enabled", []) if k in CATALOG],
        "allow_custom": bool(data.get("allow_custom", False)),
    }


def save_admin_config(changes: dict) -> None:
    current = admin_config()
    for provider, values in (changes.get("oauth") or {}).items():
        if provider not in OAUTH:
            continue
        if values.get("client_id") is not None:
            current["oauth"][provider]["client_id"] = values["client_id"].strip()
        secret = values.get("client_secret")
        if secret is None and values.get("clear_secret"):
            current["oauth"][provider]["client_secret"] = ""
        elif secret and secret.strip():
            current["oauth"][provider]["client_secret"] = secret.strip()
    if "enabled" in changes:
        current["enabled"] = [k for k in changes["enabled"] if k in CATALOG]
    if "allow_custom" in changes:
        current["allow_custom"] = bool(changes["allow_custom"])
    settings.update_section("integrations", current)


def configured(provider: str) -> bool:
    oauth = admin_config()["oauth"].get(provider) or {}
    return bool(oauth.get("client_id") and oauth.get("client_secret"))


def admin_view(base_url: str) -> dict:
    cfg = admin_config()
    return {
        "oauth": {p: {"client_id": v["client_id"], "secret_set": bool(v["client_secret"]),
                      "secret_hint": f"…{v['client_secret'][-4:]}" if len(v["client_secret"]) >= 8 else "",
                      "label": OAUTH[p]["label"], "console": OAUTH[p]["console"]}
                  for p, v in cfg["oauth"].items()},
        "enabled": cfg["enabled"],
        "allow_custom": cfg["allow_custom"],
        "redirect_uri": redirect_uri(base_url),
        "catalog": catalog_view(),
    }


def catalog_view() -> list[dict]:
    return [{"kind": k, "name": v["name"], "provider": v["provider"], "description": v["description"],
             "can_write": bool(v["write"])} for k, v in CATALOG.items()]


def redirect_uri(base_url: str) -> str:
    base = (config.PUBLIC_URL or base_url).rstrip("/")
    return base + CALLBACK_PATH


# --- encrypted tokens ------------------------------------------------------


def _seal(data: dict) -> str:
    return vault.seal(json.dumps(data))


def _open(blob: str | None) -> dict:
    if not blob:
        return {}
    if vault.is_sealed(blob):
        try:
            return json.loads(vault.unseal(blob) or "{}")
        except ValueError:
            return {}
    return _open_legacy(blob)


def _open_legacy(blob: str) -> dict:
    """Tokens encrypted with the old data/secret.key, before the master key existed."""
    legacy = auth.legacy_secret()
    if not legacy:
        return {}
    try:
        key = base64.urlsafe_b64encode(hashlib.sha256(b"integrations:" + legacy).digest())
        return json.loads(Fernet(key).decrypt(blob.encode()))
    except (InvalidToken, ValueError):
        return {}  # unreadable: the user has to reconnect


def migrate() -> int:
    """Re-encrypt the old tokens with the master key, then drop data/secret.key. Returns how many."""
    with connect() as conn:
        rows = conn.execute("SELECT id, secret FROM integrations WHERE secret IS NOT NULL").fetchall()
    moved = 0
    for row in rows:
        if vault.is_sealed(row["secret"]):
            continue
        data = _open_legacy(row["secret"])
        _set(row["id"], secret=_seal(data) if data else None, **({} if data else {"last_error": "À reconnecter"}))
        moved += 1
    if auth.SECRET_FILE.exists():
        auth.SECRET_FILE.unlink()  # no longer used: sessions are signed with a key derived from the master key
    return moved


# --- storage -----------------------------------------------------------------


def _view(row) -> dict:
    item = dict(row)
    item.pop("secret", None)
    item["read_only"] = bool(item["read_only"])
    item["enabled"] = bool(item["enabled"])
    item["icon"] = item["kind"] if item["kind"] in CATALOG else "mcp"
    return item


def list_for(owner: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM integrations WHERE owner = ? ORDER BY created_at", (owner,)).fetchall()
    return [_view(r) for r in rows]


def _row(integration_id: str, owner: str):
    with connect() as conn:
        return conn.execute("SELECT * FROM integrations WHERE id = ? AND owner = ?", (integration_id, owner)).fetchone()


def get(integration_id: str, owner: str) -> dict | None:
    row = _row(integration_id, owner)
    return _view(row) if row else None


def _count(owner: str) -> int:
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM integrations WHERE owner = ?", (owner,)).fetchone()[0]


def save_connection(owner: str, kind: str, name: str, url: str, secret: dict, read_only: bool, account: str = "") -> dict:
    """Create the connection, or replace the same application's (reconnecting keeps one tile)."""
    with connect() as conn:
        existing = None
        if kind != "custom":
            existing = conn.execute("SELECT id FROM integrations WHERE owner = ? AND kind = ?", (owner, kind)).fetchone()
        if existing:
            conn.execute("UPDATE integrations SET secret = ?, read_only = ?, account = ?, last_error = NULL, url = ?"
                         " WHERE id = ?", (_seal(secret), int(read_only), account, url, existing["id"]))
            integration_id = existing["id"]
        else:
            if conn.execute("SELECT COUNT(*) FROM integrations WHERE owner = ?", (owner,)).fetchone()[0] >= MAX_PER_USER:
                raise ValueError(f"{MAX_PER_USER} applications connectées au maximum.")
            integration_id = uuid.uuid4().hex[:12]
            conn.execute(
                "INSERT INTO integrations (id, owner, kind, name, url, secret, read_only, enabled, account, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
                (integration_id, owner, kind, name, url, _seal(secret), int(read_only), account, _now()),
            )
    return get(integration_id, owner)


def update(integration_id: str, owner: str, enabled: bool | None = None, name: str | None = None) -> dict | None:
    with connect() as conn:
        if enabled is not None:
            conn.execute("UPDATE integrations SET enabled = ? WHERE id = ? AND owner = ?", (int(enabled), integration_id, owner))
        if name is not None:
            conn.execute("UPDATE integrations SET name = ? WHERE id = ? AND owner = ?", (name, integration_id, owner))
    return get(integration_id, owner)


def _set(integration_id: str, **fields) -> None:
    sets = ", ".join(f"{k} = ?" for k in fields)
    with connect() as conn:
        conn.execute(f"UPDATE integrations SET {sets} WHERE id = ?", (*fields.values(), integration_id))


async def delete(integration_id: str, owner: str) -> bool:
    row = _row(integration_id, owner)
    if not row:
        return False
    secret = _open(row["secret"])
    provider = CATALOG.get(row["kind"], {}).get("provider")
    if provider and secret.get("access_token"):
        await _revoke(provider, secret.get("refresh_token") or secret["access_token"])
    with connect() as conn:
        conn.execute("DELETE FROM integrations WHERE id = ? AND owner = ?", (integration_id, owner))
    return True


async def _revoke(provider: str, token: str) -> None:
    """Best effort: tell Google or Slack the access is withdrawn."""
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            if provider == "google":
                await http.post(OAUTH["google"]["revoke"], data={"token": token})
            else:
                await http.post(OAUTH["slack"]["revoke"], headers={"Authorization": f"Bearer {token}"})
    except Exception:
        pass


# --- OAuth sign-in -------------------------------------------------------------

_pending: dict[str, dict] = {}
_pending_lock = threading.Lock()


def authorize_url(owner: str, kind: str, read_only: bool, base_url: str) -> str:
    app_ = CATALOG[kind]
    provider = app_["provider"]
    oauth = admin_config()["oauth"][provider]
    if not (oauth["client_id"] and oauth["client_secret"]):
        raise ValueError(f"{OAUTH[provider]['label']} n'est pas encore configuré par un administrateur.")
    if kind not in admin_config()["enabled"]:
        raise ValueError(f"{app_['name']} n'est pas proposé par votre cabinet.")
    scopes = app_["read"] + ([] if read_only else app_["write"])
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    with _pending_lock:
        now = time.time()
        for key in [k for k, v in _pending.items() if now - v["at"] > STATE_TTL_SECONDS]:
            del _pending[key]
        _pending[state] = {"owner": owner, "kind": kind, "read_only": read_only, "verifier": verifier,
                           "redirect_uri": redirect_uri(base_url), "at": now}
    scope = OAUTH[provider]["scope_sep"].join(dict.fromkeys(scopes))
    params = {"client_id": oauth["client_id"], "redirect_uri": redirect_uri(base_url), "response_type": "code",
              "scope": scope, "state": state}
    if provider == "google":
        params.update({"access_type": "offline", "prompt": "consent", "include_granted_scopes": "false",
                       "code_challenge": challenge, "code_challenge_method": "S256"})
    else:
        params["user_scope"] = scope  # Slack's name for user-token scopes
    return OAUTH[provider]["authorize"] + "?" + urlencode(params)


async def finish_sign_in(owner: str, state: str, code: str) -> dict:
    with _pending_lock:
        pending = _pending.pop(state, None)
    if not pending or pending["owner"] != owner or time.time() - pending["at"] > STATE_TTL_SECONDS:
        raise ValueError("Connexion expirée ou demandée par un autre compte : recommencez depuis « Mes connexions ».")
    kind = pending["kind"]
    provider = CATALOG[kind]["provider"]
    oauth = admin_config()["oauth"][provider]
    request = {"grant_type": "authorization_code", "code": code, "redirect_uri": pending["redirect_uri"],
               "client_id": oauth["client_id"], "client_secret": oauth["client_secret"]}
    if provider == "google":
        request["code_verifier"] = pending["verifier"]
    tokens = await _token_request(provider, request)
    account = ""
    if provider == "slack":
        account = (tokens.get("team") or {}).get("name", "")
    secret = {"access_token": tokens["access_token"], "refresh_token": tokens.get("refresh_token"),
              "expires_at": time.time() + int(tokens["expires_in"]) if tokens.get("expires_in") else None}
    app_ = CATALOG[kind]
    connection = save_connection(owner, kind, app_["name"], app_["url"], secret, pending["read_only"], account)
    if provider == "google" and not account:
        account = await _google_email(secret["access_token"])
        if account:
            _set(connection["id"], account=account)
    return get(connection["id"], owner)


async def _token_request(provider: str, data: dict) -> dict:
    async with httpx.AsyncClient(timeout=20) as http:
        response = await http.post(OAUTH[provider]["token"], data=data, headers={"Accept": "application/json"})
    try:
        body = response.json()
    except ValueError:
        body = {}
    if provider == "slack":
        if not body.get("ok"):
            raise ValueError(f"Slack a refusé la connexion : {body.get('error') or response.status_code}.")
        user = body.get("authed_user") or {}
        body = {**body, **{k: v for k, v in user.items() if k in ("access_token", "refresh_token", "expires_in")}}
    if response.status_code >= 400 or not body.get("access_token"):
        detail = body.get("error_description") or body.get("error") or response.text[:200]
        raise ValueError(f"{OAUTH[provider]['label']} a refusé la connexion : {detail}")
    return body


async def _google_email(access_token: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            r = await http.get("https://www.googleapis.com/oauth2/v3/tokeninfo", params={"access_token": access_token})
        return r.json().get("email", "") if r.status_code == 200 else ""
    except Exception:
        return ""


async def access_token(row) -> str | None:
    """A valid access token for this connection, refreshed if it is about to expire."""
    secret = _open(row["secret"])
    if not secret:
        return None
    expires_at = secret.get("expires_at")
    provider = CATALOG.get(row["kind"], {}).get("provider")
    if provider and expires_at is not None and expires_at - time.time() < 120 and secret.get("refresh_token"):
        oauth = admin_config()["oauth"][provider]
        tokens = await _token_request(provider, {
            "grant_type": "refresh_token", "refresh_token": secret["refresh_token"],
            "client_id": oauth["client_id"], "client_secret": oauth["client_secret"],
        })
        secret["access_token"] = tokens["access_token"]
        secret["refresh_token"] = tokens.get("refresh_token") or secret["refresh_token"]
        secret["expires_at"] = time.time() + int(tokens["expires_in"]) if tokens.get("expires_in") else None
        _set(row["id"], secret=_seal(secret))
    return secret.get("access_token")


# --- custom servers and tools ---------------------------------------------------


async def list_tools(row) -> list[dict]:
    token = await access_token(row)
    async with MCPClient(row["url"], token, timeout=30) as client:
        return await client.list_tools()


async def check(integration_id: str, owner: str) -> dict:
    """Open a session and list the tools: the "Tester" button."""
    row = _row(integration_id, owner)
    if not row:
        raise LookupError
    try:
        tools = await list_tools(row)
    except Exception as e:
        message = str(e).splitlines()[0][:300] if str(e) else type(e).__name__
        _set(integration_id, last_error=message)
        raise ValueError(message)
    _set(integration_id, last_error=None, last_used_at=_now())
    return {"ok": True, "tools": [{"name": t.get("name"), "description": (t.get("description") or "")[:200],
                                   "read_only": is_read_only(t)} for t in tools]}


async def add_custom(owner: str, name: str, url: str, token: str, read_only: bool) -> dict:
    if not admin_config()["allow_custom"]:
        raise ValueError("Votre cabinet n'autorise pas l'ajout d'autres serveurs MCP.")
    try:
        async with MCPClient(url, token or None, timeout=20) as client:
            await client.list_tools()
    except Exception as e:
        message = str(e).splitlines()[0][:300] if str(e) else type(e).__name__
        raise ValueError(f"Connexion au serveur impossible : {message}")
    return save_connection(owner, "custom", name, url, {"access_token": token or None}, read_only)


def is_read_only(tool: dict) -> bool:
    return bool((tool.get("annotations") or {}).get("readOnlyHint"))


def mark_used(integration_id: str, error: str | None = None) -> None:
    _set(integration_id, last_used_at=_now(), last_error=error)


def active_rows(owner: str) -> list:
    """The connections a run of this user may use: switched on, and still offered by the firm."""
    cfg = admin_config()
    with connect() as conn:
        rows = conn.execute("SELECT * FROM integrations WHERE owner = ? AND enabled = 1 ORDER BY created_at", (owner,)).fetchall()
    return [r for r in rows if (r["kind"] == "custom" and cfg["allow_custom"]) or r["kind"] in cfg["enabled"]]
