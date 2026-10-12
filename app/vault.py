"""Encryption of the secrets AutoCollab keeps on disk, with a master key kept *outside* data/.

What it protects: AI provider keys and the Google/Slack OAuth secrets (data/settings.json), users'
Gmail/Slack tokens (database), and the key that signs sessions. Copying data/ is then not enough
to read them: the master key is needed too.

Where the master key comes from, in this order:
1. the AUTOCOLLAB_MASTER_KEY environment variable (production: the host's secret manager, a
   systemd credential, a .env kept outside the project...);
2. otherwise a file outside the project, ~/.autocollab/master.key by default (or the path in
   AUTOCOLLAB_MASTER_KEY_FILE), created on first use and readable by the service account only.

Losing the master key means re-entering the AI keys and reconnecting the applications: keep a copy
of it apart from the backups of data/.
"""

import base64
import hashlib
import hmac
import logging
import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

PREFIX = "enc:v1:"
ENV_KEY = "AUTOCOLLAB_MASTER_KEY"
ENV_FILE = "AUTOCOLLAB_MASTER_KEY_FILE"
DEFAULT_FILE = Path.home() / ".autocollab" / "master.key"

_master: bytes | None = None
_source = ""


def _load_master() -> bytes:
    global _master, _source
    if _master is not None:
        return _master
    value = os.getenv(ENV_KEY, "").strip()
    if value:
        if len(value) < 32:
            logger.warning("%s fait moins de 32 caractères : choisissez une clé plus longue.", ENV_KEY)
        _master, _source = value.encode(), "env"
        return _master
    path = Path(os.getenv(ENV_FILE, "").strip() or DEFAULT_FILE).expanduser()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_urlsafe(48), encoding="utf-8")
        logger.warning("Clé maîtresse créée dans %s. En production, fournissez-la par %s.", path, ENV_KEY)
    if os.name == "posix":
        os.chmod(path.parent, 0o700)
        os.chmod(path, 0o600)
    _master, _source = path.read_text(encoding="utf-8").strip().encode(), f"file:{path}"
    return _master


def derive(purpose: str) -> bytes:
    """A separate 32-byte key for each use (encryption, sessions...), all from the master key."""
    return hmac.new(_load_master(), purpose.encode(), hashlib.sha256).digest()


def _fernet() -> Fernet:
    return Fernet(base64.urlsafe_b64encode(derive("vault:secrets")))


def is_sealed(value) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


def seal(value: str) -> str:
    """Encrypt a text for storage; empty stays empty, already encrypted stays as is."""
    if not value or is_sealed(value):
        return value
    return PREFIX + _fernet().encrypt(value.encode()).decode()


def unseal(value: str) -> str:
    """Decrypt; a plain value (written before encryption existed) is returned unchanged.
    A value encrypted with another master key reads as empty: it has to be entered again."""
    if not is_sealed(value):
        return value or ""
    try:
        return _fernet().decrypt(value[len(PREFIX):].encode()).decode()
    except InvalidToken:
        logger.error("Secret illisible : la clé maîtresse a changé. Il faut le saisir de nouveau.")
        return ""


def source() -> dict:
    """Where the master key comes from, for the Administration page (never the key itself)."""
    _load_master()
    kind, _, path = _source.partition(":")
    return {"source": kind, "path": path or None}
