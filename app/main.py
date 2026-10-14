import asyncio
import base64
import os
import hmac
import ipaddress
import json
import re
from datetime import datetime
from typing import Literal
from urllib.parse import quote, urlparse

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from urllib.parse import unquote
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import (agents, apidoc, assistant, auth, billing, browsers, chains, config, connections, context, files, guide, integrations, mcp,
               netguard, oauth, pricing, schedule, settings, sites, templates, tokens, twofa, usage)
from html import escape
from .llm import create_llm
from .auth import current_admin, current_user
from .runner import TaskManager

STATIC_DIR = config.ROOT / "static"

app = FastAPI(title="AutoCollab", docs_url=None, redoc_url=None, openapi_url=None)
# Shared stylesheet and assets; the pages themselves go through the routes below (login checks).
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
manager = TaskManager()
scheduler = schedule.Scheduler(manager, config.AGENT_MAX_STEPS)
logins = connections.ConnectionManager()
chain_manager = chains.ChainManager(manager)
scheduler.chain_manager = chain_manager


@app.on_event("startup")
async def start_scheduler():
    moved = integrations.migrate()  # tokens encrypted with the old data/secret.key, if any
    if moved:
        print(f"{moved} jeton(s) d'application re-chiffré(s) avec la clé maîtresse.")
    settings.load()  # encrypts AI keys still stored in clear
    await asyncio.to_thread(browsers.close_orphans)  # browsers of runs cut short by the previous stop
    scheduler.start()


# Pages only load the app's own files and Google Fonts. Inline scripts/styles are part of the pages, so
# they stay allowed; everything else (other sites' scripts, plugins, being framed) is refused.
CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline'",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
    "img-src 'self' data: blob:",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "frame-ancestors 'none'",
])
SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Frame-Options": "DENY",                    # no page of the app inside someone else's page (clickjacking)
    "X-Content-Type-Options": "nosniff",          # a downloaded file is never run as a page or a script
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}


@app.exception_handler(billing.LimitReached)
async def limit_reached(request: Request, exc: billing.LimitReached):
    return JSONResponse({"detail": str(exc)}, status_code=402)


@app.middleware("http")
async def revalidate_pages(request: Request, call_next):
    """Security headers on every answer; pages and stylesheet re-checked on every load, so updates show at once."""
    response = await call_next(request)
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    if (config.PUBLIC_URL or "").startswith("https://"):
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    path = request.url.path
    if path in ("/", "/login", "/admin") or path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


class NewTask(BaseModel):
    task: str = Field(min_length=3, max_length=agents.MAX_INSTRUCTIONS)
    headless: bool | None = None
    max_steps: int | None = Field(default=None, ge=1, le=200)
    attachments: list[str] = Field(default=[], max_length=20)  # ids returned by POST /api/uploads
    rerun_of: str | None = None  # relaunch: reuse the files given to that run


class AgentIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    instructions: str = Field(min_length=3, max_length=agents.MAX_INSTRUCTIONS)
    max_steps: int | None = Field(default=None, ge=1, le=200)
    allowed_domains: list[str] = Field(default=[], max_length=agents.MAX_DOMAINS)
    approval_mode: bool = False
    schedule: dict | None = None
    schedule_enabled: bool = False


class AgentChanges(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    instructions: str | None = Field(default=None, min_length=3, max_length=agents.MAX_INSTRUCTIONS)
    max_steps: int | None = Field(default=None, ge=1, le=200)
    allowed_domains: list[str] | None = Field(default=None, max_length=agents.MAX_DOMAINS)
    approval_mode: bool | None = None
    schedule: dict | None = None
    schedule_enabled: bool | None = None


class Approval(BaseModel):
    approved: bool
    comment: str = Field(default="", max_length=1000)


class RunAgent(BaseModel):
    headless: bool | None = None


class Preview(BaseModel):
    instructions: str = Field(max_length=agents.MAX_INSTRUCTIONS)


class Login(BaseModel):
    username: str
    password: str


class OpenBrowser(BaseModel):
    url: str | None = None
    site_id: str | None = None


class SiteIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    url: str = Field(min_length=3, max_length=2000)


class AppConnect(BaseModel):
    kind: str
    read_only: bool = True


class CustomServerIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    url: str = Field(min_length=8, max_length=500)
    token: str = Field(default="", max_length=4000)
    read_only: bool = True


class AppChanges(BaseModel):
    enabled: bool | None = None
    name: str | None = Field(default=None, min_length=1, max_length=40)


class OAuthAppIn(BaseModel):
    client_id: str | None = Field(default=None, max_length=300)
    client_secret: str | None = Field(default=None, max_length=300)
    clear_secret: bool = False


class IntegrationSettings(BaseModel):
    oauth: dict[Literal["google", "slack"], OAuthAppIn] = {}
    enabled: list[str] = []
    allow_custom: bool = False


class BrowserAction(BaseModel):
    type: Literal["click", "type", "key", "scroll", "goto", "back"]
    x: float | None = Field(default=None, ge=0, le=1)
    y: float | None = Field(default=None, ge=0, le=1)
    text: str | None = Field(default=None, max_length=500)
    key: str | None = None
    dy: int | None = Field(default=None, ge=-3000, le=3000)
    url: str | None = Field(default=None, max_length=2000)


class AISettings(BaseModel):
    provider: Literal["anthropic", "mistral", "openai", "deepseek", "nvidia"]
    model: str = Field(min_length=1, max_length=100)
    use_vision: bool = False
    deepseek_endpoint: str = Field(default=settings.DEFAULT_DEEPSEEK_ENDPOINT, max_length=300)
    # Empty or missing = keep the current key; a value replaces it.
    api_keys: dict[Literal["anthropic", "mistral", "openai", "deepseek", "nvidia"], str] = {}
    clear_keys: list[Literal["anthropic", "mistral", "openai", "deepseek", "nvidia"]] = []


class ContextIn(BaseModel):
    instructions: str = ""
    glossary: list[dict] = []
    sites: list[dict] = []


class ContextPreview(BaseModel):
    task: str = Field(default="", max_length=agents.MAX_INSTRUCTIONS)
    allowed_domains: list[str] = Field(default=[], max_length=agents.MAX_DOMAINS)


class TokenIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class ChainIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    steps: list[dict] = Field(min_length=1, max_length=chains.MAX_STEPS_PER_CHAIN)
    schedule: dict | None = None
    schedule_enabled: bool = False


class ChainChanges(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    steps: list[dict] | None = None
    schedule: dict | None = None
    schedule_enabled: bool | None = None


class AssistantMessage(BaseModel):
    message: str = Field(min_length=1, max_length=assistant.MAX_MESSAGE)
    conversation_id: str | None = Field(default=None, max_length=40)
    page: str = Field(default="", max_length=200)   # where the panel was opened, e.g. /#/executions/<id>
    lang: Literal["fr", "en"] = "fr"
    provider: str | None = Field(default=None, max_length=40)   # a model picked in the panel (see /api/assistant/models)
    model: str | None = Field(default=None, max_length=120)


class MeChanges(BaseModel):
    lang: Literal["fr", "en"]


class Organisation(BaseModel):
    name: str = Field(max_length=settings.ORG_NAME_MAX)


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


class NewUser(BaseModel):
    username: str
    name: str = ""
    email: str = ""
    password: str
    admin: bool = False


class UserChanges(BaseModel):
    name: str | None = None
    email: str | None = None
    password: str | None = None
    admin: bool | None = None
    reset_2fa: bool = False   # lost phone: the person sets it up again at next sign-in


def _get_run(task_id: str, user: str, write: bool = True):
    """write=False: anyone in the firm may look at the run; True (stop, approve, rerun): only its owner.

    An unknown task answers 404, and so does someone else's for an action, so ids can't be probed for it.
    """
    run = manager.runs.get(task_id)
    if not run or (write and run.owner != user):
        raise HTTPException(404, "Tâche introuvable")
    return run


@app.get("/")
def index(request: Request):
    if not auth.session_user(request):
        return RedirectResponse("/login")
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/admin")
def admin_page(request: Request):
    username = auth.session_user(request)
    if not username:
        return RedirectResponse("/login")
    if not auth.is_admin(username):
        return RedirectResponse("/")
    return FileResponse(STATIC_DIR / "admin.html")


@app.get("/guide")
def guide_page(request: Request):
    if not auth.session_user(request):
        return RedirectResponse("/login")
    return FileResponse(STATIC_DIR / "guide.html")


def _safe_next(next_: str | None) -> str | None:
    """Only back to an OAuth approval of this app after signing in, never elsewhere."""
    return next_ if next_ and next_.startswith("/oauth/authorize?") else None


@app.get("/login")
def login_page(request: Request, next: str | None = None):
    if auth.session_user(request):
        return RedirectResponse(_safe_next(next) or "/")
    return FileResponse(STATIC_DIR / "login.html")


@app.post("/api/login")
async def login(body: Login, request: Request, response: Response):
    key = f"{request.client.host if request.client else ''}|{body.username.strip().lower()}"
    if auth.is_locked(key):
        raise HTTPException(429, "Trop de tentatives. Réessayez dans 15 minutes.")
    username = await asyncio.to_thread(auth.authenticate, body.username, body.password)
    if not username:
        auth.record_failure(key)
        await asyncio.sleep(1)
        raise HTTPException(401, "Identifiant ou mot de passe incorrect.")
    auth.clear_failures(key)
    if twofa.enabled(username):
        # Password right: now the code from the authenticator app (or a recovery code). No session yet.
        return {"two_factor": True, "ticket": twofa.make_ticket(username)}
    auth.set_session_cookie(response, username)
    return {"username": username, "name": auth.display_name(username), "must_change_password": auth.must_change_password(username),
            "two_factor_setup": twofa.must_enroll(username)}


class SecondFactor(BaseModel):
    ticket: str = Field(max_length=500)
    code: str = Field(min_length=6, max_length=20)


@app.post("/api/login/2fa")
async def login_second_factor(body: SecondFactor, request: Request, response: Response):
    username = twofa.read_ticket(body.ticket)
    if not username:
        raise HTTPException(401, "Session de connexion expirée : saisissez de nouveau votre mot de passe.")
    key = f"{request.client.host if request.client else ''}|{username}|2fa"
    if auth.is_locked(key):
        raise HTTPException(429, "Trop de tentatives. Réessayez dans 15 minutes.")
    used = twofa.verify(username, body.code)
    if not used:
        auth.record_failure(key)
        await asyncio.sleep(1)
        raise HTTPException(401, "Code incorrect ou déjà utilisé.")
    auth.clear_failures(key)
    auth.set_session_cookie(response, username)
    return {"username": username, "name": auth.display_name(username), "must_change_password": auth.must_change_password(username),
            "recovery_used": used == "recovery", "recovery_left": twofa.status(username)["recovery_left"]}


# --- two-factor authentication: one's own setup ---------------------------------------------


class TwoFactorCode(BaseModel):
    code: str = Field(min_length=6, max_length=20)


class TwoFactorOff(BaseModel):
    password: str = Field(max_length=200)
    code: str = Field(min_length=6, max_length=20)


@app.post("/api/me/2fa/setup")
def two_factor_setup(user: str = Depends(current_user)):
    """A secret and its QR code to scan; nothing changes until a first code confirms it."""
    if twofa.enabled(user):
        raise HTTPException(409, "La double authentification est déjà activée.")
    return twofa.start_setup(user)


@app.post("/api/me/2fa/enable")
def two_factor_enable(body: TwoFactorCode, user: str = Depends(current_user)):
    codes = twofa.finish_setup(user, body.code)
    if not codes:
        raise HTTPException(400, "Code incorrect : vérifiez l'heure du téléphone et saisissez le code affiché maintenant.")
    return {"recovery_codes": codes, **twofa.status(user)}


@app.post("/api/me/2fa/disable")
async def two_factor_disable(body: TwoFactorOff, user: str = Depends(current_user)):
    if twofa.required(user):
        raise HTTPException(400, "La double authentification est obligatoire pour votre compte : elle ne peut pas être désactivée.")
    if not await asyncio.to_thread(auth.authenticate, user, body.password) or not twofa.verify(user, body.code):
        raise HTTPException(400, "Mot de passe ou code incorrect.")
    twofa.disable(user)
    return twofa.status(user)


@app.post("/api/me/2fa/recovery")
async def two_factor_new_recovery(body: TwoFactorOff, user: str = Depends(current_user)):
    if not twofa.enabled(user):
        raise HTTPException(400, "La double authentification n'est pas activée.")
    if not await asyncio.to_thread(auth.authenticate, user, body.password) or not twofa.verify(user, body.code):
        raise HTTPException(400, "Mot de passe ou code incorrect.")
    return {"recovery_codes": twofa.new_recovery_codes(user), **twofa.status(user)}


@app.post("/api/logout")
def logout(response: Response):
    response.delete_cookie(auth.COOKIE_NAME)
    return {"ok": True}


@app.get("/api/me")
def me(user: str = Depends(current_user)):
    return {
        "username": user,
        "name": auth.display_name(user),
        "email": auth.load_users().get(user, {}).get("email", ""),
        "admin": auth.is_admin(user),
        "must_change_password": auth.must_change_password(user),
        "lang": auth.load_users().get(user, {}).get("lang"),
        "two_factor": twofa.status(user),  # None until the user picks one
        "organisation": settings.organisation_name(),
    }


@app.get("/api/branding")
def branding():
    """Public on purpose: the login page shows the organisation's name before anyone signs in."""
    return {"organisation": settings.organisation_name()}


@app.patch("/api/me")
def update_me(body: MeChanges, user: str = Depends(current_user)):
    """Preferences of the signed-in user (interface language)."""
    with auth.users_lock:
        users = auth.load_users()
        users[user]["lang"] = body.lang
        auth.save_users(users)
    return {"lang": body.lang}


@app.post("/api/me/password")
async def change_my_password(body: PasswordChange, request: Request, response: Response, user: str = Depends(current_user)):
    key = f"password|{user}"
    if auth.is_locked(key):
        raise HTTPException(429, "Trop de tentatives. Réessayez dans 15 minutes.")
    stored = auth.load_users().get(user, {}).get("password", "")
    if not await asyncio.to_thread(auth.verify_password, body.current_password, stored):
        auth.record_failure(key)
        await asyncio.sleep(1)
        raise HTTPException(400, "Mot de passe actuel incorrect.")
    auth.clear_failures(key)
    if error := auth.password_error(body.new_password):
        raise HTTPException(400, error)
    if body.new_password == body.current_password:
        raise HTTPException(400, "Le nouveau mot de passe doit être différent de l'actuel.")
    with auth.users_lock:
        users = auth.load_users()
        users[user]["password"] = auth.hash_password(body.new_password)
        users[user].pop("must_change_password", None)
        auth.save_users(users)
    # The new password invalidates every session, this one included: hand this browser a fresh one.
    auth.set_session_cookie(response, user)
    return {"ok": True}


# --- administration -------------------------------------------------------


def _user_view(username: str, user: dict, me: str) -> dict:
    return {
        "username": username,
        "name": user.get("name") or username,
        "email": user.get("email", ""),
        "admin": bool(user.get("admin")),
        "temporary_password": bool(user.get("must_change_password")),
        "two_factor": bool((user.get("totp") or {}).get("enabled")),
        "me": username == me,
    }


@app.get("/api/admin/users")
def admin_list_users(admin: str = Depends(current_admin)):
    return [_user_view(u, data, admin) for u, data in sorted(auth.load_users().items())]


@app.post("/api/admin/users", status_code=201)
def admin_create_user(body: NewUser, admin: str = Depends(current_admin)):
    username = auth.normalize_username(body.username)
    if error := auth.username_error(username) or auth.password_error(body.password):
        raise HTTPException(400, error)
    email = auth.normalize_email(body.email)
    with auth.users_lock:
        users = auth.load_users()
        if username in users:
            raise HTTPException(409, f"Le compte « {username} » existe déjà.")
        if error := auth.email_error(email, users):
            raise HTTPException(400, error)
        billing.check_new_user(len(users))
        users[username] = {
            "name": body.name.strip() or username,
            "email": email,
            "password": auth.hash_password(body.password),
            "admin": body.admin,
            # The administrator chose this password: the person replaces it at first login.
            "must_change_password": True,
        }
        auth.save_users(users)
    return _user_view(username, users[username], admin)


@app.patch("/api/admin/users/{username}")
def admin_update_user(username: str, body: UserChanges, admin: str = Depends(current_admin)):
    if body.password is not None and (error := auth.password_error(body.password)):
        raise HTTPException(400, error)
    # An admin can't demote themselves: there would be nobody left to undo it.
    if username == admin and body.admin is False:
        raise HTTPException(400, "Vous ne pouvez pas retirer votre propre rôle administrateur.")
    with auth.users_lock:
        users = auth.load_users()
        user = users.get(username)
        if not user:
            raise HTTPException(404, "Compte introuvable.")
        if body.name is not None:
            user["name"] = body.name.strip() or username
        if body.email is not None:
            email = auth.normalize_email(body.email)
            if error := auth.email_error(email, users, exclude=username):
                raise HTTPException(400, error)
            user["email"] = email
        if body.password is not None:
            user["password"] = auth.hash_password(body.password)
            if username != admin:
                user["must_change_password"] = True
        if body.admin is not None:
            user["admin"] = body.admin
        auth.save_users(users)
    if body.reset_2fa:
        twofa.disable(username)
        user = auth.load_users()[username]
    return _user_view(username, user, admin)


def _settings_changes(body: AISettings) -> dict:
    if not body.deepseek_endpoint.startswith("https://"):
        raise HTTPException(400, "L'adresse DeepSeek doit commencer par https://")
    keys: dict = {name: value for name, value in body.api_keys.items() if value and value.strip()}
    for name in body.clear_keys:
        keys[name] = None
    return {
        "provider": body.provider,
        "model": body.model.strip(),
        "use_vision": body.use_vision,
        "deepseek_endpoint": body.deepseek_endpoint.strip(),
        "api_keys": keys,
    }


@app.get("/api/admin/security")
def admin_security(admin: str = Depends(current_admin)):
    """Where the secrets' master key comes from (never the key itself), and other deployment checks."""
    from . import vault

    return {"master_key": vault.source(), "cookie_secure": config.COOKIE_SECURE,
            "https": (config.PUBLIC_URL or "").startswith("https://"), "os": os.name, "require_2fa": twofa.policy()}


class SecurityIn(BaseModel):
    require_2fa: Literal["none", "admins", "all"]


@app.put("/api/admin/security")
def admin_save_security(body: SecurityIn, admin: str = Depends(current_admin)):
    if body.require_2fa != "none" and not twofa.enabled(admin):
        raise HTTPException(400, "Activez d'abord la double authentification sur votre propre compte (Mon compte), "
                                 "pour ne pas vous bloquer vous-même.")
    twofa.set_policy(body.require_2fa)
    return admin_security(admin)


@app.get("/api/admin/settings")
def admin_get_settings(admin: str = Depends(current_admin)):
    return settings.public_view()


@app.get("/api/admin/usage")
def admin_usage(month: str | None = None, admin: str = Depends(current_admin)):
    """Tokens billed by the AI providers, their cost and the credits they make, for one month."""
    month = month or datetime.now().strftime("%Y-%m")
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise HTTPException(400, "Mois au format AAAA-MM, par exemple 2026-10.")
    return usage.monthly_report(month)


@app.get("/api/admin/pricing")
def admin_pricing(admin: str = Depends(current_admin)):
    """The price table behind credits, with the typical credits per agent step of each model."""
    return {
        "credit_value_usd": pricing.CREDIT_VALUE_USD,
        "min_credits_per_step": pricing.MIN_CREDITS_PER_STEP,
        "models": [{"provider": provider, "model": model, **price, "credits_per_step": pricing.estimate_per_step(provider, model)}
                   for provider, models in pricing.PRICES.items() for model, price in models.items()],
    }


class Checkout(BaseModel):
    plan: str | None = None
    period: Literal["monthly", "yearly"] = "monthly"
    pack: bool = False


@app.get("/api/admin/billing")
def admin_billing(admin: str = Depends(current_admin)):
    return billing.status()


@app.post("/api/admin/billing/checkout")
async def admin_billing_checkout(body: Checkout, request: Request, admin: str = Depends(current_admin)):
    """Address of the Stripe page where the administrator pays a plan or a credit pack."""
    if not billing.enabled():
        raise HTTPException(400, "La facturation n'est pas activée sur cette installation.")
    try:
        url = await asyncio.to_thread(billing.checkout, config.PUBLIC_URL or _base_url(request), body.plan, body.period, body.pack)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    return {"url": url}


@app.post("/api/admin/billing/portal")
async def admin_billing_portal(request: Request, admin: str = Depends(current_admin)):
    """Address of Stripe's customer portal (card, invoices, plan change, cancellation)."""
    if not billing.enabled():
        raise HTTPException(400, "La facturation n'est pas activée sur cette installation.")
    try:
        url = await asyncio.to_thread(billing.portal, config.PUBLIC_URL or _base_url(request))
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    return {"url": url}


@app.post("/api/stripe/webhook", include_in_schema=False)
async def stripe_webhook(request: Request):
    """Stripe tells the app about payments and subscription changes; the signature proves it is Stripe."""
    if not billing.enabled():
        raise HTTPException(404)
    try:
        event = billing.verify(await request.body(), request.headers.get("stripe-signature", ""))
    except ValueError:
        raise HTTPException(400, "Signature invalide")
    try:
        await asyncio.to_thread(billing.handle, event)
    except RuntimeError as e:  # Stripe could not be reached: answering an error makes Stripe send it again
        raise HTTPException(502, str(e))
    return {"received": True}


@app.put("/api/admin/organisation")
def admin_save_organisation(body: Organisation, admin: str = Depends(current_admin)):
    settings.set_organisation_name(body.name)
    return {"organisation": settings.organisation_name()}


@app.put("/api/admin/settings")
def admin_save_settings(body: AISettings, admin: str = Depends(current_admin)):
    changes = _settings_changes(body)
    current = settings.load()["api_keys"]
    chosen = body.provider
    has_key = (changes["api_keys"].get(chosen) if chosen in changes["api_keys"] else current.get(chosen))
    if not has_key:
        raise HTTPException(400, f"Saisissez la clé d'API {settings.PROVIDERS[chosen]['label']} : c'est le fournisseur choisi.")
    settings.update(changes)
    return settings.public_view()


@app.post("/api/admin/settings/test")
async def admin_test_settings(body: AISettings, admin: str = Depends(current_admin)):
    """Send one tiny message with the settings as typed (saved or not), to check key and model."""
    changes = _settings_changes(body)
    overrides = {**changes, "api_keys": {k: v for k, v in changes["api_keys"].items() if v}}
    saved_key = settings.load()["api_keys"].get(body.provider, "")
    tested_key = overrides["api_keys"].get(body.provider) or ("" if body.provider in body.clear_keys else saved_key)

    def remember(ok: bool, message: str) -> None:
        settings.record_test(body.provider, changes["model"], settings.key_hint(tested_key), ok, message)

    try:
        llm = create_llm(overrides)
        reply = await asyncio.wait_for(llm.ainvoke("Réponds uniquement par le mot OK."), timeout=45)
    except asyncio.TimeoutError:
        remember(False, "Pas de réponse du fournisseur après 45 s.")
        raise HTTPException(400, "Pas de réponse du fournisseur après 45 s.")
    except ValueError as e:  # no key for this provider
        remember(False, str(e))
        raise HTTPException(400, str(e))
    except Exception as e:
        text = str(e).splitlines()[0] if str(e) else type(e).__name__
        lowered = text.lower()
        if "401" in text or "authentication" in lowered or "api key" in lowered or "api-key" in lowered:
            hint = "Clé d'API refusée par le fournisseur : vérifiez-la."
        elif "404" in text or "not_found" in lowered or "model" in lowered and "not" in lowered:
            hint = "Modèle introuvable chez ce fournisseur : vérifiez son nom (bouton « Modèle conseillé »)."
        elif "402" in text or "balance" in lowered or "credit" in lowered or "quota" in lowered:
            hint = "Crédit insuffisant sur le compte du fournisseur."
        else:
            hint = "Échec de la connexion."
        remember(False, hint)
        raise HTTPException(400, f"{hint} Détail : {text[:250]}")
    remember(True, "Connexion réussie.")
    return {"ok": True, "reply": str(getattr(reply, "content", reply))[:100]}


@app.delete("/api/admin/users/{username}")
def admin_delete_user(username: str, admin: str = Depends(current_admin)):
    if username == admin:
        raise HTTPException(400, "Vous ne pouvez pas supprimer votre propre compte.")
    with auth.users_lock:
        users = auth.load_users()
        if username not in users:
            raise HTTPException(404, "Compte introuvable.")
        del users[username]
        auth.save_users(users)
    tokens.revoke_all(username)
    oauth.revoke_all(username)
    return {"ok": True}


@app.get("/api/config")
def get_config(user: str = Depends(current_user)):
    return {
        "provider": settings.load()["provider"],
        "model": settings.load()["model"],
        "vision": bool(settings.load()["use_vision"]),
        "headless": config.BROWSER_HEADLESS,
        "max_steps": config.AGENT_MAX_STEPS,
        "approval_timeout": config.APPROVAL_TIMEOUT_MINUTES,
        "browser": browsers.browser_label(),
    }


# --- agents -------------------------------------------------------------------


# --- firm-wide view: everyone sees everyone's agents, chains and runs; only the owner acts on them

Scope = Literal["mine", "all"]


def _names() -> dict[str, str]:
    return {u: (v.get("name") or u) for u, v in auth.load_users().items()}


def _owned(item: dict, user: str, names: dict[str, str] | None = None) -> dict:
    owner = item.get("owner")
    return {**item, "owner": owner, "owner_name": (names or _names()).get(owner, owner), "mine": owner == user}


def _chains_by_agent(chain_list: list[dict]) -> dict[str, list[dict]]:
    """For each agent, the chains it is a step of: shown on its card."""
    out: dict[str, list[dict]] = {}
    for c in chain_list:
        for i, step in enumerate(c["steps"]):
            out.setdefault(step["agent_id"], []).append({
                "id": c["id"], "name": c["name"], "step": i + 1, "total": len(c["steps"]),
                "schedule_label": schedule.describe(c["schedule"]) if c["schedule"] else None,
                "schedule_enabled": bool(c["schedule_enabled"]), "next_run_at": c.get("next_run_at")})
    return out


def _agent_view(agent: dict, in_chains: dict[str, list[dict]] | None = None) -> dict:
    runs = [r for r in manager.runs.values() if r.agent_id == agent["id"]]
    last = max(runs, key=lambda r: r.created_at, default=None)
    keys = ("id", "name", "instructions", "max_steps", "created_at", "updated_at", "allowed_domains",
            "approval_mode", "schedule", "schedule_enabled", "next_run_at", "created_via", "updated_via")
    view = {k: agent.get(k) for k in keys}
    view["schedule_label"] = schedule.describe(agent["schedule"])
    view["attachments"] = [f.name for f in files.agent_files(agent["id"])]
    view["last_run"] = {"id": last.id, "status": last.status, "created_at": last.created_at} if last else None
    view["run_count"] = len(runs)
    view["owner"] = agent.get("owner")
    if in_chains is None:
        in_chains = _chains_by_agent(chains.list_for(agent["owner"]))
    view["chains"] = in_chains.get(agent["id"], [])
    return view


def _get_agent(agent_id: str, user: str) -> dict:
    agent = agents.get(agent_id, user)
    if not agent:
        raise HTTPException(404, "Agent introuvable")
    return agent


def _clean_agent_fields(changes: dict) -> dict:
    """Validate and normalize the guardrail and schedule fields; raises 400 with a French message."""
    for key in ("name", "instructions"):
        if isinstance(changes.get(key), str):
            changes[key] = changes[key].strip()
    if changes.get("allowed_domains") is not None:
        domains, error = agents.normalize_domains(changes["allowed_domains"])
        if error:
            raise HTTPException(400, error)
        changes["allowed_domains"] = domains
    if changes.get("schedule"):
        if error := schedule.validate(changes["schedule"]):
            raise HTTPException(400, error)
        changes["schedule"] = schedule.normalize(changes["schedule"])
    return changes


@app.get("/api/variables")
def list_variables(user: str = Depends(current_user)):
    return agents.VARIABLES


@app.get("/api/templates")
def list_templates(user: str = Depends(current_user)):
    return templates.catalog()


@app.post("/api/variables/preview")
def preview_variables(body: Preview, user: str = Depends(current_user)):
    return {"text": agents.render(body.instructions)}


@app.get("/api/agents")
def list_agents(scope: Scope = "mine", user: str = Depends(current_user)):
    names = _names()
    in_chains = _chains_by_agent(chains.list_all() if scope == "all" else chains.list_for(user))
    return [_owned(_agent_view(a, in_chains), user, names) for a in (agents.list_all() if scope == "all" else agents.list_for(user))]


@app.post("/api/agents", status_code=201)
def create_agent(body: AgentIn, user: str = Depends(current_user)):
    fields = _clean_agent_fields(body.model_dump())
    agent = agents.create(user, **fields)
    return _agent_view(agent)


@app.patch("/api/agents/{agent_id}")
def update_agent(agent_id: str, body: AgentChanges, user: str = Depends(current_user)):
    _get_agent(agent_id, user)
    changes = _clean_agent_fields(body.model_dump(exclude_unset=True))
    return _agent_view(agents.update(agent_id, user, changes))


@app.delete("/api/agents/{agent_id}")
def delete_agent(agent_id: str, user: str = Depends(current_user)):
    # Past runs keep their copy of the agent's name, so the history stays intact.
    if not agents.delete(agent_id, user):
        raise HTTPException(404, "Agent introuvable")
    files.delete_agent_files(agent_id)
    return {"ok": True}


@app.post("/api/agents/{agent_id}/run")
async def run_agent(agent_id: str, body: RunAgent, user: str = Depends(current_user)):
    agent = _get_agent(agent_id, user)
    try:
        run = manager.start(
            owner=user,
            task=agents.render(agent["instructions"]),
            headless=config.BROWSER_HEADLESS if body.headless is None else body.headless,
            max_steps=agent["max_steps"] or config.AGENT_MAX_STEPS,
            agent_id=agent["id"],
            agent_name=agent["name"],
            options=agents.run_options(agent),
        )
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return run.summary()


# --- my connections (the user's own browser profile) ---------------------------------


def _web_url(url: str | None) -> str | None:
    if url is None:
        return None
    url = url.strip()
    if url and "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    try:
        parsed.port  # raises on a malformed port, e.g. "https://javascript:alert(1)"
    except ValueError:
        host = ""
    if parsed.scheme not in ("https", "http") or "." not in host:
        raise HTTPException(400, "Adresse invalide : saisissez l'adresse d'un site web, par exemple https://www.exemple.fr")
    try:
        internal = not ipaddress.ip_address(host).is_global
    except ValueError:
        internal = host.endswith((".local", ".internal", ".localhost"))
    if internal and not netguard.allowed_host(host):
        # The browser runs on the server: keep it away from the server's own network.
        raise HTTPException(400, "Adresse refusée : les adresses internes ne sont pas accessibles depuis le navigateur des agents.")
    return url


@app.get("/api/connections")
def connections_status(user: str = Depends(current_user)):
    session = logins.get(user)
    return {
        "open": session is not None,
        "browser": browsers.browser_label(),
        "busy": session is None and browsers.owner_lock(user).locked(),
    }


@app.get("/api/connections/sites")
def list_sites(user: str = Depends(current_user)):
    return {"sites": sites.list_for(user), "suggestions": sites.SUGGESTIONS}


@app.post("/api/connections/sites", status_code=201)
def add_site(body: SiteIn, user: str = Depends(current_user)):
    try:
        return sites.create(user, body.name.strip(), _web_url(body.url))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.patch("/api/connections/sites/{site_id}")
def edit_site(site_id: str, body: SiteIn, user: str = Depends(current_user)):
    if not sites.get(site_id, user):
        raise HTTPException(404, "Connexion introuvable")
    return sites.update(site_id, user, body.name.strip(), _web_url(body.url))


@app.delete("/api/connections/sites/{site_id}")
def remove_site(site_id: str, user: str = Depends(current_user)):
    if not sites.delete(site_id, user):
        raise HTTPException(404, "Connexion introuvable")
    return {"ok": True}


@app.post("/api/connections/open")
async def connections_open(body: OpenBrowser, user: str = Depends(current_user)):
    url = _web_url(body.url)
    if body.site_id:
        site = sites.get(body.site_id, user)
        if not site:
            raise HTTPException(404, "Connexion introuvable")
        url = site["url"]
    try:
        await logins.open(user, url, body.site_id)
        if body.site_id:
            sites.mark_opened(body.site_id, user)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    except Exception as e:
        raise HTTPException(502, f"Le navigateur n'a pas pu s'ouvrir : {str(e)[:200]}")
    return {"open": True}


@app.get("/api/connections/screen")
async def connections_screen(user: str = Depends(current_user)):
    session = logins.get(user)
    if not session:
        return Response(status_code=204)
    image, url, title = await session.screenshot()
    headers = {"Cache-Control": "no-store", "X-Page-Url": quote(url, safe=""), "X-Page-Title": quote(title, safe="")}
    return Response(image, media_type="image/jpeg", headers=headers)


@app.post("/api/connections/action")
async def connections_action(body: BrowserAction, user: str = Depends(current_user)):
    session = logins.get(user)
    if not session:
        raise HTTPException(409, "Le navigateur est fermé. Rouvrez-le.")
    action = body.model_dump()
    if body.type == "click" and (body.x is None or body.y is None):
        raise HTTPException(400, "Position du clic manquante.")
    if body.type == "type" and not body.text:
        raise HTTPException(400, "Texte manquant.")
    if body.type == "key" and body.key not in connections.KEYS:
        raise HTTPException(400, "Touche non prise en charge.")
    if body.type == "scroll" and body.dy is None:
        raise HTTPException(400, "Défilement manquant.")
    if body.type == "goto":
        action["url"] = _web_url(body.url)
    try:
        await session.act(action)
    except Exception as e:
        raise HTTPException(400, f"Action impossible : {str(e).splitlines()[0][:200]}")
    return {"ok": True}


@app.post("/api/connections/close")
async def connections_close(user: str = Depends(current_user)):
    await logins.close(user)
    return {"open": False}


@app.post("/api/connections/reset")
async def connections_reset(user: str = Depends(current_user)):
    if logins.get(user) or browsers.owner_lock(user).locked():
        raise HTTPException(409, "Fermez le navigateur et attendez la fin de vos exécutions avant de le réinitialiser.")
    await asyncio.to_thread(browsers.reset_profile, user)
    return {"ok": True}


# --- applications connected through MCP (Gmail, Drive, Slack...) -----------------------


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _offered(base_url: str) -> list[dict]:
    """Every application, with why it can't be connected yet: not offered, or OAuth app missing."""
    cfg = integrations.admin_config()
    return [{**app_, "offered": app_["kind"] in cfg["enabled"], "configured": integrations.configured(app_["provider"]),
             "available": app_["kind"] in cfg["enabled"] and integrations.configured(app_["provider"])}
            for app_ in integrations.catalog_view()]


@app.get("/api/integrations")
def list_integrations(request: Request, user: str = Depends(current_user)):
    cfg = integrations.admin_config()
    return {"catalog": _offered(_base_url(request)), "connections": integrations.list_for(user),
            "allow_custom": cfg["allow_custom"]}


@app.post("/api/integrations/connect")
def connect_integration(body: AppConnect, request: Request, user: str = Depends(current_user)):
    """Start the sign-in: the page then sends the user to Google or Slack."""
    if body.kind not in integrations.CATALOG:
        raise HTTPException(404, "Application inconnue")
    try:
        return {"url": integrations.authorize_url(user, body.kind, body.read_only, _base_url(request))}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get(integrations.CALLBACK_PATH, include_in_schema=False)
async def integration_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    user = auth.session_user(request)
    if not user:
        return RedirectResponse("/login")
    if error or not code:
        message = "Connexion annulée." if error in ("access_denied", "") else f"Connexion refusée : {error}"
        return RedirectResponse("/?app_error=" + quote(message) + "#/connexions/applications")
    try:
        connection = await integrations.finish_sign_in(user, state, code)
    except ValueError as e:
        return RedirectResponse("/?app_error=" + quote(str(e)[:300]) + "#/connexions/applications")
    except Exception as e:
        return RedirectResponse("/?app_error=" + quote(f"Connexion impossible : {str(e)[:200]}") + "#/connexions/applications")
    return RedirectResponse("/?app_ok=" + quote(connection["name"]) + "#/connexions/applications")


def _mcp_url(url: str) -> str:
    url = _web_url(url)
    if not url.startswith("https://"):
        raise HTTPException(400, "Le serveur MCP doit avoir une adresse en https://")
    return url


@app.post("/api/integrations/custom", status_code=201)
async def add_custom_integration(body: CustomServerIn, user: str = Depends(current_user)):
    try:
        return await integrations.add_custom(user, body.name.strip(), _mcp_url(body.url), body.token.strip(), body.read_only)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.patch("/api/integrations/{integration_id}")
def edit_integration(integration_id: str, body: AppChanges, user: str = Depends(current_user)):
    if not integrations.get(integration_id, user):
        raise HTTPException(404, "Application introuvable")
    return integrations.update(integration_id, user, body.enabled, body.name.strip() if body.name else None)


@app.post("/api/integrations/{integration_id}/test")
async def test_integration(integration_id: str, user: str = Depends(current_user)):
    try:
        return await integrations.check(integration_id, user)
    except LookupError:
        raise HTTPException(404, "Application introuvable")
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/integrations/{integration_id}")
async def remove_integration(integration_id: str, user: str = Depends(current_user)):
    if not await integrations.delete(integration_id, user):
        raise HTTPException(404, "Application introuvable")
    return {"ok": True}


@app.get("/api/admin/integrations")
def admin_get_integrations(request: Request, admin: str = Depends(current_admin)):
    return integrations.admin_view(_base_url(request))


@app.put("/api/admin/integrations")
def admin_save_integrations(body: IntegrationSettings, request: Request, admin: str = Depends(current_admin)):
    unknown = [k for k in body.enabled if k not in integrations.CATALOG]
    if unknown:
        raise HTTPException(400, f"Application inconnue : {', '.join(unknown)}")
    integrations.save_admin_config({
        "oauth": {p: v.model_dump() for p, v in body.oauth.items()},
        "enabled": body.enabled,
        "allow_custom": body.allow_custom,
    })
    return integrations.admin_view(_base_url(request))


# --- context added to agents' instructions ----------------------------------------------


@app.get("/api/context")
def get_context(user: str = Depends(current_user)):
    return {
        "cabinet": context.load("cabinet"),
        "personal": context.load(context.scope_of(user)),
        "can_edit_cabinet": auth.is_admin(user),
        "limits": context.LIMITS,
    }


def _save_context(scope: str, body: ContextIn, user: str) -> dict:
    data, error = context.clean(body.model_dump())
    if error:
        raise HTTPException(400, error)
    context.save(scope, data, user)
    return context.load(scope)


@app.put("/api/context/cabinet")
def save_cabinet_context(body: ContextIn, admin: str = Depends(current_admin)):
    return _save_context("cabinet", body, admin)


@app.put("/api/context/personal")
def save_personal_context(body: ContextIn, user: str = Depends(current_user)):
    return _save_context(context.scope_of(user), body, user)


@app.post("/api/context/preview")
def preview_context(body: ContextPreview, user: str = Depends(current_user)):
    task = agents.render(body.task)
    text = context.build(user, task, body.allowed_domains) or ""
    return {"text": text, "chars": len(text), "tokens": round(len(text) / 4),
            "summary": context.summary(user, task, body.allowed_domains)}


# --- developers: API keys, OpenAPI, MCP ---------------------------------------------------


@app.get("/api/tokens")
def list_api_tokens(user: str = Depends(current_user)):
    return tokens.list_for(user)


@app.post("/api/tokens", status_code=201)
def create_api_token(body: TokenIn, user: str = Depends(current_user)):
    try:
        view, token = tokens.create(user, body.name.strip())
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {**view, "token": token}  # the only time the full key is ever shown


@app.delete("/api/tokens/{token_id}")
def revoke_api_token(token_id: str, user: str = Depends(current_user)):
    if not tokens.revoke(token_id, user):
        raise HTTPException(404, "Clé introuvable")
    return {"ok": True}


@app.get("/api/docs")
def api_docs(user: str = Depends(current_user)):
    return apidoc.reference(app)


@app.get("/api/openapi.json", include_in_schema=False)
def openapi_spec(user: str = Depends(current_user)):
    return app.openapi()


@app.get("/mcp", include_in_schema=False)
def mcp_get():
    # No server-to-client stream: this server answers each POST directly.
    return Response(status_code=405, headers={"Allow": "POST"})


@app.post("/mcp", include_in_schema=False)
async def mcp_endpoint(request: Request):
    if auth.rate_limited(f"mcp|{_client_ip(request)}", 300, 60):
        return JSONResponse(mcp._error(None, -32000, "Trop de requêtes : réessayez dans un moment."), status_code=429)
    origin = request.headers.get("origin")
    if origin and urlparse(origin).netloc != request.headers.get("host"):
        return JSONResponse(mcp._error(None, -32600, "Origine refusée"), status_code=403)
    header = request.headers.get("authorization", "")
    bearer = header[7:].strip() if header.lower().startswith("bearer ") else ""
    # OAuth access tokens are only valid here; API keys and the session cookie work everywhere.
    user = oauth.owner_of(bearer) if bearer.startswith(oauth.ACCESS_PREFIX) else auth.session_user(request)
    if not user:
        metadata = oauth.base_url(str(request.base_url)) + "/.well-known/oauth-protected-resource"
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32001, "message": "Clé d'API ou jeton manquant ou invalide"}},
                            status_code=401, headers={"WWW-Authenticate": f'Bearer realm="autocollab", resource_metadata="{metadata}"'})
    if auth.must_change_password(user):
        return JSONResponse(mcp._error(None, -32001, "Choisissez d'abord votre mot de passe dans l'application"), status_code=403)
    if twofa.must_enroll(user):
        return JSONResponse(mcp._error(None, -32001, "Activez d'abord la double authentification dans l'application"), status_code=403)
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse(mcp._error(None, -32700, "JSON invalide"), status_code=400)
    messages = payload if isinstance(payload, list) else [payload]
    base = oauth.base_url(str(request.base_url))
    docs = lambda topic: guide.topic(topic, base, app)  # noqa: E731
    answers = [a for a in (mcp.handle(m, user, manager, chain_manager, docs) for m in messages) if a is not None]
    if not answers:
        return Response(status_code=202)  # only notifications
    return JSONResponse(answers if isinstance(payload, list) else answers[0])


# --- documentation for AI assistants (llms.txt) --------------------------------------------


@app.get("/llms.txt", include_in_schema=False)
def llms_txt(request: Request):
    """Public on purpose: describes how to use the app, holds no data and no key."""
    return Response(guide.llms_txt(oauth.base_url(str(request.base_url)), app), media_type="text/markdown; charset=utf-8",
                    headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=300"})


@app.get("/llms-full.txt", include_in_schema=False)
def llms_full_txt(request: Request):
    return Response(guide.llms_full_txt(oauth.base_url(str(request.base_url)), app), media_type="text/markdown; charset=utf-8",
                    headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=300"})


# --- OAuth for MCP clients (see app/oauth.py) ---------------------------------------------

_CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
         "Access-Control-Allow-Headers": "Authorization, Content-Type, MCP-Protocol-Version"}


def _oauth_json(data: dict, status: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status, headers={**_CORS, "Cache-Control": "no-store"})


def _oauth_error(e: oauth.OAuthError) -> JSONResponse:
    return _oauth_json({"error": e.code, "error_description": e.description}, e.status)


@app.options("/.well-known/{path:path}", include_in_schema=False)
@app.options("/oauth/{path:path}", include_in_schema=False)
def oauth_preflight(path: str):
    return Response(status_code=204, headers=_CORS)


@app.get("/.well-known/oauth-protected-resource", include_in_schema=False)
@app.get("/.well-known/oauth-protected-resource/mcp", include_in_schema=False)
def oauth_resource_metadata(request: Request):
    return _oauth_json(oauth.resource_metadata(oauth.base_url(str(request.base_url))))


@app.get("/.well-known/oauth-authorization-server", include_in_schema=False)
@app.get("/.well-known/oauth-authorization-server/mcp", include_in_schema=False)
@app.get("/.well-known/openid-configuration", include_in_schema=False)
def oauth_server_metadata(request: Request):
    return _oauth_json(oauth.server_metadata(oauth.base_url(str(request.base_url))))


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _too_many(request: Request, bucket: str, limit: int, window: int) -> JSONResponse | None:
    if auth.rate_limited(f"{bucket}|{_client_ip(request)}", limit, window):
        return _oauth_json({"error": "slow_down", "error_description": "Trop de requêtes : réessayez dans un moment."}, 429)
    return None


@app.post("/oauth/register", include_in_schema=False)
async def oauth_register(request: Request):
    if limited := _too_many(request, "oauth-register", 20, 3600):
        return limited
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError
    except ValueError:
        return _oauth_json({"error": "invalid_client_metadata", "error_description": "JSON attendu."}, 400)
    try:
        return _oauth_json(oauth.register(body), 201)
    except oauth.OAuthError as e:
        return _oauth_error(e)


def _consent_page(title: str, body: str, status: int = 200) -> Response:
    return Response(f"""<!doctype html><html lang="fr" translate="no"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="google" content="notranslate">
<title>{escape(title)} · AutoCollab</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Geist:wght@400..700&display=swap">
<link rel="stylesheet" href="/static/app.css"><script src="/static/i18n.js"></script>
<style>
  body {{ min-height: 100vh; display: grid; place-items: center; padding: 24px 16px; }}
  .consent {{ width: 100%; max-width: 460px; display: flex; flex-direction: column; gap: 18px; }}
  .consent h1 {{ margin: 0; font-size: 21px; letter-spacing: -.02em; }}
  .consent ul {{ margin: 0; padding-left: 20px; display: flex; flex-direction: column; gap: 6px; color: var(--ink-2); font-size: 14px; }}
  .who {{ display: flex; align-items: center; gap: 10px; font-size: 13.5px; color: var(--muted); }}
  .host {{ font-family: var(--mono); font-size: 13px; background: var(--sunken); border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; overflow-wrap: anywhere; }}
  .consent form {{ display: flex; gap: 8px; }}
  .consent form .btn {{ flex: 1; }}
</style></head><body><main class="card consent">
<a class="brand" href="/" style="color: var(--ink); padding: 0"><span class="brand-mark"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 19V5a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v14l-4-2-4 2-4-2z"/><path d="M8 8h8M8 12h5"/></svg></span><span class="brand-name"><strong>AutoCollab</strong></span></a>
{body}</main></body></html>""", status_code=status, media_type="text/html", headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY"})


_AUTHORIZE_FIELDS = ("client_id", "redirect_uri", "response_type", "code_challenge", "code_challenge_method", "state", "scope", "resource")


def _redirect_back(redirect_uri: str, **params) -> RedirectResponse:
    from urllib.parse import urlencode
    sep = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(redirect_uri + sep + urlencode({k: v for k, v in params.items() if v}), status_code=303)


@app.get("/oauth/authorize", include_in_schema=False)
def oauth_authorize(request: Request):
    params = {k: request.query_params.get(k, "") for k in _AUTHORIZE_FIELDS}
    base = oauth.base_url(str(request.base_url))
    try:
        client = oauth.check_request(params, base)
    except oauth.OAuthError as e:
        return _consent_page("Connexion impossible", f"<h1>Connexion impossible</h1><p class=\"form-err\">{escape(e.description)}</p>", 400)
    user = auth.read_token(request.cookies.get(auth.COOKIE_NAME))
    if not user:
        return RedirectResponse("/login?next=" + quote(str(request.url.path) + "?" + str(request.url.query), safe=""))
    if auth.must_change_password(user) or twofa.must_enroll(user):
        return RedirectResponse("/")
    account = auth.load_users().get(user, {})
    host = urlparse(client["redirect_uri"]).hostname or client["redirect_uri"]
    hidden = "".join(f'<input type="hidden" name="{k}" value="{escape(params[k])}">' for k in _AUTHORIZE_FIELDS)
    hidden += f'<input type="hidden" name="redirect_uri_checked" value="{escape(client["redirect_uri"])}">'
    hidden += f'<input type="hidden" name="consent" value="{oauth.consent_token(user, {**params, "redirect_uri": client["redirect_uri"]})}">'
    body = f"""<h1>Autoriser « {escape(client['name'])} » ?</h1>
<div class="who"><span class="avatar" style="background: var(--accent-soft); color: var(--accent)">{escape((account.get('name') or user)[:1].upper())}</span>
<span>Connecté en tant que <strong style="color: var(--ink)">{escape(account.get('name') or user)}</strong> ({escape(user)})</span></div>
<div><p style="margin: 0 0 8px; font-weight: 600">Cette application pourra, en votre nom :</p>
<ul><li>voir vos agents, chaînes et exécutions ;</li><li>créer et modifier des agents et des chaînes ;</li>
<li>lancer des agents, des tâches et des chaînes ;</li><li>répondre à une demande de validation, sur votre instruction.</li></ul>
<p class="hint" style="margin: 8px 0 0">Elle ne pourra rien supprimer. Vous pourrez retirer cet accès à tout moment dans Développeurs.</p></div>
<div><p class="hint" style="margin: 0 0 6px">Vous serez ensuite renvoyé vers :</p><div class="host">{escape(host)}</div></div>
<form method="post" action="/oauth/authorize">{hidden}
<button class="btn btn-outline" name="decision" value="deny">Refuser</button>
<button class="btn btn-primary" name="decision" value="allow">Autoriser</button></form>"""
    return _consent_page(f"Autoriser {client['name']}", body)


@app.post("/oauth/authorize", include_in_schema=False)
async def oauth_authorize_answer(request: Request):
    origin = request.headers.get("origin")
    if origin and urlparse(origin).netloc != request.headers.get("host"):
        return _consent_page("Connexion impossible", "<h1>Connexion impossible</h1><p class=\"form-err\">Origine refusée.</p>", 403)
    form = await _form(request)
    params = {k: form.get(k, "") for k in _AUTHORIZE_FIELDS}
    user = auth.read_token(request.cookies.get(auth.COOKIE_NAME))
    try:
        client = oauth.check_request(params, oauth.base_url(str(request.base_url)))
    except oauth.OAuthError as e:
        return _consent_page("Connexion impossible", f"<h1>Connexion impossible</h1><p class=\"form-err\">{escape(e.description)}</p>", 400)
    expected = oauth.consent_token(user or "", {**params, "redirect_uri": client["redirect_uri"]})
    if not user or not hmac.compare_digest(expected, str(form.get("consent", ""))) or auth.must_change_password(user):
        return _consent_page("Connexion impossible", "<h1>Connexion impossible</h1><p class=\"form-err\">Session expirée : recommencez depuis votre assistant IA.</p>", 400)
    iss = oauth.base_url(str(request.base_url))
    if form.get("decision") != "allow":
        return _redirect_back(client["redirect_uri"], error="access_denied", state=params["state"], iss=iss)
    code = oauth.create_code(user, client, params)
    return _redirect_back(client["redirect_uri"], code=code, state=params["state"], iss=iss)


async def _form(request: Request) -> dict[str, str]:
    """An application/x-www-form-urlencoded body (all OAuth uses), without extra dependency."""
    from urllib.parse import parse_qsl
    body = await request.body()
    try:
        return dict(parse_qsl(body.decode("utf-8"), keep_blank_values=True))
    except UnicodeDecodeError:
        return {}


def _basic_auth(request: Request) -> tuple[str, str] | None:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("basic "):
        return None
    try:
        from urllib.parse import unquote_plus
        client_id, _, secret = base64.b64decode(header[6:]).decode().partition(":")
        return unquote_plus(client_id), unquote_plus(secret)
    except Exception:
        return None


@app.post("/oauth/token", include_in_schema=False)
async def oauth_token(request: Request):
    if limited := _too_many(request, "oauth-token", 60, 60):
        return limited
    form = await _form(request)
    try:
        return _oauth_json(oauth.exchange(form, _basic_auth(request)))
    except oauth.OAuthError as e:
        return _oauth_error(e)


@app.post("/oauth/revoke", include_in_schema=False)
async def oauth_revoke(request: Request):
    if limited := _too_many(request, "oauth-revoke", 60, 60):
        return limited
    form = await _form(request)
    basic = _basic_auth(request)
    oauth.revoke_token(form.get("token", ""), (basic[0] if basic else None) or form.get("client_id") or None)
    return _oauth_json({})  # RFC 7009: same answer whether the token existed or not


@app.get("/api/oauth/grants")
def list_oauth_grants(user: str = Depends(current_user)):
    return oauth.grants_of(user)


@app.delete("/api/oauth/grants/{grant_id}")
def revoke_oauth_grant(grant_id: str, user: str = Depends(current_user)):
    if not oauth.revoke_grant(grant_id, user):
        raise HTTPException(404, "Autorisation introuvable")
    return {"ok": True}


# --- in-app assistant (side panel, read only: see app/assistant.py) ------------------------


@app.get("/api/assistant/models")
def assistant_models(user: str = Depends(current_user)):
    return assistant.available_models()


@app.get("/api/assistant/conversations")
def assistant_conversations(user: str = Depends(current_user)):
    return assistant.list_conversations(user)


@app.get("/api/assistant/conversations/{conversation_id}")
def assistant_conversation(conversation_id: str, user: str = Depends(current_user)):
    conversation = assistant.get_conversation(conversation_id, user)
    if not conversation:
        raise HTTPException(404, "Conversation introuvable")
    return conversation


@app.delete("/api/assistant/conversations/{conversation_id}")
def delete_assistant_conversation(conversation_id: str, user: str = Depends(current_user)):
    if not assistant.delete_conversation(conversation_id, user):
        raise HTTPException(404, "Conversation introuvable")
    return {"ok": True}


@app.post("/api/assistant/chat")
async def assistant_chat(body: AssistantMessage, request: Request, user: str = Depends(current_user)):
    """Server-sent events: conversation, then tool / delta as the answer is written, then done or error."""
    if auth.rate_limited(f"assistant|{user}", 30, 300):
        raise HTTPException(429, "Trop de questions d'affilée : patientez quelques minutes.")
    base = oauth.base_url(str(request.base_url))
    docs = lambda topic: guide.topic(topic, base, app)  # noqa: E731

    async def stream():
        async for kind, data in assistant.chat(user, body.message, body.conversation_id, body.page, body.lang,
                                               manager, chain_manager, docs, body.provider, body.model):
            yield f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


# --- chains -------------------------------------------------------------------------------


def _chain_view(chain: dict) -> dict:
    names = {a["id"]: a["name"] for a in agents.list_for(chain["owner"])}  # the chain owner's agents
    runs = [r for r in chain_manager.runs.values() if r.chain_id == chain["id"]]
    last = max(runs, key=lambda r: r.created_at, default=None)
    return {**{k: chain.get(k) for k in ("id", "owner", "name", "schedule", "schedule_enabled", "next_run_at", "created_at", "updated_at", "created_via", "updated_via")},
            "steps": [{**s, "agent_name": names.get(s["agent_id"], "Agent supprimé")} for s in chain["steps"]],
            "schedule_label": schedule.describe(chain["schedule"]),
            "last_run": {"id": last.id, "status": last.status, "created_at": last.created_at} if last else None,
            "run_count": len(runs)}


def _get_chain(chain_id: str, user: str) -> dict:
    chain = chains.get(chain_id, user)
    if not chain:
        raise HTTPException(404, "Chaîne introuvable")
    return chain


def _chain_fields(changes: dict, user: str) -> dict:
    if "name" in changes and changes["name"] is not None:
        changes["name"] = changes["name"].strip()
    if changes.get("steps") is not None:
        steps, error = chains.validate_steps(changes["steps"], user)
        if error:
            raise HTTPException(400, error)
        changes["steps"] = steps
    if changes.get("schedule"):
        if error := schedule.validate(changes["schedule"]):
            raise HTTPException(400, error)
        changes["schedule"] = schedule.normalize(changes["schedule"])
    return changes


@app.get("/api/chains")
def list_chains(scope: Scope = "mine", user: str = Depends(current_user)):
    names = _names()
    return [_owned(_chain_view(c), user, names) for c in (chains.list_all() if scope == "all" else chains.list_for(user))]


@app.post("/api/chains", status_code=201)
def create_chain(body: ChainIn, user: str = Depends(current_user)):
    f = _chain_fields(body.model_dump(), user)
    return _chain_view(chains.create(user, f["name"], f["steps"], f["schedule"], f["schedule_enabled"]))


@app.patch("/api/chains/{chain_id}")
def update_chain(chain_id: str, body: ChainChanges, user: str = Depends(current_user)):
    _get_chain(chain_id, user)
    return _chain_view(chains.update(chain_id, user, _chain_fields(body.model_dump(exclude_unset=True), user)))


@app.delete("/api/chains/{chain_id}")
def delete_chain(chain_id: str, user: str = Depends(current_user)):
    if not chains.delete(chain_id, user):
        raise HTTPException(404, "Chaîne introuvable")
    return {"ok": True}


@app.post("/api/chains/{chain_id}/run")
async def run_chain(chain_id: str, user: str = Depends(current_user)):
    try:
        return chain_manager.start(_get_chain(chain_id, user)).summary()
    except RuntimeError as e:
        raise HTTPException(409, str(e))


def _get_chain_run(chain_run_id: str, user: str, write: bool = True):
    """write=False: anyone may look; True: only the owner may act."""
    chain_run = chain_manager.runs.get(chain_run_id)
    if not chain_run or (write and chain_run.owner != user):
        raise HTTPException(404, "Exécution de chaîne introuvable")
    return chain_run


@app.get("/api/chain-runs")
def list_chain_runs(scope: Scope = "mine", user: str = Depends(current_user)):
    names = _names()
    pool = chain_manager.runs.values() if scope == "all" else chain_manager.runs_of(user)
    return [_owned(r.summary(), user, names) for r in sorted(pool, key=lambda r: r.created_at, reverse=True)]


@app.get("/api/chain-runs/{chain_run_id}")
def get_chain_run(chain_run_id: str, user: str = Depends(current_user)):
    return _owned(_get_chain_run(chain_run_id, user, write=False).summary(), user)


@app.post("/api/chain-runs/{chain_run_id}/stop")
def stop_chain_run(chain_run_id: str, user: str = Depends(current_user)):
    chain_run = _get_chain_run(chain_run_id, user)
    if chain_run.status == "en_cours":
        chain_manager.stop(chain_run)
    return chain_run.summary()


# --- tasks --------------------------------------------------------------------


def _run_matches(run, kind: str, status: str, q: str, since: str) -> bool:
    if kind and kind != ("chain" if run.chain_name else "agent" if run.agent_id else "task"):
        return False
    if status == "actives":
        if run.status not in ("en_cours", "en_attente"):
            return False
    elif status and run.status != status:
        return False
    if since and run.created_at < since:
        return False
    if q:
        text = " ".join(str(x or "") for x in (run.agent_name, run.task, run.chain_name, run.id, run.model)).lower()
        if q.lower() not in text:
            return False
    return True


@app.get("/api/tasks")
def list_tasks(scope: Scope = "mine", kind: Literal["", "agent", "task", "chain"] = "", status: str = "", q: str = "",
               since: str = "", offset: int | None = Query(None, ge=0), limit: int | None = Query(None, ge=1, le=200),
               light: bool = False, user: str = Depends(current_user)):
    """Newest first. With offset/limit: one page, as {"items", "total"}; without: the whole (filtered) list.

    Filtering happens on the runs in memory; only the runs returned are summarized, so a page stays fast
    however long the history. light=true skips counting each run's files on disk.
    """
    names = _names()
    pool = list(manager.runs.values()) if scope == "all" else manager.runs_of(user)
    found = [r for r in reversed(pool) if _run_matches(r, kind, status, q.strip(), since)]
    if offset is None and limit is None:
        return [_owned(r.summary(with_files=not light), user, names) for r in found]
    start = offset or 0
    page = found[start:start + (limit or 25)]
    return {"items": [_owned(r.summary(with_files=not light), user, names) for r in page], "total": len(found)}


@app.post("/api/tasks")
async def create_task(body: NewTask, user: str = Depends(current_user)):
    attachments = []
    if body.rerun_of:
        previous = _get_run(body.rerun_of, user)
        attachments += [previous.inputs_dir / f["name"] for f in files.listing(previous.inputs_dir)]
    for upload_id in body.attachments:
        path = files.staged(user, upload_id)
        if not path:
            raise HTTPException(400, "Une pièce jointe a expiré : ajoutez-la de nouveau.")
        attachments.append(path)
    try:
        run = manager.start(
            owner=user,
            task=body.task.strip(),
            headless=config.BROWSER_HEADLESS if body.headless is None else body.headless,
            max_steps=body.max_steps or config.AGENT_MAX_STEPS,
            options={"attachments": attachments},
        )
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return run.summary()


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str, user: str = Depends(current_user)):
    run = _get_run(task_id, user, write=False)
    return {**_owned(run.summary(), user), "events": run.events}


@app.post("/api/tasks/{task_id}/stop")
def stop_task(task_id: str, user: str = Depends(current_user)):
    run = _get_run(task_id, user)
    if run.status in ("en_attente", "en_cours", "a_valider"):
        manager.stop(run)
    return run.summary()


@app.post("/api/tasks/{task_id}/approval")
def answer_approval(task_id: str, body: Approval, user: str = Depends(current_user)):
    run = _get_run(task_id, user)
    if not run.resolve_approval(body.approved, body.comment.strip() or None, user):
        raise HTTPException(409, "Aucune validation en attente pour cette exécution.")
    return run.summary()


@app.get("/api/tasks/{task_id}/events")
async def task_events(task_id: str, user: str = Depends(current_user)):
    """Server-sent events: replays past events, then streams new ones until the run ends."""
    run = _get_run(task_id, user, write=False)

    async def stream():
        queue = run.subscribe()
        try:
            for event in list(run.events):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            if run.events and run.events[-1]["type"] == "done":
                return
            # A server restart leaves no final event on disk. End the replay instead of
            # keeping the page waiting forever for an execution that is already interrupted.
            if run.status not in ("en_attente", "en_cours", "a_valider"):
                event = {"type": "done", "status": run.status, "result": run.result,
                         "time": run.finished_at or run.created_at}
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                return
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event["type"] == "done":
                    return
        finally:
            run.unsubscribe(queue)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/api/tasks/{task_id}/live")
def live_screenshot(task_id: str, user: str = Depends(current_user)):
    run = _get_run(task_id, user, write=False)
    if not run.live_screenshot:
        return Response(status_code=204)
    # URL and title ride along in headers (percent-encoded: headers must be ASCII).
    headers = {
        "Cache-Control": "no-store",
        "X-Page-Url": quote(run.live_url, safe=""),
        "X-Page-Title": quote(run.live_title, safe=""),
    }
    return Response(run.live_screenshot, media_type="image/png", headers=headers)


@app.get("/api/tasks/{task_id}/context")
def run_context(task_id: str, user: str = Depends(current_user)):
    path = _get_run(task_id, user, write=False).dir / "contexte.txt"
    return {"text": path.read_text(encoding="utf-8") if path.exists() else ""}


@app.get("/api/tasks/{task_id}/files")
def list_files(task_id: str, user: str = Depends(current_user)):
    return _get_run(task_id, user, write=False).all_files()


@app.get("/api/tasks/{task_id}/files/{source}/{name}")
def download_file(task_id: str, source: str, name: str, user: str = Depends(current_user)):
    # Only plain files directly inside one of the run's two folders: no ".." escapes.
    path = _get_run(task_id, user, write=False).file_path(source, name)
    if not path:
        raise HTTPException(404, "Fichier introuvable")
    return FileResponse(path, filename=path.name)


# --- attachments --------------------------------------------------------------------


async def _read_upload(request: Request) -> tuple[str, bytes]:
    """The file is sent as the raw request body, its name in the X-File-Name header."""
    name = files.clean_name(unquote(request.headers.get("x-file-name", "")))
    too_big = HTTPException(413, f"Fichier trop volumineux : {files.MAX_BYTES // (1024 * 1024)} Mo au maximum.")
    try:
        declared = int(request.headers.get("content-length") or 0)
    except ValueError:
        declared = 0
    if declared > files.MAX_BYTES:
        raise too_big
    # Read piece by piece: a body sent without (or with a false) Content-Length stops at the limit,
    # instead of being loaded whole into memory first.
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > files.MAX_BYTES:
            raise too_big
        chunks.append(chunk)
    data = b"".join(chunks)
    if error := files.check(name, len(data)):
        raise HTTPException(400, error)
    return name, data


@app.post("/api/uploads", status_code=201)
async def upload_attachment(request: Request, user: str = Depends(current_user)):
    name, data = await _read_upload(request)
    return await asyncio.to_thread(files.stage, user, name, data)


@app.get("/api/agents/{agent_id}/files")
def list_agent_files(agent_id: str, user: str = Depends(current_user)):
    if not agents.get_any(agent_id):
        raise HTTPException(404, "Agent introuvable")
    return files.listing(files.agent_dir(agent_id))


@app.post("/api/agents/{agent_id}/files", status_code=201)
async def add_agent_file(agent_id: str, request: Request, user: str = Depends(current_user)):
    _get_agent(agent_id, user)
    if len(files.agent_files(agent_id)) >= 20:
        raise HTTPException(400, "20 pièces jointes au maximum par agent.")
    name, data = await _read_upload(request)
    path = files.unique_path(files.agent_dir(agent_id), name)
    await asyncio.to_thread(path.write_bytes, data)
    return {"name": path.name, "size": len(data)}


@app.delete("/api/agents/{agent_id}/files/{name}")
def delete_agent_file(agent_id: str, name: str, user: str = Depends(current_user)):
    _get_agent(agent_id, user)
    path = files.inside(files.agent_dir(agent_id), name)
    if not path:
        raise HTTPException(404, "Fichier introuvable")
    path.unlink()
    return {"ok": True}


@app.get("/api/tasks/{task_id}/screenshots/{step}")
def step_screenshot(task_id: str, step: int, user: str = Depends(current_user)):
    run = _get_run(task_id, user, write=False)
    path = run.dir / f"etape_{step:03d}.png"
    if not path.exists():
        raise HTTPException(404, "Capture introuvable")
    return FileResponse(path, media_type="image/png")
