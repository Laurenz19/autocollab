import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "runs"
DATA_DIR = ROOT / "data"

load_dotenv(ROOT / ".env")


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "oui")


LLM_PROVIDER = os.getenv("LLM_PROVIDER", "deepseek").strip().lower()
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat").strip()
LLM_USE_VISION = _bool("LLM_USE_VISION", False)

BROWSER_PATH = os.getenv("BROWSER_PATH", "").strip().strip('"') or None
# One browser profile per user (their logged-in sessions) lives in this folder.
BROWSER_PROFILES_DIR = ROOT / (os.getenv("BROWSER_PROFILES_DIR", "").strip().strip('"') or "data/profils")  # relative = from the project
# How many agent runs may use a browser at the same time (one per user at most). ~300-500 MB each.
MAX_PARALLEL_RUNS = max(1, int(os.getenv("MAX_PARALLEL_RUNS", "2")))
BROWSER_HEADLESS = _bool("BROWSER_HEADLESS", True)

AGENT_MAX_STEPS = int(os.getenv("AGENT_MAX_STEPS", "40"))

# The address people use to reach the app, e.g. https://autocollab.exemple.fr. Google and Slack send
# users back to it after they connect an application. Empty = the address of the current request.
PUBLIC_URL = os.getenv("PUBLIC_URL", "").strip().rstrip("/")

# Name of the organisation using this installation, shown under the logo and on the login page.
# Administrators can change it in Administration; this is only the starting value.
ORG_NAME = os.getenv("ORG_NAME", "").strip()

APP_HOST = os.getenv("APP_HOST", "127.0.0.1")
APP_PORT = int(os.getenv("APP_PORT", "8800"))

# Empty = a random key generated once in data/secret.key.
SESSION_SECRET = os.getenv("SESSION_SECRET", "").strip()
SESSION_HOURS = int(os.getenv("SESSION_HOURS", "12"))
# true once the server is behind HTTPS, so the session cookie is never sent in clear.
COOKIE_SECURE = _bool("COOKIE_SECURE", False)

# How long an agent in approval mode waits for someone to click Valider or Refuser.
APPROVAL_TIMEOUT_MINUTES = int(os.getenv("APPROVAL_TIMEOUT_MINUTES", "60"))
