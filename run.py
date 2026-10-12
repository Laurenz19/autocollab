"""Start the app: python run.py, then open http://127.0.0.1:8800

    python run.py --reload    restart automatically when a file in app/ changes (development)
"""

import asyncio
import logging
import subprocess
import sys
import time

import uvicorn

from app import config

WATCH_DIR = config.ROOT / "app"
POLL_SECONDS = 1.0


def serve() -> None:
    server = uvicorn.Server(uvicorn.Config("app.main:app", host=config.APP_HOST, port=config.APP_PORT))
    # asyncio.run keeps Python's default Proactor loop on Windows, which Playwright needs to launch the browser.
    asyncio.run(server.serve())


def _snapshot() -> dict[str, float]:
    return {str(p): p.stat().st_mtime for p in WATCH_DIR.rglob("*.py")}


def reload_loop() -> None:
    """Run the server in a child process and restart it when a file in app/ changes.

    uvicorn's own --reload hands one listening socket from child to child. On Windows a socket
    can be tied to only one Proactor loop, so every child after the first fails to accept
    connections (WinError 87). Here each child opens the port itself.
    """
    log = logging.getLogger("reload")
    while True:
        before = _snapshot()
        child = subprocess.Popen([sys.executable, __file__])
        log.info("Serveur démarré (pid %s). Surveillance de %s", child.pid, WATCH_DIR)
        try:
            while child.poll() is None and _snapshot() == before:
                time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            child.terminate()
            child.wait()
            return
        if child.poll() is None:
            log.info("Modification détectée, redémarrage…")
            child.terminate()
            child.wait()
        else:
            # The server stopped on its own (often a syntax error): wait for the next edit.
            log.warning("Le serveur s'est arrêté (code %s). En attente d'une modification…", child.returncode)
            try:
                while _snapshot() == before:
                    time.sleep(POLL_SECONDS)
            except KeyboardInterrupt:
                return


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if "--reload" in sys.argv:
        reload_loop()
    else:
        serve()
