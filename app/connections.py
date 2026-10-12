""""Mes connexions": a browser on the user's own profile, shown and driven from the web page.

On a server nobody can open a browser window, so this is how people log in to their sites
(Gmail, Pennylane, their bank...) for their agents: the page shows screenshots of this browser
and forwards clicks and typing. Sessions stay in the profile for the agents' next runs.
No password goes through the application's storage: the user types it into the site itself.
"""

import asyncio
import logging
import time

from playwright.async_api import async_playwright

from . import browsers, netguard

logger = logging.getLogger(__name__)

VIEWPORT = {"width": 1280, "height": 800}
IDLE_SECONDS = 10 * 60
NAV_TIMEOUT_MS = 30_000
KEYS = {"Enter", "Tab", "Backspace", "Delete", "Escape", "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown",
        "Home", "End", "PageUp", "PageDown", "Shift+Tab"}


class LoginSession:
    def __init__(self, owner: str):
        self.owner = owner
        self.last_activity = time.monotonic()
        self.site_id: str | None = None  # the site last opened with "Se connecter"
        self._pw = None
        self._context = None
        self._lock = browsers.owner_lock(owner)

    @property
    def page(self):
        pages = [p for p in self._context.pages if not p.is_closed()] if self._context else []
        return pages[-1] if pages else None

    async def open(self, url: str | None) -> None:
        if self._lock.locked():
            raise RuntimeError("Votre navigateur est utilisé par une exécution en cours. Réessayez quand elle sera terminée.")
        await self._lock.acquire()
        try:
            profile = browsers.profile_dir(self.owner)
            await asyncio.to_thread(browsers.close_orphans, profile)
            browsers.clear_stale_lock(profile)
            browsers.forget_last_session(profile)
            self._pw = await async_playwright().start()
            self._context = await self._pw.chromium.launch_persistent_context(
                str(profile),
                executable_path=await browsers.binary_path_async(),
                headless=True,  # shown in the page, never on the server's screen
                viewport=VIEWPORT,
                locale="fr-FR",
                args=["--no-first-run", "--no-default-browser-check"],
            )
            # Same rule as the agents: no request to the server's own network (app/netguard.py).
            await self._context.route("**/*", netguard.route_guard())
            page = self.page or await self._context.new_page()
            if url:
                await page.goto(url, timeout=NAV_TIMEOUT_MS)
        except Exception:
            await self.close()
            raise

    async def close(self) -> None:
        try:
            if self._context:
                await self._context.close()
            if self._pw:
                await self._pw.stop()
        except Exception:
            logger.debug("Closing login session failed", exc_info=True)
        finally:
            self._context = None
            self._pw = None
            if self._lock.locked():
                self._lock.release()

    async def pages_state(self) -> list[tuple[str, bool]]:
        """(address, shows a password field) for each open tab: how "Connecté" is decided."""
        out = []
        for page in [p for p in self._context.pages if not p.is_closed()] if self._context else []:
            try:
                has_password = await page.evaluate(
                    "[...document.querySelectorAll('input[type=password]')].some(e => e.getClientRects().length > 0)")
            except Exception:
                has_password = False
            out.append((page.url, bool(has_password)))
        return out

    def touch(self) -> None:
        self.last_activity = time.monotonic()

    async def screenshot(self) -> tuple[bytes, str, str]:
        page = self.page
        if not page:
            page = await self._context.new_page()
        image = await page.screenshot(type="jpeg", quality=70)
        try:
            title = await page.title()
        except Exception:
            title = ""
        return image, page.url, title

    async def act(self, action: dict) -> None:
        """One user input, already validated by the API layer."""
        self.touch()
        page = self.page or await self._context.new_page()
        kind = action["type"]
        if kind == "click":
            await page.mouse.click(action["x"] * VIEWPORT["width"], action["y"] * VIEWPORT["height"])
        elif kind == "type":
            await page.keyboard.type(action["text"], delay=15)
        elif kind == "key":
            await page.keyboard.press(action["key"])
        elif kind == "scroll":
            await page.mouse.move(VIEWPORT["width"] / 2, VIEWPORT["height"] / 2)
            await page.mouse.wheel(0, action["dy"])
        elif kind == "goto":
            await page.goto(action["url"], timeout=NAV_TIMEOUT_MS)
        elif kind == "back":
            await page.go_back(timeout=NAV_TIMEOUT_MS)
        # Let the page react before the next screenshot.
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=3000)
        except Exception:
            pass


class ConnectionManager:
    def __init__(self):
        self.sessions: dict[str, LoginSession] = {}
        self._watchdog: asyncio.Task | None = None

    def get(self, owner: str) -> LoginSession | None:
        return self.sessions.get(owner)

    async def open(self, owner: str, url: str | None, site_id: str | None = None) -> LoginSession:
        if not self._watchdog:
            self._watchdog = asyncio.create_task(self._close_idle())
        session = self.sessions.get(owner)
        if session:
            if url:
                await self._record(session)  # the site we are leaving
                await session.act({"type": "goto", "url": url})
            session.site_id = site_id or session.site_id
            return session
        session = LoginSession(owner)
        await session.open(url)
        session.site_id = site_id
        self.sessions[owner] = session
        return session

    async def close(self, owner: str) -> None:
        session = self.sessions.pop(owner, None)
        if session:
            await self._record(session)
            await session.close()

    async def _record(self, session: LoginSession) -> None:
        from . import sites

        try:
            for url, has_password in await session.pages_state():
                sites.record_page(session.owner, url, has_password, session.site_id)
        except Exception:
            logger.debug("Reading the sign-in state failed", exc_info=True)

    async def _close_idle(self) -> None:
        """Release forgotten sessions so the user's agents can run again."""
        while True:
            await asyncio.sleep(30)
            now = time.monotonic()
            for owner, session in list(self.sessions.items()):
                if now - session.last_activity > IDLE_SECONDS:
                    logger.info("Session de connexion de %s fermée (inactive)", owner)
                    await self.close(owner)
