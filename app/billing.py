"""Subscription and credits of this installation, paid with Stripe.

One installation = one organisation = one Stripe customer. An administrator subscribes from
Administration › Abonnement (Stripe Checkout), and manages card, invoices, plan change and
cancellation in Stripe's customer portal. Stripe tells the app what happened through the webhook
(/api/stripe/webhook): the plan, its billing period and the credit packs bought are kept in
data/settings.json ("billing" section).

Credits used are the runs' credits (app/pricing.py) since the start of the billing period, so
nothing is counted twice. Pack credits are used after the plan's and carry over from month to month.

Without STRIPE_SECRET_KEY billing is off and nothing is limited: an installation on a client's own
servers (Entreprise) or ours before launch. One Stripe account serves every installation, so each
installation tags what it creates with its own id and ignores the events of the others.
"""

import calendar
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

from . import config, settings
from .db import connect

# limits: None = unlimited. "parallel" = agents running at the same time.
PLANS = {
    "gratuit": {"label": "Gratuit", "credits": 100, "parallel": 1, "agents": 3, "schedules": 0, "users": 1, "usd": {"monthly": 0, "yearly": 0}},
    "solo": {"label": "Solo", "credits": 3_000, "parallel": 1, "agents": 10, "schedules": 3, "users": 1, "usd": {"monthly": 20, "yearly": 200}},
    "equipe": {"label": "Équipe", "credits": 20_000, "parallel": 3, "agents": None, "schedules": None, "users": 10, "usd": {"monthly": 129, "yearly": 1290}},
    "entreprise": {"label": "Entreprise", "credits": 80_000, "parallel": 10, "agents": None, "schedules": None, "users": None, "usd": {"monthly": 449, "yearly": 449 * 12}},
}
FREE = "gratuit"
PERIODS = ("monthly", "yearly")
PACK_CREDITS = 10_000
PACK_USD = 39
# Stripe statuses that keep the plan: past_due = a payment failed, Stripe is retrying.
ACTIVE = ("active", "trialing", "past_due")

API = "https://api.stripe.com/v1/"
SIGNATURE_TOLERANCE = 300  # seconds: older webhook calls are refused (replays)

_lock = threading.Lock()


class LimitReached(RuntimeError):
    """The plan does not allow this; the message says why and what to do."""


def enabled() -> bool:
    return bool(config.STRIPE_SECRET_KEY)


def price_id(plan: str, period: str) -> str:
    return config.STRIPE_PRICES.get(f"{plan}_{period}", "")


def _plan_of_price(price: str) -> tuple[str, str] | None:
    for key, value in config.STRIPE_PRICES.items():
        if value and value == price and key != "credits":
            plan, period = key.rsplit("_", 1)
            return plan, period
    return None


# --- state ---------------------------------------------------------------------------


def _state() -> dict:
    state = dict(settings.load().get("billing") or {})
    if not state.get("installation"):
        state["installation"] = secrets.token_hex(8)
        settings.update_section("billing", state)
    return state


def _save(state: dict) -> None:
    settings.update_section("billing", state)


def _month_bounds(now: datetime) -> tuple[str, str]:
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    return start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")


def _iso(timestamp: int | None) -> str | None:
    return datetime.fromtimestamp(timestamp).isoformat(timespec="seconds") if timestamp else None


def _paid(state: dict) -> bool:
    return state.get("status") in ACTIVE and state.get("plan") in PLANS and state.get("plan") != FREE


def _period(state: dict) -> tuple[str, str]:
    """Start and end of the current credit period: the Stripe billing period, else the calendar month.

    A yearly plan still gets its credits month by month: the period is the month of the
    subscription year we are in.
    """
    now = datetime.now()
    if _paid(state) and state.get("period_start") and state.get("period_end"):
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


def _used_since(start: str, end: str | None = None) -> float:
    with connect() as conn:
        if end:
            row = conn.execute("SELECT SUM(credits) FROM runs WHERE created_at >= ? AND created_at < ?", (start, end)).fetchone()
        else:
            row = conn.execute("SELECT SUM(credits) FROM runs WHERE created_at >= ?", (start,)).fetchone()
    return round(row[0] or 0, 1)


def _settle(state: dict) -> dict:
    """At a new period, pack credits still left are those the previous period did not need."""
    start, _ = _period(state)
    previous = state.get("settled_period")
    if previous == start:
        return state
    if previous and state.get("extra_credits"):
        overflow = max(0.0, _used_since(previous, start) - (state.get("settled_plan_credits") or 0))
        state["extra_credits"] = round(max(0.0, state["extra_credits"] - overflow), 1)
    state["settled_period"] = start
    state["settled_plan_credits"] = PLANS[current_plan_key(state)]["credits"]
    _save(state)
    return state


def current_plan_key(state: dict | None = None) -> str:
    state = state if state is not None else _state()
    return state["plan"] if _paid(state) else FREE


def plan() -> dict:
    return PLANS[current_plan_key()]


def status() -> dict:
    """What Administration › Abonnement shows."""
    with _lock:
        state = _settle(_state())
    key = current_plan_key(state)
    start, end = _period(state)
    used = _used_since(start)
    included, extra = PLANS[key]["credits"], state.get("extra_credits") or 0
    return {
        "enabled": enabled(),
        "plan": key, "label": PLANS[key]["label"], "period": state.get("period") if key != FREE else None,
        "status": state.get("status"), "cancel_at_period_end": bool(state.get("cancel_at_period_end")),
        "renews_at": state.get("period_end") if key != FREE else None,
        "credits": {"included": included, "extra": extra, "used": used,
                    "remaining": round(max(0.0, included + extra - used), 1), "period_start": start, "period_end": end},
        "limits": {k: PLANS[key][k] for k in ("parallel", "agents", "schedules", "users")},
        "customer": bool(state.get("customer")),
        "plans": [{"key": k, "label": p["label"], "credits": p["credits"], "usd": p["usd"],
                   "limits": {x: p[x] for x in ("parallel", "agents", "schedules", "users")},
                   "periods": [period for period in PERIODS if price_id(k, period)]}
                  for k, p in PLANS.items()],
        "pack": {"credits": PACK_CREDITS, "usd": PACK_USD, "available": bool(config.STRIPE_PRICES.get("credits"))},
    }


# --- limits (all no-ops while billing is off) -------------------------------------------


def check_credits() -> None:
    if not enabled():
        return
    if status()["credits"]["remaining"] <= 0:
        raise LimitReached("Plus de crédits ce mois-ci. Un administrateur peut acheter un pack de crédits ou "
                           "changer de formule dans Administration › Abonnement.")


def parallel_limit() -> int | None:
    return plan()["parallel"] if enabled() else None


def _count(sql: str) -> int:
    with connect() as conn:
        return conn.execute(sql).fetchone()[0]


def check_new_agent() -> None:
    limit = plan()["agents"] if enabled() else None
    if limit is not None and _count("SELECT COUNT(*) FROM agents") >= limit:
        raise LimitReached(f"La formule {plan()['label']} permet {limit} agents enregistrés. "
                           "Supprimez-en un, ou passez à une formule supérieure (Administration › Abonnement).")


def check_new_schedule() -> None:
    limit = plan()["schedules"] if enabled() else None
    if limit is None:
        return
    used = _count("SELECT (SELECT COUNT(*) FROM agents WHERE schedule_enabled = 1) + (SELECT COUNT(*) FROM chains WHERE schedule_enabled = 1)")
    if used >= limit:
        allowed = f"permet {limit} tâches planifiées" if limit else "ne comprend pas les tâches planifiées"
        raise LimitReached(f"La formule {plan()['label']} {allowed}. Passez à une formule supérieure (Administration › Abonnement).")


def check_new_user(count: int) -> None:
    limit = plan()["users"] if enabled() else None
    if limit is not None and count >= limit:
        raise LimitReached(f"La formule {plan()['label']} permet {limit} utilisateur{'s' if limit > 1 else ''}. "
                           "Passez à une formule supérieure (Administration › Abonnement).")


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


def checkout(base_url: str, plan_key: str | None = None, period: str = "monthly", pack: bool = False) -> str:
    """Address of the Stripe Checkout page for a plan or a credit pack."""
    with _lock:
        state = _state()
    back = f"{base_url}/admin#abonnement"
    params: dict = {
        "success_url": back + "?paiement=ok", "cancel_url": back,
        "client_reference_id": state["installation"], "metadata": {"installation": state["installation"]},
        "allow_promotion_codes": True,  # e.g. the -50 % Pionniers coupon
        "billing_address_collection": "required", "tax_id_collection": {"enabled": True},
    }
    if state.get("customer"):
        params["customer"] = state["customer"]
        params["customer_update"] = {"address": "auto", "name": "auto"}
    if pack:
        price = config.STRIPE_PRICES.get("credits")
        if not price:
            raise RuntimeError("Le pack de crédits n'est pas configuré (STRIPE_PRICE_CREDITS).")
        params.update(mode="payment", line_items=[{"price": price, "quantity": 1}], invoice_creation={"enabled": True})
        params["metadata"]["credits"] = PACK_CREDITS
        if not state.get("customer"):
            params["customer_creation"] = "always"
    else:
        if plan_key not in PLANS or plan_key == FREE or period not in PERIODS or not price_id(plan_key, period):
            raise RuntimeError("Formule non disponible.")
        if _paid(state):
            raise RuntimeError("Vous avez déjà un abonnement : changez de formule dans « Gérer l'abonnement ».")
        params.update(mode="subscription", line_items=[{"price": price_id(plan_key, period), "quantity": 1}],
                      subscription_data={"metadata": {"installation": state["installation"]}})
    return _stripe("POST", "checkout/sessions", params)["url"]


def portal(base_url: str) -> str:
    """Address of Stripe's customer portal: card, invoices, plan change, cancellation."""
    with _lock:
        customer = _state().get("customer")
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


def _ours(state: dict, obj: dict) -> bool:
    if (obj.get("metadata") or {}).get("installation") == state["installation"]:
        return True
    return bool(state.get("customer")) and obj.get("customer") == state["customer"]


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
    """Apply one Stripe event to this installation, once, and only if it concerns it."""
    kind, obj = event.get("type", ""), (event.get("data") or {}).get("object") or {}
    with _lock:
        state = _settle(_state())
        seen = state.get("events") or []
        if event.get("id") in seen:
            return
        if kind == "checkout.session.completed":
            if obj.get("client_reference_id") != state["installation"]:
                return
            state["customer"] = obj.get("customer") or state.get("customer")
            if obj.get("mode") == "payment" and obj.get("payment_status") == "paid":
                state["extra_credits"] = round((state.get("extra_credits") or 0) + int((obj.get("metadata") or {}).get("credits") or 0), 1)
            elif obj.get("mode") == "subscription" and obj.get("subscription"):
                _apply_subscription(state, _stripe("GET", f"subscriptions/{obj['subscription']}"))
        elif kind.startswith("customer.subscription."):
            if not _ours(state, obj):
                return
            _apply_subscription(state, obj)
            if kind == "customer.subscription.deleted":
                state["status"] = "canceled"
        elif kind == "invoice.paid":
            if not _ours(state, obj) or not state.get("subscription"):
                return
            _apply_subscription(state, _stripe("GET", f"subscriptions/{state['subscription']}"))
        else:
            return
        state["events"] = (seen + [event.get("id")])[-200:]
        _save(state)
