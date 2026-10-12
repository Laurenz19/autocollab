"""OAuth 2.1 sign-in for the MCP server, so AI clients such as claude.ai or ChatGPT can connect
without anyone copying an API key.

What the MCP specification expects from a server, nothing more:
- discovery: /.well-known/oauth-protected-resource and /.well-known/oauth-authorization-server;
- dynamic client registration (POST /oauth/register), since these clients register themselves;
- authorization code with PKCE (S256 only), the user approving on /oauth/authorize;
- short access tokens and rotating refresh tokens, only valid on /mcp.

Codes and tokens are random strings stored as SHA-256 hashes. Each approval is a "grant",
listed on the Developers page, where the user can withdraw it.
"""

import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid
from datetime import datetime
from urllib.parse import urlparse

from . import auth, config
from .db import connect

ACCESS_PREFIX, REFRESH_PREFIX = "aco_", "acr_"
ACCESS_SECONDS = 3600
REFRESH_SECONDS = 30 * 24 * 3600
CODE_SECONDS = 600
MAX_CLIENTS = 500
SCOPE = "autocollab"


class OAuthError(Exception):
    """An error answered in the OAuth format: {"error": code, "error_description": text}."""

    def __init__(self, code: str, description: str, status: int = 400):
        super().__init__(description)
        self.code, self.description, self.status = code, description, status


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def base_url(request_base: str) -> str:
    return (config.PUBLIC_URL or request_base).rstrip("/")


# --- discovery ---------------------------------------------------------------------


def resource_metadata(base: str) -> dict:
    return {"resource": base + "/mcp", "authorization_servers": [base], "scopes_supported": [SCOPE],
            "bearer_methods_supported": ["header"], "resource_name": "AutoCollab"}


def server_metadata(base: str) -> dict:
    return {
        "issuer": base,
        "authorization_endpoint": base + "/oauth/authorize",
        "token_endpoint": base + "/oauth/token",
        "registration_endpoint": base + "/oauth/register",
        "revocation_endpoint": base + "/oauth/revoke",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
        "revocation_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
        "scopes_supported": [SCOPE],
    }


# --- clients (dynamic registration) --------------------------------------------------------


def _valid_redirect(uri: str) -> bool:
    parsed = urlparse(uri)
    if parsed.fragment or not parsed.scheme:
        return False
    if parsed.scheme == "https":
        return bool(parsed.hostname)
    if parsed.scheme == "http":
        return parsed.hostname in ("localhost", "127.0.0.1", "::1")  # desktop clients listening locally
    # Custom schemes of desktop apps (cursor://, vscode://...), never script or file ones.
    return parsed.scheme not in ("javascript", "data", "file", "vbscript", "about", "blob", "ftp")


def register(body: dict) -> dict:
    uris = body.get("redirect_uris")
    if not isinstance(uris, list) or not 1 <= len(uris) <= 10 or not all(isinstance(u, str) and len(u) <= 500 for u in uris):
        raise OAuthError("invalid_redirect_uri", "redirect_uris : 1 à 10 adresses.")
    bad = [u for u in uris if not _valid_redirect(u)]
    if bad:
        raise OAuthError("invalid_redirect_uri", f"Adresse de retour refusée : {bad[0][:100]}")
    method = body.get("token_endpoint_auth_method") or "none"
    if method not in ("none", "client_secret_post", "client_secret_basic"):
        raise OAuthError("invalid_client_metadata", "token_endpoint_auth_method non pris en charge.")
    grants = body.get("grant_types") or ["authorization_code", "refresh_token"]
    if "authorization_code" not in grants:
        raise OAuthError("invalid_client_metadata", "grant_types doit contenir authorization_code.")
    name = str(body.get("client_name") or "").strip()[:80] or (urlparse(uris[0]).hostname or "Application")
    client_id = "acc_" + secrets.token_urlsafe(18)
    secret = secrets.token_urlsafe(32) if method != "none" else None
    with connect() as conn:
        # Registration is open by design: forget clients never used after a week, and cap the rest.
        conn.execute("DELETE FROM oauth_clients WHERE last_used_at IS NULL AND created_at < ?",
                     (datetime.fromtimestamp(time.time() - 7 * 86400).isoformat(timespec="seconds"),))
        if conn.execute("SELECT COUNT(*) FROM oauth_clients").fetchone()[0] >= MAX_CLIENTS:
            raise OAuthError("temporarily_unavailable", "Trop d'applications enregistrées.", 503)
        conn.execute("INSERT INTO oauth_clients (client_id, secret_hash, name, redirect_uris, auth_method, created_at)"
                     " VALUES (?, ?, ?, ?, ?, ?)",
                     (client_id, _hash(secret) if secret else None, name, json.dumps(uris), method, _now()))
    answer = {"client_id": client_id, "client_id_issued_at": int(time.time()), "client_name": name,
              "redirect_uris": uris, "token_endpoint_auth_method": method,
              "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"], "scope": SCOPE}
    if secret:
        answer.update({"client_secret": secret, "client_secret_expires_at": 0})
    return answer


def get_client(client_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM oauth_clients WHERE client_id = ?", (client_id or "",)).fetchone()
    if not row:
        return None
    client = dict(row)
    client["redirect_uris"] = json.loads(client["redirect_uris"])
    return client


def _authenticate_client(client_id: str, secret: str | None) -> dict:
    client = get_client(client_id)
    if not client:
        raise OAuthError("invalid_client", "Application inconnue.", 401)
    if client["auth_method"] != "none":
        if not secret or not hmac.compare_digest(_hash(secret), client["secret_hash"] or ""):
            raise OAuthError("invalid_client", "Authentification de l'application refusée.", 401)
    return client


# --- authorization ---------------------------------------------------------------------


def check_request(params: dict, base: str) -> dict:
    """Validate an authorization request. Errors before the redirect address is trusted are shown,
    not sent back (OAuth rule: never redirect to an unchecked address)."""
    client = get_client(params.get("client_id", ""))
    if not client:
        raise OAuthError("invalid_client", "Application inconnue : recommencez la connexion depuis votre assistant IA.")
    redirect_uri = params.get("redirect_uri") or (client["redirect_uris"][0] if len(client["redirect_uris"]) == 1 else "")
    if redirect_uri not in client["redirect_uris"]:
        raise OAuthError("invalid_request", "Adresse de retour non déclarée par cette application.")
    if params.get("response_type") != "code":
        raise OAuthError("unsupported_response_type", "Seul response_type=code est pris en charge.")
    if not params.get("code_challenge") or params.get("code_challenge_method", "plain") != "S256":
        raise OAuthError("invalid_request", "PKCE (code_challenge, méthode S256) est obligatoire.")
    resource = params.get("resource")
    if resource and resource.rstrip("/") not in (base + "/mcp", base):
        raise OAuthError("invalid_target", "Ressource inconnue.")
    return {**client, "redirect_uri": redirect_uri}


def consent_token(user: str, params: dict) -> str:
    """Ties the approval form to this user and this exact request (no forged approvals)."""
    message = "|".join([user] + [params.get(k, "") for k in ("client_id", "redirect_uri", "code_challenge", "state", "resource")])
    return hmac.new(auth._secret(), message.encode(), hashlib.sha256).hexdigest()


def create_code(user: str, client: dict, params: dict) -> str:
    code = secrets.token_urlsafe(32)
    with connect() as conn:
        conn.execute("DELETE FROM oauth_codes WHERE expires_at < ?", (time.time(),))
        conn.execute("INSERT INTO oauth_codes (code_hash, client_id, owner, redirect_uri, challenge, resource, expires_at)"
                     " VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (_hash(code), client["client_id"], user, client["redirect_uri"], params["code_challenge"],
                      params.get("resource") or "", time.time() + CODE_SECONDS))
    return code


# --- tokens -------------------------------------------------------------------------------


def _issue(conn, grant_id: str, client_id: str, owner: str) -> dict:
    access, refresh = ACCESS_PREFIX + secrets.token_urlsafe(32), REFRESH_PREFIX + secrets.token_urlsafe(32)
    now = time.time()
    for kind, value, ttl in (("access", access, ACCESS_SECONDS), ("refresh", refresh, REFRESH_SECONDS)):
        conn.execute("INSERT INTO oauth_tokens (token_hash, kind, grant_id, client_id, owner, expires_at)"
                     " VALUES (?, ?, ?, ?, ?, ?)", (_hash(value), kind, grant_id, client_id, owner, now + ttl))
    conn.execute("UPDATE oauth_clients SET last_used_at = ? WHERE client_id = ?", (_now(), client_id))
    return {"access_token": access, "token_type": "Bearer", "expires_in": ACCESS_SECONDS,
            "refresh_token": refresh, "scope": SCOPE}


def exchange(form: dict, basic: tuple[str, str] | None) -> dict:
    client_id = (basic[0] if basic else None) or form.get("client_id", "")
    client = _authenticate_client(client_id, (basic[1] if basic else None) or form.get("client_secret"))
    grant_type = form.get("grant_type")
    if grant_type == "authorization_code":
        return _from_code(client, form)
    if grant_type == "refresh_token":
        return _from_refresh(client, form)
    raise OAuthError("unsupported_grant_type", "grant_type non pris en charge.")


def _from_code(client: dict, form: dict) -> dict:
    code, verifier = form.get("code", ""), form.get("code_verifier", "")
    with connect() as conn:  # committed on its own: the code is spent even if the checks below fail
        row = conn.execute("SELECT * FROM oauth_codes WHERE code_hash = ?", (_hash(code),)).fetchone()
        conn.execute("DELETE FROM oauth_codes WHERE code_hash = ?", (_hash(code),))
    with connect() as conn:
        if not row or row["expires_at"] < time.time() or row["client_id"] != client["client_id"]:
            raise OAuthError("invalid_grant", "Code invalide ou expiré.")
        if form.get("redirect_uri") and form["redirect_uri"] != row["redirect_uri"]:
            raise OAuthError("invalid_grant", "Adresse de retour différente de celle de la demande.")
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        if not verifier or not hmac.compare_digest(expected, row["challenge"]):
            raise OAuthError("invalid_grant", "code_verifier incorrect.")
        if row["owner"] not in auth.load_users():
            raise OAuthError("invalid_grant", "Compte supprimé.")
        grant = conn.execute("SELECT id FROM oauth_grants WHERE client_id = ? AND owner = ?",
                             (client["client_id"], row["owner"])).fetchone()
        grant_id = grant["id"] if grant else uuid.uuid4().hex[:12]
        if not grant:
            conn.execute("INSERT INTO oauth_grants (id, client_id, owner, created_at) VALUES (?, ?, ?, ?)",
                         (grant_id, client["client_id"], row["owner"], _now()))
        return _issue(conn, grant_id, client["client_id"], row["owner"])


def _from_refresh(client: dict, form: dict) -> dict:
    token = form.get("refresh_token", "")
    with connect() as conn:
        row = conn.execute("SELECT * FROM oauth_tokens WHERE token_hash = ? AND kind = 'refresh'", (_hash(token),)).fetchone()
        if not row or row["client_id"] != client["client_id"] or row["expires_at"] < time.time():
            raise OAuthError("invalid_grant", "Jeton de renouvellement invalide ou expiré.")
        if row["owner"] not in auth.load_users():
            raise OAuthError("invalid_grant", "Compte supprimé.")
        # Rotation: the old refresh token and the grant's previous access tokens stop working.
        conn.execute("DELETE FROM oauth_tokens WHERE grant_id = ?", (row["grant_id"],))
        return _issue(conn, row["grant_id"], client["client_id"], row["owner"])


def owner_of(token: str) -> str | None:
    """The user behind an OAuth access token (only accepted on /mcp)."""
    if not token.startswith(ACCESS_PREFIX):
        return None
    with connect() as conn:
        row = conn.execute("SELECT owner, grant_id, expires_at FROM oauth_tokens WHERE token_hash = ? AND kind = 'access'",
                           (_hash(token),)).fetchone()
        if not row or row["expires_at"] < time.time():
            return None
        conn.execute("UPDATE oauth_grants SET last_used_at = ? WHERE id = ?", (_now(), row["grant_id"]))
    return row["owner"] if row["owner"] in auth.load_users() else None


def revoke_token(token: str, client_id: str | None = None) -> None:
    """RFC 7009: revoking either token of a grant ends the whole sign-in."""
    with connect() as conn:
        row = conn.execute("SELECT grant_id, client_id FROM oauth_tokens WHERE token_hash = ?", (_hash(token),)).fetchone()
        if row and (client_id is None or row["client_id"] == client_id):
            conn.execute("DELETE FROM oauth_tokens WHERE grant_id = ?", (row["grant_id"],))


# --- what users see on the Developers page ----------------------------------------------


def grants_of(owner: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT g.id, g.created_at, g.last_used_at, c.name, c.redirect_uris FROM oauth_grants g"
            " JOIN oauth_clients c ON c.client_id = g.client_id WHERE g.owner = ? ORDER BY g.created_at DESC", (owner,)).fetchall()
    return [{"id": r["id"], "name": r["name"], "created_at": r["created_at"], "last_used_at": r["last_used_at"],
             "host": urlparse(json.loads(r["redirect_uris"])[0]).hostname or ""} for r in rows]


def revoke_grant(grant_id: str, owner: str) -> bool:
    with connect() as conn:
        if not conn.execute("DELETE FROM oauth_grants WHERE id = ? AND owner = ?", (grant_id, owner)).rowcount:
            return False
        conn.execute("DELETE FROM oauth_tokens WHERE grant_id = ?", (grant_id,))
    return True


def revoke_all(owner: str) -> None:
    """When an account is deleted or its password reset."""
    with connect() as conn:
        conn.execute("DELETE FROM oauth_tokens WHERE owner = ?", (owner,))
        conn.execute("DELETE FROM oauth_grants WHERE owner = ?", (owner,))
        conn.execute("DELETE FROM oauth_codes WHERE owner = ?", (owner,))
