"""Regenerates the user guide's screenshots (static/guide/*.png) from a demo instance.

Nothing real is shown or touched: the script starts AutoCollab on a temporary data folder, fills it with
a fictional organisation (accounts, agents, chains, runs, context, connections), opens each page in a
browser and saves the screenshot under the name the guide already uses. Then it refreshes the public
copy of the guide (site/guide/).

    .venv\\Scripts\\python.exe tools\\guide_screenshots.py            # every screenshot
    .venv\\Scripts\\python.exe tools\\guide_screenshots.py execution  # only some (names without .png)

Run it again whenever a screen shown in the guide changes.
"""

import asyncio
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "static" / "guide"
PORT = 8897
BASE = f"http://127.0.0.1:{PORT}"
ORG = "Exemple & Associés"
PASSWORD = "guide-demo-2026"
VIEWPORT = {"width": 1440, "height": 900}


# --- an isolated instance ------------------------------------------------------------------------


def isolate(tmp: Path) -> dict:
    """Environment of the demo instance: its own data, runs, browser profiles and encryption key."""
    env = {
        "AUTOCOLLAB_DATA_DIR": str(tmp / "data"),
        "AUTOCOLLAB_RUNS_DIR": str(tmp / "runs"),
        "AUTOCOLLAB_MASTER_KEY_FILE": str(tmp / "master.key"),
        "BROWSER_PROFILES_DIR": str(tmp / "profils"),
        "ORG_NAME": ORG,
        "APP_HOST": "127.0.0.1",
        "APP_PORT": str(PORT),
        "PUBLIC_URL": "",
        "COOKIE_SECURE": "false",
        "MAX_PARALLEL_RUNS": "3",
        # Empty, not absent: .env must not fill them in (load_dotenv leaves variables already set). Without this,
        # a DATABASE_URL in .env makes the demo write into the real database and replace its accounts and settings.
        "DATABASE_URL": "",
        "AUTOCOLLAB_MASTER_KEY": "",
        "STRIPE_SECRET_KEY": "",
        "STRIPE_WEBHOOK_SECRET": "",
    }
    os.environ.update(env)  # before any app module is imported: config reads them once
    sys.path.insert(0, str(ROOT))
    return {**os.environ, **env}


# --- fictional data --------------------------------------------------------------------------------

USERS = {
    "camille.durand": ("Camille Durand", True),
    "thomas.martin": ("Thomas Martin", False),
    "julie.bernard": ("Julie Bernard", False),
    "karim.benali": ("Karim Benali", False),
}

PORTAL = """<!doctype html><html lang="fr"><meta charset="utf-8"><style>
body{{margin:0;font:14px/1.5 Segoe UI,system-ui,sans-serif;color:#1d2433;background:#f4f6fb}}
header{{background:#2f4ac2;color:#fff;padding:12px 24px;display:flex;gap:24px;align-items:center}}
header b{{font-size:16px}} header span{{opacity:.8}}
nav{{background:#fff;border-bottom:1px solid #dde2ee;padding:0 24px;display:flex;gap:22px}}
nav a{{padding:12px 0;color:#5b6478;text-decoration:none}} nav a.on{{color:#2f4ac2;border-bottom:2px solid #2f4ac2;font-weight:600}}
main{{padding:24px}} .card{{background:#fff;border:1px solid #dde2ee;border-radius:8px;padding:18px}}
h1{{font-size:18px;margin:0 0 4px}} p{{margin:0 0 14px;color:#5b6478}}
table{{width:100%;border-collapse:collapse}} th,td{{text-align:left;padding:9px 10px;border-bottom:1px solid #eef1f7}}
th{{font-size:12px;color:#5b6478;text-transform:uppercase}} tr.hl td{{background:#fff7d6}}
.tag{{background:#e5f3ec;color:#16794d;border-radius:4px;padding:1px 8px;font-size:12px}}
.bar{{display:flex;gap:10px;margin-bottom:14px}} .bar span{{border:1px solid #dde2ee;border-radius:6px;padding:5px 10px;background:#fff}}
</style><header><b>Portail Fournisseurs</b><span>Exemple &amp; Associés · Achats</span></header>
<nav><a>Accueil</a><a class="on">Factures</a><a>Commandes</a><a>Paiements</a></nav>
<main><div class="card"><h1>{title}</h1><p>{sub}</p><div class="bar">{filters}</div><table>
<tr><th>Date</th><th>Fournisseur</th><th>N° facture</th><th>Montant TTC</th><th></th></tr>{rows}</table></div></main></html>"""

INVOICES = [("03/10/2026", "Bureau Plus", "FA-26-1042", "214,80 €"), ("07/10/2026", "Orange Pro", "OP-778120", "54,90 €"),
            ("12/10/2026", "Transports Lebrun", "TL-2026-311", "1 260,00 €"), ("18/10/2026", "Imprimerie Duval", "ID-5531", "389,40 €"),
            ("24/10/2026", "Nettoyage Clair", "NC-1009", "540,00 €"), ("29/10/2026", "Énergie Verte", "EV-10-2026", "312,15 €")]


def portal_page(step: int) -> str:
    filters = "<span>Période : octobre 2026</span><span>Statut : toutes</span>" if step >= 2 else "<span>Période : toutes</span>"
    rows = "".join(f'<tr class="{"hl" if step >= 3 else ""}"><td>{d}</td><td>{f}</td><td>{n}</td><td>{m}</td>'
                   f'<td>{"<span class=tag>Téléchargée</span>" if step >= 4 else ""}</td></tr>' for d, f, n, m in INVOICES)
    title = {1: "Factures", 2: "Factures · octobre 2026"}.get(step, "Factures · octobre 2026")
    sub = "6 factures sur la période" if step >= 2 else "128 factures"
    return PORTAL.format(title=title, sub=sub, filters=filters, rows=rows)


def seed(when: datetime) -> str:
    """Fills the demo instance; returns the id of the run shown on execution.png."""
    from app import agents, auth, chains, context, integrations, settings, sites, tokens, twofa, vault
    from app.db import connect
    from app.runner import TaskRun

    users = {}
    for login, (name, admin) in USERS.items():
        users[login] = {"name": name, "email": f"{login}@exemple.fr", "password": auth.hash_password(PASSWORD),
                        "admin": admin, "lang": "fr"}
    _, hashes = twofa._new_recovery()
    users["thomas.martin"]["totp"] = {"secret": vault.seal(twofa.new_secret()), "enabled": True, "last_step": 0,
                                      "recovery": hashes, "enabled_at": (when - timedelta(days=20)).isoformat(timespec="seconds")}
    auth.save_users(users)

    settings._save({"provider": "anthropic", "model": "claude-haiku-5-5", "use_vision": True,
                    "deepseek_endpoint": settings.DEFAULT_DEEPSEEK_ENDPOINT,
                    "api_keys": {"anthropic": "sk-ant-demo-0000000000000000000000x7Qd", "openai": "", "mistral": "", "deepseek": ""},
                    "organisation": {"name": ORG}})
    settings.record_test("anthropic", "claude-haiku-5-5", "…x7Qd", True, "Le modèle a répondu en 0,8 s.")
    integrations.save_admin_config({"oauth": {"google": {"client_id": "123456789012-demo.apps.googleusercontent.com",
                                                         "client_secret": "demo-secret"}},
                                    "enabled": ["gmail", "drive", "sheets", "calendar", "slack"], "allow_custom": True})

    me = "camille.durand"
    for kind, read_only in (("gmail", True), ("drive", False)):
        app_ = integrations.CATALOG[kind]
        integrations.save_connection(me, kind, app_["name"], app_["url"], {"access_token": "demo", "refresh_token": "demo"},
                                     read_only, f"{me}@exemple.fr")
    for name, url, signed_in in (("Pennylane", "https://app.pennylane.com", 1), ("Qonto", "https://app.qonto.com", 1),
                                 ("Portail fournisseurs", "https://portail.fournisseurs-demo.fr", 1),
                                 ("impots.gouv (professionnel)", "https://cfspro.impots.gouv.fr", 0)):
        site = sites.create(me, name, url)
        with connect() as conn:
            conn.execute("UPDATE sites SET signed_in = ?, checked_at = ?, last_opened_at = ? WHERE id = ?",
                         (signed_in, (when - timedelta(hours=3)).isoformat(timespec="seconds"),
                          (when - timedelta(days=2)).isoformat(timespec="seconds"), site["id"]))
    with connect() as conn:
        conn.execute("UPDATE integrations SET last_used_at = ? WHERE owner = ?", ((when - timedelta(hours=5)).isoformat(timespec="seconds"), me))

    context.save("cabinet", {
        "instructions": "Ne jamais supprimer de document ni d'écriture.\nNe jamais valider un paiement.\n"
                        "Les montants sont en euros, au format 1 234,56.\nEn cas de doute, arrête-toi et explique pourquoi.",
        "glossary": [{"term": "FNP", "definition": "Factures non parvenues : charges de la période dont la facture n'est pas encore arrivée."},
                     {"term": "PJ", "definition": "Pièce justificative (facture, ticket, relevé)."},
                     {"term": "Dossier", "definition": "Un client, identifié par son code (ex. DUP01)."}],
        "sites": [{"site": "app.pennylane.com", "notes": "Factures fournisseurs : Achats › Factures.\nFNP : Comptabilité › Écritures, filtre « FNP »."},
                  {"site": "portail.fournisseurs-demo.fr", "notes": "Les factures sont dans l'onglet Factures ; filtrer par période avant de télécharger."}],
    }, me)
    context.save(context.scope_of(me), {"instructions": "Mes dossiers : DUP01, MAR02.\nRends toujours le résultat sous forme de tableau.",
                                        "glossary": [{"term": "MAR02", "definition": "SAS Martin Restauration, exercice clos au 30/06."}],
                                        "sites": []}, me)

    monthly = {"kind": "monthly", "time": "08:00", "monthday": 1}
    weekly = {"kind": "weekly", "time": "09:00", "days": [0]}
    made = {}
    for owner, name, instructions, domains, approval, sched in (
        (me, "Factures fournisseurs", "Sur le portail fournisseurs, télécharge les factures de {mois_precedent} en PDF, "
         "puis range-les dans Google Drive, dossier Factures › {annee}.", ["portail.fournisseurs-demo.fr", "drive.google.com"], False, monthly),
        (me, "Relevés bancaires du mois", "Sur Qonto, télécharge le relevé de {mois_precedent} au format PDF pour chaque compte.",
         ["app.qonto.com"], False, monthly),
        (me, "Pièces manquantes", "Sur Pennylane, liste les transactions de {mois_precedent} sans justificatif, dossier par dossier, "
         "dans un tableau date · libellé · montant.", ["app.pennylane.com"], False, None),
        (me, "Relances clients", "Pour chaque facture client échue depuis plus de 15 jours, prépare un e-mail de relance poli "
         "et demande ma validation avant de l'envoyer.", ["mail.google.com", "app.pennylane.com"], True, weekly),
        (me, "Échéances fiscales", "Sur impots.gouv, relève les échéances déclaratives du mois prochain pour chaque dossier.",
         ["impots.gouv.fr"], False, None),
        ("thomas.martin", "Notes de frais", "Récupère les notes de frais validées de la semaine dans l'outil RH et "
         "exporte-les dans le tableau de suivi.", [], False, weekly),
        ("thomas.martin", "Déclaration de TVA", "Prépare le brouillon de déclaration de TVA de {mois_precedent} sans l'envoyer.",
         ["impots.gouv.fr"], True, None),
        ("julie.bernard", "Suivi des commandes", "Liste les commandes en attente d'expédition depuis plus de 48 h.", [], False, None),
    ):
        made[name] = agents.create(owner, name, instructions, 30, domains, approval, sched, bool(sched))

    chains.create(me, "Clôture mensuelle", [{"agent_id": made["Relevés bancaires du mois"]["id"], "on_failure": "stop"},
                                            {"agent_id": made["Pièces manquantes"]["id"], "on_failure": "continue"},
                                            {"agent_id": made["Relances clients"]["id"], "on_failure": "stop"}],
                  {"kind": "monthly", "time": "07:30", "monthday": 2}, True)

    tokens.create(me, "n8n · automatisations")
    tokens.create(me, "Tableau de bord interne")

    # Past runs: two weeks of history for the dashboard and the lists.
    rng = random.Random(7)
    pool = [(a["owner"], a) for a in made.values()]
    tasks = ["Va sur service-public.fr et trouve la date limite de la CA12",
             "Liste les 5 derniers e-mails reçus de la banque",
             "Télécharge l'attestation URSSAF de DUP01",
             "Cherche le numéro SIRET de la SARL Dupuis Bâtiment"]
    for day in range(14, 0, -1):
        for _ in range(rng.randint(1, 4)):
            start = (when - timedelta(days=day)).replace(hour=rng.randint(8, 18), minute=rng.randint(0, 59), second=rng.randint(0, 59))
            if rng.random() < .2:
                owner, agent, task = me, None, rng.choice(tasks)
            else:
                owner, agent = rng.choice(pool)
                task = agents.render(agent["instructions"])
            status = rng.choices(["termine", "echec", "arrete"], [86, 10, 4])[0]
            steps = rng.randint(6, 24)
            _run(TaskRun, owner, agent, task, status, start, steps, rng.randint(40, 260),
                 "Terminé : voir le résultat." if status == "termine" else None, rng.choice(["planifie", "manuel"]) if agent else "manuel")
    return _detail_run(TaskRun, made["Factures fournisseurs"], when)


def _run(TaskRun, owner, agent, task, status, start, steps, seconds, result, trigger="manuel", run_id=None):
    run = TaskRun(owner, task, True, 30, agent["id"] if agent else None, agent["name"] if agent else None, {"trigger": trigger})
    shutil.rmtree(run.dir, ignore_errors=True)
    run.id = run_id or f"{start:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
    run.dir = run.dir.parent / run.id
    run.dir.mkdir(parents=True, exist_ok=True)
    run.created_at = start.isoformat(timespec="seconds")
    run.finished_at = (start + timedelta(seconds=seconds)).isoformat(timespec="seconds")
    run.status, run.steps, run.result = status, steps, result
    run.provider, run.model = "anthropic", "claude-haiku-5-5"
    run.tokens.update({"input_tokens": steps * 9800, "output_tokens": steps * 380, "calls": steps})
    run.cost_usd = round(steps * 0.00117, 6)
    run.credits = round(steps * 1.2, 1)
    run.save()
    return run


def _detail_run(TaskRun, agent, when: datetime) -> str:
    """The run shown on execution.png: five steps with their screenshots, three downloaded invoices."""
    start = (when - timedelta(hours=2)).replace(minute=2, second=4)
    result = ("6 factures d'octobre 2026 téléchargées et rangées dans Drive › Factures › 2026 :\n"
              + "\n".join(f"- {d[:5]} · {f} · {n} · {m}" for d, f, n, m in INVOICES))
    run = _run(TaskRun, agent["owner"], agent, agents_render(agent), "termine", start, 5, 136, result, "planifie")
    steps = [
        ("Ouvrir le portail fournisseurs.", "La page de connexion du portail s'affiche, la session est déjà ouverte.",
         [{"go_to_url": {"url": "https://portail.fournisseurs-demo.fr"}}]),
        ("Aller dans l'onglet Factures.", "Succès : l'accueil du portail est affiché.", [{"click_element_by_index": {"index": 7}}]),
        ("Filtrer sur octobre 2026.", "Succès : la liste des factures est affichée.",
         [{"select_dropdown_option": {"index": 12, "text": "Octobre 2026"}}]),
        ("Télécharger les 6 factures en PDF.", "Succès : 6 factures sur la période.", [{"click_element_by_index": {"index": 21}}]),
        ("Ranger les factures dans Drive et rendre le résultat.", "Succès : 6 factures téléchargées.", [{"done": {"success": True}}]),
    ]
    events = [{"type": "status", "time": run.created_at, "status": "en_cours", "task": run.task}]
    for i, (goal, evaluation, actions) in enumerate(steps, start=1):
        t = (start + timedelta(seconds=8 + i * 24)).isoformat(timespec="seconds")
        events.append({"type": "step", "time": t, "step": i, "url": "https://portail.fournisseurs-demo.fr/factures?periode=2026-10",
                       "title": "Portail Fournisseurs · Factures", "evaluation": evaluation, "memory": "", "next_goal": goal,
                       "actions": [{"name": n, "params": p} for a in actions for n, p in a.items()],
                       "screenshot": f"/api/tasks/{run.id}/screenshots/{i}",
                       "usage": {"input_tokens": 9800, "output_tokens": 380, "cache_read_tokens": 0, "cache_write_tokens": 0,
                                 "calls": 1, "cost_usd": 0.00117, "credits": 1.2}})
    events.append({"type": "done", "time": run.finished_at, "status": "termine", "result": result})
    (run.dir / "events.jsonl").write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events), encoding="utf-8")
    downloads = run.dir / "telechargements"
    downloads.mkdir(exist_ok=True)
    for _, supplier, number, _ in INVOICES[:3]:
        padding = b"%" * random.Random(number).randint(60_000, 140_000)  # a realistic size in the Files list
        (downloads / f"{number}.pdf").write_bytes(b"%PDF-1.4\n% facture de demonstration\n" + padding + b"\n%%EOF\n")
    return run.id


def agents_render(agent: dict) -> str:
    from app import agents
    return agents.render(agent["instructions"])


async def portal_screenshots(run_dir: Path, page) -> None:
    for step in range(1, 6):
        await page.set_content(portal_page(step))
        await page.screenshot(path=str(run_dir / f"etape_{step:03d}.png"))


# --- screenshots -------------------------------------------------------------------------------------


def wait_for_server(proc) -> None:
    for _ in range(120):
        if proc.poll() is not None:
            raise SystemExit("Le serveur de démonstration s'est arrêté au démarrage.")
        try:
            urllib.request.urlopen(f"{BASE}/login", timeout=1)
            return
        except Exception:
            time.sleep(.5)
    raise SystemExit("Le serveur de démonstration ne répond pas.")


async def capture(only: set[str], run_id: str, runs_dir: Path) -> list[str]:
    from playwright.async_api import async_playwright

    done = []
    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch()
        except Exception:
            browser = await p.chromium.launch(channel="msedge")
        new = lambda: browser.new_context(viewport=VIEWPORT, locale="fr-FR", color_scheme="light", reduced_motion="reduce",
                                         bypass_csp=True)  # Playwright waits run scripts the CSP would refuse

        # Demo pages the run "saw".
        ctx = await new()
        page = await ctx.new_page()
        await page.set_viewport_size({"width": 1280, "height": 800})
        await portal_screenshots(runs_dir / run_id, page)
        await ctx.close()

        async def shot(page, name, full=False, settle=700):
            if only and name not in only:
                return
            await page.wait_for_timeout(settle)
            if full:  # the whole page, side menu included: grow the window rather than stitching a full-page capture
                height = await page.evaluate("Math.max(document.documentElement.scrollHeight, document.body.scrollHeight)")
                await page.set_viewport_size({**VIEWPORT, "height": max(VIEWPORT["height"], height)})
                await page.wait_for_timeout(400)
            await page.screenshot(path=str(OUT / f"{name}.png"))
            if full:
                await page.set_viewport_size(VIEWPORT)
            done.append(name)
            print(f"  {name}.png")

        async def login(page, user):
            await page.goto(f"{BASE}/login")
            await page.fill("#username", user)
            await page.fill("#password", PASSWORD)
            await page.click("#btn")

        # Sign-in screens.
        ctx = await new()
        page = await ctx.new_page()
        await page.goto(f"{BASE}/login")
        await shot(page, "connexion", settle=300)
        await login(page, "thomas.martin")
        await page.wait_for_selector("#codeField:not([hidden])")
        await shot(page, "connexion-code", settle=300)
        await ctx.close()

        # Everything else, as Camille (administrator).
        ctx = await new()
        page = await ctx.new_page()
        await login(page, "camille.durand")
        await page.wait_for_function("location.pathname === '/'")
        await page.wait_for_selector("#meName:not(:empty)")

        async def go(route):
            await page.goto(f"{BASE}/#/{route}")
            await page.wait_for_load_state("networkidle")

        await go("tableau-de-bord")
        await shot(page, "tableau-de-bord", settle=1200)

        await go("agents")
        await shot(page, "agents")
        await page.click('[data-tools="agents"] [data-lv="list"]')
        await shot(page, "agents-liste")
        await page.click('[data-tools="agents"] [data-lv="cards"]')
        # An agent with approval mode and a schedule: the bottom of its window shows both.
        await page.locator("#agentGrid article", has_text="Relances clients").locator("[data-act='edit']").click()
        await page.wait_for_selector("#agentDlg[open]")
        await shot(page, "agent-fenetre")
        await page.evaluate("""() => { const d = document.getElementById('agentDlg');
            [d, ...d.querySelectorAll('*')].forEach(el => { if (el.scrollHeight > el.clientHeight + 4) el.scrollTop = el.scrollHeight; }); }""")
        tips = page.locator("#agentDlg .tip")
        if await tips.count():
            await tips.last.hover()
        await shot(page, "agent-fenetre-2")
        await page.keyboard.press("Escape")

        await page.click('#viewAgents [data-scope="all"]')
        await page.wait_for_load_state("networkidle")
        await shot(page, "agents-cabinet", settle=1000)
        await page.click('#viewAgents [data-scope="mine"]')

        await go("chaines")
        await shot(page, "chaines", settle=1000)
        await page.click("#viewChains [data-act='edit']")
        await page.wait_for_selector("#chainDlg[open]")
        await shot(page, "chaine-fenetre")
        await page.keyboard.press("Escape")

        await go("planification")
        await shot(page, "planification", settle=1000)

        await go("taches")
        await shot(page, "taches")
        await page.click("#newTaskBtn")
        await page.fill("#task", "Va sur service-public.fr et trouve la date limite de dépôt de la déclaration CA12 pour 2026. "
                                 "Rends la date et le lien de la page officielle.")
        await shot(page, "tache-fenetre")
        await page.keyboard.press("Escape")

        await go("executions")
        await shot(page, "executions", settle=1000)
        await go(f"executions/{run_id}")
        await page.wait_for_selector("#result:not([hidden])")
        await shot(page, "execution", settle=1200)

        await go("contexte")
        await page.fill("#ctxSample", "Va sur Pennylane et liste les FNP de {mois_precedent}")
        await page.wait_for_selector("#ctxKept li")
        await shot(page, "contexte", full=True, settle=900)

        await go("connexions")
        await shot(page, "connexions", full=True, settle=1200)

        await page.click("#accountBtn")
        await page.wait_for_selector("#pwdDlg[open]")
        await shot(page, "mon-compte")
        await page.click("#tfaOnBtn")
        await page.wait_for_selector("#tfaDlg[open] #tfaQr svg")
        await shot(page, "double-authentification")
        await page.keyboard.press("Escape")
        await page.keyboard.press("Escape")

        await go("developpeurs")
        await shot(page, "developpeurs", settle=1000)
        await page.click('[data-devtab="mcp"]')
        await page.click('#mcpTabs [data-client="claudeai"]')
        await shot(page, "developpeurs-mcp", full=True)

        await page.goto(f"{BASE}/admin")
        await page.wait_for_load_state("networkidle")
        await shot(page, "administration", settle=1000)
        await page.click("#tabAIBtn")
        await shot(page, "admin-ia", full=True, settle=1000)
        await page.click("#tabIntBtn")
        await shot(page, "admin-integrations", full=True, settle=1000)

        await browser.close()
    return done


def main() -> None:
    only = set(sys.argv[1:])
    tmp = Path(tempfile.mkdtemp(prefix="autocollab-guide-"))
    env = isolate(tmp)
    when = datetime.now().replace(microsecond=0)
    print(f"Instance de démonstration : {tmp}")
    run_id = seed(when)
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(PORT),
                               "--log-level", "warning"], cwd=ROOT, env=env)
    try:
        wait_for_server(server)
        print("Captures :")
        done = asyncio.run(capture(only, run_id, tmp / "runs"))
    finally:
        server.terminate()
        server.wait(timeout=15)
        shutil.rmtree(tmp, ignore_errors=True)
    missing = only - set(done)
    if missing:
        print("Inconnues :", ", ".join(sorted(missing)))
    print(f"{len(done)} capture(s) dans {OUT}")
    subprocess.run([sys.executable, str(ROOT / "site" / "build_guide.py")], cwd=ROOT, check=False)


if __name__ == "__main__":
    main()
