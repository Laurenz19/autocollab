"""Saved agents: reusable instructions that a user can launch again and again.

Instructions may contain date variables such as {mois_precedent}; they are
filled in at launch, so the same agent works every month unchanged.
Each agent also carries its guardrails (allowed sites, approval mode) and,
optionally, a schedule.
"""

import calendar
import json
import re
import uuid
from datetime import date, datetime
from urllib.parse import urlparse

from . import auth, billing, files
from .db import connect

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin",
        "juillet", "août", "septembre", "octobre", "novembre", "décembre"]

# An instruction is sent to the AI at every step: past this, it is a mistake or an attempt to run up the bill.
MAX_INSTRUCTIONS = 20_000
MAX_DOMAINS = 50

VARIABLES = {
    "date": "date du jour (11/10/2026)",
    "mois": "mois en cours (octobre 2026)",
    "mois_precedent": "mois précédent (septembre 2026)",
    "debut_mois_precedent": "1er jour du mois précédent (01/09/2026)",
    "fin_mois_precedent": "dernier jour du mois précédent (30/09/2026)",
    "annee": "année en cours (2026)",
    "annee_precedente": "année précédente (2025)",
    "resultat_precedent": "dans une chaîne : le résultat de l'agent précédent",
}

_VAR_RE = re.compile(r"\{(\w+)\}")
_DOMAIN_RE = re.compile(r"^(\*\.)?([a-z0-9-]+\.)+[a-z]{2,}$")


def _variable_values(today: date) -> dict[str, str]:
    prev_year, prev_month = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
    last_day = calendar.monthrange(prev_year, prev_month)[1]
    return {
        "date": today.strftime("%d/%m/%Y"),
        "mois": f"{MOIS[today.month - 1]} {today.year}",
        "mois_precedent": f"{MOIS[prev_month - 1]} {prev_year}",
        "debut_mois_precedent": f"01/{prev_month:02d}/{prev_year}",
        "fin_mois_precedent": f"{last_day:02d}/{prev_month:02d}/{prev_year}",
        "annee": str(today.year),
        "annee_precedente": str(today.year - 1),
    }


def render(instructions: str, today: date | None = None, extra: dict | None = None) -> str:
    """Fill in known {variables}; anything else in braces is left untouched.

    `extra` adds run-specific values, e.g. the previous agent's result inside a chain.
    """
    values = {"resultat_precedent": "(aucun : cet agent n'est pas lancé dans une chaîne)",
              **_variable_values(today or date.today()), **(extra or {})}
    return _VAR_RE.sub(lambda m: values.get(m.group(1), m.group(0)), instructions)


# --- allowed sites ----------------------------------------------------------------


def normalize_domains(entries: list[str]) -> tuple[list[str], str | None]:
    """Turn what people type ("https://app.pennylane.com/x", "Gmail.com") into bare host names.

    "*.example.com" allows every subdomain. Returns (domains, error).
    """
    out: list[str] = []
    for raw in entries:
        entry = raw.strip().lower()
        if not entry:
            continue
        host = entry
        if "://" in entry or "/" in entry:
            host = urlparse(entry if "://" in entry else "https://" + entry).hostname or ""
        if not _DOMAIN_RE.match(host):
            return [], f"Site invalide : « {raw.strip()} ». Exemple attendu : app.pennylane.com"
        if host not in out:
            out.append(host)
    return out, None


# --- storage ---------------------------------------------------------------------


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def decode(row: dict | None) -> dict | None:
    if not row:
        return None
    agent = dict(row)
    agent["allowed_domains"] = json.loads(agent.get("allowed_domains") or "[]")
    agent["schedule"] = json.loads(agent["schedule"]) if agent.get("schedule") else None
    agent["approval_mode"] = bool(agent.get("approval_mode"))
    agent["schedule_enabled"] = bool(agent.get("schedule_enabled"))
    return agent


def run_options(agent: dict, trigger: str = "manuel") -> dict:
    """What a run needs to know about its agent besides the instructions."""
    return {
        "allowed_domains": agent["allowed_domains"],
        "approval_mode": agent["approval_mode"],
        "trigger": trigger,
        "attachments": files.agent_files(agent["id"]),
    }


def _next_run_at(schedule: dict | None, enabled: bool) -> str | None:
    from .schedule import next_run  # schedule imports this module

    if not schedule or not enabled:
        return None
    return next_run(schedule, datetime.now()).isoformat(timespec="seconds")


def list_for(owner: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM agents WHERE owner = ? ORDER BY lower(name)", (owner,)).fetchall()
    return [decode(dict(r)) for r in rows]


def list_all() -> list[dict]:
    """Everyone's agents, for the firm-wide view (read only for non-owners)."""
    with connect() as conn:
        rows = conn.execute("SELECT * FROM agents ORDER BY lower(name)").fetchall()
    return [decode(dict(r)) for r in rows]


def get_any(agent_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
    return decode(dict(row)) if row else None


def get(agent_id: str, owner: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM agents WHERE id = ? AND owner = ?", (agent_id, owner)).fetchone()
    return decode(dict(row)) if row else None


def create(
    owner: str,
    name: str,
    instructions: str,
    max_steps: int | None,
    allowed_domains: list[str] | None = None,
    approval_mode: bool = False,
    schedule: dict | None = None,
    schedule_enabled: bool = False,
    via: str = "app",
) -> dict:
    billing.check_new_agent(auth.org_of(owner))
    if schedule and schedule_enabled:
        billing.check_new_schedule(auth.org_of(owner))
    now = _now()
    row = {
        "id": uuid.uuid4().hex[:12], "owner": owner, "name": name, "instructions": instructions,
        "max_steps": max_steps, "created_at": now, "updated_at": now,
        "allowed_domains": json.dumps(allowed_domains or []),
        "approval_mode": int(approval_mode),
        "schedule": json.dumps(schedule) if schedule else None,
        "schedule_enabled": int(bool(schedule) and schedule_enabled),
        "next_run_at": _next_run_at(schedule, schedule_enabled),
        "created_via": via, "updated_via": via,
    }
    with connect() as conn:
        conn.execute(
            f"INSERT INTO agents ({', '.join(row)}) VALUES ({', '.join(':' + k for k in row)})",
            row,
        )
    return decode(row)


def update(agent_id: str, owner: str, changes: dict, via: str = "app") -> dict | None:
    current = get(agent_id, owner)
    if not current:
        return None
    merged = {**current, **{k: v for k, v in changes.items() if k in current}}
    if "schedule" in changes and not changes["schedule"]:
        merged["schedule_enabled"] = False
    sets = {
        "name": merged["name"],
        "instructions": merged["instructions"],
        "max_steps": merged["max_steps"],
        "allowed_domains": json.dumps(merged["allowed_domains"]),
        "approval_mode": int(merged["approval_mode"]),
        "schedule": json.dumps(merged["schedule"]) if merged["schedule"] else None,
        "schedule_enabled": int(bool(merged["schedule"]) and merged["schedule_enabled"]),
        "updated_at": _now(),
        "updated_via": via,
    }
    if sets["schedule_enabled"] and not current["schedule_enabled"]:
        billing.check_new_schedule(auth.org_of(owner))
    # Only move the next run when the schedule itself or its on/off switch changed.
    if merged["schedule"] != current["schedule"] or bool(sets["schedule_enabled"]) != current["schedule_enabled"]:
        sets["next_run_at"] = _next_run_at(merged["schedule"], bool(sets["schedule_enabled"]))
    with connect() as conn:
        conn.execute(
            f"UPDATE agents SET {', '.join(f'{k} = :{k}' for k in sets)} WHERE id = :id AND owner = :owner",
            {**sets, "id": agent_id, "owner": owner},
        )
    return get(agent_id, owner)


def delete(agent_id: str, owner: str) -> bool:
    with connect() as conn:
        cur = conn.execute("DELETE FROM agents WHERE id = ? AND owner = ?", (agent_id, owner))
    return cur.rowcount > 0
