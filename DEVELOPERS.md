# AutoCollab — documentation développeur

Ce document décrit comment piloter l'assistant depuis d'autres outils (scripts, n8n, assistants IA
via MCP) et comment le code est organisé. Pour l'installation et l'usage, voir `README.md`.

- [1. Vue d'ensemble](#1-vue-densemble)
- [2. Authentification](#2-authentification)
- [3. Conventions](#3-conventions)
- [4. Référence de l'API REST](#4-référence-de-lapi-rest)
- [5. Flux d'événements d'une exécution](#5-flux-dévénements-dune-exécution)
- [6. Serveur MCP](#6-serveur-mcp)
- [7. Exemples](#7-exemples)
- [8. Organisation du code](#8-organisation-du-code)

---

## 1. Vue d'ensemble

| Élément | Rôle |
|---|---|
| **Application** | FastAPI (Python 3.11), servie par uvicorn sur `APP_HOST:APP_PORT` (127.0.0.1:8800 par défaut), derrière un proxy HTTPS en production. |
| **Agent** | browser-use 0.1.48 pilote un navigateur Chromium (Playwright) ; un modèle d'IA (Claude, Mistral, OpenAI, DeepSeek) décide des actions. |
| **Exécution (run)** | Un lancement d'agent ou de tâche ponctuelle. Asynchrone : la création renvoie tout de suite, on suit ensuite l'état. |
| **File d'attente** | Une exécution à la fois par utilisateur (un profil de navigateur chacun), plusieurs utilisateurs en parallèle jusqu'à `MAX_PARALLEL_RUNS`. |
| **Stockage** | `data/app.db` (SQLite : agents, exécutions, connexions, contexte, clés d'API), `data/users.json` (comptes), `data/settings.json` (réglages d'IA et clés des fournisseurs), `data/profils/<utilisateur>/` (sessions de navigateur), `runs/<id>/` (journal, captures, fichiers de chaque exécution). |

Chaque utilisateur ne voit que **ses** agents, exécutions, connexions et clés. Les administrateurs ont en
plus les routes `/api/admin/*` et le contexte du cabinet ; ils ne voient pas le travail des autres.

## 2. Authentification

Deux méthodes, acceptées par toutes les routes `/api/*` et par `/mcp` :

| Méthode | Usage |
|---|---|
| **Clé d'API** — en-tête `Authorization: Bearer ac_…` | Scripts, n8n, clients MCP. Créée dans l'application (page **Développeurs**) ou via `POST /api/tokens`. Affichée une seule fois ; seule son empreinte SHA-256 est stockée. 10 clés au plus par utilisateur. |
| **Cookie de session** `session` | L'interface web. Obtenu par `POST /api/login` ; HttpOnly, SameSite=Lax, `Secure` si `COOKIE_SECURE=true`. Valable `SESSION_HOURS` (12 h). |

- Une clé agit **avec les droits de son propriétaire** : elle accède à l'administration seulement si
  le propriétaire est administrateur. Révoquée dès la suppression de la clé ou du compte.
- Un compte au **mot de passe provisoire** (défini par un administrateur) reçoit `403` partout sauf
  `GET /api/me`, `POST /api/me/password`, `POST /api/logout`, jusqu'à ce qu'il choisisse le sien.
- `POST /api/login` : 5 échecs en 15 min pour un même identifiant et une même adresse IP bloquent la connexion (`429`).

## 3. Conventions

- **Format** : JSON en UTF-8, sauf les envois de fichiers (corps brut) et les fichiers téléchargés.
- **Dates** : ISO 8601 à l'heure locale du serveur, sans fuseau (`2026-10-11T08:00:00`).
- **Erreurs** : code HTTP + `{"detail": "message en français"}`. `400` données invalides, `401` non
  authentifié, `403` interdit, `404` introuvable (y compris la ressource d'un autre utilisateur), `409`
  conflit (ex. navigateur occupé), `413` fichier trop volumineux, `422` corps mal formé (détail Pydantic), `429` trop de tentatives.

### Statuts d'une exécution

| Statut | Signification |
|---|---|
| `en_attente` | Dans la file (`queue_position` = rang). |
| `en_cours` | L'agent travaille. |
| `a_valider` | Mode avec validation : l'agent attend une réponse (`approval` décrit l'action). |
| `termine` | Terminée avec succès (`result` contient la réponse de l'agent). |
| `echec` | L'agent n'a pas atteint l'objectif, ou une erreur s'est produite. |
| `arrete` | Arrêtée ou retirée de la file à la demande. |
| `interrompu` | Coupée par un redémarrage du serveur. |

### Objet « exécution » (résumé)

```json
{
  "id": "20261011-080000-3e031c",
  "owner": "jdupont",
  "task": "Va sur Pennylane et liste les FNP de septembre 2026",
  "agent_id": "a1b2c3d4e5f6",
  "agent_name": "FNP du mois",
  "status": "termine",
  "created_at": "2026-10-11T08:00:00",
  "finished_at": "2026-10-11T08:03:12",
  "result": "3 factures non parvenues : …",
  "steps": 9,
  "max_steps": 40,
  "queue_position": null,
  "trigger": "manuel",
  "approval": null,
  "approval_mode": false,
  "allowed_domains": ["app.pennylane.com"],
  "files": 2,
  "uploads": [{"name": "Releve.pdf", "host": "app.pennylane.com", "time": "2026-10-11T08:02:40"}]
}
```

`trigger` : `manuel`, `planifie` ou `mcp`. `task` est la consigne exacte envoyée, variables remplies.

## 4. Référence de l'API REST

Accès : **public** (sans authentification), **utilisateur** (tout compte connecté), **admin**
(administrateur). La spécification OpenAPI complète est servie à `GET /api/openapi.json` (authentifié).

### 4.1 Session et compte

| Méthode | Route | Accès | Corps → Réponse |
|---|---|---|---|
| POST | `/api/login` | public | `{"username": "jdupont ou e-mail", "password": "…"}` → `{"username", "name", "must_change_password"}` + cookie |
| POST | `/api/logout` | public | → `{"ok": true}`, supprime le cookie |
| GET | `/api/me` | utilisateur | → `{"username", "name", "email", "admin", "must_change_password", "lang"}` (`lang` : `"fr"`, `"en"` ou `null` si jamais choisie) |
| PATCH | `/api/me` | utilisateur | `{"lang": "fr" \| "en"}` → enregistre la langue de l'interface dans le compte |
| POST | `/api/me/password` | utilisateur | `{"current_password", "new_password"}` (10 caractères min.) → `{"ok": true}` ; déconnecte les autres sessions et renvoie un nouveau cookie |
| GET | `/api/config` | utilisateur | → fournisseur et modèle d'IA, vision, `headless`, `max_steps`, navigateur, `approval_timeout` |

**Double authentification** : si elle est activée, `POST /api/login` renvoie `{"two_factor": true, "ticket"}` sans
cookie ; `POST /api/login/2fa` `{"ticket", "code"}` (code à 6 chiffres ou code de secours) ouvre la session.
`POST /api/me/2fa/setup` → `{"secret", "uri", "qr_svg"}` ; `POST /api/me/2fa/enable` `{"code"}` → `{"recovery_codes"}` ;
`POST /api/me/2fa/disable` et `POST /api/me/2fa/recovery` `{"password", "code"}`. Politique : `GET/PUT /api/admin/security`
`{"require_2fa": "none" | "admins" | "all"}`. Un compte qui doit l'activer reçoit `403` partout ailleurs. Les clés
d'API (`Authorization: Bearer ac_…`) ne demandent pas de code, mais sont refusées tant que la 2FA requise n'est
pas activée. Limites de débit : `/oauth/register` 20 par heure, `/oauth/token` et `/oauth/revoke` 60 par minute,
`/mcp` 300 par minute, par adresse IP.

### 4.2 Tâches et exécutions

| Méthode | Route | Accès | Corps → Réponse |
|---|---|---|---|
| GET | `/api/tasks` | utilisateur | → liste des exécutions (résumés), plus récentes d'abord |
| POST | `/api/tasks` | utilisateur | `{"task": "…", "max_steps": 40?, "headless": true?, "attachments": ["<id d'upload>"]?, "rerun_of": "<id>"?}` → exécution créée (`en_attente`) |
| GET | `/api/tasks/{id}` | utilisateur | → résumé + `events` (liste complète, voir §5) |
| POST | `/api/tasks/{id}/stop` | utilisateur | → résumé ; arrête l'agent après l'étape en cours, ou retire de la file |
| POST | `/api/tasks/{id}/approval` | utilisateur | `{"approved": true, "comment": "…"?}` → résumé ; `409` si aucune validation en attente |
| GET | `/api/tasks/{id}/events` | utilisateur | Flux **Server-Sent Events** (§5) |
| GET | `/api/tasks/{id}/live` | utilisateur | Capture PNG en direct (`204` si aucune) ; en-têtes `X-Page-Url`, `X-Page-Title` (encodés URL) |
| GET | `/api/tasks/{id}/screenshots/{step}` | utilisateur | Capture PNG d'une étape |
| GET | `/api/tasks/{id}/context` | utilisateur | → `{"text"}` : contexte ajouté à la consigne au démarrage |
| GET | `/api/tasks/{id}/files` | utilisateur | → `[{"name", "size", "source": "fourni" \| "telecharge"}]` |
| GET | `/api/tasks/{id}/files/{source}/{name}` | utilisateur | Le fichier (pièce jointe ou téléchargement de l'agent) |

### 4.3 Agents

| Méthode | Route | Accès | Corps → Réponse |
|---|---|---|---|
| GET | `/api/agents` | utilisateur | → liste des agents, avec `last_run`, `run_count`, `schedule_label`, `attachments` |
| POST | `/api/agents` | utilisateur | Agent (ci-dessous) → agent créé |
| PATCH | `/api/agents/{id}` | utilisateur | Champs à modifier → agent |
| DELETE | `/api/agents/{id}` | utilisateur | → `{"ok": true}` ; l'historique des exécutions est conservé |
| POST | `/api/agents/{id}/run` | utilisateur | `{"headless": true?}` → exécution créée |
| GET | `/api/agents/{id}/files` | utilisateur | → pièces jointes `[{"name", "size"}]` |
| POST | `/api/agents/{id}/files` | utilisateur | Corps brut du fichier + en-tête `X-File-Name` (§4.6) → `{"name", "size"}` ; 20 au plus |
| DELETE | `/api/agents/{id}/files/{name}` | utilisateur | → `{"ok": true}` |
| GET | `/api/variables` | utilisateur | → variables utilisables dans une consigne (`{mois_precedent}`…) |
| POST | `/api/variables/preview` | utilisateur | `{"instructions"}` → `{"text"}` avec les variables remplies |

Corps d'un agent :

```json
{
  "name": "Relevés bancaires",
  "instructions": "Télécharge le relevé du {debut_mois_precedent} au {fin_mois_precedent}.",
  "max_steps": 40,
  "allowed_domains": ["app.qonto.com"],
  "approval_mode": false,
  "schedule": {"kind": "monthly", "time": "08:00", "monthday": 2},
  "schedule_enabled": true
}
```

`schedule` : `{"kind": "daily"|"weekdays", "time"}`, `{"kind": "weekly", "time", "days": [0..6]}` (0 = lundi)
ou `{"kind": "monthly", "time", "monthday": 1..31 | -1}` (-1 = dernier jour) ; `null` = non planifié.
`allowed_domains` accepte des adresses ou des hôtes (`*.exemple.fr` pour les sous-domaines).

### Vue « Tout le cabinet »

`GET /api/agents`, `/api/chains`, `/api/tasks` et `/api/chain-runs` acceptent `?scope=all` : les éléments de tous les
utilisateurs, avec `owner`, `owner_name` et `mine`. La lecture d'une exécution d'un collègue (`GET /api/tasks/{id}`,
`/events`, `/live`, `/files`, `/screenshots`, `/context`, `GET /api/chain-runs/{id}`) est permise ; toute action
(lancer, modifier, supprimer, arrêter, relancer, valider, pièces jointes) reste réservée au propriétaire et répond
`404` sinon. Le serveur MCP ne montre que les éléments de l'utilisateur.

### 4.4 Connexions (navigateur de l'utilisateur)

| Méthode | Route | Accès | Corps → Réponse |
|---|---|---|---|
| GET | `/api/connections` | utilisateur | → `{"open", "browser", "busy"}` |
| GET | `/api/connections/sites` | utilisateur | → `{"sites": [...], "suggestions": [...]}` |
| POST | `/api/connections/sites` | utilisateur | `{"name", "url"}` → site ; 30 au plus |
| PATCH | `/api/connections/sites/{id}` | utilisateur | `{"name", "url"}` → site |
| DELETE | `/api/connections/sites/{id}` | utilisateur | → `{"ok": true}` |
| POST | `/api/connections/open` | utilisateur | `{"site_id"}` ou `{"url"}` → `{"open": true}` ; `409` si une exécution utilise le navigateur |
| GET | `/api/connections/screen` | utilisateur | Capture JPEG du navigateur (`204` s'il est fermé) ; en-têtes `X-Page-Url`, `X-Page-Title` |
| POST | `/api/connections/action` | utilisateur | `{"type": "click", "x": 0..1, "y": 0..1}` · `{"type": "type", "text"}` · `{"type": "key", "key": "Enter"}` · `{"type": "scroll", "dy"}` · `{"type": "goto", "url"}` · `{"type": "back"}` |
| POST | `/api/connections/close` | utilisateur | → `{"open": false}` |
| POST | `/api/connections/reset` | utilisateur | Efface le profil (déconnexion de tous les sites) |

Les adresses doivent être `http(s)` avec un nom de domaine public : `localhost`, adresses IP privées et
`.local` sont refusés (le navigateur tourne sur le serveur).

**Applications connectées (MCP)**

| Méthode | Route | Accès | Corps → Réponse |
|---|---|---|---|
| GET | `/api/integrations` | utilisateur | → `{"catalog": [...], "connections": [...], "allow_custom"}` ; jamais de jeton |
| POST | `/api/integrations/connect` | utilisateur | `{"kind": "gmail", "read_only": true}` → `{"url"}` : y envoyer l'utilisateur (Google/Slack) |
| GET | `/api/integrations/callback` | session | Retour de Google/Slack ; redirige vers `/?app_ok=…#/connexions` ou `/?app_error=…` |
| POST | `/api/integrations/custom` | utilisateur | `{"name", "url" (https), "token", "read_only"}` ; testé avant l'enregistrement ; si autorisé |
| PATCH | `/api/integrations/{id}` | utilisateur | `{"enabled"?, "name"?}` |
| POST | `/api/integrations/{id}/test` | utilisateur | → `{"ok", "tools": [{"name", "description", "read_only"}]}` |
| DELETE | `/api/integrations/{id}` | utilisateur | Supprime et révoque l'accès chez Google/Slack |

### 4.5 Contexte

| Méthode | Route | Accès | Corps → Réponse |
|---|---|---|---|
| GET | `/api/context` | utilisateur | → `{"cabinet", "personal", "can_edit_cabinet", "limits"}` |
| PUT | `/api/context/cabinet` | admin | `{"instructions", "glossary": [{"term", "definition"}], "sites": [{"site", "notes"}]}` |
| PUT | `/api/context/personal` | utilisateur | Même corps |
| POST | `/api/context/preview` | utilisateur | `{"task", "allowed_domains"?}` → `{"text", "chars", "tokens"}` |

### 4.6 Fichiers envoyés à l'application

Les fichiers sont envoyés **en corps brut** (pas de multipart), le nom dans l'en-tête `X-File-Name`
(encodé URL). 25 Mo au plus ; extensions : pdf, png, jpg, jpeg, gif, webp, tif, tiff, heic, csv, xls,
xlsx, ods, doc, docx, odt, txt, xml, json, zip, ofx, qif.

| Méthode | Route | Accès | Usage |
|---|---|---|---|
| POST | `/api/uploads` | utilisateur | Pièce jointe d'une tâche ponctuelle → `{"id", "name", "size"}`, à passer dans `attachments` de `POST /api/tasks` (valable 24 h) |

### 4.7 Clés d'API

| Méthode | Route | Accès | Corps → Réponse |
|---|---|---|---|
| GET | `/api/tokens` | utilisateur | → `[{"id", "name", "prefix", "created_at", "last_used_at"}]` |
| POST | `/api/tokens` | utilisateur | `{"name"}` → mêmes champs + `"token"` (**seule fois où la clé est visible**) |
| DELETE | `/api/tokens/{id}` | utilisateur | → `{"ok": true}` |

### 4.8 Administration

| Méthode | Route | Accès | Corps → Réponse |
|---|---|---|---|
| GET | `/api/admin/users` | admin | → comptes (`username`, `name`, `email`, `admin`, `temporary_password`, `me`) |
| POST | `/api/admin/users` | admin | `{"username", "name", "email", "password", "admin"}` ; le mot de passe est provisoire |
| PATCH | `/api/admin/users/{username}` | admin | `{"name"?, "email"?, "password"?, "admin"?}` |
| DELETE | `/api/admin/users/{username}` | admin | Supprime le compte et révoque ses clés d'API |
| GET | `/api/admin/settings` | admin | → réglages d'IA ; les clés des fournisseurs ne sont jamais renvoyées (`{"set", "hint": "…0c54"}`) |
| PUT | `/api/admin/settings` | admin | `{"provider", "model", "use_vision", "deepseek_endpoint", "api_keys": {...}, "clear_keys": [...]}` |
| POST | `/api/admin/settings/test` | admin | Même corps → `{"ok", "reply"}` après un court échange avec le modèle |
| GET | `/api/admin/integrations` | admin | → applications proposées, OAuth Google/Slack (`secret_set`, `secret_hint`), `redirect_uri` |
| PUT | `/api/admin/integrations` | admin | `{"oauth": {"google": {"client_id", "client_secret"}, "slack": {...}}, "enabled": [...], "allow_custom"}` ; secret vide = inchangé |

### 4.9 Pages (navigateur)

`GET /` (application), `GET /login`, `GET /admin` redirigent selon la session. `GET /static/*` sert la
feuille de style. La documentation interactive de FastAPI (`/docs`) est désactivée.

## 5. Flux d'événements d'une exécution

`GET /api/tasks/{id}/events` est un flux **Server-Sent Events** : il rejoue les événements passés puis
envoie les nouveaux, et se termine après `done`. Un commentaire `: keep-alive` part toutes les 15 s.
Chaque message `data:` est un objet JSON avec `type` et `time` :

| `type` | Champs |
|---|---|
| `status` | `status` |
| `step` | `step`, `url`, `title`, `evaluation`, `memory`, `next_goal`, `actions: [{"name", "params"}]`, `screenshot` (URL) |
| `info` | `message` (file d'attente, arrêt, site bloqué…) |
| `error` | `message` (avec un conseil en français quand l'erreur est connue) |
| `approval` | `id`, `description`, `asked_at` |
| `approval_result` | `approved`, `comment`, `by` |
| `upload` | `name`, `host` |
| `app_call` | `app`, `kind`, `tool`, `arguments` (JSON tronqué), `ok`, `preview` (début de la réponse) |
| `done` | `status`, `result` |

Sans SSE, interrogez `GET /api/tasks/{id}` toutes les quelques secondes jusqu'à un statut final.

## 6. Serveur MCP

L'application expose un serveur **MCP** (Model Context Protocol) pour qu'un assistant IA la pilote.

| | |
|---|---|
| Adresse | `https://<serveur>/mcp` |
| Transport | Streamable HTTP, réponses JSON (pas de flux SSE du serveur vers le client, pas d'identifiant de session) |
| Versions du protocole | `2025-06-18`, `2025-03-26`, `2024-11-05` |
| Authentification | **OAuth 2.1** (claude.ai, ChatGPT… : connexion en un clic) **ou** clé d'API `Authorization: Bearer ac_…` ; sans jeton : `401` + `WWW-Authenticate: Bearer resource_metadata="…"` |
| Capacités | `tools` uniquement (pas de ressources ni de prompts) |
| Sécurité | En-tête `Origin` d'un autre site refusé (`403`) ; chaque appel agit avec les droits du propriétaire de la clé |

### Outils

| Outil | Arguments | Nature |
|---|---|---|
| `list_agents` | — | lecture |
| `list_variables` | — | lecture |
| `create_agent` | `name`, `instructions`, `max_steps`?, `allowed_domains`?, `approval_mode`?, `schedule`?, `schedule_enabled`? | modifie |
| `update_agent` | `agent_id` + champs à changer | modifie |
| `run_agent` | `agent_id` | agit sur les sites |
| `run_task` | `task`, `max_steps`?, `allowed_domains`?, `approval_mode`? | agit sur les sites |
| `list_runs` | `limit`? (1–50, 10), `status`? | lecture |
| `get_run` | `run_id` | lecture |
| `stop_run` | `run_id` | modifie |
| `list_chains` | — | lecture |
| `create_chain` | `name`, `steps` [{`agent_id`, `on_failure`?}], `schedule`?, `schedule_enabled`? | modifie |
| `update_chain` | `chain_id` + champs à changer | modifie |
| `run_chain` | `chain_id` | agit sur les sites |
| `get_chain_run` | `chain_run_id` | lecture |
| `stop_chain_run` | `chain_run_id` | modifie |
| `answer_approval` | `run_id`, `approved`, `comment`? | agit sur les sites |
| `get_documentation` | `topic`? | lecture |
| `get_context` | — | lecture |
| `preview_context` | `task`, `allowed_domains`? | lecture |
| `update_personal_context` | `add_rules`?, `instructions`?, `set_terms`?, `remove_terms`?, `set_sites`?, `remove_sites`? | modifie |
| `update_firm_context` | idem — **administrateurs** | modifie |

Le contexte se modifie par **changements ciblés** (ajouter des règles, ajouter/remplacer/retirer un mot ou une note de
site) : un assistant ne peut pas effacer tout le contexte par erreur. `instructions` remplace le texte des règles en
entier, à n'utiliser qu'après l'avoir relu. La modification est signée « <utilisateur> via MCP » dans la page Contexte.

« Nature » correspond aux annotations MCP (`readOnlyHint`, `destructiveHint`, `openWorldHint`) que les
clients utilisent pour demander confirmation. Aucune suppression n'est possible par MCP. Les agents et
chaînes créés ou modifiés par MCP portent `created_via` / `updated_via` = `mcp` et un badge dans l'application.

Les résultats sont renvoyés en `structuredContent` et en texte JSON. Une erreur métier (exécution
introuvable, aucune validation en attente…) est un résultat avec `isError: true` ; un outil inconnu
ou des arguments mal formés renvoient une erreur JSON-RPC `-32602`.

Les instructions envoyées à l'initialisation demandent à l'assistant de suivre une exécution avec
`get_run` jusqu'à un statut final, et de **n'appeler `answer_approval` qu'avec la décision explicite
de l'utilisateur**.

### Documentation pour les assistants IA

- **`GET /llms.txt`** (public, format [llms.txt](https://llmstxt.org)) : présentation, bonnes pratiques et outils MCP ;
  **`GET /llms-full.txt`** : tout (agents, variables, planification, chaînes, exécutions, MCP, API REST avec exemples).
  Générés à partir du code : outils, variables et routes sont toujours à jour. Aucune donnée ni clé.
- Dans le serveur MCP : outil **`get_documentation`** (`topic` : `overview`, `agents`, `chains`, `runs`, `mcp`, `api`)
  et les mêmes textes en **ressources** `autocollab://docs/<sujet>` (`resources/list`, `resources/read`).

### OAuth

Ce que les clients MCP découvrent seuls à partir du `401` :

| Route | Rôle |
|---|---|
| `GET /.well-known/oauth-protected-resource` (et `…/mcp`) | Métadonnées de la ressource (RFC 9728) : `resource` = `<base>/mcp`, serveur d'autorisation = `<base>` |
| `GET /.well-known/oauth-authorization-server` (et `/.well-known/openid-configuration`) | Métadonnées du serveur (RFC 8414) |
| `POST /oauth/register` | Enregistrement dynamique (RFC 7591) : `redirect_uris` en https, `http://localhost`/`127.0.0.1`, ou schéma d'application ; client public (`none`) ou avec secret |
| `GET /oauth/authorize` | Page « Autoriser … » (connexion d'abord si besoin) ; `response_type=code`, **PKCE S256 obligatoire**, `state`, `resource` |
| `POST /oauth/token` | `authorization_code` (+ `code_verifier`) ou `refresh_token` ; secret en `client_secret_post` ou `client_secret_basic` |
| `POST /oauth/revoke` | Révocation (RFC 7009) : met fin à toute l'autorisation |

- Code : 10 min, usage unique. Jeton d'accès `aco_…` : 1 h, **valable uniquement sur `/mcp`**.
  Jeton de renouvellement `acr_…` : 30 jours, **renouvelé à chaque usage** (l'ancien est invalidé).
- Codes et jetons sont stockés hachés (SHA-256). L'adresse de base vient de `PUBLIC_URL` (https obligatoire
  pour claude.ai et ChatGPT).
- Chaque autorisation est listée dans **Développeurs › MCP › Applications autorisées**
  (`GET /api/oauth/grants`, `DELETE /api/oauth/grants/{id}`) ; supprimer un compte révoque tout.
- Les clés d'API `ac_…` restent acceptées sur `/mcp` et sur l'API REST.

### Configuration des clients

**claude.ai** : Paramètres › Connecteurs › Ajouter un connecteur personnalisé › URL `https://<serveur>/mcp`,
puis « Se connecter » et « Autoriser ».

**ChatGPT** : Paramètres › Applications et connecteurs › Paramètres avancés › Mode développeur, puis
« Créer » : URL `https://<serveur>/mcp`, authentification OAuth.

**Claude Code**

```bash
claude mcp add --transport http autocollab https://<serveur>/mcp \
  --header "Authorization: Bearer <VOTRE_CLÉ>"
```

**Claude Desktop** (fichier `claude_desktop_config.json`, via le pont `mcp-remote`, Node.js requis)

```json
{
  "mcpServers": {
    "autocollab": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://<serveur>/mcp", "--header", "Authorization:${AUTH}"],
      "env": { "AUTH": "Bearer <VOTRE_CLÉ>" }
    }
  }
}
```

**n8n** — nœud *MCP Client Tool* : Endpoint `https://<serveur>/mcp`, Server Transport *HTTP Streamable*,
Authentication *Header Auth* (`Authorization` = `Bearer <VOTRE_CLÉ>`).

La page **Développeurs** de l'application affiche ces configurations avec l'adresse du serveur.

### Échange type

```http
POST /mcp
Authorization: Bearer ac_…
Content-Type: application/json
Accept: application/json, text/event-stream

{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
 "params": {"name": "run_task", "arguments": {"task": "Va sur service-public.fr et trouve la date limite de la CA12"}}}
```

```json
{"jsonrpc": "2.0", "id": 1, "result": {
  "content": [{"type": "text", "text": "{\"run\": {\"id\": \"20261011-…\", \"status\": \"en_attente\", …}}"}],
  "structuredContent": {"run": {"id": "20261011-…", "status": "en_attente", "link": "/#/executions/20261011-…"}},
  "isError": false}}
```

Les notifications (`notifications/initialized`…) reçoivent `202 Accepted` sans corps ; les lots
(tableau JSON) sont acceptés.

## 7. Exemples

### curl : lancer une tâche et la suivre

```bash
KEY="ac_…"; BASE="https://<serveur>"
RUN=$(curl -s -X POST "$BASE/api/tasks" -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"task": "Va sur service-public.fr et trouve la date limite de la CA12"}' | jq -r .id)
curl -s "$BASE/api/tasks/$RUN" -H "Authorization: Bearer $KEY" | jq '{status, result}'
```

### Python : lancer un agent avec une pièce jointe, attendre le résultat

```python
import time, urllib.parse, requests

BASE, KEY = "https://<serveur>", "ac_…"
H = {"Authorization": f"Bearer {KEY}"}

with open("Releve.pdf", "rb") as f:
    upload = requests.post(f"{BASE}/api/uploads", data=f,
                           headers={**H, "X-File-Name": urllib.parse.quote("Releve.pdf")}).json()

run = requests.post(f"{BASE}/api/tasks", headers=H,
                    json={"task": "Importe le relevé fourni dans Pennylane", "attachments": [upload["id"]]}).json()

while run["status"] in ("en_attente", "en_cours", "a_valider"):
    if run["status"] == "a_valider":
        print("Validation demandée :", run["approval"]["description"])  # à décider par un humain
    time.sleep(5)
    run = requests.get(f"{BASE}/api/tasks/{run['id']}", headers=H).json()
print(run["status"], run["result"])
```

### n8n sans MCP

1. Nœud *HTTP Request* `POST /api/agents/<id>/run` (Header Auth `Authorization: Bearer …`).
2. Boucle *Wait* (30 s) + *HTTP Request* `GET /api/tasks/{{$json.id}}` jusqu'à un statut final.
3. Exploiter `result`, ou récupérer les fichiers via `/api/tasks/{id}/files`.

## 8. Organisation du code

| Fichier | Rôle |
|---|---|
| `run.py` | Démarrage (`--reload` : rechargeur maison compatible Playwright sous Windows) |
| `app/main.py` | Routes FastAPI, contrôle d'accès, validation des entrées |
| `app/runner.py` | Exécution d'un agent (browser-use), file d'attente, événements, validation humaine, envoi de fichiers, verrou de navigation |
| `app/auth.py` | Comptes, mots de passe (scrypt), cookie signé, clés d'API, anti-force brute |
| `app/tokens.py` | Clés d'API personnelles |
| `app/mcp.py` | Serveur MCP (JSON-RPC, outils) |
| `app/assistant.py`, `static/assistant.js` | Assistant intégré (panneau latéral) : outils MCP en lecture seule, conversations par utilisateur |
| `app/agents.py` | Agents, variables de date, sites autorisés |
| `app/schedule.py` | Fréquences et planificateur |
| `app/browsers.py` | Profils de navigateur par utilisateur, choix du binaire, ports |
| `app/connections.py` | « Mes connexions » : navigateur piloté depuis la page |
| `app/sites.py` | Liste des connexions de chaque utilisateur |
| `app/context.py` | Contexte du cabinet et personnel ajouté aux consignes |
| `app/files.py` | Pièces jointes et fichiers des exécutions |
| `app/settings.py`, `app/llm.py` | Réglages d'IA de l'administrateur, création du modèle |
| `app/db.py` | Schéma SQLite et migrations automatiques |
| `static/` | Interface (HTML/JS sans framework, `app.css` commun) |

**Ajouter une route** : la déclarer dans `app/main.py` avec `user: str = Depends(current_user)` (ou
`current_admin`), vérifier que la ressource appartient à `user` (sinon `404`), valider le corps avec un
modèle Pydantic, et l'ajouter à ce document. **Ajouter un outil MCP** : le décrire dans `TOOLS` et le
traiter dans `call_tool` (`app/mcp.py`).

**Développement local** : `python run.py --reload` redémarre le serveur à chaque modification de
`app/` ; les pages de `static/` sont relues à chaque chargement.
