"""MCP server (Model Context Protocol, "Streamable HTTP" transport, JSON responses).

Lets an AI assistant (Claude Desktop, Claude Code, n8n's MCP client...) drive the app with
the rights of the user whose API key it uses: list and launch agents, run one-off tasks,
follow a run, stop it, answer an approval request.

Implemented directly (JSON-RPC 2.0 over POST /mcp) rather than with the MCP SDK, whose
recent versions require newer Pydantic/Starlette than browser-use and LangChain allow.
Stateless: no session id, no server-to-client stream.
"""

import json

from . import agents, config, schedule

SERVER_INFO = {"name": "autocollab", "title": "AutoCollab", "version": "1.2.0"}
PROTOCOL_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"]
INSTRUCTIONS = (
    "AutoCollab, l'outil du cabinet : des agents IA travaillent dans un navigateur (Gmail, Pennylane, banques...).\n"
    "- Lancer : run_task (consigne ponctuelle), run_agent (agent enregistré), run_chain (suite d'agents).\n"
    "- Construire : create_agent / update_agent, create_chain / update_chain. list_variables donne les variables "
    "utilisables dans une consigne ({mois_precedent}, {resultat_precedent} dans une chaîne...).\n"
    "- Avant de créer ou modifier un agent ou une chaîne, montre le projet à l'utilisateur et attends son accord.\n"
    "- Dès qu'un agent modifie des données (envoi, import, validation, paiement), propose des sites autorisés "
    "(allowed_domains) et le mode avec validation (approval_mode).\n"
    "- Dans une chaîne, l'agent d'une étape reçoit le résultat de la précédente via {resultat_precedent} : "
    "place cette variable dans sa consigne.\n"
    "- Les exécutions sont asynchrones : suis-les avec get_run ou get_chain_run jusqu'à un statut final. "
    "Si le statut est a_valider, montre la demande à l'utilisateur et n'appelle answer_approval qu'avec sa décision.\n"
    "- La suppression d'un agent ou d'une chaîne se fait uniquement dans l'application.\n"
    "- Contexte : les règles, le glossaire et les notes par site du cabinet et de l'utilisateur sont ajoutés "
    "automatiquement à chaque consigne. Lis-les (get_context) avant d'écrire un agent, ne les répète pas dans la "
    "consigne et ne les contredis pas ; preview_context montre ce qu'un agent recevra.\n"
    "- Pour modifier le contexte (update_personal_context, update_firm_context), montre d'abord le changement exact "
    "(avant / après) et attends l'accord de l'utilisateur ; le contexte du cabinet s'applique à tous les collègues.\n"
    "- En cas de doute sur le fonctionnement (variables, planification, chaînes, statuts), appelle get_documentation."
)

DOC_TOPICS = {
    "overview": "Vue d'ensemble : ce que fait AutoCollab et ses notions",
    "agents": "Agents : consigne, variables, garde-fous, planification",
    "chains": "Chaînes : enchaîner des agents qui se passent leur résultat",
    "runs": "Exécutions : statuts, suivi, validations, fichiers",
    "mcp": "Serveur MCP : connexion (OAuth ou clé) et outils",
    "api": "API REST : routes, corps et réponses",
}
DOC_URI = "autocollab://docs/"

_STR = {"type": "string"}
_SCHEDULE = {
    "type": ["object", "null"],
    "description": "Planification ; null = non planifié. kind daily|weekdays : {kind, time} ; weekly : {kind, time, days: [0..6], 0 = lundi} ; "
                   "monthly : {kind, time, monthday: 1..31 ou -1 = dernier jour}. time au format HH:MM.",
    "properties": {"kind": {"type": "string", "enum": ["daily", "weekdays", "weekly", "monthly"]}, "time": _STR,
                   "days": {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 6}},
                   "monthday": {"type": "integer", "minimum": -1, "maximum": 31}},
}
_AGENT_FIELDS = {
    "name": {**_STR, "description": "Nom court de l'agent"},
    "instructions": {**_STR, "description": "Consigne détaillée en français : site, étapes, ce qu'il faut rendre. Peut contenir des variables (list_variables)."},
    "max_steps": {"type": "integer", "minimum": 1, "maximum": 200},
    "allowed_domains": {"type": "array", "items": _STR, "description": "Sites autorisés, ex. [\"app.pennylane.com\"] ; vide = aucune restriction"},
    "approval_mode": {"type": "boolean", "description": "Demander une validation humaine avant toute action difficile à annuler"},
    "schedule": _SCHEDULE,
    "schedule_enabled": {"type": "boolean"},
}
_STEPS = {"type": "array", "minItems": 1, "maxItems": 10, "description": "Étapes dans l'ordre",
          "items": {"type": "object", "properties": {"agent_id": _STR, "on_failure": {"type": "string", "enum": ["stop", "continue"]}},
                    "required": ["agent_id"], "additionalProperties": False}}

_TERM = {"type": "object", "properties": {"term": _STR, "definition": _STR}, "required": ["term", "definition"], "additionalProperties": False}
_SITE_NOTE = {"type": "object", "properties": {"site": {**_STR, "description": "ex. app.pennylane.com ou Pennylane"}, "notes": _STR},
              "required": ["site", "notes"], "additionalProperties": False}
_CONTEXT_CHANGES = {
    "add_rules": {"type": "array", "items": _STR, "description": "Règles à ajouter à la fin des règles existantes (une par élément)"},
    "instructions": {**_STR, "description": "Remplace TOUT le texte des règles (une par ligne). Pour seulement ajouter, utiliser add_rules."},
    "set_terms": {"type": "array", "items": _TERM, "description": "Mots du glossaire à ajouter ; un mot déjà présent est remplacé"},
    "remove_terms": {"type": "array", "items": _STR, "description": "Mots du glossaire à retirer"},
    "set_sites": {"type": "array", "items": _SITE_NOTE, "description": "Notes par site à ajouter ; un site déjà présent est remplacé"},
    "remove_sites": {"type": "array", "items": _STR, "description": "Sites dont retirer les notes"},
}

READ = {"readOnlyHint": True, "openWorldHint": False}
BUILD = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}
ACT = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True}  # agents act on real sites


def _tool(name, title, description, properties, required=(), annotations=READ):
    return {"name": name, "title": title, "description": description,
            "inputSchema": {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False},
            "annotations": {"title": title, **annotations}}


TOOLS = [
    _tool("get_documentation", "Documentation d'AutoCollab",
          "Documentation d'AutoCollab pour bien l'utiliser : " + " ; ".join(f"{k} = {v}" for k, v in DOC_TOPICS.items())
          + ". Sans sujet : la vue d'ensemble.",
          {"topic": {"type": "string", "enum": list(DOC_TOPICS)}}),
    _tool("list_agents", "Lister les agents", "Liste les agents enregistrés : consigne, sites autorisés, mode avec validation, planification, dernière exécution.", {}),
    _tool("list_variables", "Variables de consigne", "Variables utilisables dans une consigne d'agent, remplacées au lancement.", {}),
    _tool("create_agent", "Créer un agent", "Crée un agent enregistré (sans le lancer). Montrer le projet à l'utilisateur avant.",
          _AGENT_FIELDS, ["name", "instructions"], BUILD),
    _tool("update_agent", "Modifier un agent", "Modifie un agent : seuls les champs fournis changent.",
          {"agent_id": _STR, **_AGENT_FIELDS}, ["agent_id"], BUILD),
    _tool("run_agent", "Lancer un agent", "Lance un agent enregistré. Renvoie l'exécution (asynchrone : suivre avec get_run).",
          {"agent_id": {**_STR, "description": "Identifiant de l'agent (voir list_agents)"}}, ["agent_id"], ACT),
    _tool("run_task", "Lancer une tâche ponctuelle", "Exécute une consigne ponctuelle dans le navigateur, sans créer d'agent.",
          {"task": {**_STR, "description": "La consigne, précise : site, ce qu'il faut faire, ce qu'il faut rendre"},
           "max_steps": {"type": "integer", "minimum": 1, "maximum": 200},
           "allowed_domains": _AGENT_FIELDS["allowed_domains"], "approval_mode": _AGENT_FIELDS["approval_mode"]}, ["task"], ACT),
    _tool("list_runs", "Lister les exécutions", "Exécutions récentes, les plus récentes d'abord.",
          {"limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
           "status": {"type": "string", "enum": ["en_attente", "en_cours", "a_valider", "termine", "echec", "arrete", "interrompu"]}}),
    _tool("get_run", "Détail d'une exécution", "Statut, résultat, étapes, fichiers, validation en attente.", {"run_id": _STR}, ["run_id"]),
    _tool("stop_run", "Arrêter une exécution", "Arrête une exécution en cours ou la retire de la file.", {"run_id": _STR}, ["run_id"],
          {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}),
    _tool("list_chains", "Lister les chaînes", "Chaînes : suites d'agents qui se passent leur résultat et leurs fichiers.", {}),
    _tool("create_chain", "Créer une chaîne", "Compose une chaîne d'agents existants (sans la lancer). Chaque étape reçoit le résultat de la précédente "
          "via {resultat_precedent} et ses fichiers téléchargés. on_failure : stop (défaut) ou continue.",
          {"name": _STR, "steps": _STEPS, "schedule": _SCHEDULE, "schedule_enabled": {"type": "boolean"}}, ["name", "steps"], BUILD),
    _tool("update_chain", "Modifier une chaîne", "Modifie une chaîne : seuls les champs fournis changent.",
          {"chain_id": _STR, "name": _STR, "steps": _STEPS, "schedule": _SCHEDULE, "schedule_enabled": {"type": "boolean"}}, ["chain_id"], BUILD),
    _tool("run_chain", "Lancer une chaîne", "Lance une chaîne. Renvoie l'exécution de chaîne (asynchrone : suivre avec get_chain_run).",
          {"chain_id": _STR}, ["chain_id"], ACT),
    _tool("get_chain_run", "Progression d'une chaîne", "Statut de la chaîne et de chaque étape (avec l'identifiant de son exécution).",
          {"chain_run_id": _STR}, ["chain_run_id"]),
    _tool("stop_chain_run", "Arrêter une chaîne", "Arrête l'étape en cours ; les suivantes sont ignorées.", {"chain_run_id": _STR}, ["chain_run_id"],
          {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}),
    _tool("answer_approval", "Répondre à une validation", "Répond à une demande de validation (statut a_valider). "
          "Uniquement avec la décision explicite de l'utilisateur.",
          {"run_id": _STR, "approved": {"type": "boolean"}, "comment": {**_STR, "description": "Remarque pour l'agent (facultatif)"}},
          ["run_id", "approved"], ACT),
]
TOOLS += [
    _tool("get_context", "Lire le contexte",
          "Règles, glossaire et notes par site du cabinet et de l'utilisateur, ajoutés automatiquement à chaque consigne d'agent. "
          "À lire avant d'écrire un agent.", {}),
    _tool("preview_context", "Aperçu du contexte",
          "Le texte de contexte exact qu'un agent recevrait avec cette consigne (seules les notes des sites concernés sont incluses).",
          {"task": {**_STR, "description": "La consigne, variables comprises"}, "allowed_domains": {"type": "array", "items": _STR}}, ["task"]),
    _tool("update_personal_context", "Modifier mon contexte",
          "Modifie le contexte personnel de l'utilisateur : ajoute des règles, ajoute ou retire des mots du glossaire et des notes par site. "
          "Montrer le changement à l'utilisateur avant.", _CONTEXT_CHANGES, (), {**BUILD, "destructiveHint": True}),
    _tool("update_firm_context", "Modifier le contexte du cabinet",
          "Modifie le contexte du cabinet, appliqué aux agents de tous les collègues. Réservé aux administrateurs ; "
          "montrer le changement exact et obtenir l'accord explicite de l'utilisateur avant.", _CONTEXT_CHANGES, (), {**BUILD, "destructiveHint": True}),
]
TOOL_NAMES = {t["name"] for t in TOOLS}


class ToolError(Exception):
    """A failure to report to the assistant as a tool result (isError), not a protocol error."""


def _run_view(run, detailed: bool = False) -> dict:
    view = {k: v for k, v in run.summary().items() if k in (
        "id", "agent_id", "agent_name", "status", "created_at", "finished_at", "result", "steps", "queue_position", "trigger")}
    view["name"] = run.agent_name or (run.task[:80] + ("…" if len(run.task) > 80 else ""))
    view["link"] = f"/#/executions/{run.id}"
    if run.approval:
        view["approval"] = run.approval
    if detailed:
        view["task"] = run.task
        view["timeline"] = [
            {"step": e.get("step"), "goal": e.get("next_goal"), "url": e.get("url"), "actions": [a["name"] for a in e.get("actions", [])]}
            if e["type"] == "step" else {"type": e["type"], "message": e.get("message") or e.get("description") or e.get("name")}
            for e in run.events if e["type"] in ("step", "error", "approval", "approval_result", "upload")
        ][-40:]
        view["files"] = run.all_files()
        view["uploads"] = run.uploads
    return view


def _agent_changes(args: dict, partial: bool) -> dict:
    """Validate agent fields the same way as the app; raises ToolError with the French message."""
    from . import schedule as sched

    out = {}
    for key in ("name", "instructions"):
        if key in args:
            value = str(args[key] or "").strip()
            if key == "name" and not 1 <= len(value) <= 80:
                raise ToolError("Le nom doit faire entre 1 et 80 caractères.")
            if key == "instructions" and len(value) < 3:
                raise ToolError("Consigne trop courte.")
            if key == "instructions" and len(value) > agents.MAX_INSTRUCTIONS:
                raise ToolError(f"Consigne trop longue : {agents.MAX_INSTRUCTIONS} caractères au maximum.")
            out[key] = value
        elif not partial:
            raise ToolError(f"Champ manquant : {key}.")
    if "max_steps" in args:
        if args["max_steps"] is not None and (not isinstance(args["max_steps"], int) or not 1 <= args["max_steps"] <= 200):
            raise ToolError("max_steps doit être un entier entre 1 et 200.")
        out["max_steps"] = args["max_steps"]
    if "allowed_domains" in args:
        domains, error = agents.normalize_domains([str(d) for d in (args["allowed_domains"] or [])])
        if error:
            raise ToolError(error)
        out["allowed_domains"] = domains
    if "approval_mode" in args:
        out["approval_mode"] = bool(args["approval_mode"])
    out.update(_schedule_changes(args, sched))
    return out


def _schedule_changes(args: dict, sched) -> dict:
    out = {}
    if "schedule" in args:
        value = args["schedule"]
        if value:
            if not isinstance(value, dict) or (error := sched.validate(value)):
                raise ToolError(error if isinstance(value, dict) else "schedule doit être un objet ou null.")
            value = sched.normalize(value)
        out["schedule"] = value or None
    if "schedule_enabled" in args:
        out["schedule_enabled"] = bool(args["schedule_enabled"])
    return out


def _agent_view(a: dict, manager) -> dict:
    last = max((r for r in manager.runs.values() if r.agent_id == a["id"]), key=lambda r: r.created_at, default=None)
    return {"id": a["id"], "name": a["name"], "instructions": a["instructions"], "max_steps": a["max_steps"],
            "allowed_domains": a["allowed_domains"], "approval_mode": a["approval_mode"],
            "schedule": schedule.describe(a["schedule"]) + ("" if a["schedule_enabled"] or not a["schedule"] else " (en pause)"),
            "next_run_at": a.get("next_run_at"), "created_via": a.get("created_via", "app"),
            "last_run": {"id": last.id, "status": last.status, "created_at": last.created_at} if last else None}


def _chain_view(c: dict) -> dict:
    names = {a["id"]: a["name"] for a in agents.list_for(c["owner"])}
    return {"id": c["id"], "name": c["name"], "created_via": c.get("created_via", "app"),
            "steps": [{"agent_id": st["agent_id"], "agent_name": names.get(st["agent_id"], "Agent supprimé"), "on_failure": st["on_failure"]} for st in c["steps"]],
            "schedule": schedule.describe(c["schedule"]) + ("" if c["schedule_enabled"] or not c["schedule"] else " (en pause)"),
            "next_run_at": c.get("next_run_at")}


def _run_of(manager, user: str, run_id: str):
    run = manager.runs.get(run_id)
    if not run or run.owner != user:
        raise ToolError("Exécution introuvable.")
    return run


def _context_view(data: dict) -> dict:
    return {k: data[k] for k in ("instructions", "glossary", "sites", "updated_at", "updated_by")}


def _apply_context_changes(data: dict, args: dict) -> tuple[dict, list[str]]:
    """Targeted edits, so an assistant never rewrites the whole context by accident."""
    from . import context as ctx

    def items(key: str) -> list:
        value = args.get(key) or []
        if not isinstance(value, list):
            raise ToolError(f"{key} doit être une liste.")
        return value

    data = {"instructions": data["instructions"], "glossary": list(data["glossary"]), "sites": list(data["sites"])}
    done = []
    if "instructions" in args:
        data["instructions"] = str(args["instructions"] or "").strip()
        done.append("règles remplacées")
    rules = [str(r).strip() for r in items("add_rules") if str(r).strip()]
    if rules:
        data["instructions"] = "\n".join(x for x in [data["instructions"]] + rules if x)
        done.append(f"{len(rules)} règle(s) ajoutée(s)")
    for key, field, label in (("glossary", "term", "mot"), ("sites", "site", "site")):
        removed = {ctx._fold(str(x).strip()) for x in items("remove_terms" if key == "glossary" else "remove_sites")}
        if removed:
            before = len(data[key])
            data[key] = [x for x in data[key] if ctx._fold(x[field]) not in removed]
            done.append(f"{before - len(data[key])} {label}(s) retiré(s)")
        added = items("set_terms" if key == "glossary" else "set_sites")
        for item in added:
            if not isinstance(item, dict):
                raise ToolError("Chaque élément doit être un objet.")
            folded = ctx._fold(str(item.get(field, "")).strip())
            data[key] = [x for x in data[key] if ctx._fold(x[field]) != folded] + [item]
        if added:
            done.append(f"{len(added)} {label}(s) ajouté(s) ou remplacé(s)")
    if not done:
        raise ToolError("Aucun changement demandé.")
    return data, done


def _context_tool(name: str, args: dict, user: str) -> dict:
    from . import agents as ag, auth, context as ctx

    if name == "get_context":
        return {"cabinet": _context_view(ctx.load("cabinet")), "personal": _context_view(ctx.load(ctx.scope_of(user))),
                "can_edit_cabinet": auth.is_admin(user), "limits": ctx.LIMITS}
    if name == "preview_context":
        task = str(args.get("task") or "").strip()[:agents.MAX_INSTRUCTIONS]
        if not task:
            raise ToolError("Champ manquant : task.")
        domains, error = ag.normalize_domains([str(d) for d in (args.get("allowed_domains") or [])])
        if error:
            raise ToolError(error)
        text = ctx.build(user, ag.render(task), domains) or ""
        return {"text": text or "Aucun contexte ne s'applique à cette consigne.", "chars": len(text), "tokens": round(len(text) / 4)}
    if name == "update_firm_context" and not auth.is_admin(user):
        raise ToolError("Seul un administrateur peut modifier le contexte du cabinet. Proposez plutôt update_personal_context.")
    scope = "cabinet" if name == "update_firm_context" else ctx.scope_of(user)
    data, done = _apply_context_changes(ctx.load(scope), args)
    data, error = ctx.clean(data)
    if error:
        raise ToolError(error)
    ctx.save(scope, data, f"{user} via MCP")
    return {"changes": done, "context": _context_view(ctx.load(scope))}


def call_tool(name: str, args: dict, user: str, manager, chain_manager=None) -> dict:
    if name in ("get_context", "preview_context", "update_personal_context", "update_firm_context"):
        return _context_tool(name, args, user)
    if name in ("list_chains", "run_chain", "get_chain_run", "create_chain", "update_chain", "stop_chain_run"):
        from . import chains, schedule as sched

        if name == "list_chains":
            return {"chains": [_chain_view(c) for c in chains.list_for(user)]}
        if name in ("create_chain", "update_chain"):
            changes = _schedule_changes(args, sched)
            if "name" in args:
                changes["name"] = str(args["name"] or "").strip()
                if not 1 <= len(changes["name"]) <= 80:
                    raise ToolError("Le nom doit faire entre 1 et 80 caractères.")
            if "steps" in args:
                steps, error = chains.validate_steps(args["steps"] if isinstance(args["steps"], list) else [], user)
                if error:
                    raise ToolError(error + " (voir list_agents)")
                changes["steps"] = steps
            if name == "create_chain":
                if "name" not in changes or "steps" not in changes:
                    raise ToolError("name et steps sont obligatoires.")
                chain = chains.create(user, changes["name"], changes["steps"], changes.get("schedule"),
                                      changes.get("schedule_enabled", False), via="mcp")
                return {"chain": _chain_view(chain), "link": "/#/chaines"}
            if not chains.get(str(args.get("chain_id", "")), user):
                raise ToolError("Chaîne introuvable (voir list_chains).")
            return {"chain": _chain_view(chains.update(args["chain_id"], user, changes, via="mcp"))}
        if name == "stop_chain_run":
            chain_run = chain_manager.runs.get(str(args.get("chain_run_id", "")))
            if not chain_run or chain_run.owner != user:
                raise ToolError("Exécution de chaîne introuvable.")
            if chain_run.status == "en_cours":
                chain_manager.stop(chain_run)
            return {"chain_run": chain_run.summary()}
        if name == "run_chain":
            chain = chains.get(str(args.get("chain_id", "")), user)
            if not chain:
                raise ToolError("Chaîne introuvable (voir list_chains).")
            try:
                return {"chain_run": chain_manager.start(chain, trigger="mcp").summary()}
            except RuntimeError as e:
                raise ToolError(str(e))
        chain_run = chain_manager.runs.get(str(args.get("chain_run_id", "")))
        if not chain_run or chain_run.owner != user:
            raise ToolError("Exécution de chaîne introuvable.")
        return {"chain_run": chain_run.summary()}
    if name == "list_agents":
        return {"agents": [_agent_view(a, manager) for a in agents.list_for(user)]}
    if name == "list_variables":
        return {"variables": agents.VARIABLES}
    if name == "create_agent":
        f = _agent_changes(args, partial=False)
        agent = agents.create(user, f["name"], f["instructions"], f.get("max_steps"), f.get("allowed_domains", []),
                              f.get("approval_mode", False), f.get("schedule"), f.get("schedule_enabled", False), via="mcp")
        return {"agent": _agent_view(agent, manager), "link": "/#/agents"}
    if name == "update_agent":
        if not agents.get(str(args.get("agent_id", "")), user):
            raise ToolError("Agent introuvable (voir list_agents).")
        changes = _agent_changes({k: v for k, v in args.items() if k != "agent_id"}, partial=True)
        return {"agent": _agent_view(agents.update(args["agent_id"], user, changes, via="mcp"), manager)}
    if name == "run_agent":
        agent = agents.get(str(args.get("agent_id", "")), user)
        if not agent:
            raise ToolError("Agent introuvable (voir list_agents).")
        try:
            run = manager.start(owner=user, task=agents.render(agent["instructions"]), headless=True,
                                max_steps=agent["max_steps"] or config.AGENT_MAX_STEPS, agent_id=agent["id"],
                                agent_name=agent["name"], options=agents.run_options(agent, trigger="mcp"))
        except RuntimeError as e:
            raise ToolError(str(e))
        return {"run": _run_view(run)}
    if name == "run_task":
        task = str(args.get("task", "")).strip()
        if len(task) < 3:
            raise ToolError("Consigne trop courte.")
        if len(task) > agents.MAX_INSTRUCTIONS:
            raise ToolError(f"Consigne trop longue : {agents.MAX_INSTRUCTIONS} caractères au maximum.")
        steps = args.get("max_steps")
        if steps is not None and (not isinstance(steps, int) or not 1 <= steps <= 200):
            raise ToolError("max_steps doit être un entier entre 1 et 200.")
        guard = _agent_changes({k: args[k] for k in ("allowed_domains", "approval_mode") if k in args}, partial=True)
        try:
            run = manager.start(owner=user, task=task, headless=True, max_steps=steps or config.AGENT_MAX_STEPS,
                                options={"trigger": "mcp", "allowed_domains": guard.get("allowed_domains", []),
                                         "approval_mode": guard.get("approval_mode", False)})
        except RuntimeError as e:
            raise ToolError(str(e))
        return {"run": _run_view(run)}
    if name == "list_runs":
        limit = args.get("limit", 10)
        limit = limit if isinstance(limit, int) and 1 <= limit <= 50 else 10
        runs = sorted(manager.runs_of(user), key=lambda r: r.created_at, reverse=True)
        if args.get("status"):
            runs = [r for r in runs if r.status == args["status"]]
        return {"runs": [_run_view(r) for r in runs[:limit]]}
    if name == "get_run":
        return {"run": _run_view(_run_of(manager, user, str(args.get("run_id", ""))), detailed=True)}
    if name == "stop_run":
        run = _run_of(manager, user, str(args.get("run_id", "")))
        if run.status in ("en_attente", "en_cours", "a_valider"):
            manager.stop(run)
        return {"run": _run_view(run)}
    if name == "answer_approval":
        run = _run_of(manager, user, str(args.get("run_id", "")))
        if not isinstance(args.get("approved"), bool):
            raise ToolError("approved doit être true ou false.")
        comment = str(args.get("comment") or "").strip()[:1000] or None
        if not run.resolve_approval(args["approved"], comment, f"{user} (MCP)"):
            raise ToolError("Aucune validation en attente pour cette exécution.")
        return {"run": _run_view(run)}
    raise ToolError(f"Outil inconnu : {name}")


def _error(id_, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def handle(message: dict, user: str, manager, chain_manager=None, docs=None) -> dict | None:
    """One JSON-RPC message; returns the response, or None for a notification.

    docs(topic) gives the documentation text (app/guide.py); passed in to avoid a circular import.
    """
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
        return _error(message.get("id") if isinstance(message, dict) else None, -32600, "Requête JSON-RPC invalide")
    id_, method, params = message.get("id"), message["method"], message.get("params") or {}
    if "id" not in message:
        return None  # notifications (notifications/initialized, cancelled...) need no answer
    if method == "initialize":
        asked = params.get("protocolVersion")
        return {"jsonrpc": "2.0", "id": id_, "result": {
            "protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
            "capabilities": {"tools": {"listChanged": False}, "resources": {"listChanged": False, "subscribe": False}},
            "serverInfo": SERVER_INFO,
            "instructions": INSTRUCTIONS,
        }}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": id_, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": id_, "result": {"tools": TOOLS}}
    if method == "resources/list":
        return {"jsonrpc": "2.0", "id": id_, "result": {"resources": [
            {"uri": DOC_URI + key, "name": key, "title": label, "description": label, "mimeType": "text/markdown"}
            for key, label in DOC_TOPICS.items()]}}
    if method == "resources/templates/list":
        return {"jsonrpc": "2.0", "id": id_, "result": {"resourceTemplates": []}}
    if method == "resources/read":
        uri = str(params.get("uri") or "")
        key = uri[len(DOC_URI):] if uri.startswith(DOC_URI) else ""
        if key not in DOC_TOPICS or docs is None:
            return _error(id_, -32002, f"Ressource introuvable : {uri}")
        return {"jsonrpc": "2.0", "id": id_, "result": {"contents": [{"uri": uri, "mimeType": "text/markdown", "text": docs(key)}]}}
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        if name not in TOOL_NAMES:
            return _error(id_, -32602, f"Outil inconnu : {name}")
        if not isinstance(args, dict):
            return _error(id_, -32602, "arguments doit être un objet")
        if name == "get_documentation":
            topic = args.get("topic") or "overview"
            if topic not in DOC_TOPICS or docs is None:
                return _error(id_, -32602, f"Sujet inconnu : {topic}. Sujets : {', '.join(DOC_TOPICS)}")
            text = docs(topic)
            return {"jsonrpc": "2.0", "id": id_, "result": {"content": [{"type": "text", "text": text}], "isError": False}}
        try:
            data = call_tool(name, args, user, manager, chain_manager)
            return {"jsonrpc": "2.0", "id": id_, "result": {
                "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=1)}],
                "structuredContent": data, "isError": False}}
        except ToolError as e:
            return {"jsonrpc": "2.0", "id": id_, "result": {"content": [{"type": "text", "text": str(e)}], "isError": True}}
    return _error(id_, -32601, f"Méthode non prise en charge : {method}")
