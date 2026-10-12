"""Personal API keys: scripts, n8n and MCP clients act as the user who created the key.

The key is shown once at creation; only its SHA-256 is stored (keys are long random
strings, so a fast hash is enough). Sent as `Authorization: Bearer ac_...`.
"""

import hashlib
import secrets
import uuid
from datetime import datetime

from .db import connect

PREFIX = "ac_"
MAX_PER_USER = 10


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def create(owner: str, name: str) -> tuple[dict, str]:
    with connect() as conn:
        if conn.execute("SELECT COUNT(*) FROM api_tokens WHERE owner = ?", (owner,)).fetchone()[0] >= MAX_PER_USER:
            raise ValueError(f"{MAX_PER_USER} clés d'API au maximum : supprimez-en une.")
        token = PREFIX + secrets.token_urlsafe(32)
        row = {"id": uuid.uuid4().hex[:12], "owner": owner, "name": name, "token_hash": _hash(token),
               "prefix": token[:10], "created_at": _now(), "last_used_at": None}
        conn.execute("INSERT INTO api_tokens (id, owner, name, token_hash, prefix, created_at, last_used_at)"
                     " VALUES (:id, :owner, :name, :token_hash, :prefix, :created_at, :last_used_at)", row)
    return _view(row), token


def _view(row) -> dict:
    return {k: row[k] for k in ("id", "name", "prefix", "created_at", "last_used_at")}


def list_for(owner: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM api_tokens WHERE owner = ? ORDER BY created_at DESC", (owner,)).fetchall()
    return [_view(r) for r in rows]


def revoke(token_id: str, owner: str) -> bool:
    with connect() as conn:
        return conn.execute("DELETE FROM api_tokens WHERE id = ? AND owner = ?", (token_id, owner)).rowcount > 0


def revoke_all(owner: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM api_tokens WHERE owner = ?", (owner,))


def owner_of(token: str) -> str | None:
    """The user a key belongs to, or None. Records when it was last used."""
    if not token.startswith(PREFIX):
        return None
    with connect() as conn:
        row = conn.execute("SELECT id, owner FROM api_tokens WHERE token_hash = ?", (_hash(token),)).fetchone()
        if row:
            conn.execute("UPDATE api_tokens SET last_used_at = ? WHERE id = ?", (_now(), row["id"]))
    return row["owner"] if row else None
