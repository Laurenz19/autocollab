"""AI settings chosen by an administrator in the app (database, table app_settings).

The first time, they are filled from the .env values, so an existing setup keeps working;
after that the Administration page is the place to change them. API keys never leave the
server: the page only sees whether a key is set and its last characters. Stored, they are
encrypted with the master key (app/vault.py), which is kept outside data/.
"""

import json
import os
import threading
from datetime import datetime

from . import config, db, vault

# "models": suggestions shown in the page (any other model name can be typed); "vision": reads screenshots.
PROVIDERS = {
    "anthropic": {"label": "Claude (Anthropic)", "model": "claude-sonnet-5-5", "vision": True,
                  "models": ["claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5"],
                  "console": "https://console.anthropic.com/settings/keys", "region": "États-Unis, sans entraînement sur vos données"},
    "mistral": {"label": "Mistral (France)", "model": "mistral-large-latest", "vision": False,
                "models": ["mistral-large-latest", "mistral-medium-latest", "pixtral-large-latest"],
                "console": "https://console.mistral.ai/api-keys", "region": "Hébergé en Europe (France)"},
    "openai": {"label": "OpenAI", "model": "gpt-4o", "vision": True,
               "models": ["gpt-4o", "gpt-4.1", "gpt-4o-mini"],
               "console": "https://platform.openai.com/api-keys", "region": "États-Unis"},
    "deepseek": {"label": "DeepSeek", "model": "deepseek-chat", "vision": False,
                 "models": ["deepseek-chat", "deepseek-reasoner"],
                 "console": "https://platform.deepseek.com/api_keys", "region": "Serveurs en Chine"},
    # NVIDIA's hosted catalogue (build.nvidia.com), OpenAI-compatible; the free tier is for trying models out.
    # On it, only the small gpt-oss-20b answers in time: the large reasoning models queue past the 45 s test,
    # so it is the only suggestion (another model name can still be typed).
    "nvidia": {"label": "NVIDIA", "model": "openai/gpt-oss-20b", "vision": False,
               "models": ["openai/gpt-oss-20b"],
               "console": "https://build.nvidia.com/settings/api-keys", "region": "États-Unis (NVIDIA)"},
}
KEY_ENV = {"deepseek": "DEEPSEEK_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "mistral": "MISTRAL_API_KEY",
           "nvidia": "NVIDIA_API_KEY"}
NVIDIA_ENDPOINT = "https://integrate.api.nvidia.com/v1"
DEFAULT_DEEPSEEK_ENDPOINT = "https://api.deepseek.com"

_lock = threading.Lock()


def _from_env() -> dict:
    return {
        "provider": config.LLM_PROVIDER if config.LLM_PROVIDER in PROVIDERS else "deepseek",
        "model": config.LLM_MODEL,
        "use_vision": config.LLM_USE_VISION,
        "deepseek_endpoint": os.getenv("DEEPSEEK_ENDPOINT", DEFAULT_DEEPSEEK_ENDPOINT).strip() or DEFAULT_DEEPSEEK_ENDPOINT,
        "api_keys": {name: os.getenv(env, "").strip() for name, env in KEY_ENV.items()},
    }


def _secrets(data: dict):
    """(container, key) of every secret in the file: AI keys and OAuth client secrets."""
    for name in list((data.get("api_keys") or {})):
        yield data["api_keys"], name
    for values in ((data.get("integrations") or {}).get("oauth") or {}).values():
        if isinstance(values, dict) and "client_secret" in values:
            yield values, "client_secret"


def _save(data: dict) -> None:
    """Write the file with every secret encrypted (see app/vault.py); `data` itself is left in clear."""
    stored = json.loads(json.dumps(data))
    for container, key in _secrets(stored):
        container[key] = vault.seal(container[key] or "")
    now = datetime.now().isoformat(timespec="seconds")
    with db.connect() as conn:
        conn.execute("INSERT INTO app_settings (key, data, updated_at) VALUES ('settings', ?, ?)"
                     " ON CONFLICT (key) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
                     (json.dumps(stored, ensure_ascii=False), now))


def _exists() -> bool:
    with db.connect() as conn:
        return conn.execute("SELECT 1 FROM app_settings WHERE key = 'settings'").fetchone() is not None


def _read() -> dict:
    with db.connect() as conn:
        row = conn.execute("SELECT data FROM app_settings WHERE key = 'settings'").fetchone()
    data = json.loads(row["data"])
    plain = any(value and not vault.is_sealed(value) for container, key in _secrets(data) for value in [container[key]])
    for container, key in _secrets(data):
        container[key] = vault.unseal(container[key])
    if plain:  # written before encryption existed: encrypt it now
        _save(data)
    return data


def load() -> dict:
    with _lock:
        if not _exists():
            _save(_from_env())
        return _read()


def update(changes: dict) -> dict:
    """Merge validated changes. In api_keys, a non-empty value replaces a key and None removes it."""
    with _lock:
        data = _read() if _exists() else _from_env()
        for field in ("provider", "model", "use_vision", "deepseek_endpoint"):
            if field in changes:
                data[field] = changes[field]
        for name, value in (changes.get("api_keys") or {}).items():
            if value is None:
                data["api_keys"][name] = ""
            elif value.strip():
                data["api_keys"][name] = value.strip()
        _save(data)
        return data


def update_section(name: str, value: dict) -> None:
    """Replace one section of the file (e.g. "integrations"), leaving the AI settings as they are."""
    with _lock:
        data = _read() if _exists() else _from_env()
        data[name] = value
        _save(data)


ORG_NAME_MAX = 80


def _org() -> str:
    return db.current_org.get() or db.default_org()


def organisation_name(org: str | None = None) -> str:
    """The display name of an organisation (the current request's by default), else ORG_NAME from .env."""
    with db.connect(org=org) as conn:
        row = conn.execute("SELECT name FROM organisations WHERE id = ?", (org or _org(),)).fetchone()
    return ((row["name"] if row else "") or config.ORG_NAME or "").strip()


def set_organisation_name(name: str) -> None:
    with db.connect() as conn:
        conn.execute("UPDATE organisations SET name = ? WHERE id = ?", (" ".join(name.split())[:ORG_NAME_MAX], _org()))


def org_settings(org: str | None = None) -> dict:
    """Choices that belong to one organisation (two-factor policy...), not to the whole server."""
    with db.connect(org=org) as conn:
        row = conn.execute("SELECT settings FROM organisations WHERE id = ?", (org or _org(),)).fetchone()
    return json.loads(row["settings"]) if row else {}


def update_org_settings(changes: dict) -> None:
    with db.connect() as conn:
        org = _org()
        row = conn.execute("SELECT settings FROM organisations WHERE id = ?", (org,)).fetchone()
        current = json.loads(row["settings"]) if row else {}
        conn.execute("UPDATE organisations SET settings = ? WHERE id = ?", (json.dumps({**current, **changes}, ensure_ascii=False), org))


def api_key(name: str) -> str:
    return load()["api_keys"].get(name, "")


def public_view() -> dict:
    """What the Administration page may see: everything except the keys themselves."""
    data = load()
    return {
        "provider": data["provider"],
        "model": data["model"],
        "use_vision": data["use_vision"],
        "deepseek_endpoint": data["deepseek_endpoint"],
        "keys": {name: {"set": bool(key), "hint": f"…{key[-4:]}" if len(key) >= 8 else ("défini" if key else "")}
                 for name, key in data["api_keys"].items()},
        "providers": PROVIDERS,
        "last_test": data.get("last_test"),
    }


def record_test(provider: str, model: str, key_hint: str, ok: bool, message: str) -> None:
    """Remembered so the page can say whether the configuration in use was tested, and when."""
    from datetime import datetime

    update_section("last_test", {"provider": provider, "model": model, "key_hint": key_hint, "ok": ok,
                                 "message": message[:300], "at": datetime.now().isoformat(timespec="seconds")})


def key_hint(key: str) -> str:
    return f"…{key[-4:]}" if len(key) >= 8 else ("défini" if key else "")
