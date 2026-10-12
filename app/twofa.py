"""Two-factor authentication with an authenticator app (TOTP, RFC 6238: 6 digits, 30 seconds).

Works with Google Authenticator, Microsoft Authenticator, Authy, 1Password, Bitwarden...

Stored in data/users.json, under "totp": the secret (encrypted with the master key, see vault.py),
the last time step used (a code can't be replayed), and 10 one-time recovery codes kept as hashes.
The administrator chooses who must use it: nobody, administrators, or everyone (data/settings.json,
section "security"); someone who must but hasn't set it up is asked to do so before anything else.
"""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from datetime import datetime
from urllib.parse import quote

import segno

from . import auth, settings, vault

ISSUER = "AutoCollab"
STEP_SECONDS = 30
DIGITS = 6
RECOVERY_CODES = 10
TICKET_SECONDS = 300
POLICIES = ("none", "admins", "all")


# --- TOTP -------------------------------------------------------------------------


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _code(secret: str, counter: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 10 ** DIGITS
    return str(value).zfill(DIGITS)


def check_code(secret: str, code: str, last_step: int = 0) -> int | None:
    """The time step matched (one step of clock drift either way), or None. Never one already used."""
    code = "".join(c for c in code if c.isdigit())
    if len(code) != DIGITS:
        return None
    now = int(time.time() // STEP_SECONDS)
    for step in (now - 1, now, now + 1):
        if step > last_step and hmac.compare_digest(_code(secret, step), code):
            return step
    return None


def provisioning_uri(secret: str, account: str) -> str:
    return (f"otpauth://totp/{quote(ISSUER)}:{quote(account)}?secret={secret}&issuer={quote(ISSUER)}"
            f"&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}")


def qr_svg(uri: str) -> str:
    return segno.make(uri, error="m").svg_inline(scale=5, border=2, dark="#18181B", light="#FFFFFF")


# --- recovery codes ----------------------------------------------------------------


def _hash(code: str) -> str:
    return hashlib.sha256(code.replace("-", "").strip().lower().encode()).hexdigest()


def _new_recovery() -> tuple[list[str], list[str]]:
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    codes = ["-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(2)) for _ in range(RECOVERY_CODES)]
    return codes, [_hash(c) for c in codes]


# --- policy ------------------------------------------------------------------------


def policy() -> str:
    value = (settings.load().get("security") or {}).get("require_2fa", "none")
    return value if value in POLICIES else "none"


def set_policy(value: str) -> None:
    current = settings.load().get("security") or {}
    settings.update_section("security", {**current, "require_2fa": value})


def required(username: str) -> bool:
    p = policy()
    return p == "all" or (p == "admins" and auth.is_admin(username))


def enabled(username: str) -> bool:
    return bool((auth.load_users().get(username, {}).get("totp") or {}).get("enabled"))


def must_enroll(username: str) -> bool:
    return required(username) and not enabled(username)


def status(username: str) -> dict:
    totp = auth.load_users().get(username, {}).get("totp") or {}
    return {"enabled": bool(totp.get("enabled")), "required": required(username),
            "recovery_left": len(totp.get("recovery") or []) if totp.get("enabled") else 0,
            "enabled_at": totp.get("enabled_at")}


# --- setup ---------------------------------------------------------------------------


def start_setup(username: str) -> dict:
    """A new secret, kept aside until confirmed with a first code (so a half-done setup locks nobody out)."""
    secret = new_secret()
    with auth.users_lock:
        users = auth.load_users()
        users[username]["totp_pending"] = vault.seal(secret)
        auth.save_users(users)
    account = users[username].get("email") or username
    uri = provisioning_uri(secret, account)
    return {"secret": " ".join(secret[i:i + 4] for i in range(0, len(secret), 4)), "uri": uri, "qr_svg": qr_svg(uri)}


def finish_setup(username: str, code: str) -> list[str] | None:
    """Turn it on if the code matches the pending secret; returns the recovery codes (shown once)."""
    with auth.users_lock:
        users = auth.load_users()
        user = users[username]
        secret = vault.unseal(user.get("totp_pending") or "")
        step = check_code(secret, code) if secret else None
        if step is None:
            return None
        codes, hashes = _new_recovery()
        user["totp"] = {"secret": vault.seal(secret), "enabled": True, "last_step": step, "recovery": hashes,
                        "enabled_at": datetime.now().isoformat(timespec="seconds")}
        user.pop("totp_pending", None)
        auth.save_users(users)
    return codes


def disable(username: str) -> None:
    with auth.users_lock:
        users = auth.load_users()
        users[username].pop("totp", None)
        users[username].pop("totp_pending", None)
        auth.save_users(users)


def new_recovery_codes(username: str) -> list[str]:
    codes, hashes = _new_recovery()
    with auth.users_lock:
        users = auth.load_users()
        users[username]["totp"]["recovery"] = hashes
        auth.save_users(users)
    return codes


def verify(username: str, code: str) -> str | None:
    """Check a code from the app, or a recovery code (used up). Returns "totp", "recovery" or None."""
    with auth.users_lock:
        users = auth.load_users()
        totp = (users.get(username) or {}).get("totp") or {}
        if not totp.get("enabled"):
            return None
        secret = vault.unseal(totp.get("secret") or "")
        step = check_code(secret, code, int(totp.get("last_step") or 0)) if secret else None
        if step is not None:
            totp["last_step"] = step
            auth.save_users(users)
            return "totp"
        hashed = _hash(code)
        if len(code.replace("-", "").strip()) == 8 and hashed in (totp.get("recovery") or []):
            totp["recovery"] = [h for h in totp["recovery"] if h != hashed]
            auth.save_users(users)
            return "recovery"
    return None


# --- the ticket between the password and the code ------------------------------------


def make_ticket(username: str) -> str:
    """Proof that the password was right, valid 5 minutes, without opening a session yet."""
    payload = base64.urlsafe_b64encode(f"{username}|{int(time.time()) + TICKET_SECONDS}|{secrets.token_hex(8)}".encode()).decode()
    sig = hmac.new(vault.derive("2fa-ticket"), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def read_ticket(ticket: str) -> str | None:
    payload, _, sig = (ticket or "").partition(".")
    expected = hmac.new(vault.derive("2fa-ticket"), payload.encode(), hashlib.sha256).hexdigest()
    if not sig or not hmac.compare_digest(sig, expected):
        return None
    try:
        username, expires, _nonce = base64.urlsafe_b64decode(payload.encode()).decode().split("|")
    except (ValueError, UnicodeDecodeError):
        return None
    return username if int(expires) > time.time() and username in auth.load_users() else None
