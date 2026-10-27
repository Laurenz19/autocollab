"""The platform's back office: its clients (organisations), what they pay and what they cost.

Only the administrators of the platform's own organisation reach it (Administration › Clients).
Figures are read across organisations (db.connect(system=True)); changes to a client's plan,
credits or access go through app/billing.py, which logs them in the client's journal.
"""

import json
import uuid
from datetime import datetime

from . import auth, billing, db
from .db import connect

NAME_MAX = 80


def _month(now: datetime | None = None) -> tuple[str, str]:
    now = now or datetime.now()
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    return start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")


def clients() -> dict:
    """Every organisation with its plan, this month's runs, AI cost and revenue, and the totals."""
    start, end = _month()
    with connect(system=True) as conn:
        orgs = conn.execute("SELECT id, name, created_at FROM organisations ORDER BY created_at, id").fetchall()
        people: dict[str, list[dict]] = {}
        for row in conn.execute("SELECT organisation_id, data FROM users").fetchall():
            people.setdefault(row["organisation_id"], []).append(json.loads(row["data"]))
        month = {row["organisation_id"]: row for row in conn.execute(
            "SELECT organisation_id, COUNT(*) AS runs, COALESCE(SUM(credits), 0) AS credits, COALESCE(SUM(cost_usd), 0) AS cost"
            " FROM runs WHERE created_at >= ? AND created_at < ? GROUP BY organisation_id", (start, end)).fetchall()}
        last = {row["organisation_id"]: row["last"] for row in conn.execute(
            "SELECT organisation_id, MAX(created_at) AS last FROM runs GROUP BY organisation_id").fetchall()}
        agents = {row["organisation_id"]: row["n"] for row in conn.execute(
            "SELECT organisation_id, COUNT(*) AS n FROM agents GROUP BY organisation_id").fetchall()}
    lines = []
    for org in orgs:
        status = billing.status(org["id"])
        used = month.get(org["id"])
        cost = round(float(used["cost"]) if used else 0.0, 2)
        revenue = billing.monthly_revenue_usd(org["id"])
        members = people.get(org["id"], [])
        lines.append({
            "id": org["id"], "name": org["name"], "created_at": org["created_at"], "platform": status["platform"],
            "users": len(members), "admins": sum(1 for u in members if u.get("admin")), "agents": agents.get(org["id"], 0),
            "plan": status["plan"], "label": status["label"], "source": status["source"],
            "stripe_status": status["status"] if status["source"] == "stripe" else None,
            "cancel_at_period_end": status["cancel_at_period_end"], "suspended": status["suspended"],
            "credits": status["credits"],
            "month": {"runs": used["runs"] if used else 0, "credits": round(float(used["credits"]) if used else 0.0, 1),
                      "ai_cost_usd": cost, "revenue_usd": revenue, "margin_usd": round(revenue - cost, 2)},
            "last_activity": last.get(org["id"]),
        })
    clients_only = [line for line in lines if not line["platform"]]
    revenue = round(sum(line["month"]["revenue_usd"] for line in clients_only), 2)
    cost = round(sum(line["month"]["ai_cost_usd"] for line in clients_only), 2)
    return {
        "month": start[:7], "billing_enabled": billing.enabled(),
        "totals": {
            "clients": len(clients_only),
            "paying": sum(1 for line in clients_only if line["month"]["revenue_usd"] > 0),
            "suspended": sum(1 for line in clients_only if line["suspended"]),
            "past_due": sum(1 for line in clients_only if line["stripe_status"] == "past_due"),
            "revenue_usd": revenue, "ai_cost_usd": cost, "margin_usd": round(revenue - cost, 2),
            "platform_ai_cost_usd": round(sum(line["month"]["ai_cost_usd"] for line in lines if line["platform"]), 2),
        },
        "clients": lines,
    }


def client(org: str) -> dict | None:
    """One organisation: its accounts, billing, journal, and the last six months."""
    with connect(system=True) as conn:
        row = conn.execute("SELECT id, name, created_at FROM organisations WHERE id = ?", (org,)).fetchone()
        if not row:
            return None
        accounts = conn.execute("SELECT username, data FROM users WHERE organisation_id = ? ORDER BY username", (org,)).fetchall()
        history = conn.execute(
            "SELECT substr(created_at, 1, 7) AS month, COUNT(*) AS runs, COALESCE(SUM(credits), 0) AS credits,"
            " COALESCE(SUM(cost_usd), 0) AS cost FROM runs WHERE organisation_id = ? AND created_at >= ?"
            " GROUP BY substr(created_at, 1, 7) ORDER BY month DESC",
            (org, _six_months_ago())).fetchall()
    users = []
    for account in accounts:
        data = json.loads(account["data"])
        users.append({"username": account["username"], "name": data.get("name") or account["username"], "email": data.get("email", ""),
                      "admin": bool(data.get("admin")), "temporary_password": bool(data.get("must_change_password")),
                      "two_factor": bool((data.get("totp") or {}).get("enabled"))})
    return {
        "id": row["id"], "name": row["name"], "created_at": row["created_at"],
        "billing": {**billing.status(org), **billing.details(org), "revenue_usd": billing.monthly_revenue_usd(org)},
        "users": users,
        "history": [{"month": h["month"], "runs": h["runs"], "credits": round(float(h["credits"]), 1),
                     "ai_cost_usd": round(float(h["cost"]), 2)} for h in history],
    }


def _six_months_ago() -> str:
    now = datetime.now()
    year, month = (now.year, now.month - 5) if now.month > 5 else (now.year - 1, now.month + 7)
    return datetime(year, month, 1).isoformat(timespec="seconds")


def create_client(name: str, username: str, display_name: str, email: str, password: str, by: str,
                  manual_plan: str | None = None, manual_price_usd: float | None = None) -> dict:
    """A new organisation and its first administrator, who replaces the password at first sign-in."""
    name = " ".join(name.split())[:NAME_MAX]
    if not name:
        raise ValueError("Donnez un nom au client.")
    username = auth.normalize_username(username)
    email = auth.normalize_email(email)
    if error := auth.username_error(username) or auth.password_error(password):
        raise ValueError(error)
    if manual_plan is not None and manual_plan not in billing.plans():
        raise ValueError("Formule inconnue.")
    with auth.users_lock:
        if auth.taken_elsewhere(username):
            raise ValueError(f"L'identifiant « {username} » est déjà pris : choisissez-en un autre.")
        if error := auth.email_error(email, {}):
            raise ValueError(error)
        org = "org-" + uuid.uuid4().hex[:12]
        account = {"name": display_name.strip() or username, "email": email, "password": auth.hash_password(password),
                   "admin": True, "must_change_password": True}
        with connect(system=True) as conn:
            conn.execute("INSERT INTO organisations (id, name, settings, created_at) VALUES (?, ?, '{}', ?)",
                         (org, name, datetime.now().isoformat(timespec="seconds")))
            conn.execute("INSERT INTO users (username, data, organisation_id) VALUES (?, ?, ?)",
                         (username, json.dumps(account, ensure_ascii=False), org))
        auth.forget_orgs()
    billing.log(org, by, f"Client créé, premier administrateur « {username} »")
    if manual_plan is not None or manual_price_usd is not None:
        billing.manage(org, by, manual_plan=manual_plan, manual_price_usd=manual_price_usd)
    return client(org)


def rename(org: str, name: str) -> None:
    name = " ".join(name.split())[:NAME_MAX]
    if not name:
        raise ValueError("Donnez un nom au client.")
    with connect(system=True) as conn:
        conn.execute("UPDATE organisations SET name = ? WHERE id = ?", (name, org))


# Plan fields that can be changed one by one (MCP): (lowest, highest, empty allowed = unlimited).
_LIMIT_BOUNDS = {"parallel": (1, 1000), "agents": (0, 100_000), "schedules": (0, 100_000), "users": (1, 100_000)}


def _number(value, field: str, low: float, high: float, integer: bool = True):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or (integer and value != int(value)) or not low <= value <= high:
        raise ValueError(f"{field} : {'entier' if integer else 'nombre'} entre {low:g} et {high:g} attendu.")
    return int(value) if integer else round(float(value), 2)


def _stripe_price(value, field: str) -> str:
    value = str(value or "").strip()
    if value and not value.startswith("price_"):
        raise ValueError(f"{field} : un identifiant de prix Stripe commence par « price_ ».")
    return value[:100]


def update_plan(key: str, changes: dict) -> dict:
    """Change some fields of one plan (label, credits, limits, prices, Stripe price ids); the rest stays."""
    catalog = billing.catalog()
    if key not in catalog["plans"]:
        raise ValueError(f"Formule inconnue : {key}. Formules : {', '.join(catalog['plans'])}.")
    plan = catalog["plans"][key]
    for field, value in changes.items():
        if field == "label":
            plan["label"] = " ".join(str(value or "").split())[:40]
            if not plan["label"]:
                raise ValueError("Le nom de la formule ne peut pas être vide.")
        elif field == "credits":
            plan["credits"] = _number(value, "credits", 0, 100_000_000)
        elif field in _LIMIT_BOUNDS:
            plan[field] = None if value is None else _number(value, field, *_LIMIT_BOUNDS[field])
        elif field in ("usd_monthly", "usd_yearly", "stripe_monthly", "stripe_yearly"):
            if key == billing.FREE:
                raise ValueError("La formule gratuite n'a ni prix ni identifiant Stripe.")
            kind, period = field.split("_")
            plan[kind][period] = _number(value, field, 0, 1_000_000, integer=False) if kind == "usd" else _stripe_price(value, field)
        else:
            raise ValueError(f"Champ inconnu : {field}.")
    return billing.save_catalog(catalog["plans"], catalog["pack"])


def update_pack(changes: dict) -> dict:
    """Change the credit pack: credits, price, Stripe price id."""
    catalog = billing.catalog()
    pack = catalog["pack"]
    for field, value in changes.items():
        if field == "credits":
            pack["credits"] = _number(value, "credits", 1, 100_000_000)
        elif field == "usd":
            pack["usd"] = _number(value, "usd", 0, 1_000_000, integer=False)
        elif field == "stripe":
            pack["stripe"] = _stripe_price(value, "stripe")
        else:
            raise ValueError(f"Champ inconnu : {field}.")
    return billing.save_catalog(catalog["plans"], pack)


def delete_empty(org: str) -> None:
    """Remove an organisation that holds nothing (created by mistake, or left over by a migration).
    One with accounts or history is suspended instead: its data stays."""
    if org == db.default_org():
        raise ValueError("L'organisation de la plateforme ne peut pas être supprimée.")
    with connect(system=True) as conn:
        for table in db.ORG_TABLES:
            if conn.execute(f"SELECT 1 FROM {table} WHERE organisation_id = ? LIMIT 1", (org,)).fetchone():
                raise ValueError("Ce client a des comptes ou un historique : suspendez-le plutôt, ses données seront conservées.")
        conn.execute("DELETE FROM organisations WHERE id = ?", (org,))


def exists(org: str) -> bool:
    with connect(system=True) as conn:
        return conn.execute("SELECT 1 FROM organisations WHERE id = ?", (org,)).fetchone() is not None
