"""Shared knowledge added to every agent's instructions: the firm's vocabulary, rules and
how its sites work, plus each user's own additions.

Two scopes: "cabinet" (edited by administrators, applies to everyone) and one personal scope
per user. To keep the prompt short, site notes are only included when the task is about that
site, and a long glossary is cut down to the terms the task mentions.
"""

import json
import unicodedata
from datetime import datetime

from .db import connect

LIMITS = {"instructions": 4000, "terms": 100, "term": 60, "definition": 300, "sites": 30, "site": 100, "notes": 1500}
# Below this size the whole glossary goes in; above, only the terms the task mentions.
FULL_GLOSSARY_CHARS = 3000



def _empty() -> dict:
    return {"instructions": "", "glossary": [], "sites": []}


def scope_of(owner: str | None) -> str:
    return f"user:{owner}" if owner else "cabinet"


def load(scope: str) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT data, updated_at, updated_by FROM contexts WHERE scope = ?", (scope,)).fetchone()
    if not row:
        return {**_empty(), "updated_at": None, "updated_by": None}
    return {**_empty(), **json.loads(row["data"]), "updated_at": row["updated_at"], "updated_by": row["updated_by"]}


def clean(data: dict) -> tuple[dict, str | None]:
    """Trim, drop empty rows and enforce the limits. Returns (data, error)."""
    out = {"instructions": (data.get("instructions") or "").strip(), "glossary": [], "sites": []}
    if len(out["instructions"]) > LIMITS["instructions"]:
        return out, f"Règles générales : {LIMITS['instructions']} caractères au maximum."
    for item in data.get("glossary") or []:
        term, definition = (item.get("term") or "").strip(), (item.get("definition") or "").strip()
        if not term and not definition:
            continue
        if not term or not definition:
            return out, "Glossaire : chaque ligne doit avoir un mot-clé et sa signification."
        if len(term) > LIMITS["term"] or len(definition) > LIMITS["definition"]:
            return out, f"Glossaire : {LIMITS['term']} caractères par mot-clé et {LIMITS['definition']} par signification au maximum."
        out["glossary"].append({"term": term, "definition": definition})
    for item in data.get("sites") or []:
        site, notes = (item.get("site") or "").strip(), (item.get("notes") or "").strip()
        if not site and not notes:
            continue
        if not site or not notes:
            return out, "Notes par site : chaque ligne doit avoir un site et des notes."
        if len(site) > LIMITS["site"] or len(notes) > LIMITS["notes"]:
            return out, f"Notes par site : {LIMITS['notes']} caractères de notes au maximum par site."
        out["sites"].append({"site": site, "notes": notes})
    if len(out["glossary"]) > LIMITS["terms"] or len(out["sites"]) > LIMITS["sites"]:
        return out, f"{LIMITS['terms']} mots-clés et {LIMITS['sites']} sites au maximum."
    return out, None


def save(scope: str, data: dict, by: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO contexts (scope, data, updated_at, updated_by) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(scope) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at, updated_by = excluded.updated_by",
            (scope, json.dumps(data, ensure_ascii=False), datetime.now().isoformat(timespec="seconds"), by),
        )


# --- building the text the agent receives ----------------------------------------------


def _fold(text: str) -> str:
    """Lowercase without accents, so "Relevé" matches "releve"."""
    return unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()


def _site_matches(site: str, task: str, domains: list[str]) -> bool:
    key = _fold(site).removeprefix("https://").removeprefix("http://").strip("/")
    names = {key, key.split("/")[0]}
    host = key.split("/")[0]
    if "." in host:  # "app.pennylane.com" also answers to "pennylane"
        parts = host.split(".")
        names.add(parts[-2] if len(parts) >= 2 else host)
    if any(len(n) >= 3 and n in task for n in names):
        return True
    for d in (_fold(x).lstrip("*.") for x in domains):
        if "." in host and (host == d or host.endswith("." + d) or d.endswith("." + host)):
            return True
        if "." not in host and host in d.split("."):  # a name such as "Qonto" for app.qonto.com
            return True
    return False


def _glossary_for(data: dict, task: str) -> list[dict]:
    glossary = data["glossary"]
    if sum(len(g["term"]) + len(g["definition"]) for g in glossary) > FULL_GLOSSARY_CHARS:
        glossary = [g for g in glossary if _fold(g["term"]) in task]
    return glossary


def _section(title: str, data: dict, task: str, domains: list[str]) -> str | None:
    lines = []
    if data["instructions"]:
        lines.append(data["instructions"])
    glossary = _glossary_for(data, task)
    if glossary:
        lines.append("Vocabulaire :\n" + "\n".join(f"- {g['term']} : {g['definition']}" for g in glossary))
    sites = [s for s in data["sites"] if _site_matches(s["site"], task, domains)]
    if sites:
        lines.append("Particularités des sites :\n" + "\n".join(f"- {s['site']} : {s['notes']}" for s in sites))
    return f"{title}\n" + "\n\n".join(lines) if lines else None


def build(owner: str, task: str, domains: list[str] | None = None) -> str | None:
    """The context block for one run, or None when nothing applies."""
    folded = _fold(task)
    parts = [
        _section("CONTEXTE DU CABINET (à respecter) :", load("cabinet"), folded, domains or []),
        _section("CONTEXTE DE L'UTILISATEUR :", load(scope_of(owner)), folded, domains or []),
    ]
    text = "\n\n".join(p for p in parts if p)
    return text or None


def summary(owner: str, task: str, domains: list[str] | None = None) -> dict:
    """What build() keeps for this task, per scope, in plain counts and names (for the preview page)."""
    folded = _fold(task)

    def one(data: dict) -> dict:
        sites = data["sites"]
        kept = [s["site"] for s in sites if _site_matches(s["site"], folded, domains or [])]
        return {
            "rules": sum(1 for line in data["instructions"].splitlines() if line.strip()),
            "terms_sent": len(_glossary_for(data, folded)),
            "terms_total": len(data["glossary"]),
            "sites_kept": kept,
            "sites_skipped": [s["site"] for s in sites if s["site"] not in kept],
        }

    return {"cabinet": one(load("cabinet")), "personal": one(load(scope_of(owner)))}
