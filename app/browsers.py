"""Per-user browser profiles, shared by agent runs and the "Mes connexions" login screen.

Each user has their own profile folder (cookies, logged-in sessions) under
BROWSER_PROFILES_DIR/<username>, so one person's agents never use another's accounts.
A profile can be open in only one browser at a time: owner_lock() serializes everything
that uses it (that user's runs and their login session).

The browser is BROWSER_PATH when set (e.g. Edge on a workstation), otherwise the Chromium
bundled with Playwright (`playwright install chromium`), which is what a server uses.
"""

import asyncio
import json
import logging
import os
import shutil
import socket
from pathlib import Path

from . import config

logger = logging.getLogger(__name__)

_binary: str | None = None
_locks: dict[str, asyncio.Lock] = {}


def binary_path() -> str:
    global _binary
    if config.BROWSER_PATH:
        return config.BROWSER_PATH
    if _binary is None:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            _binary = p.chromium.executable_path
        if not Path(_binary).exists():
            raise RuntimeError("Chromium n'est pas installé sur le serveur : lancez « playwright install chromium ».")
    return _binary


async def binary_path_async() -> str:
    # sync_playwright refuses to run inside an event loop: resolve it in a thread.
    return config.BROWSER_PATH or await asyncio.to_thread(binary_path)


def browser_label() -> str:
    return Path(config.BROWSER_PATH).name if config.BROWSER_PATH else "Chromium (intégré)"


def profile_dir(username: str) -> Path:
    path = (config.BROWSER_PROFILES_DIR / username).resolve()
    # Usernames are validated at creation; refuse anything that would escape the profiles folder.
    if path.parent != config.BROWSER_PROFILES_DIR.resolve():
        raise ValueError("Profil invalide")
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        # Sessions on the user's sites: readable by the service account only. On Windows, Chromium
        # already encrypts cookies with the Windows account (DPAPI). The real protection on any server
        # is an encrypted disk or volume for data/.
        os.chmod(path.parent, 0o700)
        os.chmod(path, 0o700)
    return path


def clear_stale_lock(profile: Path) -> None:
    """A browser killed abruptly leaves a lock file that blocks the next start."""
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        try:
            (profile / name).unlink()
        except (FileNotFoundError, PermissionError, OSError):
            pass


def forget_last_session(profile: Path) -> None:
    """Start on a single empty tab, never on the tabs of the previous browser.

    A browser closed abruptly (server restart, orphan closed) reopens its old tabs on the next
    start. The agent then sees tabs it didn't open, often still loading in the background, and
    switching to one blocks until a 30 s timeout. The cookies, so the sign-ins, are kept.
    """
    default = profile / "Default"
    shutil.rmtree(default / "Sessions", ignore_errors=True)
    for name in ("Current Session", "Current Tabs", "Last Session", "Last Tabs"):
        try:
            (default / name).unlink()
        except OSError:
            pass
    prefs = default / "Preferences"
    try:
        data = json.loads(prefs.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    data.setdefault("profile", {}).update(exit_type="Normal", exited_cleanly=True)
    data.setdefault("session", {})["restore_on_startup"] = 5  # open the new tab page
    try:
        prefs.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass


def _profile_of(cmdline: list[str]) -> str | None:
    for arg in cmdline or []:
        if arg.startswith("--user-data-dir="):
            return os.path.normcase(os.path.abspath(arg.split("=", 1)[1].strip('"')))
    return None


def close_orphans(profile: Path | None = None) -> int:
    """Close browsers left running on a profile (or on every profile), returns how many.

    When the server restarts during a run (automatic reload, crash, update), the Python process
    stops but its Chromium keeps running and keeps the profile locked: the next run's browser
    then hands over to it and quits, and the agent can't connect ("close all existing Chrome
    instances"). Called while holding the owner's lock, so no browser of ours uses the profile.
    Only browsers started with one of our profile folders are touched, never anyone's own Chrome.
    """
    import psutil

    root = os.path.normcase(os.path.abspath(config.BROWSER_PROFILES_DIR))
    wanted = os.path.normcase(os.path.abspath(profile)) if profile else None
    found = []
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            used = _profile_of(proc.info["cmdline"])
        except (psutil.Error, OSError):
            continue
        if not used or (used != wanted if wanted else os.path.dirname(used) != root):
            continue
        if "--type=" in " ".join(proc.info["cmdline"] or []):
            continue  # a helper process: it goes with its main browser process
        found.append(proc)
    victims = []
    for proc in found:
        try:
            victims += [proc, *proc.children(recursive=True)]
        except psutil.Error:
            pass
    for proc in victims:
        try:
            proc.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(victims, timeout=5)
    for proc in alive:
        try:
            proc.kill()
        except psutil.Error:
            pass
    if found:
        logger.warning("%d navigateur(s) orphelin(s) fermé(s) (%s)", len(found), profile or "tous les profils")
    return len(found)


def reset_profile(username: str) -> None:
    """Forget every session of this user (log out of all sites)."""
    path = profile_dir(username)
    close_orphans(path)
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)


def free_port() -> int:
    """A free local port for the browser's control channel.

    browser-use reuses any browser already listening on its port, so a fixed port would let
    one user's agent take over another user's browser. Every run gets its own.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def owner_lock(username: str) -> asyncio.Lock:
    if username not in _locks:
        _locks[username] = asyncio.Lock()
    return _locks[username]
