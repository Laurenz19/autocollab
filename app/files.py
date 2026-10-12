"""Files the agent may upload to a site: attachments given by the user (on a one-off task or
saved with an agent) and, during a run, whatever the agent itself downloads.

Each run gets its own folder; the upload action can only pick files from it, never any
other file on the server.
"""

import re
import shutil
import time
import unicodedata
import uuid
from pathlib import Path

from . import config

MAX_BYTES = 25 * 1024 * 1024
ALLOWED_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".tif", ".tiff", ".heic",
    ".csv", ".xls", ".xlsx", ".ods", ".doc", ".docx", ".odt", ".txt", ".xml", ".json",
    ".zip", ".ofx", ".qif",
}
STAGING_DIR = config.DATA_DIR / "uploads"
AGENT_FILES_DIR = config.DATA_DIR / "agent_files"
STAGING_TTL_SECONDS = 24 * 3600


def clean_name(name: str) -> str:
    """A safe file name that keeps what people recognise (accents become plain letters)."""
    name = Path(name.replace("\\", "/")).name
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" .")
    stem, ext = Path(name).stem[:100] or "fichier", Path(name).suffix.lower()
    return f"{stem}{ext}"


def check(name: str, size: int) -> str | None:
    if Path(name).suffix.lower() not in ALLOWED_EXTENSIONS:
        return "Type de fichier non accepté (PDF, images, Excel/CSV, Word, texte, XML, ZIP, OFX/QIF)."
    if size > MAX_BYTES:
        return f"Fichier trop volumineux : {MAX_BYTES // (1024 * 1024)} Mo au maximum."
    if size == 0:
        return "Le fichier est vide."
    return None


def unique_path(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    n = 2
    while path.exists():
        path = folder / f"{Path(name).stem} ({n}){Path(name).suffix}"
        n += 1
    return path


def listing(folder: Path) -> list[dict]:
    if not folder.is_dir():
        return []
    return [{"name": f.name, "size": f.stat().st_size}
            for f in sorted(folder.iterdir(), key=lambda f: f.stat().st_mtime) if f.is_file()]


def inside(folder: Path, name: str) -> Path | None:
    """The file `name` directly inside `folder`, or None (no "..", no sub-folders)."""
    path = (folder / name).resolve()
    return path if path.parent == folder.resolve() and path.is_file() else None


# --- one-off task attachments: uploaded first, attached when the task is launched ----


def stage(owner: str, name: str, data: bytes) -> dict:
    _purge_staging()
    upload_id = uuid.uuid4().hex[:16]
    path = unique_path(STAGING_DIR / owner / upload_id, clean_name(name))
    path.write_bytes(data)
    return {"id": upload_id, "name": path.name, "size": len(data)}


def staged(owner: str, upload_id: str) -> Path | None:
    if not re.fullmatch(r"[0-9a-f]{16}", upload_id):
        return None
    folder = STAGING_DIR / owner / upload_id
    found = [f for f in folder.iterdir() if f.is_file()] if folder.is_dir() else []
    return found[0] if found else None


def _purge_staging() -> None:
    limit = time.time() - STAGING_TTL_SECONDS
    for folder in STAGING_DIR.glob("*/*"):
        try:
            if folder.stat().st_mtime < limit:
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            pass


# --- files saved with an agent, given to every one of its runs ------------------------


def agent_dir(agent_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{12}", agent_id):
        raise ValueError("Agent invalide")
    return AGENT_FILES_DIR / agent_id


def agent_files(agent_id: str) -> list[Path]:
    folder = agent_dir(agent_id)
    return sorted(f for f in folder.iterdir() if f.is_file()) if folder.is_dir() else []


def delete_agent_files(agent_id: str) -> None:
    shutil.rmtree(agent_dir(agent_id), ignore_errors=True)
