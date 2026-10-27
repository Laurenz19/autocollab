"""Subscriptions and credits, one per organisation (client), paid with Stripe.

Each organisation has its own plan, Stripe customer, subscription and credits, kept in
organisations.settings ("billing"). A client's administrator subscribes from Administration ›
Abonnement (Stripe Checkout) and manages card, invoices, plan change and cancellation in Stripe's
customer portal. Stripe tells the app what happened through the webhook (/api/stripe/webhook); each
event is routed to its organisation by the metadata the app put on what it created, else by the
Stripe customer.

The platform's administrators (app/backoffice.py) can also give a plan by hand (Entreprise on
quote, a trial), grant credits and suspend an organisation. The platform's own organisation is
never limited: it runs the server.

Credits used are the organisation's runs' credits (app/pricing.py) since the start of its billing
period, so nothing is counted twice. Pack and granted credits are used after the plan's and carry
over from month to month.

Plans, prices and Stripe price ids start from DEFAULT_PLANS and .env; the platform's administrators
can change them in the back office (settings section "catalog").

Without STRIPE_SECRET_KEY billing is off and nothing is limited: an installation on a client's own
servers (Entreprise) or ours before launch. Suspension works either way. One Stripe account serves
every installation, so each installation tags what it creates with its own id and ignores the
events of the others.
"""

import calendar
import copy
import hashlib
import hmac
import json
import secrets
import threading
import time
from datetime import datetime
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from . import config, db, settings
from .db import connect

# limits: None = unlimited. "parallel" = agents running at the same time.
DEFAULT_PLANS = {
    "gratuit": {"label": "Gratuit", "credits": 100, "parallel": 1, "agents": 3, "schedules": 0, "users": 1, "usd": {"monthly": 0, "yearly": 0}},
    "solo": {"label": "Solo", "credits": 3_000, "parallel": 1, "agents": 10, "schedules": 3, "users": 1, "usd": {"monthly": 20, "yearly": 200}},
    "equipe": {"label": "Équipe", "credits": 20_000, "parallel": 3, "agents": None, "schedules": None, "users": 10, "usd": {"monthly": 129, "yearly": 1290}},
    "entreprise": {"label": "Entreprise", "credits": 80_000, "parallel": 10, "agents": None, "schedules": None, "users": None, "usd": {"monthly": 449, "yearly": 449 * 12}},
}
DEFAULT_PACK = {"credits": 10_000, "usd": 39}
LIMITS = ("parallel", "agents", "schedules", "users")
FREE = "gratuit"
PERIODS = ("monthly", "yearly")
# Stripe statuses that keep the plan: past_due = a payment failed, Stripe is retrying.
ACTIVE = ("active", "trialing", "past_due")

API = "https://api.stripe.com/v1/"
SIGNATURE_TOLERANCE = 300  # seconds: older webhook calls are refused (replays)

_lock = threading.RLock()


class LimitReached(RuntimeError):
    """The plan does not allow this; the message says why and what to do."""


def enabled() -> bool:
    return bool(config.STRIPE_SECRET_KEY)


# --- catalog: plans, prices, Stripe price ids ---------------------------------------------


_CATALOG_SECONDS = 5  # read again after this, so a change made by another server process shows quickly
_catalog_cache: tuple[float, dict] | None = None


def catalog() -> dict:
    """The plans and the credit pack as they apply now: the defaults, changed by the back office."""
    global _catalog_cache
    if _catalog_cache and time.monotonic() - _catalog_cache[0] < _CATALOG_SECONDS:
        return copy.deepcopy(_catalog_cache[1])
    stored = settings.load().get("catalog") or {}
    plans = copy.deepcopy(DEFAULT_PLANS)
    for key, plan in plans.items():
        change = (stored.get("plans") or {}).get(key) or {}
        for field in ("label", "credits", *LIMITS):
            if field in change:
                plan[field] = change[field]
        plan["usd"] = {**plan["usd"], **(change.get("usd") or {})}
        plan["stripe"] = {period: (change.get("stripe") or {}).get(period) or config.STRIPE_PRICES.get(f"{key}_{period}", "")
                          for period in PERIODS} if key != FREE else {}
    pack = {**DEFAULT_PACK, **{k: v for k, v in (stored.get("pack") or {}).items() if k in ("credits", "usd")}}
    pack["stripe"] = (stored.get("pack") or {}).get("stripe") or config.STRIPE_PRICES.get("credits", "")
    _catalog_cache = (time.monotonic(), {"plans": plans, "pack": pack})
    return copy.deepcopy(_catalog_cache[1])


def save_catalog(plans: dict, pack: dict) -> dict:
    """Store what differs from the defaults (validated by the caller): plans keep their keys."""
    stored = {"plans": {}, "pack": {}}
    for key, plan in plans.items():
        if key not in DEFAULT_PLANS:
            continue
        stored["plans"][key] = {field: plan[field] for field in ("label", "credits", *LIMITS) if field in plan}
        stored["plans"][key]["usd"] = {p: plan["usd"][p] for p in PERIODS if p in (plan.get("usd") or {})}
        if key != FREE:
            stored["plans"][key]["stripe"] = {p: (plan.get("stripe") or {}).get(p, "").strip() for p in PERIODS}
    stored["pack"] = {k: pack[k] for k in ("credits", "usd") if k in pack}
    stored["pack"]["stripe"] = (pack.get("stripe") or "").strip()
    global _catalog_cache
    settings.update_section("catalog", stored)
    _catalog_cache = None
    return catalog()


def reset_cache() -> None:
    """Forget what is kept in memory (tests switch databases)."""
    global _catalog_cache, _installation_id
    _catalog_cache, _installation_id = None, None


def plans() -> dict:
    return catalog()["plans"]


def price_id(plan: str, period: str) -> str:
    return (plans().get(plan) or {}).get("stripe", {}).get(period, "")


def _plan_of_price(price: str) -> tuple[str, str] | None:
    for key, plan in plans().items():
        for period, value in (plan.get("stripe") or {}).items():
            if value and value == price:
                return key, period
    return None


# --- state ---------------------------------------------------------------------------


def _org(org: str | None = None) -> str:
    return org or db.current_org.get() or db.default_org()


def is_platform(org: str) -> bool:
    return org == db.default_org()


_installation_id: str | None = None


def _installation() -> str:
    """This installation's id on the shared Stripe account. Before billing per organisation, the section
    "billing" of the settings held the subscription itself: it moves to the platform's organisation."""
    global _installation_id
    if _installation_id:
        return _installation_id
    with _lock:
        legacy = dict(settings.load().get("billing") or {})
        installation = legacy.get("installation") or secrets.token_hex(8)
        if set(legacy) - {"installation"} or not legacy.get("installation"):
            moved = {k: v for k, v in legacy.items() if k != "installation"}
            if moved:
                platform = db.default_org()
                current = _read(platform)
                if not set(current) - {"events"}:
                    _write(platform, moved)
            settings.update_section("billing", {"installation": installation})
        _installation_id = installation
        return installation


def _read(org: str) -> dict:
    with connect(system=True) as conn:
        row = conn.execute("SELECT settings FROM organisations WHERE id = ?", (org,)).fetchone()
    return dict((json.loads(row["settings"]) if row else {}).get("billing") or {})


def _write(org: str, state: dict) -> None:
    with connect(system=True) as conn:
        row = conn.execute("SELECT settings FROM organisations WHERE id = ?", (org,)).fetchone()
        if not row:
            return
        data = json.loads(row["settings"])
        data["billing"] = state
        conn.execute("UPDATE organisations SET settings = ? WHERE id = ?", (json.dumps(data, ensure_ascii=False), org))


def _state(org: str) -> dict:
    _installation()
    return _read(org)


def _month_bounds(now: datetime) -> tuple[str, str]:
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    return start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")


def _iso(timestamp: int | None) -> str | None:
    return datetime.fromtimestamp(timestamp).isoformat(timespec="seconds") if timestamp else None


def _paid(state: dict) -> bool:
    return state.get("status") in ACTIVE and state.get("plan") in plans() and state.get("plan") != FREE


def _manual(state: dict) -> str | None:
    """A plan given by the platform (Entreprise on quote, a trial): it wins over Stripe while it is set."""
    plan = state.get("manual_plan")
    return plan if plan in plans() else None


def source(state: dict) -> str:
    """Where the plan comes from: manuel (back office), stripe (paid subscription) or gratuit."""
    return "manuel" if _manual(state) else "stripe" if _paid(state) else "gratuit"


def _period(state: dict) -> tuple[str, str]:
    """Start and end of the current credit period: the Stripe billing period, else the calendar month.

    A yearly plan still gets its credits month by month: the period is the month of the
    subscription year we are in.
    """
    now = datetime.now()
    if not _manual(state) and _paid(state) and state.get("period_start") and state.get("period_end"):
        start, end = datetime.fromisoformat(state["period_start"]), datetime.fromisoformat(state["period_end"])
        if start <= now < end:
            if state.get("period") != "yearly":
                return state["period_start"], state["period_end"]
            months = 0
            while _add_months(start, months + 1) <= now:
                months += 1
            return (_add_months(start, months).isoformat(timespec="seconds"),
                    min(_add_months(start, months + 1), end).isoformat(timespec="seconds"))
    return _month_bounds(now)


def _add_months(start: datetime, months: int) -> datetime:
    """`start` moved by whole months, on the last day of the month when that month is shorter."""
    year, month = divmod(start.month - 1 + months, 12)
    year, month = start.year + year, month + 1
    return start.replace(year=year, month=month, day=min(start.day, calendar.monthrange(year, month)[1]))


def used_since(org: str, start: str, end: str | None = None) -> float:
    """Credits of the organisation's runs since `start` (and before `end`)."""
    with connect(system=True) as conn:
        if end:
            row = conn.execute("SELECT SUM(credits) FROM runs WHERE organisation_id = ? AND created_at >= ? AND created_at < ?",
                               (org, start, end)).fetchone()
        else:
            row = conn.execute("SELECT SUM(credits) FROM runs WHERE organisation_id = ? AND created_at >= ?", (org, start)).fetchone()
    return round(row[0] or 0, 1)


def _settle(org: str, state: dict) -> dict:
    """At a new period, extra credits still left are those the previous period did not need."""
    start, _ = _period(state)
    previous = state.get("settled_period")
    if previous == start:
        return state
    if previous and state.get("extra_credits"):
        overflow = max(0.0, used_since(org, previous, start) - (state.get("settled_plan_credits") or 0))
        state["extra_credits"] = round(max(0.0, state["extra_credits"] - overflow), 1)
    state["settled_period"] = start
    state["settled_plan_credits"] = plans()[current_plan_key(state)]["credits"]
    _write(org, state)
    return state


def current_plan_key(state: dict) -> str:
    return _manual(state) or (state["plan"] if _paid(state) else FREE)


def _limited(org: str) -> bool:
    """Plans are enforced when billing is on, except for the platform's own organisation."""
    return enabled() and not is_platform(org)


def plan(org: str | None = None) -> dict:
    return plans()[current_plan_key(_state(_org(org)))]


def status(org: str | None = None) -> dict:
    """What Administration › Abonnement shows, for the current organisation (or `org`)."""
    org = _org(org)
    with _lock:
        state = _settle(org, _state(org))
    every = catalog()
    key = current_plan_key(state)
    start, end = _period(state)
    used = used_since(org, start)
    included, extra = every["plans"][key]["credits"], state.get("extra_credits") or 0
    paid = source(state) == "stripe"
    return {
        "enabled": enabled(),
        "unlimited": not _limited(org),
        "platform": is_platform(org),
        "plan": key, "label": every["plans"][key]["label"], "source": source(state),
        "period": state.get("period") if paid else None,
        "status": state.get("status"), "cancel_at_period_end": bool(state.get("cancel_at_period_end")),
        "renews_at": state.get("period_end") if paid else None,
        "suspended": bool(state.get("suspended")), "suspended_reason": state.get("suspended_reason") or "",
        "credits": {"included": included, "extra": extra, "used": used,
                    "remaining": round(max(0.0, included + extra - used), 1), "period_start": start, "period_end": end},
        "limits": {k: every["plans"][key][k] for k in LIMITS},
        "customer": bool(state.get("customer")),
        "plans": [{"key": k, "label": p["label"], "credits": p["credits"], "usd": p["usd"],
                   "limits": {x: p[x] for x in LIMITS},
                   "periods": [period for period in PERIODS if p.get("stripe", {}).get(period)]}
                  for k, p in every["plans"].items()],
        "pack": {"credits": every["pack"]["credits"], "usd": every["pack"]["usd"], "available": bool(every["pack"]["stripe"])},
    }


# --- suspension ------------------------------------------------------------------------------

SUSPENDED = "L'accès de votre organisation est suspendu. Contactez votre interlocuteur pour le rétablir."


def suspended(org: str | None) -> bool:
    """True for a suspended organisation; the platform's own one never is."""
    if not org or is_platform(org):
        return False
    return bool(_read(org).get("suspended"))


# --- limits (all no-ops while billing is off, and for the platform) ---------------------------


def check_credits(org: str | None = None) -> None:
    org = _org(org)
    if suspended(org):
        raise LimitReached(SUSPENDED)
    if not _limited(org):
        return
    if status(org)["credits"]["remaining"] <= 0:
        raise LimitReached("Plus de crédits ce mois-ci. Un administrateur peut acheter un pack de crédits ou "
                           "changer de formule dans Administration › Abonnement.")


def parallel_limit(org: str | None = None) -> int | None:
    org = _org(org)
    return plan(org)["parallel"] if _limited(org) else None


def _count(sql: str, org: str) -> int:
    with connect(system=True) as conn:
        return conn.execute(sql, (org,) * sql.count("?")).fetchone()[0]


def check_new_agent(org: str | None = None) -> None:
    org = _org(org)
    limit = plan(org)["agents"] if _limited(org) else None
    if limit is not None and _count("SELECT COUNT(*) FROM agents WHERE organisation_id = ?", org) >= limit:
        raise LimitReached(f"La formule {plan(org)['label']} permet {limit} agents enregistrés. "
                           "Supprimez-en un, ou passez à une formule supérieure (Administration › Abonnement).")


def check_new_schedule(org: str | None = None) -> None:
    org = _org(org)
    limit = plan(org)["schedules"] if _limited(org) else None
    if limit is None:
        return
    used = _count("SELECT (SELECT COUNT(*) FROM agents WHERE schedule_enabled = 1 AND organisation_id = ?)"
                  " + (SELECT COUNT(*) FROM chains WHERE schedule_enabled = 1 AND organisation_id = ?)", org)
    if used >= limit:
        allowed = f"permet {limit} tâches planifiées" if limit else "ne comprend pas les tâches planifiées"
        raise LimitReached(f"La formule {plan(org)['label']} {allowed}. Passez à une formule supérieure (Administration › Abonnement).")


def check_new_user(count: int, org: str | None = None) -> None:
    org = _org(org)
    limit = plan(org)["users"] if _limited(org) else None
    if limit is not None and count >= limit:
        raise LimitReached(f"La formule {plan(org)['label']} permet {limit} utilisateur{'s' if limit > 1 else ''}. "
                           "Passez à une formule supérieure (Administration › Abonnement).")


# --- back office: what the platform's administrators change by hand ----------------------------


def manage(org: str, by: str, *, manual_plan: str | None | object = ..., manual_price_usd: float | None | object = ...,
           suspend: bool | None = None, reason: str = "", note: str | None = None) -> dict:
    """Give or remove a plan by hand, its monthly price, suspend or reactivate. Each change is logged."""
    if is_platform(org) and suspend:
        raise ValueError("L'organisation de la plateforme ne peut pas être suspendue.")
    with _lock:
        state = _state(org)
        log = []
        if manual_plan is not ...:
            if manual_plan is not None and manual_plan not in plans():
                raise ValueError("Formule inconnue.")
            if manual_plan != state.get("manual_plan"):
                state["manual_plan"] = manual_plan
                log.append(f"Formule manuelle : {plans()[manual_plan]['label'] if manual_plan else 'retirée'}")
        if manual_price_usd is not ... and manual_price_usd != state.get("manual_price_usd"):
            state["manual_price_usd"] = manual_price_usd
            log.append(f"Prix mensuel convenu : {manual_price_usd if manual_price_usd is not None else 'aucun'} $")
        if suspend is not None and suspend != bool(state.get("suspended")):
            state["suspended"] = suspend
            state["suspended_reason"] = reason.strip()[:300] if suspend else ""
            log.append("Suspendue" + (f" : {state['suspended_reason']}" if state["suspended_reason"] else "") if suspend else "Réactivée")
        if note is not None:
            state["note"] = note.strip()[:2000]
        if log:
            _journal(state, by, " · ".join(log))
        _write(org, state)
    return status(org)


def grant_credits(org: str, credits: float, by: str, note: str = "") -> dict:
    """Add credits by hand (a gesture, a correction): like a pack, they carry over. Negative = remove."""
    with _lock:
        state = _settle(org, _state(org))
        state["extra_credits"] = round(max(0.0, (state.get("extra_credits") or 0) + credits), 1)
        _journal(state, by, f"{'+' if credits >= 0 else ''}{credits:g} crédits" + (f" : {note.strip()[:300]}" if note.strip() else ""))
        _write(org, state)
    return status(org)


def log(org: str, by: str, what: str) -> None:
    """Add a line to the organisation's journal (shown in the back office)."""
    with _lock:
        state = _state(org)
        _journal(state, by, what)
        _write(org, state)


def _journal(state: dict, by: str, what: str) -> None:
    state["journal"] = ([{"at": datetime.now().isoformat(timespec="seconds"), "by": by, "what": what}]
                        + (state.get("journal") or []))[:100]


def details(org: str) -> dict:
    """What the back office shows about one organisation's billing, on top of status()."""
    state = _state(org)
    return {"manual_plan": _manual(state), "manual_price_usd": state.get("manual_price_usd"), "note": state.get("note") or "",
            "stripe_customer": state.get("customer"), "stripe_subscription": state.get("subscription"),
            "journal": state.get("journal") or []}


def monthly_revenue_usd(org: str, state: dict | None = None) -> float:
    """What the organisation pays per month, before tax: the agreed price of a manual plan, else its Stripe plan."""
    state = state if state is not None else _state(org)
    if _manual(state):
        return float(state.get("manual_price_usd") or 0)
    if _paid(state):
        usd = plans()[state["plan"]]["usd"]
        return round(usd["yearly"] / 12, 2) if state.get("period") == "yearly" else float(usd["monthly"])
    return 0.0


# --- Stripe API ---------------------------------------------------------------------------


def _form(params: dict, prefix: str = "") -> list[tuple[str, str]]:
    """Stripe's form encoding: nested dicts and lists become a[b][0]=c."""
    pairs = []
    for key, value in params.items():
        name = f"{prefix}[{key}]" if prefix else str(key)
        if isinstance(value, dict):
            pairs += _form(value, name)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                pairs += _form(item, f"{name}[{i}]") if isinstance(item, dict) else [(f"{name}[{i}]", str(item))]
        elif value is not None:
            pairs.append((name, str(value).lower() if isinstance(value, bool) else str(value)))
    return pairs


def _stripe(method: str, path: str, params: dict | None = None) -> dict:
    data = urlencode(_form(params)).encode() if params and method == "POST" else None
    url = API + path + (f"?{urlencode(_form(params))}" if params and method == "GET" else "")
    request = Request(url, data=data, method=method, headers={"Authorization": f"Bearer {config.STRIPE_SECRET_KEY}"})
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read())
    except HTTPError as e:
        try:
            message = json.loads(e.read())["error"]["message"]
        except Exception:
            message = str(e)
        raise RuntimeError(f"Stripe : {message}") from None


def checkout(base_url: str, plan_key: str | None = None, period: str = "monthly", pack: bool = False, org: str | None = None) -> str:
    """Address of the Stripe Checkout page for a plan or a credit pack, for the current organisation."""
    org = _org(org)
    installation = _installation()
    with _lock:
        state = _state(org)
    if is_platform(org):
        raise RuntimeError("L'organisation de la plateforme n'a pas d'abonnement.")
    back = f"{base_url}/admin#abonnement"
    tags = {"installation": installation, "organisation": org}
    params: dict = {
        "success_url": back + "?paiement=ok", "cancel_url": back,
        "client_reference_id": f"{installation}:{org}", "metadata": dict(tags),
        "allow_promotion_codes": True,  # e.g. the -50 % Pionniers coupon
        "billing_address_collection": "required", "tax_id_collection": {"enabled": True},
    }
    if state.get("customer"):
        params["customer"] = state["customer"]
        params["customer_update"] = {"address": "auto", "name": "auto"}
    if pack:
        offer = catalog()["pack"]
        if not offer["stripe"]:
            raise RuntimeError("Le pack de crédits n'est pas configuré.")
        params.update(mode="payment", line_items=[{"price": offer["stripe"], "quantity": 1}], invoice_creation={"enabled": True})
        params["metadata"]["credits"] = offer["credits"]
        if not state.get("customer"):
            params["customer_creation"] = "always"
    else:
        if _manual(state):
            raise RuntimeError("Votre formule est gérée directement avec nous : contactez votre interlocuteur pour la changer.")
        if plan_key not in plans() or plan_key == FREE or period not in PERIODS or not price_id(plan_key, period):
            raise RuntimeError("Formule non disponible.")
        if _paid(state):
            raise RuntimeError("Vous avez déjà un abonnement : changez de formule dans « Gérer l'abonnement ».")
        params.update(mode="subscription", line_items=[{"price": price_id(plan_key, period), "quantity": 1}],
                      subscription_data={"metadata": dict(tags)})
    return _stripe("POST", "checkout/sessions", params)["url"]


def portal(base_url: str, org: str | None = None) -> str:
    """Address of Stripe's customer portal: card, invoices, plan change, cancellation."""
    with _lock:
        customer = _state(_org(org)).get("customer")
    if not customer:
        raise RuntimeError("Aucun abonnement ni achat pour l'instant.")
    return _stripe("POST", "billing_portal/sessions", {"customer": customer, "return_url": f"{base_url}/admin#abonnement"})["url"]


# --- webhook ---------------------------------------------------------------------------


def verify(payload: bytes, header: str) -> dict:
    """The event, if the Stripe-Signature header proves it comes from Stripe; ValueError otherwise."""
    if not config.STRIPE_WEBHOOK_SECRET:
        raise ValueError("STRIPE_WEBHOOK_SECRET manquant")
    parts = [part.split("=", 1) for part in header.split(",") if "=" in part]
    timestamp = next((v for k, v in parts if k == "t"), "")
    signatures = [v for k, v in parts if k == "v1"]
    if not timestamp.isdigit() or abs(time.time() - int(timestamp)) > SIGNATURE_TOLERANCE:
        raise ValueError("horodatage invalide")
    expected = hmac.new(config.STRIPE_WEBHOOK_SECRET.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, s) for s in signatures):
        raise ValueError("signature invalide")
    return json.loads(payload)


def _org_exists(org: str | None) -> bool:
    if not org:
        return False
    with connect(system=True) as conn:
        return conn.execute("SELECT 1 FROM organisations WHERE id = ?", (org,)).fetchone() is not None


def _org_of_customer(customer: str | None) -> str | None:
    if not customer:
        return None
    with connect(system=True) as conn:
        rows = conn.execute("SELECT id, settings FROM organisations").fetchall()
    return next((row["id"] for row in rows if (json.loads(row["settings"]).get("billing") or {}).get("customer") == customer), None)


def _target(kind: str, obj: dict, installation: str) -> str | None:
    """The organisation an event concerns, or None when it belongs to another installation (or no one)."""
    if kind == "checkout.session.completed":
        reference = obj.get("client_reference_id") or ""
        if reference == installation:  # created before billing per organisation: the platform's
            return db.default_org()
        mine, _, org = reference.partition(":")
        return org if mine == installation and _org_exists(org) else None
    metadata = obj.get("metadata") or {}
    if metadata.get("installation") == installation:
        if _org_exists(metadata.get("organisation")):
            return metadata["organisation"]
        if not metadata.get("organisation"):
            return _org_of_customer(obj.get("customer")) or db.default_org()
    return _org_of_customer(obj.get("customer"))


def _apply_subscription(state: dict, sub: dict) -> None:
    item = ((sub.get("items") or {}).get("data") or [{}])[0]
    found = _plan_of_price((item.get("price") or {}).get("id", ""))
    if not found:
        return  # a price this installation does not know: leave the plan as it is
    state["plan"], state["period"] = found
    state["status"] = sub.get("status")
    state["subscription"] = sub.get("id")
    state["customer"] = sub.get("customer") or state.get("customer")
    state["cancel_at_period_end"] = bool(sub.get("cancel_at_period_end"))
    # Newer Stripe API versions keep the period on the subscription item.
    state["period_start"] = _iso(item.get("current_period_start") or sub.get("current_period_start"))
    state["period_end"] = _iso(item.get("current_period_end") or sub.get("current_period_end"))


def handle(event: dict) -> None:
    """Apply one Stripe event to the organisation it concerns, once, and only if it is this installation's."""
    kind, obj = event.get("type", ""), (event.get("data") or {}).get("object") or {}
    if not (kind == "checkout.session.completed" or kind.startswith("customer.subscription.") or kind == "invoice.paid"):
        return
    installation = _installation()
    with _lock:
        org = _target(kind, obj, installation)
        if not org:
            return
        state = _settle(org, _state(org))
        seen = state.get("events") or []
        if event.get("id") in seen:
            return
        if kind == "checkout.session.completed":
            state["customer"] = obj.get("customer") or state.get("customer")
            if obj.get("mode") == "payment" and obj.get("payment_status") == "paid":
                state["extra_credits"] = round((state.get("extra_credits") or 0) + int((obj.get("metadata") or {}).get("credits") or 0), 1)
            elif obj.get("mode") == "subscription" and obj.get("subscription"):
                _apply_subscription(state, _stripe("GET", f"subscriptions/{obj['subscription']}"))
        elif kind.startswith("customer.subscription."):
            _apply_subscription(state, obj)
            if kind == "customer.subscription.deleted":
                state["status"] = "canceled"
        elif kind == "invoice.paid":
            if not state.get("subscription"):
                return
            _apply_subscription(state, _stripe("GET", f"subscriptions/{state['subscription']}"))
        state["events"] = (seen + [event.get("id")])[-200:]
        _write(org, state)
