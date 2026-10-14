"""User accounts and login sessions, standard library only.

Accounts live in the database, table users (managed with manage_users.py). Passwords are
hashed with scrypt. The session is a signed cookie: "<payload>.<hmac>", where the
payload holds the username, an expiry and a fingerprint of the password hash, so
changing a password logs that user out everywhere.
"""

import base64
import hashlib
import hmac
import json
import re
import secrets
import threading
import time

from fastapi import HTTPException, Request

from . import config, db

SECRET_FILE = config.DATA_DIR / "secret.key"
COOKIE_NAME = "session"
USERNAME_RE = re.compile(r"^[a-z0-9._-]{2,40}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 10

_SCRYPT = {"n": 2**14, "r": 8, "p": 1}

# Hold while reading, changing and saving the accounts so two admins can't overwrite each other.
users_lock = threading.Lock()


# --- accounts -----------------------------------------------------------


def load_users() -> dict[str, dict]:
    with db.connect() as conn:
        rows = conn.execute("SELECT username, data FROM users ORDER BY username").fetchall()
    return {row["username"]: json.loads(row["data"]) for row in rows}


def save_users(users: dict[str, dict]) -> None:
    """Replace every account by `users`, in one transaction: removed accounts are deleted."""
    with db.connect() as conn:
        for row in conn.execute("SELECT username FROM users").fetchall():
            if row["username"] not in users:
                conn.execute("DELETE FROM users WHERE username = ?", (row["username"],))
        for username, user in users.items():
            conn.execute("INSERT INTO users (username, data) VALUES (?, ?) ON CONFLICT (username) DO UPDATE SET data = excluded.data",
                         (username, json.dumps(user, ensure_ascii=False)))


def normalize_username(username: str) -> str:
    return username.strip().lower()


def username_error(username: str) -> str | None:
    if not USERNAME_RE.match(username):
        return "Identifiant invalide : 2 à 40 caractères parmi a-z, 0-9, point, tiret, tiret bas."
    return None


def normalize_email(email: str) -> str:
    return email.strip().lower()


def email_error(email: str, users: dict[str, dict], exclude: str | None = None) -> str | None:
    """Validate a normalized e-mail; an empty one is allowed. Must not belong to another account."""
    if not email:
        return None
    if len(email) > 254 or not EMAIL_RE.match(email):
        return "Adresse e-mail invalide."
    if any(u != exclude and data.get("email") == email for u, data in users.items()):
        return "Cette adresse e-mail est déjà utilisée par un autre compte."
    return None


def find_username(login: str, users: dict[str, dict]) -> str | None:
    """The account matching an identifier or an e-mail address."""
    login = login.strip().lower()
    if login in users:
        return login
    return next((u for u, data in users.items() if data.get("email") == login), None)


def password_error(password: str) -> str | None:
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Le mot de passe doit faire au moins {MIN_PASSWORD_LENGTH} caractères."
    return None


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), **_SCRYPT)
    except ValueError:
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


def authenticate(login: str, password: str) -> str | None:
    """Check an identifier or e-mail address and its password; returns the username."""
    users = load_users()
    username = find_username(login, users)
    user = users.get(username) if username else None
    if user and verify_password(password, user["password"]):
        return username
    # Hash anyway so a wrong username takes as long as a wrong password.
    if not user:
        verify_password(password, hash_password("x"))
    return None


# --- session cookie -----------------------------------------------------


def _secret() -> bytes:
    """Signs session cookies: SESSION_SECRET if set, otherwise derived from the master key
    (app/vault.py), so nothing in data/ lets anyone forge a session."""
    if config.SESSION_SECRET:
        return config.SESSION_SECRET.encode()
    from . import vault

    return vault.derive("sessions")


def legacy_secret() -> bytes | None:
    """The old data/secret.key, only to read back what was encrypted with it (see integrations.migrate)."""
    return SECRET_FILE.read_text(encoding="utf-8").strip().encode() if SECRET_FILE.exists() else None


def _fingerprint(user: dict) -> str:
    return hashlib.sha256(user["password"].encode()).hexdigest()[:16]


def _sign(payload: str) -> str:
    return hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()


def make_token(username: str) -> str:
    user = load_users()[username]
    data = {"u": username, "exp": int(time.time()) + config.SESSION_HOURS * 3600, "f": _fingerprint(user)}
    payload = base64.urlsafe_b64encode(json.dumps(data).encode()).decode()
    return f"{payload}.{_sign(payload)}"


def read_token(token: str | None) -> str | None:
    if not token or "." not in token:
        return None
    payload, signature = token.rsplit(".", 1)
    if not hmac.compare_digest(_sign(payload), signature):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(payload))
    except ValueError:
        return None
    user = load_users().get(data.get("u"))
    if not user or data.get("exp", 0) < time.time() or data.get("f") != _fingerprint(user):
        return None
    return data["u"]


def session_user(request: Request) -> str | None:
    """The user behind this request: an API key (Authorization: Bearer) or the session cookie."""
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        from . import tokens  # tokens -> db -> config; imported here to keep auth light

        owner = tokens.owner_of(header[7:].strip())
        return owner if owner and owner in load_users() else None
    return read_token(request.cookies.get(COOKIE_NAME))


# What someone with a temporary password may still reach: who they are, choosing a password, leaving.
PASSWORD_CHANGE_PATHS = {"/api/me", "/api/me/password", "/api/logout"}
# ...and someone who must set up two-factor authentication: the same, plus the setup itself.
TWO_FACTOR_SETUP_PATHS = PASSWORD_CHANGE_PATHS | {"/api/me/2fa/setup", "/api/me/2fa/enable"}
TWO_FACTOR_REQUIRED = "Activez d'abord la double authentification."


def must_change_password(username: str) -> bool:
    return bool(load_users().get(username, {}).get("must_change_password"))


def current_user(request: Request) -> str:
    """FastAPI dependency: the logged-in username, or 401.

    An account still on a temporary password (set by an administrator) gets 403 everywhere
    else until it chooses its own.
    """
    username = session_user(request)
    if not username:
        raise HTTPException(401, "Session expirée : reconnectez-vous.")
    if request.url.path not in PASSWORD_CHANGE_PATHS and must_change_password(username):
        raise HTTPException(403, "Choisissez d'abord votre propre mot de passe.")
    if request.url.path not in TWO_FACTOR_SETUP_PATHS:
        from . import twofa

        if twofa.must_enroll(username):
            raise HTTPException(403, TWO_FACTOR_REQUIRED)
    return username


def set_session_cookie(response, username: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        make_token(username),
        max_age=config.SESSION_HOURS * 3600,
        httponly=True,
        samesite="lax",
        secure=config.COOKIE_SECURE,
    )


def current_admin(request: Request) -> str:
    """FastAPI dependency: the logged-in username if they are an administrator, else 401/403."""
    username = current_user(request)
    if not is_admin(username):
        raise HTTPException(403, "Réservé aux administrateurs.")
    return username


def display_name(username: str) -> str:
    return load_users().get(username, {}).get("name") or username


def is_admin(username: str) -> bool:
    return bool(load_users().get(username, {}).get("admin"))


# --- brute-force protection ---------------------------------------------

_MAX_FAILURES = 5
_WINDOW_SECONDS = 15 * 60
_failures: dict[str, list[float]] = {}


def is_locked(key: str) -> bool:
    now = time.time()
    recent = [t for t in _failures.get(key, []) if now - t < _WINDOW_SECONDS]
    _failures[key] = recent
    return len(recent) >= _MAX_FAILURES


def record_failure(key: str) -> None:
    _failures.setdefault(key, []).append(time.time())


_hits: dict[str, list[float]] = {}


def rate_limited(key: str, limit: int, window_seconds: int) -> bool:
    """True once `key` made more than `limit` calls in the last `window_seconds` (sliding window)."""
    now = time.time()
    recent = [t for t in _hits.get(key, []) if now - t < window_seconds]
    recent.append(now)
    _hits[key] = recent[-(limit + 1):]
    if len(_hits) > 10_000:  # forget idle keys
        for k in [k for k, v in _hits.items() if now - v[-1] > 3600]:
            _hits.pop(k, None)
    return len(recent) > limit


def clear_failures(key: str) -> None:
    _failures.pop(key, None)
