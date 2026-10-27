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
import re
import secrets
import threading
import time
import uuid
from datetime import datetime
from urllib.parse import urlencode, urlparse

import httpx
from cryptography.fernet import Fernet, InvalidToken

from . import auth, config, settings, vault
from .db import connect
from .mcp_client import MCPAuthError, MCPClient, MCPError

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
# Where this app describes itself to an MCP server's OAuth server that identifies clients by URL (CIMD).
CLIENT_METADATA_PATH = "/api/integrations/client-metadata.json"


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
    elif (secret.get("oauth") or {}).get("revocation_endpoint"):
        try:
            oauth = secret["oauth"]
            async with httpx.AsyncClient(timeout=10) as http:
                await http.post(oauth["revocation_endpoint"], data={"token": secret.get("refresh_token") or secret.get("access_token"),
                                                                    "client_id": oauth["client_id"]})
        except Exception:
            pass
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
        raise ValueError(f"{app_['name']} n'est pas proposé par votre organisation.")
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
    if pending["kind"] == "custom":
        return await _finish_custom_sign_in(owner, pending, code)
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
    elif secret.get("oauth") and expires_at is not None and expires_at - time.time() < 120 and secret.get("refresh_token"):
        oauth = secret["oauth"]
        tokens = await _oauth_token(oauth, {"grant_type": "refresh_token", "refresh_token": secret["refresh_token"],
                                            **({"resource": oauth["resource"]} if oauth.get("resource") else {})})
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


async def add_custom(owner: str, name: str, url: str, token: str, read_only: bool, base_url: str) -> dict:
    """Add another MCP server: with the access token given, or without any, or through the server's own sign-in
    (OAuth, as the MCP specification describes it). Returns {"connection": ...} or {"sign_in_url": ...}."""
    if not admin_config()["allow_custom"]:
        raise ValueError("Votre organisation n'autorise pas l'ajout d'autres serveurs MCP.")
    # People often give the server's bare address: its MCP endpoint is then usually /mcp.
    candidates = [url] + ([url.rstrip("/") + "/mcp"] if urlparse(url).path in ("", "/") else [])
    failure = None
    for candidate in candidates:
        try:
            async with MCPClient(candidate, token or None, timeout=20) as client:
                await client.list_tools()
            return {"connection": save_connection(owner, "custom", name, candidate, {"access_token": token or None}, read_only)}
        except MCPAuthError:
            if token:
                raise ValueError("Le serveur a refusé ce jeton d'accès.")
            return {"sign_in_url": await _start_custom_sign_in(owner, name, candidate, read_only, base_url)}
        except Exception as e:
            failure = str(e).splitlines()[0][:300] if str(e) else type(e).__name__
    raise ValueError(f"Connexion au serveur impossible : {failure}")


# --- sign-in to other MCP servers (OAuth 2.1 as the MCP specification describes it) -----------------------
#
# The server says where to sign in (RFC 9728 protected resource metadata), its authorization server says how
# (RFC 8414), and this app registers itself: dynamic client registration (RFC 7591) when offered, else its
# client id is the address of a document describing it (Client ID Metadata Document). PKCE always.

_INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "AutoCollab", "version": "1.0"}}}


def _well_known(url: str, name: str) -> list[str]:
    """Where a /.well-known document of this address may be: path-aware first, then at the root."""
    parts = urlparse(url)
    origin, path = f"{parts.scheme}://{parts.netloc}", parts.path.rstrip("/")
    return ([f"{origin}/.well-known/{name}{path}"] if path else []) + [f"{origin}/.well-known/{name}"]


async def _json(http, url: str) -> dict | None:
    try:
        r = await http.get(url, headers={"Accept": "application/json"})
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


async def _discover(url: str) -> dict:
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as http:
        challenge = ""
        try:
            r = await http.post(url, json=_INIT, headers={"Accept": "application/json, text/event-stream"})
            challenge = r.headers.get("www-authenticate", "")
        except Exception:
            pass
        hinted = re.search(r'resource_metadata="([^"]+)"', challenge)
        resource = None
        for candidate in ([hinted.group(1)] if hinted else []) + _well_known(url, "oauth-protected-resource"):
            resource = await _json(http, candidate)
            if resource and resource.get("authorization_servers"):
                break
            resource = None
        if not resource:
            raise ValueError("Ce serveur demande une connexion sans indiquer comment l'obtenir : il faut un jeton d'accès.")
        issuer = resource["authorization_servers"][0]
        server = None
        for candidate in _well_known(issuer, "oauth-authorization-server") + _well_known(issuer, "openid-configuration"):
            server = await _json(http, candidate)
            if server and server.get("authorization_endpoint") and server.get("token_endpoint"):
                break
            server = None
        if not server:
            raise ValueError("Le serveur de connexion de ce service est introuvable : il faut un jeton d'accès.")
    hinted_scope = re.search(r'scope="([^"]+)"', challenge)
    scopes = hinted_scope.group(1).split() if hinted_scope else list(resource.get("scopes_supported") or [])
    if "offline_access" in (server.get("scopes_supported") or []) and "offline_access" not in scopes:
        scopes.append("offline_access")  # a refresh token: the connection lasts beyond the first hour
    return {"resource": resource.get("resource") or url, "server": server, "scopes": scopes}


def client_metadata(base_url: str) -> dict:
    """This app as an OAuth client, for servers that identify clients by the address of this document."""
    base = (config.PUBLIC_URL or base_url).rstrip("/")
    return {"client_id": base + CLIENT_METADATA_PATH, "client_name": "AutoCollab", "client_uri": base,
            "redirect_uris": [redirect_uri(base_url)], "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"], "token_endpoint_auth_method": "none"}


async def _register(server: dict, base_url: str) -> dict:
    methods = server.get("token_endpoint_auth_methods_supported") or ["client_secret_basic"]
    if server.get("registration_endpoint"):
        method = "none" if "none" in methods else "client_secret_post" if "client_secret_post" in methods else "client_secret_basic"
        body = {"client_name": "AutoCollab", "redirect_uris": [redirect_uri(base_url)], "response_types": ["code"],
                "grant_types": ["authorization_code", "refresh_token"], "token_endpoint_auth_method": method}
        async with httpx.AsyncClient(timeout=15) as http:
            r = await http.post(server["registration_endpoint"], json=body, headers={"Accept": "application/json"})
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code >= 400 or not data.get("client_id"):
            raise ValueError(f"Le service a refusé l'enregistrement de l'application : {data.get('error_description') or data.get('error') or r.status_code}")
        return {"client_id": data["client_id"], "client_secret": data.get("client_secret"),
                "auth_method": data.get("token_endpoint_auth_method") or method}
    if server.get("client_id_metadata_document_supported"):
        document = client_metadata(base_url)
        if not document["client_id"].startswith("https://"):
            raise ValueError("Ce service demande une adresse publique en https:// : renseignez PUBLIC_URL dans le fichier .env.")
        return {"client_id": document["client_id"], "client_secret": None, "auth_method": "none"}
    raise ValueError("Ce service n'accepte pas l'enregistrement automatique d'une application : il faut un jeton d'accès.")


async def _start_custom_sign_in(owner: str, name: str, url: str, read_only: bool, base_url: str) -> str:
    found = await _discover(url)
    server = found["server"]
    client = await _register(server, base_url)
    state, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    oauth = {**client, "token_endpoint": server["token_endpoint"], "revocation_endpoint": server.get("revocation_endpoint"),
             "resource": found["resource"], "issuer": server.get("issuer")}
    with _pending_lock:
        now = time.time()
        for key in [k for k, v in _pending.items() if now - v["at"] > STATE_TTL_SECONDS]:
            del _pending[key]
        _pending[state] = {"owner": owner, "kind": "custom", "name": name, "url": url, "read_only": read_only,
                           "verifier": verifier, "redirect_uri": redirect_uri(base_url), "oauth": oauth, "at": now}
    params = {"response_type": "code", "client_id": client["client_id"], "redirect_uri": redirect_uri(base_url),
              "state": state, "code_challenge": challenge, "code_challenge_method": "S256", "resource": found["resource"]}
    if found["scopes"]:
        params["scope"] = " ".join(found["scopes"])
    separator = "&" if "?" in server["authorization_endpoint"] else "?"
    return server["authorization_endpoint"] + separator + urlencode(params)


async def _oauth_token(oauth: dict, data: dict) -> dict:
    """A token request to another MCP server's authorization server, with the client authentication it registered."""
    data = {**data, "client_id": oauth["client_id"]}
    auth_ = None
    if oauth.get("client_secret") and oauth.get("auth_method") == "client_secret_basic":
        auth_ = (oauth["client_id"], oauth["client_secret"])
    elif oauth.get("client_secret"):
        data["client_secret"] = oauth["client_secret"]
    async with httpx.AsyncClient(timeout=20) as http:
        response = await http.post(oauth["token_endpoint"], data=data, auth=auth_, headers={"Accept": "application/json"})
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.status_code >= 400 or not body.get("access_token"):
        raise ValueError(f"Le service a refusé la connexion : {body.get('error_description') or body.get('error') or response.status_code}")
    return body


async def _finish_custom_sign_in(owner: str, pending: dict, code: str) -> dict:
    oauth = pending["oauth"]
    tokens = await _oauth_token(oauth, {"grant_type": "authorization_code", "code": code, "redirect_uri": pending["redirect_uri"],
                                        "code_verifier": pending["verifier"], "resource": oauth["resource"]})
    secret = {"access_token": tokens["access_token"], "refresh_token": tokens.get("refresh_token"),
              "expires_at": time.time() + int(tokens["expires_in"]) if tokens.get("expires_in") else None, "oauth": oauth}
    connection = save_connection(owner, "custom", pending["name"], pending["url"], secret, pending["read_only"],
                                 urlparse(oauth.get("issuer") or pending["url"]).netloc)
    try:
        await check(connection["id"], owner)  # the tools are there: the tile says so, else shows why
    except Exception:
        pass
    return get(connection["id"], owner)


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
