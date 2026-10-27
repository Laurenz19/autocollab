import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

load_dotenv(ROOT / ".env")

# Where accounts, settings and the database live, and where runs keep their screenshots and files.
# Overridable so a separate instance (e.g. the guide's demo, tools/guide_screenshots.py) never touches real data.
DATA_DIR = Path(os.getenv("AUTOCOLLAB_DATA_DIR", "").strip() or ROOT / "data")
RUNS_DIR = Path(os.getenv("AUTOCOLLAB_RUNS_DIR", "").strip() or ROOT / "runs")
# postgresql://user:password@host:5432/autocollab for a shared server; empty = SQLite in DATA_DIR/app.db.
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DATABASE_POOL_SIZE = max(2, int(os.getenv("DATABASE_POOL_SIZE", "10")))


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
# A guided session ends after this long without a message from the person guiding it: its browser (and the
# user's profile, which their other runs wait for) is not held for nothing.
GUIDED_IDLE_MINUTES = int(os.getenv("GUIDED_IDLE_MINUTES", "10"))

# Billing with Stripe (app/billing.py). Empty secret key = billing off and no limits (an installation on the
# client's own servers, or before launch). The price ids come from the Stripe dashboard (Products).
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "").strip()
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
STRIPE_PRICES = {
    f"{plan}_{period}": os.getenv(f"STRIPE_PRICE_{plan.upper()}_{period.upper()}", "").strip()
    for plan in ("solo", "equipe", "entreprise") for period in ("monthly", "yearly")
} | {"credits": os.getenv("STRIPE_PRICE_CREDITS", "").strip()}
