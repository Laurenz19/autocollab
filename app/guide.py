"""AutoCollab's documentation for AI assistants, in Markdown.

One source for /llms.txt, /llms-full.txt and the MCP server (get_documentation tool and
docs resources). Tools, variables and API routes are read from the code itself, so the text
follows the app as it changes; only the explanations below are written by hand.
"""

import json

from . import agents, apidoc, mcp

TOPICS = mcp.DOC_TOPICS

OVERVIEW = """# AutoCollab

> Outil pour les cabinets d'expertise comptable et les équipes administratives : des agents IA travaillent dans un
> navigateur ou directement dans des applications (Gmail, Drive, Slack…) pour les tâches répétitives :
> télécharger des relevés, récupérer des factures, relancer des pièces manquantes, importer dans Pennylane.

## Notions

- **Tâche ponctuelle** : une consigne exécutée une fois (`run_task`).
- **Agent** : une consigne enregistrée, relancée à la demande ou selon une planification. Elle peut contenir
  des variables de date ({mois_precedent}…) remplies au lancement.
- **Exécution** (run) : un lancement d'agent ou de tâche. Asynchrone : elle passe par une file d'attente,
  puis l'agent travaille étape par étape (capture d'écran à chaque étape).
- **Chaîne** : une suite d'agents ; chaque étape reçoit le résultat ({resultat_precedent}) et les fichiers
  de la précédente.
- **Garde-fous** : sites autorisés (le navigateur ne peut pas aller ailleurs) et mode avec validation
  (l'agent s'arrête et demande l'accord d'un humain avant toute action difficile à annuler).
- **Contexte** : glossaire, règles et notes par site de l'organisation et de l'utilisateur, ajoutés à chaque consigne.
- **Connexions** : chaque utilisateur a son propre navigateur d'agent (ses sessions sur ses sites) et peut
  connecter des applications (Gmail, Drive, Slack…) que ses agents utilisent sans navigateur.
- **Droits** : tout se fait avec les droits de l'utilisateur connecté ; il ne voit que ses agents et exécutions.

## Bonnes pratiques pour un assistant IA

- Avant de créer ou modifier un agent ou une chaîne, montrer le projet à l'utilisateur et attendre son accord.
- Écrire des consignes précises : le site, les étapes, les critères, et ce qu'il faut rendre à la fin.
- Dès qu'un agent modifie des données (envoi, import, validation, paiement) : proposer des sites autorisés
  et le mode avec validation.
- Suivre une exécution jusqu'à un statut final ; si elle attend une validation, montrer la demande à
  l'utilisateur et ne répondre qu'avec sa décision.
- La suppression d'un agent ou d'une chaîne se fait uniquement dans l'application.
"""

CHAINS = """# Chaînes

Une chaîne enchaîne de 1 à 10 agents existants. À chaque étape :

- l'agent reçoit le **résultat** de l'étape précédente : placez la variable `{resultat_precedent}` dans sa
  consigne à l'endroit voulu ;
- les **fichiers** téléchargés ou reçus par l'étape précédente lui sont fournis (il peut les envoyer sur un site) ;
- `on_failure` décide de la suite si l'étape échoue : `stop` (par défaut, la chaîne s'arrête) ou `continue`
  (l'étape suivante démarre en sachant que la précédente a échoué).

Une chaîne peut être planifiée comme un agent. Outils MCP : `list_chains`, `create_chain`, `update_chain`,
`run_chain`, `get_chain_run`, `stop_chain_run`.

Exemple : 1. « Relevés » télécharge les relevés de {mois_precedent} sur le site de la banque ;
2. « Import » envoie dans Pennylane les fichiers reçus et résume : {resultat_precedent}.
"""

RUNS = """# Exécutions

Statuts : `en_attente` (dans la file), `en_cours`, `a_valider` (attend une validation humaine), puis un statut
final : `termine`, `echec`, `arrete`, `interrompu` (serveur redémarré pendant l'exécution).

- Une exécution est **asynchrone** : lancez-la, puis interrogez `get_run` (MCP) ou `GET /api/tasks/{id}`
  toutes les quelques secondes jusqu'à un statut final. `result` contient alors la réponse de l'agent.
- Les exécutions d'un même utilisateur se suivent (un seul navigateur par utilisateur) ; celles de
  plusieurs utilisateurs tournent en parallèle selon la capacité du serveur.
- **Validation** : en mode avec validation, l'agent s'arrête avec le statut `a_valider` et une demande
  (`approval.description`). Répondre avec `answer_approval` (MCP) ou `POST /api/tasks/{id}/approval`,
  `approved` true ou false, uniquement selon la décision de l'utilisateur. Sans réponse dans le délai
  configuré, l'action est refusée.
- **Fichiers** : ceux fournis au lancement et ceux téléchargés par l'agent sont attachés à l'exécution.
- **Journal** : chaque étape (but, URL, actions), les appels aux applications connectées, les validations
  et les erreurs ; flux temps réel `GET /api/tasks/{id}/events` (Server-Sent Events).
"""

CONNECT = """## Connexion

- Adresse : `{base}/mcp` · transport Streamable HTTP (réponses JSON) · protocole 2025-06-18.
- **OAuth 2.1** (claude.ai, ChatGPT et clients récents) : ajoutez simplement l'adresse ; le client découvre
  le serveur d'autorisation via `{base}/.well-known/oauth-protected-resource`, s'enregistre seul, et
  l'utilisateur clique sur « Autoriser » dans AutoCollab.
- **Clé d'API** (Claude Code, Cursor, VS Code, n8n) : en-tête `Authorization: Bearer ac_…`, clé créée dans
  Développeurs › Clés d'API.
- Ressources de documentation : `autocollab://docs/<sujet>` ; outil `get_documentation`.
"""


def _agents_text() -> str:
    variables = "\n".join(f"- `{{{name}}}` : {text}" for name, text in agents.VARIABLES.items())
    return f"""# Agents

Champs : `name` (court), `instructions` (consigne en français), `max_steps` (1 à 200), `allowed_domains`
(sites autorisés, ex. `["app.pennylane.com", "*.qonto.com"]` ; vide = aucune restriction), `approval_mode`
(validation humaine avant les actions difficiles à annuler), `schedule` et `schedule_enabled`.

## Variables de consigne

Remplacées au lancement par leur valeur :

{variables}

## Planification

`schedule` vaut `null` (non planifié) ou :
- `{{"kind": "daily", "time": "08:00"}}` : chaque jour ;
- `{{"kind": "weekdays", "time": "08:00"}}` : du lundi au vendredi ;
- `{{"kind": "weekly", "time": "08:00", "days": [0, 3]}}` : jours de la semaine, 0 = lundi ;
- `{{"kind": "monthly", "time": "08:00", "monthday": 2}}` : jour du mois ; -1 = dernier jour.

Activez-la avec `schedule_enabled: true`.

## Bien écrire une consigne

- Nommer le site et le point de départ (« Va sur app.pennylane.com, menu Achats… »).
- Décrire les étapes et les critères (période, client, montant…), avec les variables de date.
- Dire ce qu'il faut rendre : liste, total, fichier téléchargé, résumé.
- Pour les sites où l'agent doit être connecté, l'utilisateur ouvre une session une fois dans
  « Mes connexions ».
"""


def _mcp_text(base: str) -> str:
    lines = ["# Serveur MCP d'AutoCollab", "", CONNECT.format(base=base), "## Outils", ""]
    for tool in mcp.TOOLS:
        ann = tool.get("annotations") or {}
        kind = "lecture" if ann.get("readOnlyHint") else "agit sur des sites réels" if ann.get("openWorldHint") else "modifie"
        props = tool["inputSchema"].get("properties") or {}
        required = set(tool["inputSchema"].get("required") or [])
        args = ", ".join(f"{p}{'' if p in required else '?'}" for p in props) or "—"
        lines.append(f"- **{tool['name']}**({args}) — {tool['description']} _({kind})_")
    lines += ["", "## Consignes données à l'assistant", "", mcp.INSTRUCTIONS]
    return "\n".join(lines) + "\n"


def _api_text(base: str, app, full: bool) -> str:
    ref = apidoc.reference(app)
    labels = dict((g["id"], g["label"]) for g in ref["groups"])
    lines = ["# API REST", "",
             f"Base : `{base}` · authentification `Authorization: Bearer ac_…` (clé d'API) · JSON · erreurs "
             "`{\"detail\": \"message en français\"}`.", ""]
    group = None
    for e in ref["endpoints"]:
        if e["group"] != group:
            group = e["group"]
            lines += ["", f"## {labels.get(group, group)}", ""]
        access = "" if e["access"] == "utilisateur" else f" _({e['access']})_"
        lines.append(f"- `{e['method']} {e['path']}` — {e['summary']}{access}")
        if full:
            if e["description"]:
                lines.append(f"  {e['description']}")
            if e["body"] is not None:
                lines.append(f"  Corps : `{json.dumps(e['body'], ensure_ascii=False)}`")
            if e["response"] is not None:
                lines.append(f"  Réponse : `{json.dumps(e['response'], ensure_ascii=False)[:600]}`")
    return "\n".join(lines) + "\n"


def topic(name: str, base: str, app) -> str:
    if name == "overview":
        return OVERVIEW
    if name == "agents":
        return _agents_text()
    if name == "chains":
        return CHAINS
    if name == "runs":
        return RUNS
    if name == "mcp":
        return _mcp_text(base)
    if name == "api":
        return _api_text(base, app, full=True)
    raise KeyError(name)


def llms_txt(base: str, app) -> str:
    """Short index in the llms.txt format: what it is, then where to read more."""
    links = "\n".join(f"- [{label}]({base}/llms-full.txt#{name}) " for name, label in TOPICS.items())
    return (OVERVIEW + "\n## Pour aller plus loin\n\n"
            f"- [Documentation complète]({base}/llms-full.txt) : agents, chaînes, exécutions, MCP, API.\n"
            f"- Serveur MCP : `{base}/mcp` (OAuth ou clé d'API ; outil `get_documentation`).\n\n"
            "## Sujets\n\n" + links + "\n\n" + _mcp_text(base))


def llms_full_txt(base: str, app) -> str:
    return "\n\n---\n\n".join(topic(name, base, app) for name in TOPICS)
