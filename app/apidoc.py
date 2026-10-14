"""Content of the in-app API reference (page Développeurs › Référence API).

The list of endpoints comes from the application's real routes (see reference()), so a new
route always shows up; the entries below add the French description and examples. A route
without an entry is listed with a generic text, which is the cue to document it here.
"""

from fastapi.routing import APIRoute

GROUPS = [
    ("compte", "Session et compte"),
    ("taches", "Tâches et exécutions"),
    ("agents", "Agents"),
    ("chaines", "Chaînes"),
    ("fichiers", "Fichiers"),
    ("connexions", "Connexions"),
    ("contexte", "Contexte"),
    ("assistant", "Assistant intégré"),
    ("cles", "Clés d'API"),
    ("admin", "Administration"),
    ("autres", "Autres"),
]

RUN = {"id": "20261011-080000-3e031c", "task": "Va sur Pennylane et liste les FNP de septembre 2026", "agent_id": None,
       "agent_name": None, "status": "en_attente", "created_at": "2026-10-11T08:00:00", "finished_at": None, "result": None,
       "steps": 0, "max_steps": 40, "queue_position": 1, "trigger": "manuel", "approval": None, "files": 0, "uploads": []}
AGENT = {"name": "Relevés bancaires", "instructions": "Télécharge le relevé du {debut_mois_precedent} au {fin_mois_precedent}.",
         "max_steps": 40, "allowed_domains": ["app.qonto.com"], "approval_mode": False,
         "schedule": {"kind": "monthly", "time": "08:00", "monthday": 2}, "schedule_enabled": True}

DOCS: dict[str, dict] = {
    # --- compte
    "POST /api/login/2fa": {"group": "compte", "summary": "Deuxième étape de connexion (code)", "public": True,
                            "description": "Après un mot de passe correct sur un compte avec double authentification : le ticket reçu et le code à 6 chiffres (ou un code de secours).",
                            "body": {"ticket": "…", "code": "123456"}},
    "POST /api/me/2fa/setup": {"group": "compte", "summary": "Préparer la double authentification", "description": "Nouveau secret et son QR code ; rien ne change avant la confirmation.", "response": {"secret": "ABCD EFGH …", "uri": "otpauth://totp/…", "qr_svg": "<svg …>"}},
    "POST /api/me/2fa/enable": {"group": "compte", "summary": "Activer la double authentification", "body": {"code": "123456"}, "response": {"recovery_codes": ["abcd-efgh"], "enabled": True}},
    "POST /api/me/2fa/disable": {"group": "compte", "summary": "Désactiver la double authentification", "body": {"password": "…", "code": "123456"}},
    "POST /api/me/2fa/recovery": {"group": "compte", "summary": "Nouveaux codes de secours", "body": {"password": "…", "code": "123456"}},
    "PUT /api/admin/security": {"group": "admin", "summary": "Rendre la double authentification obligatoire", "body": {"require_2fa": "admins"},
                                "description": "none, admins ou all. L'administrateur doit l'avoir activée lui-même."},
    "POST /api/login": {"group": "compte", "summary": "Se connecter", "public": True,
        "description": "Ouvre une session (cookie). Accepte l'identifiant ou l'e-mail. 5 échecs en 15 min bloquent (429). Pour un script, préférez une clé d'API.",
        "body": {"username": "jdupont", "password": "••••••••••"}, "response": {"username": "jdupont", "name": "Jean Dupont", "must_change_password": False}},
    "POST /api/logout": {"group": "compte", "summary": "Se déconnecter", "public": True, "response": {"ok": True}},
    "GET /api/me": {"group": "compte", "summary": "Mon compte", "response": {"username": "jdupont", "name": "Jean Dupont", "email": "jean.dupont@exemple.fr", "admin": False, "must_change_password": False, "organisation": "Cabinet Exemple"}},
    "GET /api/branding": {"group": "compte", "summary": "Nom de l'organisation", "public": True, "response": {"organisation": "Cabinet Exemple"}},
    "PATCH /api/me": {"group": "compte", "summary": "Mes préférences", "description": "Langue de l'interface : fr ou en.", "body": {"lang": "en"}, "response": {"lang": "en"}},
    "POST /api/me/password": {"group": "compte", "summary": "Changer mon mot de passe",
        "description": "10 caractères minimum, différent de l'actuel. Déconnecte les autres sessions et renvoie un nouveau cookie.",
        "body": {"current_password": "••••••••••", "new_password": "••••••••••"}, "response": {"ok": True}},
    "GET /api/config": {"group": "compte", "summary": "Réglages visibles par tous",
        "response": {"provider": "anthropic", "model": "claude-sonnet-5-5", "vision": True, "headless": True, "max_steps": 40, "browser": "Chromium (intégré)", "approval_timeout": 60}},
    "GET /api/variables": {"group": "agents", "summary": "Variables de date disponibles", "response": {"mois_precedent": "mois précédent (septembre 2026)"}},
    "GET /api/templates": {"group": "agents", "summary": "Modèles d'agents",
        "description": "Brouillons prêts à l'emploi, par catégorie. Ce qui est marqué [À COMPLÉTER : …] est à remplir avant d'enregistrer l'agent (POST /api/agents). estimate : crédits d'une exécution type (typical_steps) et au plus (max_steps), pour le modèle d'IA actuel.",
        "response": {"categories": [{"id": "compta", "label": "Comptabilité"}], "credits_per_step": 1.6,
                     "templates": [{"id": "justificatifs-manquants", "category": "compta", "name": "Justificatifs manquants du mois",
                                    "summary": "Liste les transactions bancaires de Pennylane sans justificatif sur le mois précédent.",
                                    "instructions": "Sur Pennylane, ouvre le dossier [À COMPLÉTER : nom du client]…",
                                    "allowed_domains": ["*.pennylane.com"], "approval_mode": False, "max_steps": 40, "typical_steps": 15,
                                    "to_complete": True, "estimate": {"credits": 24, "max_credits": 64}}]}},
    "POST /api/variables/preview": {"group": "agents", "summary": "Remplir les variables d'une consigne",
        "body": {"instructions": "Relevés de {mois_precedent}"}, "response": {"text": "Relevés de septembre 2026"}},
    # --- tâches
    "GET /api/tasks": {"group": "taches", "summary": "Lister mes exécutions", "description": "Plus récentes d'abord. Filtres : scope (mine|all), kind (agent|task|chain), status (dont « actives »), q (nom, consigne, identifiant, modèle), since (date ISO). Avec offset et limit (200 au plus), la réponse devient {\"items\", \"total\"} : une page. light=true ne compte pas les fichiers (plus rapide).", "response": [RUN]},
    "POST /api/tasks": {"group": "taches", "summary": "Lancer une tâche ponctuelle",
        "description": "Asynchrone : renvoie l'exécution créée (en_attente). Suivez-la avec GET /api/tasks/{id} ou le flux d'événements. attachments = identifiants renvoyés par POST /api/uploads ; rerun_of reprend les pièces jointes d'une exécution.",
        "body": {"task": "Va sur service-public.fr et trouve la date limite de la CA12", "max_steps": 40, "attachments": []}, "response": RUN},
    "GET /api/tasks/{task_id}": {"group": "taches", "summary": "Détail d'une exécution", "description": "Résumé plus la liste complète des événements (onglet Événements).",
        "response": {**RUN, "status": "termine", "result": "Date limite : 3 mai 2027", "events": [{"type": "done", "time": "2026-10-11T08:03:12", "status": "termine"}]}},
    "POST /api/tasks/{task_id}/stop": {"group": "taches", "summary": "Arrêter ou retirer de la file", "description": "L'agent s'arrête après l'étape en cours ; une exécution en attente quitte la file immédiatement.", "response": {**RUN, "status": "arrete"}},
    "POST /api/tasks/{task_id}/approval": {"group": "taches", "summary": "Répondre à une validation",
        "description": "Pour une exécution au statut a_valider. 409 si aucune validation n'est en attente.", "body": {"approved": True, "comment": "ok, vas-y"}, "response": {**RUN, "status": "en_cours"}},
    "GET /api/tasks/{task_id}/events": {"group": "taches", "summary": "Flux d'événements (SSE)", "description": "Server-Sent Events : rejoue l'historique puis diffuse en direct jusqu'à « done ». Voir l'onglet Événements.", "binary": "text/event-stream"},
    "GET /api/tasks/{task_id}/live": {"group": "taches", "summary": "Capture en direct", "description": "PNG de l'écran de l'agent (204 si aucune). En-têtes X-Page-Url et X-Page-Title (encodés URL).", "binary": "image/png"},
    "GET /api/tasks/{task_id}/screenshots/{step}": {"group": "taches", "summary": "Capture d'une étape", "binary": "image/png"},
    "GET /api/tasks/{task_id}/context": {"group": "taches", "summary": "Contexte utilisé par l'exécution", "response": {"text": "CONTEXTE DE L'ORGANISATION (à respecter) :\n…"}},
    "GET /api/tasks/{task_id}/files": {"group": "fichiers", "summary": "Fichiers d'une exécution",
        "description": "source = fourni (pièce jointe) ou telecharge (téléchargé par l'agent).", "response": [{"name": "Facture_FR600MXL.pdf", "size": 51234, "source": "telecharge"}]},
    "GET /api/tasks/{task_id}/files/{source}/{name}": {"group": "fichiers", "summary": "Télécharger un fichier d'une exécution", "binary": "fichier"},
    # --- agents
    "GET /api/agents": {"group": "agents", "summary": "Lister mes agents", "response": [{"id": "a1b2c3d4e5f6", **AGENT, "schedule_label": "Le 2 de chaque mois à 08h00", "next_run_at": "2026-11-02T08:00:00", "attachments": [], "last_run": None, "run_count": 0}]},
    "POST /api/agents": {"group": "agents", "summary": "Créer un agent",
        "description": "schedule : {kind: daily|weekdays, time} · {kind: weekly, time, days: [0..6]} (0 = lundi) · {kind: monthly, time, monthday: 1..31 ou -1} · null = non planifié.",
        "body": AGENT, "response": {"id": "a1b2c3d4e5f6", **AGENT}},
    "PATCH /api/agents/{agent_id}": {"group": "agents", "summary": "Modifier un agent", "description": "Envoyez seulement les champs à changer.", "body": {"schedule_enabled": False}, "response": {"id": "a1b2c3d4e5f6", **AGENT, "schedule_enabled": False}},
    "DELETE /api/agents/{agent_id}": {"group": "agents", "summary": "Supprimer un agent", "description": "L'historique de ses exécutions est conservé.", "response": {"ok": True}},
    "POST /api/agents/{agent_id}/run": {"group": "agents", "summary": "Lancer un agent", "body": {"headless": True}, "response": {**RUN, "agent_id": "a1b2c3d4e5f6", "agent_name": "Relevés bancaires"}},
    "GET /api/agents/{agent_id}/files": {"group": "fichiers", "summary": "Pièces jointes d'un agent", "response": [{"name": "Modele_relance.docx", "size": 18230}]},
    "POST /api/agents/{agent_id}/files": {"group": "fichiers", "summary": "Ajouter une pièce jointe à un agent", "upload": True,
        "description": "Corps brut du fichier, nom dans l'en-tête X-File-Name (encodé URL). 25 Mo et 20 fichiers au plus.", "response": {"name": "Modele_relance.docx", "size": 18230}},
    "DELETE /api/agents/{agent_id}/files/{name}": {"group": "fichiers", "summary": "Retirer une pièce jointe d'un agent", "response": {"ok": True}},
    "POST /api/uploads": {"group": "fichiers", "summary": "Déposer une pièce jointe de tâche", "upload": True,
        "description": "Corps brut du fichier, nom dans X-File-Name. Renvoie un identifiant à passer dans attachments de POST /api/tasks (valable 24 h). Types : PDF, images, Excel/CSV, Word, texte, XML, ZIP, OFX/QIF ; 25 Mo.",
        "response": {"id": "9f86d081884c7d65", "name": "Releve.pdf", "size": 182044}},
    # --- chaînes
    "GET /api/chains": {"group": "chaines", "summary": "Lister mes chaînes", "response": [{"id": "b7c8d9e0f1a2", "name": "Clôture mensuelle", "steps": [{"agent_id": "a1b2c3d4e5f6", "agent_name": "Relevés bancaires", "on_failure": "stop"}], "schedule_label": "Non planifié", "last_run": None, "run_count": 0}]},
    "POST /api/chains": {"group": "chaines", "summary": "Créer une chaîne",
        "description": "Les agents s'exécutent dans l'ordre. Chacun reçoit le résultat du précédent dans la variable {resultat_precedent} et ses fichiers téléchargés en pièces jointes. on_failure : stop (arrêter la chaîne, par défaut) ou continue. schedule : même format que pour un agent.",
        "body": {"name": "Clôture mensuelle", "steps": [{"agent_id": "a1b2c3d4e5f6", "on_failure": "stop"}, {"agent_id": "f6e5d4c3b2a1", "on_failure": "stop"}], "schedule": None, "schedule_enabled": False}},
    "PATCH /api/chains/{chain_id}": {"group": "chaines", "summary": "Modifier une chaîne", "body": {"name": "Clôture du mois"}},
    "DELETE /api/chains/{chain_id}": {"group": "chaines", "summary": "Supprimer une chaîne", "response": {"ok": True}},
    "POST /api/chains/{chain_id}/run": {"group": "chaines", "summary": "Lancer une chaîne", "description": "Asynchrone ; 409 si la chaîne est déjà en cours.",
        "response": {"id": "20261011-080000-c4a1e2", "chain_name": "Clôture mensuelle", "status": "en_cours", "current_step": 0, "done_steps": 0, "total_steps": 2, "steps": [{"agent_name": "Relevés bancaires", "status": "en_attente", "run_id": "20261011-080000-3e031c"}]}},
    "GET /api/chain-runs": {"group": "chaines", "summary": "Lister mes exécutions de chaînes"},
    "GET /api/chain-runs/{chain_run_id}": {"group": "chaines", "summary": "Progression d'une exécution de chaîne",
        "description": "Statut de la chaîne (en_cours, termine, echec, arrete, interrompu) et de chaque étape (a_venir, en_attente, en_cours, a_valider, termine, echec, arrete, ignore), avec run_id pour ouvrir l'exécution de l'étape."},
    "POST /api/chain-runs/{chain_run_id}/stop": {"group": "chaines", "summary": "Arrêter une exécution de chaîne", "description": "Arrête l'étape en cours ; les suivantes sont ignorées."},
    # --- connexions
    "GET /api/connections": {"group": "connexions", "summary": "État de mon navigateur", "response": {"open": False, "browser": "Chromium (intégré)", "busy": False}},
    "GET /api/connections/sites": {"group": "connexions", "summary": "Mes sites", "response": {"sites": [{"id": "c0ffee123456", "name": "Pennylane", "url": "https://app.pennylane.com", "last_opened_at": None}], "suggestions": []}},
    "POST /api/connections/sites": {"group": "connexions", "summary": "Ajouter un site", "body": {"name": "Ma banque", "url": "https://www.mabanque.fr/pro"}, "response": {"id": "c0ffee123456", "name": "Ma banque", "url": "https://www.mabanque.fr/pro"}},
    "PATCH /api/connections/sites/{site_id}": {"group": "connexions", "summary": "Modifier un site", "body": {"name": "Banque pro", "url": "https://www.mabanque.fr/pro"}},
    "DELETE /api/connections/sites/{site_id}": {"group": "connexions", "summary": "Retirer un site", "response": {"ok": True}},
    "GET /api/integrations": {"group": "connexions", "summary": "Applications connectées (MCP)", "description": "Applications proposées par l'organisation et connexions de l'utilisateur. Les jetons ne sont jamais renvoyés.",
                              "response": {"catalog": [{"kind": "gmail", "name": "Gmail", "provider": "google", "available": True, "can_write": True}],
                                           "connections": [{"id": "a1b2c3d4e5f6", "kind": "gmail", "name": "Gmail", "account": "prenom@exemple.fr", "read_only": True, "enabled": True, "last_used_at": None, "last_error": None}],
                                           "allow_custom": False}},
    "POST /api/integrations/connect": {"group": "connexions", "summary": "Connecter une application", "description": "Renvoie l'adresse de connexion Google ou Slack vers laquelle envoyer l'utilisateur ; il revient ensuite sur « Mes connexions ».",
                                       "body": {"kind": "gmail", "read_only": True}, "response": {"url": "https://accounts.google.com/o/oauth2/v2/auth?…"}},
    "GET /api/integrations/callback": {"group": "connexions", "summary": "Retour de Google ou Slack après connexion", "public": True,
                                       "description": "Appelée par le navigateur de l'utilisateur à la fin de la connexion OAuth ; redirige vers « Mes connexions »."},
    "POST /api/integrations/custom": {"group": "connexions", "summary": "Ajouter un autre serveur MCP", "description": "Si l'administrateur l'autorise. Le serveur est testé avant l'enregistrement.",
                                      "body": {"name": "Notion", "url": "https://mcp.exemple.com/mcp", "token": "…", "read_only": True}},
    "PATCH /api/integrations/{integration_id}": {"group": "connexions", "summary": "Mettre en pause / renommer", "body": {"enabled": False}},
    "POST /api/integrations/{integration_id}/test": {"group": "connexions", "summary": "Tester une application", "response": {"ok": True, "tools": [{"name": "search_threads", "description": "…", "read_only": True}]}},
    "DELETE /api/integrations/{integration_id}": {"group": "connexions", "summary": "Déconnecter une application", "description": "L'accès est aussi révoqué chez Google ou Slack.", "response": {"ok": True}},
    "POST /api/connections/open": {"group": "connexions", "summary": "Ouvrir mon navigateur", "description": "Sur un site de la liste (site_id) ou une adresse (url). 409 si une exécution l'utilise.", "body": {"site_id": "c0ffee123456"}, "response": {"open": True}},
    "GET /api/connections/screen": {"group": "connexions", "summary": "Écran de mon navigateur", "binary": "image/jpeg"},
    "POST /api/connections/action": {"group": "connexions", "summary": "Agir dans mon navigateur",
        "description": "type : click (x, y entre 0 et 1) · type (text) · key (Enter, Tab, Backspace, Escape, flèches…) · scroll (dy) · goto (url) · back.", "body": {"type": "click", "x": 0.42, "y": 0.31}, "response": {"ok": True}},
    "POST /api/connections/close": {"group": "connexions", "summary": "Fermer mon navigateur", "response": {"open": False}},
    "POST /api/connections/reset": {"group": "connexions", "summary": "Réinitialiser mon navigateur", "description": "Efface le profil : déconnexion de tous les sites.", "response": {"ok": True}},
    # --- contexte
    "GET /api/context": {"group": "contexte", "summary": "Lire le contexte", "response": {"cabinet": {"instructions": "Ne supprime jamais de document.", "glossary": [{"term": "FNP", "definition": "Factures non parvenues"}], "sites": []}, "personal": {"instructions": "", "glossary": [], "sites": []}, "can_edit_cabinet": False}},
    "PUT /api/context/cabinet": {"group": "contexte", "summary": "Enregistrer le contexte de l'organisation", "body": {"instructions": "Ne supprime jamais de document.", "glossary": [{"term": "FNP", "definition": "Factures non parvenues"}], "sites": [{"site": "app.pennylane.com", "notes": "Factures fournisseurs : Achats › Factures."}]}},
    "PUT /api/context/personal": {"group": "contexte", "summary": "Enregistrer mon contexte", "body": {"instructions": "Mes clients prioritaires : SARL Dupont.", "glossary": [], "sites": []}},
    "POST /api/context/preview": {"group": "contexte", "summary": "Aperçu du contexte pour une consigne", "body": {"task": "Va sur Pennylane et liste les FNP"}, "response": {"text": "CONTEXTE DE L'ORGANISATION…", "chars": 286, "tokens": 72,
                  "summary": {"cabinet": {"rules": 4, "terms_sent": 3, "terms_total": 3, "sites_kept": ["app.pennylane.com"], "sites_skipped": ["impots.gouv.fr"]},
                              "personal": {"rules": 0, "terms_sent": 0, "terms_total": 0, "sites_kept": [], "sites_skipped": []}}}},
    # --- clés
    "GET /api/tokens": {"group": "cles", "summary": "Mes clés d'API", "response": [{"id": "5e1f0a9b2c3d", "name": "n8n", "prefix": "ac_7zLpLIE", "created_at": "2026-10-11T16:27:00", "last_used_at": None}]},
    "POST /api/tokens": {"group": "cles", "summary": "Créer une clé d'API", "description": "Le champ token n'est renvoyé qu'ici, une seule fois.", "body": {"name": "n8n"}, "response": {"id": "5e1f0a9b2c3d", "name": "n8n", "prefix": "ac_7zLpLIE", "token": "ac_…"}},
    "DELETE /api/tokens/{token_id}": {"group": "cles", "summary": "Révoquer une clé", "response": {"ok": True}},
    "GET /api/openapi.json": {"group": "autres", "summary": "Spécification OpenAPI", "description": "Pour générer un client ou importer dans un outil (Postman, Insomnia…)."},
    "GET /api/docs": {"group": "autres", "summary": "Cette référence, au format JSON"},
    # --- admin
    "GET /api/admin/users": {"group": "admin", "summary": "Lister les comptes", "response": [{"username": "jdupont", "name": "Jean Dupont", "email": "", "admin": False, "temporary_password": True, "me": False}]},
    "POST /api/admin/users": {"group": "admin", "summary": "Créer un compte", "description": "Le mot de passe est provisoire : la personne le remplace à sa première connexion.", "body": {"username": "jdupont", "name": "Jean Dupont", "email": "jean.dupont@exemple.fr", "password": "provisoire-123", "admin": False}},
    "PATCH /api/admin/users/{username}": {"group": "admin", "summary": "Modifier un compte", "body": {"password": "nouveau-provisoire-456"}},
    "DELETE /api/admin/users/{username}": {"group": "admin", "summary": "Supprimer un compte", "description": "Révoque aussi ses clés d'API.", "response": {"ok": True}},
    # --- in-app assistant (read only)
    "POST /api/assistant/chat": {"group": "assistant", "summary": "Poser une question à l'assistant",
        "description": "Réponse en flux (text/event-stream) : conversation, puis tool et delta au fil de l'eau, puis done ou error. "
                       "Lecture seule : l'assistant consulte agents, exécutions, chaînes et contexte de l'utilisateur, sans rien modifier. "
                       "Sans conversation_id, une nouvelle conversation est créée. provider et model (facultatifs) choisissent "
                       "l'un des modèles de GET /api/assistant/models ; sans eux, le modèle choisi dans l'administration.",
        "body": {"message": "Pourquoi ma dernière exécution a-t-elle échoué ?", "conversation_id": None, "page": "/#/executions", "lang": "fr",
                 "provider": "anthropic", "model": "claude-sonnet-5-5"}},
    "GET /api/assistant/models": {"group": "assistant", "summary": "Modèles proposés à l'assistant",
        "description": "Les modèles des fournisseurs dont une clé est enregistrée ; le premier, default: true, est celui de l'administration.",
        "response": [{"provider": "anthropic", "provider_label": "Claude (Anthropic)", "model": "claude-sonnet-5-5", "default": True},
                     {"provider": "anthropic", "provider_label": "Claude (Anthropic)", "model": "claude-haiku-5-5", "default": False}]},
    "GET /api/assistant/conversations": {"group": "assistant", "summary": "Mes conversations avec l'assistant",
        "response": [{"id": "23fe295d2c23", "title": "Pourquoi ma dernière exécution a-t-elle échoué ?", "updated_at": "2026-10-11T23:35:33"}]},
    "GET /api/assistant/conversations/{conversation_id}": {"group": "assistant", "summary": "Lire une conversation",
        "response": {"id": "23fe295d2c23", "title": "…", "messages": [{"role": "user", "content": "…", "tools": [], "created_at": "2026-10-11T23:35:20"},
                                                                       {"role": "assistant", "content": "…", "tools": ["list_runs", "get_run"], "created_at": "2026-10-11T23:35:33"}]}},
    "DELETE /api/assistant/conversations/{conversation_id}": {"group": "assistant", "summary": "Supprimer une conversation", "response": {"ok": True}},
    "GET /api/oauth/grants": {"group": "cles", "summary": "Applications autorisées (OAuth)", "description": "Assistants IA autorisés par l'utilisateur à utiliser le serveur MCP.",
                               "response": [{"id": "d4613efb7cbf", "name": "Claude", "host": "claude.ai", "created_at": "2026-10-11T18:49:05", "last_used_at": None}]},
    "DELETE /api/oauth/grants/{grant_id}": {"group": "cles", "summary": "Révoquer une application autorisée", "description": "Ses jetons cessent immédiatement de fonctionner.", "response": {"ok": True}},
    "GET /api/admin/integrations": {"group": "admin", "summary": "Intégrations (MCP)", "description": "Applications proposées, applications OAuth Google et Slack (codes secrets masqués) et URI de redirection à déclarer."},
    "PUT /api/admin/integrations": {"group": "admin", "summary": "Enregistrer les intégrations", "description": "Un code secret vide garde l'actuel.",
                                    "body": {"oauth": {"google": {"client_id": "….apps.googleusercontent.com", "client_secret": "…"}}, "enabled": ["gmail", "drive", "slack"], "allow_custom": False}},
    "GET /api/admin/security": {"group": "admin", "summary": "État de sécurité", "description": "Origine de la clé maîtresse (variable d'environnement ou fichier, jamais la clé), cookie sécurisé, https.",
                                "response": {"master_key": {"source": "env", "path": None}, "cookie_secure": True, "https": True, "os": "posix"}},
    "GET /api/admin/settings": {"group": "admin", "summary": "Réglages d'IA", "description": "Les clés des fournisseurs ne sont jamais renvoyées, seulement leurs dernières lettres.",
        "response": {"provider": "anthropic", "model": "claude-sonnet-5-5", "use_vision": True, "keys": {"anthropic": {"set": True, "hint": "…6789"}}}},
    "PUT /api/admin/settings": {"group": "admin", "summary": "Enregistrer les réglages d'IA", "body": {"provider": "anthropic", "model": "claude-sonnet-5-5", "use_vision": True, "api_keys": {"anthropic": "sk-ant-…"}, "clear_keys": []}},
    "GET /api/admin/usage": {"group": "admin", "summary": "Consommation d'IA du mois", "description": "Jetons facturés par les fournisseurs, coût et crédits, par utilisateur et par modèle. Paramètre month=AAAA-MM (mois en cours par défaut).",
        "response": {"month": "2026-10", "credit_value_usd": 0.001, "total": {"runs": 42, "steps": 980, "input_tokens": 9100000, "output_tokens": 390000, "cache_read_tokens": 0, "cache_write_tokens": 0, "cost_usd": 1.11, "credits": 1960.0},
                     "lines": [{"owner": "jdupont", "provider": "anthropic", "model": "claude-haiku-5-5", "runs": 42, "steps": 980, "credits": 1960.0}]}},
    "GET /api/admin/pricing": {"group": "admin", "summary": "Table des prix des modèles", "description": "Prix des fournisseurs en $ par million de jetons, valeur d'un crédit et crédits par étape typiques.",
        "response": {"credit_value_usd": 0.001, "min_credits_per_step": 1.0, "models": [{"provider": "anthropic", "model": "claude-haiku-5-5", "input": 0.1, "output": 0.5, "credits_per_step": 1.3}]}},
    "PUT /api/admin/organisation": {"group": "admin", "summary": "Renommer l'organisation", "description": "Affiché sous le logo et sur la page de connexion. 80 caractères maximum.", "body": {"name": "Cabinet Exemple"}, "response": {"organisation": "Cabinet Exemple"}},
    "POST /api/admin/settings/test": {"group": "admin", "summary": "Tester les réglages d'IA", "body": {"provider": "anthropic", "model": "claude-sonnet-5-5"}, "response": {"ok": True, "reply": "OK"}},
}


def reference(app) -> dict:
    """Every API route of the app, with its documentation and access level."""
    endpoints = []
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api/"):
            continue
        deps = {d.call.__name__ for d in route.dependant.dependencies}
        for method in sorted(route.methods - {"HEAD"}):
            key = f"{method} {route.path}"
            doc = DOCS.get(key, {})
            access = "public" if doc.get("public") else "admin" if "current_admin" in deps else "utilisateur" if "current_user" in deps else "public"
            endpoints.append({
                "method": method, "path": route.path, "access": access,
                "group": doc.get("group", "autres"), "summary": doc.get("summary", "Route non documentée"),
                "description": doc.get("description", ""), "body": doc.get("body"), "response": doc.get("response"),
                "binary": doc.get("binary"), "upload": bool(doc.get("upload")), "documented": key in DOCS,
            })
    order = {g: i for i, (g, _) in enumerate(GROUPS)}
    endpoints.sort(key=lambda e: (order.get(e["group"], 99), e["path"], ["GET", "POST", "PUT", "PATCH", "DELETE"].index(e["method"]) if e["method"] in ("GET", "POST", "PUT", "PATCH", "DELETE") else 9))
    return {"groups": [{"id": g, "label": label} for g, label in GROUPS], "endpoints": endpoints}
