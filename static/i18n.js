/* Interface language (fr | en).

The pages are written in French. In English, this file translates what is displayed: text nodes
and the placeholder / title / aria-label / alt attributes, including content added later
(lists, toasts, dialogs), through a MutationObserver. Exact strings come from EN; strings with
variable parts (dates, counts, names) from PATTERNS. What users type (instructions, results,
context) lives in containers listed in SKIP and is never translated.

The choice is saved in the user's account (PATCH /api/me) and mirrored in localStorage so the
login page and the first paint use it too. Switching language reloads the page.
*/
(function () {
  const STORE = "ac_lang";
  let lang = "fr";
  try { lang = localStorage.getItem(STORE) || "fr"; } catch {}
  if (lang !== "en") lang = "fr";

  const EN = {
    // --- navigation & shell
    // --- context tools (MCP)
    "Règles, glossaire et notes par site (organisation et personnels) ajoutés à chaque consigne": "Rules, glossary and site notes (organization and personal) added to every instruction",
    "Contexte exact qu'un agent recevrait avec cette consigne": "Exact context an agent would receive with this instruction",
    "Modifie votre contexte personnel (modifications ciblées)": "Edits your personal context (targeted changes)",
    "Modifie le contexte de l'organisation — administrateurs": "Edits the organization context — administrators", "idem": "same",
    "Connecté": "Connected", "Non connecté": "Not signed in", "Ouvrir": "Open",
    "Les agents et les chaînes qui se lancent tout seuls, à l'heure prévue.": "Agents and chains that run by themselves, at the scheduled time.",
    "Agents et chaînes planifiés": "Scheduled agents and chains", "Nom": "Name", "agent": "agent",
    "Rien de planifié. Ouvrez un agent ou une chaîne avec « Modifier » et choisissez une fréquence dans la partie Planification.": "Nothing scheduled. Open an agent or a chain with “Edit” and choose a frequency in the Scheduling section.",
    "Tous": "All", "Planifiés": "Scheduled", "Dans une chaîne": "In a chain", "Dernier échec": "Last run failed", "Planifiées": "Scheduled",
    "Connectés": "Signed in", "Non connectés": "Not signed in", "Jamais vérifiés": "Never checked", "Actifs": "Active",
    "Filtrer": "Filter", "Personne": "Person", "Trier par": "Sort by", "Dernière vérification": "Last check", "Cartes": "Cards", "Liste": "List",
    "Affichage": "View", "Toutes les personnes": "Everyone", "Moi": "Me", "Propriétaire": "Owner", "État": "State", "Vérifié": "Checked",
    "Jamais lancée": "Never run", "Aucun agent ne correspond à ces critères.": "No agent matches these criteria.",
    "Aucune chaîne ne correspond à ces critères.": "No chain matches these criteria.", "Aucun site ne correspond à ces critères.": "No site matches these criteria.",
    "Rien ne correspond à ces critères.": "Nothing matches these criteria.",
    // --- two-factor authentication
    "Code de l'application d'authentification": "Authenticator app code", "Code de secours": "Recovery code",
    "Utiliser un code de secours": "Use a recovery code", "Utiliser le code de l'application": "Use the app code", "Valider": "Confirm",
    "Ouvrez votre application (Google Authenticator, Microsoft Authenticator…) et saisissez le code à 6 chiffres affiché pour AutoCollab.": "Open your app (Google Authenticator, Microsoft Authenticator…) and enter the 6-digit code shown for AutoCollab.",
    "Un des 10 codes de secours notés à l'activation (format abcd-efgh). Chacun ne sert qu'une fois.": "One of the 10 recovery codes noted at setup (abcd-efgh format). Each works only once.",
    "Dernière étape : la double authentification protège votre compte.": "Last step: two-factor authentication protects your account.",
    "Code incorrect ou déjà utilisé.": "Wrong or already used code.", "Session de connexion expirée : saisissez de nouveau votre mot de passe.": "Sign-in expired: enter your password again.",
    "Double authentification": "Two-factor authentication", "Activer": "Turn on", "Désactiver": "Turn off", "Nouveaux codes de secours": "New recovery codes",
    "Activer la double authentification": "Turn on two-factor authentication", "Activez la double authentification": "Turn on two-factor authentication",
    "Désactiver la double authentification": "Turn off two-factor authentication", "Vos codes de secours": "Your recovery codes",
    "Installez une application d'authentification : Google Authenticator, Microsoft Authenticator, Authy, 1Password…": "Install an authenticator app: Google Authenticator, Microsoft Authenticator, Authy, 1Password…",
    "Scannez ce QR code avec l'application (ou saisissez la clé à la main).": "Scan this QR code with the app (or type the key by hand).",
    "Saisissez le code à 6 chiffres qu'elle affiche.": "Enter the 6-digit code it shows.", "Clé (saisie manuelle)": "Key (manual entry)",
    "Type « basé sur le temps », 6 chiffres.": "“Time-based” type, 6 digits.", "Code affiché par l'application": "Code shown by the app",
    "Télécharger (.txt)": "Download (.txt)", "J'ai noté mes codes": "I've noted my codes", "Générer": "Generate",
    "Code de l'application (ou code de secours)": "App code (or recovery code)", "Mot de passe": "Password",
    "Double authentification activée.": "Two-factor authentication turned on.", "Double authentification désactivée.": "Two-factor authentication turned off.",
    "Codes copiés.": "Codes copied.", "Activez d'abord la double authentification.": "Turn on two-factor authentication first.",
    "Code incorrect : vérifiez l'heure du téléphone et saisissez le code affiché maintenant.": "Wrong code: check the phone's time and enter the code shown now.",
    "Mot de passe ou code incorrect.": "Wrong password or code.",
    "La double authentification est obligatoire pour votre compte : elle ne peut pas être désactivée.": "Two-factor authentication is required for your account: it can't be turned off.",
    "Obligatoire pour votre compte : activez-la.": "Required for your account: turn it on.",
    "Désactivée. Recommandée : un mot de passe volé ne suffira plus.": "Off. Recommended: a stolen password won't be enough any more.",
    "Double authentification obligatoire": "Required two-factor authentication", "Personne": "Nobody", "Administrateurs": "Administrators", "Tout le monde": "Everyone",
    "Un code à 6 chiffres d'une application sur le téléphone, en plus du mot de passe. Les personnes concernées l'activent à leur prochaine connexion.": "A 6-digit code from a phone app, on top of the password. The people concerned turn it on at their next sign-in.",
    "Activée": "On", "Désactivée": "Off", "À activer": "To turn on", "Réinitialiser (téléphone perdu ou changé)": "Reset (lost or new phone)",
    "La personne la configurera de nouveau à sa prochaine connexion si votre organisation l'exige, ou depuis Mon compte.": "The person will set it up again at next sign-in if your organization requires it, or from My account.",
    "Double authentification facultative.": "Two-factor authentication optional.",
    "Aucun agent pour l'instant. Cliquez sur « Nouvel agent », ou enregistrez une tâche qui a bien fonctionné avec « Enregistrer comme agent ».": "No agent yet. Click “New agent”, or save a task that worked well with “Save as agent”.",
    "Aucune chaîne pour l'instant. Cliquez sur « Nouvelle chaîne » pour enchaîner des agents existants.": "No chain yet. Click “New chain” to link existing agents.",
    "Des consignes enregistrées, prêtes à relancer chaque mois. Leur historique est dans": "Saved instructions, ready to run again every month. Their history is in",
    "Des agents qui s'enchaînent : chacun passe son résultat et ses fichiers au suivant. Leur historique est dans": "Agents that follow one another: each passes its result and files to the next. Their history is in",
    "Les miens": "Mine", "Toute l'organisation": "Whole organization", "Afficher": "Show", "Agents de l'organisation": "Organization's agents",
    "Lecture seule": "Read-only", "Voir la dernière exécution": "See the last run", "Active": "Active", "En pause": "Paused",
    "Pas encore lancé": "Not run yet", "Pas encore lancée": "Not run yet",
    "Type d'exécution": "Run type", "Tous statuts": "All statuses", "Rechercher par nom ou identifiant…": "Search by name or ID…", "Activité": "Activity",
    "Planifiée": "Scheduled", "Via MCP": "Via MCP", "Avec validation": "With approval", "Sites limités": "Limited sites",
    "Étape d'une chaîne": "Step of a chain", "Copier l'identifiant": "Copy ID", "Identifiant copié.": "ID copied.",
    // --- AI settings page (status, provider cards)
    "Les agents ne peuvent pas démarrer": "Agents can't start", "Le dernier test a échoué": "The last test failed",
    "Les agents sont prêts": "Agents are ready", "Configuration pas encore testée": "Configuration not tested yet",
    "Cliquez sur « Tester sans enregistrer » pour vérifier la clé et le modèle.": "Click “Test without saving” to check the key and the model.",
    "Utilisé par tous les agents de l'organisation. Choisissez-le, collez sa clé, puis « Enregistrer et tester ».": "Used by all the organization's agents. Pick it, paste its key, then “Save and test”.",
    "Pas de clé": "No key", "Clé enregistrée": "Key saved", "Lit les captures": "Reads screenshots", "Utilisé": "In use",
    "Nouvelle clé à enregistrer": "New key to save", "Clé supprimée à l'enregistrement": "Key deleted on save",
    "Clé d'API": "API key", "Obtenir une clé ↗": "Get a key ↗", "Laisser vide pour garder la clé actuelle": "Leave empty to keep the current key",
    "Aucune clé enregistrée pour ce fournisseur.": "No key saved for this provider.", "La clé sera supprimée.": "The key will be deleted.",
    "Plus fiable sur les pages complexes, un peu plus coûteux.": "More reliable on complex pages, a bit more expensive.",
    "Enregistrer et tester": "Save and test", "Tester sans enregistrer": "Test without saving",
    "Clés gardées pour pouvoir changer de fournisseur rapidement. Elles restent sur le serveur et ne sont jamais réaffichées.": "Keys kept to switch provider quickly. They stay on the server and are never shown again.",
    "Fournisseur :": "Provider:", "Modèle :": "Model:", "Clé :": "Key:", "aucune": "none", "Captures d'écran :": "Screenshots:",
    "envoyées": "sent", "non": "no", "États-Unis, sans entraînement sur vos données": "United States, no training on your data", "États-Unis": "United States",
    "Connexion réussie.": "Connection succeeded.",
    "Clé d'API refusée par le fournisseur : vérifiez-la.": "API key refused by the provider: check it.",
    "Pas de réponse du fournisseur après 45 s.": "No answer from the provider after 45 s.",
    "Échec de la connexion.": "Connection failed.", "Crédit insuffisant sur le compte du fournisseur.": "Insufficient credit on the provider's account.",
    // --- OAuth for AI assistants
    "Applications autorisées (OAuth)": "Authorized applications (OAuth)",
    "Les assistants IA que vous avez autorisés depuis la page « Autoriser … ». Ils agissent avec vos droits, uniquement par MCP. Révoquer coupe l'accès immédiatement.": "The AI assistants you authorized on the “Authorize …” page. They act with your rights, only through MCP. Revoking cuts access immediately.",
    "Aucune application autorisée.": "No authorized application.", "Application": "Application", "Retour vers": "Redirects to", "Autorisée": "Authorized",
    "Accès révoqué.": "Access revoked.",
    "OAuth": "OAuth", "(connexion en un clic, pour claude.ai, ChatGPT…) ou clé d'API": "(one-click sign-in, for claude.ai, ChatGPT…) or API key",
    "Cette application pourra, en votre nom :": "This application will be able to, on your behalf:",
    "voir vos agents, chaînes et exécutions ;": "see your agents, chains and runs;",
    "créer et modifier des agents et des chaînes ;": "create and edit agents and chains;",
    "lancer des agents, des tâches et des chaînes ;": "run agents, tasks and chains;",
    "répondre à une demande de validation, sur votre instruction.": "answer an approval request, on your instruction.",
    "Elle ne pourra rien supprimer. Vous pourrez retirer cet accès à tout moment dans Développeurs.": "It won't be able to delete anything. You can withdraw this access at any time in Developers.",
    "Vous serez ensuite renvoyé vers :": "You will then be sent back to:", "Connecté en tant que": "Signed in as",
    "Refuser": "Deny", "Autoriser": "Authorize", "Connexion impossible": "Can't connect",
    "Application inconnue : recommencez la connexion depuis votre assistant IA.": "Unknown application: start the connection again from your AI assistant.",
    "Adresse de retour non déclarée par cette application.": "Redirect address not declared by this application.",
    "PKCE (code_challenge, méthode S256) est obligatoire.": "PKCE (code_challenge, S256 method) is required.",
    "Session expirée : recommencez depuis votre assistant IA.": "Session expired: start again from your AI assistant.",

    "Applications": "Applications", "Autre serveur MCP": "Other MCP server", "Type de connexion": "Connection type",
    "Non activée par votre organisation": "Not enabled by the organization", "Désactivée par votre organisation": "Turned off by the organization", "Configurer": "Set up",
    "Aucune application n'est encore activée. Choisissez-les et renseignez les accès Google / Slack dans": "No application is enabled yet. Choose them and enter the Google / Slack access in",
    "Administration › Intégrations": "Administration › Integrations",
    "Aucune application n'est encore activée : demandez à un administrateur de les configurer (Administration › Intégrations).": "No application is enabled yet: ask an administrator to set them up (Administration › Integrations).",
    "Vos agents les utilisent directement, sans ouvrir de page : plus rapide et plus fiable que le navigateur.": "Your agents use them directly, without opening a page: faster and more reliable than the browser.",
    "Aucune application proposée pour l'instant. Un administrateur peut en activer dans Administration › Intégrations.": "No application offered yet. An administrator can turn some on in Administration › Integrations.",
    "Connecté": "Connected", "Lecture seule": "Read-only", "Lecture et écriture": "Read and write", "En pause": "Paused", "À reconnecter": "Reconnect needed",
    "À configurer par un administrateur": "To be set up by an administrator", "Connecter": "Connect", "Reconnecter": "Reconnect",
    "Jamais utilisée": "Never used", "Utilisée par mes agents": "Used by my agents",
    "Google Agenda": "Google Calendar",
    "Chercher et lire les e-mails ; préparer des brouillons.": "Search and read e-mails; prepare drafts.",
    "Chercher et lire les fichiers ; en créer.": "Search and read files; create some.",
    "Lire et rédiger des documents.": "Read and write documents.", "Lire et remplir des tableurs.": "Read and fill in spreadsheets.",
    "Consulter les agendas et les disponibilités.": "View calendars and availability.",
    "Chercher et lire les messages ; en envoyer.": "Search and read messages; send some.",
    "Lecture seule (recommandé)": "Read-only (recommended)",
    "Vos agents peuvent chercher et lire. Ils ne peuvent rien envoyer, créer ni modifier.": "Your agents can search and read. They can't send, create or change anything.",
    "Ils peuvent aussi envoyer, créer ou modifier. Avec un agent « avec validation », chaque écriture vous est d'abord soumise.": "They can also send, create or change. With an agent “with approval”, every write is submitted to you first.",
    "Vous vous connectez sur la page de": "You sign in on the page of",
    ": l'application ne voit jamais votre mot de passe. Vous pourrez retirer l'accès à tout moment.": ": the application never sees your password. You can withdraw access at any time.",
    "Adresse du serveur (Streamable HTTP)": "Server address (Streamable HTTP)", "Jeton d'accès (facultatif)": "Access token (optional)",
    "Envoyé en « Authorization: Bearer … »": "Sent as “Authorization: Bearer …”", "Notion de l'équipe": "Organization's Notion",
    "Lecture seule : seuls les outils marqués « lecture » sont proposés ; les autres demandent votre validation": "Read-only: only tools marked “read” are offered; the others ask for your approval",
    "Tester et ajouter": "Test and add",
    "Applications proposées": "Applications offered", "Intégrations": "Integrations",
    "Comptes de l'organisation, intelligence artificielle et applications connectées.": "The organization's accounts, artificial intelligence and connected applications.",
    "Chaque utilisateur connecte son propre compte dans « Mes connexions ». Ses agents utilisent alors ces applications directement (serveurs MCP officiels), sans navigateur.": "Each user connects their own account in “My connections”. Their agents then use these applications directly (official MCP servers), without a browser.",
    "Autoriser les utilisateurs à ajouter d'autres serveurs MCP (adresse + jeton)": "Let users add other MCP servers (address + token)",
    "Données :": "Data:",
    "le contenu lu par les agents (e-mails, fichiers, messages) est envoyé au fournisseur d'IA choisi dans l'onglet « Intelligence artificielle ».": "content read by the agents (e-mails, files, messages) is sent to the AI provider chosen in the “Artificial intelligence” tab.",
    "Application Google (Gmail, Drive, Docs, Sheets, Agenda)": "Google application (Gmail, Drive, Docs, Sheets, Calendar)", "Application Slack": "Slack application",
    "Dans": "In", "Google Cloud › Identifiants": "Google Cloud › Credentials", ", créez un « ID client OAuth » de type": ", create an “OAuth client ID” of type",
    "Application Web": "Web application", "Ajoutez l'URI de redirection ci-dessous dans « URI de redirection autorisés ».": "Add the redirect URI below to “Authorized redirect URIs”.",
    "Activez les API Gmail, Drive… et leurs services MCP (gmailmcp.googleapis.com, drivemcp.googleapis.com…).": "Enable the Gmail, Drive… APIs and their MCP services (gmailmcp.googleapis.com, drivemcp.googleapis.com…).",
    "Guide Google": "Google guide", "Collez ici l'ID client et le code secret.": "Paste the client ID and secret here.",
    "URI de redirection": "Redirect URI", "ID client": "Client ID", "Code secret du client": "Client secret", "Aucun code secret": "No secret",
    "Laisser vide pour garder le code actuel": "Leave empty to keep the current secret",
    "Sur": "On", ", créez une application interne à votre espace de travail.": ", create an internal app for your workspace.",
    "Dans « OAuth & Permissions », ajoutez l'URI de redirection ci-dessous.": "In “OAuth & Permissions”, add the redirect URI below.",
    "Collez ici le Client ID et le Client Secret (onglet « Basic Information »).": "Paste the Client ID and Client Secret here (“Basic Information” tab).",
    "Google et Slack exigent une adresse en https:// : renseignez PUBLIC_URL dans le fichier .env du serveur.": "Google and Slack require an https:// address: set PUBLIC_URL in the server's .env file.",
    "Intégrations enregistrées.": "Integrations saved.",
    "Connexion annulée.": "Sign-in cancelled.",
    "Connexion expirée ou demandée par un autre compte : recommencez depuis « Mes connexions ».": "Sign-in expired or started by another account: start again from “My connections”.",
    "Votre organisation n'autorise pas l'ajout d'autres serveurs MCP.": "Your organization doesn't allow adding other MCP servers.",
    "Le serveur MCP doit avoir une adresse en https://": "The MCP server must have an https:// address",
    "Accès refusé par le service : reconnectez-le dans « Mes connexions ».": "Access refused by the service: reconnect it in “My connections”.",
    "Application introuvable": "Application not found", "Application inconnue": "Unknown application",
    // --- tables: search, filters, row actions, pagination
    "Rechercher…": "Search…", "Rechercher dans les exécutions": "Search runs",
    "Filtrer par statut": "Filter by status", "Toutes": "All", "Terminées": "Completed", "Échecs": "Failed", "Mes tâches": "My tasks",
    "Actions": "Actions", "Ouvrir": "Open", "Lignes par page": "Rows per page", "Page suivante": "Next page",
    "Aucune exécution ne correspond à cette recherche.": "No run matches this search.",
    // --- dashboard
    "Tableau de bord": "Dashboard", "L'activité de vos agents sur les 30 derniers jours.": "Your agents' activity over the last 30 days.",
    "Taux de réussite": "Success rate", "Temps de travail des agents": "Agent working time",
    "Durée cumulée des exécutions terminées": "Total duration of finished runs", "Activité · 14 derniers jours": "Activity · last 14 days",
    "Réussies": "Succeeded", "Autres": "Other", "Exécutions par jour": "Runs per day", "À traiter": "To handle",
    "Rien à traiter : aucune validation en attente ni échec récent.": "Nothing to handle: no pending approval and no recent failure.",
    "Prochaines exécutions": "Upcoming runs", "Aucune exécution planifiée.": "No scheduled run.",
    "Agents les plus utilisés": "Most used agents", "Aucun agent lancé ces 30 derniers jours.": "No agent run in the last 30 days.",
    "Aucune exécution": "No run", "Aucune exécution terminée": "No finished run",
    "Aucune validation en attente": "No pending approval", "Aucun agent au travail": "No agent at work",
    "Mes agents": "My agents", "Chaînes": "Chains", "Tâches": "Tasks", "Exécutions": "Runs", "Planification": "Scheduling",
    "Contexte": "Context", "Mes connexions": "My connections", "Développeurs": "Developers", "Administration": "Administration",
    "Guide d'utilisation": "User guide",
    "Récents": "Recent", "Navigation principale": "Main navigation", "Fil d'Ariane": "Breadcrumb",
    "Mon compte": "My account", "Mon compte : changer mon mot de passe": "My account: change my password",
    "Se déconnecter": "Sign out", "Se connecter": "Sign in", "Exécutions qui attendent votre validation": "Runs waiting for your approval",
    "Navigateur ouvert": "Browser open",
    "Administration · AutoCollab": "Administration · AutoCollab",
    "Connexion · AutoCollab": "Sign in · AutoCollab",
    "Langue": "Language",
    // --- login
    "Vos tâches répétitives, confiées à des agents que vous suivez en direct.": "Your repetitive tasks, handed to agents you follow live.",
    "Factures, relevés, pièces manquantes : chaque étape est visible, chaque fichier est conservé.": "Invoices, statements, missing documents: every step is visible, every file is kept.",
    "Connexion": "Sign in", "Utilisez l'identifiant ou l'e-mail fourni par votre administrateur.": "Use the username or e-mail provided by your administrator.",
    "Identifiant ou e-mail": "Username or e-mail", "Mot de passe": "Password",
    "Mot de passe oublié ? Demandez à un administrateur de le réinitialiser.": "Forgot your password? Ask an administrator to reset it.",
    "Afficher le mot de passe": "Show password", "Masquer le mot de passe": "Hide password",
    // --- assistant panel (static/assistant.js)
    "Assistant": "Assistant", "Ouvrir l'assistant": "Open the assistant", "Fermer l'assistant": "Close the assistant", "Fermer": "Close",
    "Retour à la conversation": "Back to the conversation", "Retour": "Back",
    "Conversations précédentes": "Previous conversations", "Nouvelle conversation": "New conversation",
    "Posez votre question…": "Ask your question…",
    "Votre message": "Your message", "Envoyer": "Send", "Envoyer (Entrée)": "Send (Enter)", "Arrêter la réponse": "Stop the answer", "Arrêter": "Stop",
    "Lecture seule : l'assistant consulte vos agents, exécutions et contexte, mais ne lance et ne modifie rien.":
      "Read-only: the assistant looks at your agents, runs and context, but never launches or changes anything.",
    "Comment puis-je vous aider ?": "How can I help?",
    "Questions sur AutoCollab, explication d'une exécution, rédaction d'un agent.": "Questions about AutoCollab, explaining a run, drafting an agent.",
    "Pourquoi cette exécution n'a-t-elle pas abouti ?": "Why didn't this run succeed?",
    "Aide-moi à rédiger un agent qui télécharge les relevés bancaires du mois précédent": "Help me draft an agent that downloads last month's bank statements",
    "Quelles exécutions ont échoué récemment ?": "Which runs failed recently?",
    "Comment fonctionnent les chaînes d'agents ?": "How do agent chains work?",
    "Projet d'agent": "Draft agent", "Sans nom": "Untitled", "Tous les sites": "All sites", "Rédaction de l'agent…": "Drafting the agent…",
    "Ouvrir dans le formulaire": "Open in the form", "Copier la consigne": "Copy the instructions", "Copier": "Copy", "Copié": "Copied",
    "Lecture de la documentation": "Reading the documentation", "Consultation de vos agents": "Looking at your agents",
    "Lecture des variables": "Reading the variables", "Consultation de vos exécutions": "Looking at your runs",
    "Lecture d'une exécution": "Reading a run", "Consultation de vos chaînes": "Looking at your chains",
    "Lecture d'une exécution de chaîne": "Reading a chain run", "Lecture du contexte": "Reading the context", "Aperçu du contexte": "Context preview",
    "Aucune conversation pour l'instant.": "No conversations yet.", "Chargement…": "Loading…",
    "Supprimer la conversation": "Delete the conversation", "Supprimer cette conversation ?": "Delete this conversation?",
    "L'assistant répond…": "The assistant is answering…", "Réponse terminée.": "Answer complete.", "Pas de réponse.": "No answer.",
    "Message vide ou trop long.": "Empty or too long message.",
    "Trop de questions d'affilée : patientez quelques minutes.": "Too many questions in a row: wait a few minutes.",
    "Identifiant ou mot de passe incorrect.": "Incorrect username or password.", "Connexion impossible.": "Unable to sign in.",
    "Serveur injoignable.": "Server unreachable.", "Trop de tentatives. Réessayez dans 15 minutes.": "Too many attempts. Try again in 15 minutes.",
    "prenom.nom@exemple.fr": "firstname.lastname@example.com",
    // --- statuses
    "En attente": "Queued", "En cours": "Running", "À valider": "Needs approval", "Terminé": "Done", "Échec": "Failed",
    "Arrêté": "Stopped", "Interrompu": "Interrupted", "À venir": "Upcoming", "Ignorée": "Skipped",
    // --- agents
    "Des consignes enregistrées, prêtes à relancer chaque mois.": "Saved instructions, ready to run again every month.",
    "Nouvel agent": "New agent", "Créer un agent": "Create an agent", "Lancer": "Run", "Modifier": "Edit", "Supprimer": "Delete",
    "Plus d'actions": "More actions", "Dernière exécution": "Last run", "Dupliquer": "Duplicate", "Suivre l'exécution": "Follow the run",
    "Valider l'action": "Approve the action", "Pas encore lancé": "Not run yet", "Jamais lancé": "Never run", "Non planifié": "Not scheduled",
    "Avec validation": "With approval", "Créé via MCP": "Created via MCP", "Modifié via MCP": "Edited via MCP",
    "Pensez à relire sa consigne et ses garde-fous": "Remember to review its instructions and guardrails",
    "Pensez à relire les étapes": "Remember to review the steps",
    "L'agent demande votre accord avant toute action difficile à annuler": "The agent asks for your approval before any action that is hard to undo",
    "Exécutions des agents": "Agent runs", "Aucune exécution d'agent pour l'instant. Cliquez sur « Lancer » sur une fiche.": "No agent runs yet. Click “Run” on a card.",
    "Nom": "Name", "Consigne": "Instructions", "Factures fournisseurs du mois": "Supplier invoices of the month",
    "Décrivez précisément ce que l'agent doit faire, sur quels sites, et ce qu'il doit rendre…": "Describe precisely what the agent must do, on which sites, and what it must return…",
    "Variables remplacées au lancement (cliquez pour insérer) :": "Variables filled in at launch (click to insert):",
    "Aperçu avec les variables remplies": "Preview with variables filled in", "Étapes max": "Max steps", "défaut": "default",
    "Pièces jointes": "Attachments", "Ajouter des fichiers": "Add files", "Aucune": "None",
    "Fournies à chaque exécution de cet agent, qui peut les envoyer sur un site. Pour des fichiers qui changent chaque mois, faites-les plutôt télécharger par l'agent pendant la tâche.":
      "Given to every run of this agent, which can upload them to a site. For files that change every month, have the agent download them during the task instead.",
    "Garde-fous": "Guardrails", "Sites autorisés": "Allowed sites",
    "Un site par ligne. L'agent ne pourra ouvrir aucun autre site. Vide = aucune restriction. « *.exemple.fr » autorise tous les sous-domaines.":
      "One site per line. The agent won't be able to open any other site. Empty = no restriction. “*.example.com” allows all subdomains.",
    "Mode avec validation": "Approval mode",
    "Avant toute action difficile à annuler (envoyer, valider, supprimer, payer…), l'agent décrit ce qu'il va faire et attend que vous cliquiez sur Valider.":
      "Before any action that is hard to undo (send, submit, delete, pay…), the agent describes what it will do and waits for you to click Approve.",
    "Fréquence": "Frequency", "Chaque jour": "Every day", "Du lundi au vendredi": "Monday to Friday", "Certains jours de la semaine": "Some days of the week",
    "Une fois par mois": "Once a month", "Jour du mois": "Day of the month", "Heure": "Time", "Jours": "Days", "Planification active": "Schedule active",
    "Dernier jour": "Last day", "1er": "1st", "Lun": "Mon", "Mar": "Tue", "Mer": "Wed", "Jeu": "Thu", "Ven": "Fri", "Sam": "Sat", "Dim": "Sun",
    "Enregistrer": "Save", "Annuler": "Cancel", "Nouvelle chaîne": "New chain", "Fermer": "Close",
    "Agent dupliqué.": "Agent duplicated.", "Chaîne dupliquée.": "Chain duplicated.", "Créez d'abord un agent": "Create an agent first", "Une chaîne lance plusieurs agents l'un après l'autre : chacun passe son résultat et ses fichiers au suivant. Créez au moins un agent dans « Mes agents », puis revenez ici pour les enchaîner.": "A chain runs several agents one after the other: each passes its result and files to the next. Create at least one agent in “My agents”, then come back here to chain them.", "Arrêt demandé : la chaîne s'arrête après l'étape en cours.": "Stop requested: the chain stops after the current step.", "Créez d'abord des agents dans « Mes agents » : une chaîne les enchaîne.": "First create agents in “My agents”: a chain links them together.",
    // variables
    "date du jour (11/10/2026)": "today's date (11/10/2026)", "année en cours (2026)": "current year (2026)", "année précédente (2025)": "previous year (2025)",
    "dans une chaîne : le résultat de l'agent précédent": "in a chain: the previous agent's result",
    // --- one-off tasks
    "Une consigne, une exécution. Pour la relancer régulièrement, enregistrez-la comme agent.": "One instruction, one run. To run it regularly, save it as an agent.",
    "Tâche ponctuelle": "One-off task", "Nouvelle tâche": "New task",
    "Décrivez ce que l'agent doit faire, par exemple : « Va sur service-public.fr et trouve la date limite de la déclaration CA12 »":
      "Describe what the agent must do, for example: “Go to service-public.fr and find the deadline for the CA12 return”",
    "Exemples :": "Examples:", "5 derniers e-mails": "Last 5 e-mails", "Factures PDF du mois": "PDF invoices of the month", "Date limite CA12": "CA12 deadline",
    "Joindre des fichiers": "Attach files", "Ou glissez-les ici. L'agent pourra les envoyer sur un site.": "Or drop them here. The agent will be able to upload them to a site.",
    "Enregistrer comme agent": "Save as agent", "Afficher le navigateur": "Show the browser", "Mes tâches récentes": "My recent tasks",
    "Aucune tâche ponctuelle pour l'instant.": "No one-off tasks yet.", "Décrivez la tâche à réaliser.": "Describe the task to perform.",
    "Attendez la fin de l'envoi des pièces jointes.": "Wait until the attachments have finished uploading.",
    "Une pièce jointe a expiré : ajoutez-la de nouveau.": "An attachment has expired: add it again.",
    // --- runs list / detail
    "Toutes vos tâches, avec leurs étapes, captures et fichiers.": "All your tasks, with their steps, screenshots and files.",
    "Aucune exécution pour l'instant.": "No runs yet.", "Aucune exécution pour l'instant. Lancez un agent ou une tâche ponctuelle.": "No runs yet. Run an agent or a one-off task.",
    "Tâche": "Task", "Lancée": "Started", "Durée": "Duration", "Étapes": "Steps", "Fichiers": "Files", "Statut": "Status",
    "Exécution": "Run", "Voir la consigne": "View instructions", "Arrêter": "Stop", "Relancer": "Run again", "Retirer de la file": "Remove from queue",
    "Navigateur": "Browser", "Enregistrement": "Recording", "Ouvrir la capture dans un nouvel onglet": "Open the screenshot in a new tab", "Plein écran": "Full screen",
    "Nouvel onglet": "New tab", "L'écran de l'agent s'affichera ici.": "The agent's screen will appear here.", "En attente de la première capture…": "Waiting for the first screenshot…",
    "La tâche démarrera à son tour dans la file.": "The task will start when its turn comes.", "Écran de l'agent": "Agent screen",
    "Étape précédente": "Previous step", "Étape suivante": "Next step", "Aucune étape": "No steps", "Étape de l'enregistrement": "Recording step",
    "Aucun fichier téléchargé par l'agent pour cette tâche.": "No files downloaded by the agent for this task.",
    "Étapes de l'agent": "Agent steps", "Les étapes apparaîtront ici en direct.": "Steps will appear here live.",
    "Aucun fichier pour l'instant.": "No files yet.", "Envoyés par l'agent": "Uploaded by the agent", "fourni": "provided", "téléchargé": "downloaded",
    "Résultat": "Result", "Fin de la tâche": "End of the task", "Aucun résultat renvoyé par l'agent.": "No result returned by the agent.",
    "Résultat produit par l'IA : vérifiez-le avant de l'utiliser.": "Result produced by AI: check it before using it.",
    "Ouvrir la page source ↗": "Open the source page ↗", "Détails techniques": "Technical details",
    "L'agent travaille…": "The agent is working…", "En attente de votre validation…": "Waiting for your approval…", "En attente dans la file…": "Waiting in the queue…",
    "Info": "Info", "Erreur": "Error", "Fichier envoyé": "File uploaded", "Validation demandée": "Approval requested", "Action validée": "Action approved", "Action refusée": "Action rejected",
    "Validation requise": "Approval required", "Remarque pour l'agent (facultatif)": "Note for the agent (optional)", "Valider": "Approve", "Refuser": "Reject",
    "Consigne envoyée à l'agent": "Instructions sent to the agent", "Contexte ajouté (page Contexte, au démarrage)": "Context added (Context page, at start)",
    "Voir la capture de cette étape": "View this step's screenshot", "Tâche retirée de la file.": "Task removed from the queue.",
    "Arrêt demandé : l'agent s'arrête après l'étape en cours.": "Stop requested: the agent stops after the current step.",
    "Retirée de la file avant son démarrage.": "Removed from the queue before it started.",
    "Validé : l'agent poursuit.": "Approved: the agent continues.", "Refusé : l'agent n'exécutera pas cette action.": "Rejected: the agent will not perform this action.",
    "Aucune capture à ouvrir pour l'instant.": "No screenshot to open yet.", "Exécution introuvable.": "Run not found.", "Tâche introuvable": "Task not found",
    "Aucune validation en attente pour cette exécution.": "No approval pending for this run.",
    "En attente : tous les navigateurs du serveur sont occupés. Elle démarrera dès qu'une place se libère.": "Queued: all the server's browsers are busy. It will start as soon as one is free.",
    "En attente : votre navigateur est occupé (tâche précédente ou « Mes connexions » ouvert). Elle démarrera ensuite.": "Queued: your browser is busy (previous task or “My connections” open). It will start afterwards.",
    "Session expirée : reconnectez-vous.": "Session expired: sign in again.", "Choisissez d'abord votre propre mot de passe.": "First choose your own password.",
    // --- chains
    "Des agents qui s'enchaînent : chacun passe son résultat et ses fichiers au suivant.": "Agents that follow one another: each passes its result and files to the next.",
    "Créer une chaîne": "Create a chain", "Exécutions des chaînes": "Chain runs", "Aucune exécution de chaîne pour l'instant.": "No chain runs yet.",
    "Chaîne": "Chain", "Progression": "Progress", "Jamais lancée": "Never run", "Pas encore lancée": "Not run yet", "Non planifiée": "Not scheduled",
    "Suivre la chaîne": "Follow the chain", "Arrêter la chaîne": "Stop the chain", "Ouvrir l'exécution": "Open the run",
    "Recevra le résultat et les fichiers de l'étape précédente.": "Will receive the result and files of the previous step.", "continue si échec": "continues on failure",
    "Étapes, dans l'ordre": "Steps, in order", "+ Ajouter une étape": "+ Add a step", "Choisir un agent…": "Choose an agent…",
    "Si échec : arrêter": "On failure: stop", "Si échec : continuer": "On failure: continue", "Clôture mensuelle": "Monthly closing",
    "Chaque étape reçoit le": "Each step receives the", "résultat de la précédente": "previous step's result", "(variable": "(variable",
    "à placer dans la consigne de l'agent) et ses": "to place in the agent's instructions) and its", "fichiers téléchargés": "downloaded files",
    "en pièces jointes. Chaque agent garde ses sites autorisés et son mode avec validation.": "as attachments. Each agent keeps its allowed sites and approval mode.",
    "Choisissez un agent pour chaque étape (ou retirez l'étape vide).": "Choose an agent for each step (or remove the empty step).",
    "10 étapes au maximum.": "10 steps maximum.", "Arrêt demandé.": "Stop requested.",
    "Arrêter la chaîne ? L'étape en cours s'arrête et les suivantes sont ignorées.": "Stop the chain? The current step stops and the next ones are skipped.",
    "Cette chaîne est déjà en cours d'exécution.": "This chain is already running.", "Ajoutez au moins une étape.": "Add at least one step.",
    "Une étape désigne un agent introuvable : choisissez-en un autre.": "A step points to an agent that doesn't exist: choose another one.",
    // --- scheduling
    "Les agents qui se lancent tout seuls, à l'heure prévue.": "Agents that run by themselves, at the scheduled time.",
    "Agents planifiés": "Scheduled agents", "Agent": "Agent", "Prochaine exécution": "Next run", "Active": "Active",
    "Aucun agent planifié. Ouvrez un agent avec « Modifier » et choisissez une fréquence dans la partie Planification.": "No scheduled agents. Open an agent with “Edit” and choose a frequency in the Scheduling section.",
    "Planification activée.": "Schedule enabled.", "Planification en pause.": "Schedule paused.",
    // --- context
    "Contexte des agents": "Agents' context", "Le vocabulaire, les règles et les particularités des sites que vos agents connaissent avant de commencer.": "The vocabulary, rules and site specifics your agents know before they start.",
    "Organisation": "Organization", "Personnel": "Personal", "lecture seule": "read-only", "Portée du contexte": "Context scope",
    "Appliqué à toutes les exécutions de l'organisation.": "Applied to every run in the organization.", "Appliqué à vos exécutions, après le contexte de l'organisation.": "Applied to your runs, after the organization's context.",
    "Règles": "Rules", "Glossaire": "Glossary", "Sites": "Sites", "Règles générales": "General rules",
    "Ce que l'agent doit toujours respecter. Une règle par ligne fonctionne le mieux.": "What the agent must always respect. One rule per line works best.",
    "Une règle par ligne…": "One rule per line…", "Les mots de l'organisation et ce qu'ils veulent dire : sigles, noms de dossiers, habitudes.": "The organization's words and what they mean: acronyms, folder names, habits.",
    "Mot-clé": "Keyword", "Mot-clé (ex. FNP)": "Keyword (e.g. FNP)", "Signification": "Meaning", "Signification (ex. factures non parvenues)": "Meaning (e.g. invoices not yet received)",
    "Ajouter": "Add", "Rechercher dans le glossaire…": "Search the glossary…", "Rechercher dans le glossaire": "Search the glossary",
    "Aucun mot-clé. Ajoutez le premier ci-dessus : tapez, puis Entrée.": "No keywords. Add the first one above: type, then Enter.",
    "Où trouver les choses sur chaque site. Ajoutées seulement quand la tâche concerne ce site.": "Where to find things on each site. Added only when the task is about that site.",
    "+ Ajouter un site": "+ Add a site", "Nouveau site": "New site", "Ajoutez des notes…": "Add notes…", "Site": "Site", "Notes": "Notes", "Supprimer ce site": "Delete this site",
    "app.pennylane.com ou Pennylane": "app.pennylane.com or Pennylane", "Où se trouvent les factures, comment filtrer, pièges à éviter…": "Where invoices are, how to filter, pitfalls to avoid…",
    "Aucune note. Exemple : « app.pennylane.com : les factures fournisseurs sont dans Achats › Factures ».": "No notes. Example: “app.pennylane.com: supplier invoices are under Purchases › Invoices”.",
    "Aperçu en direct": "Live preview", "Consigne d'essai": "Test instructions", "Contexte vide": "Empty context", "repère : 1 500 jetons": "guide: 1,500 tokens",
    "Ce que l'agent recevra s'affiche ici.": "What the agent will receive appears here.", "Aucun contexte ne s'applique à cette consigne.": "No context applies to these instructions.",
    "Version enregistrée, organisation puis personnel. Ajoutée à chaque étape de l'agent : plus c'est court, moins c'est coûteux.": "Saved version, organization then personal. Added to every agent step: the shorter, the cheaper.",
    "Jamais modifié": "Never edited", "Modifications…": "Changes…", "Enregistrement…": "Saving…", "Enregistré": "Saved",
    "Va sur Pennylane et liste les FNP de {mois_precedent}": "Go to Pennylane and list the FNP for {mois_precedent}",
    "Glossaire : chaque ligne doit avoir un mot-clé et sa signification.": "Glossary: each line needs a keyword and its meaning.",
    "Notes par site : chaque ligne doit avoir un site et des notes.": "Site notes: each line needs a site and notes.",
    "Ce que vos agents savent avant de commencer : les règles à respecter, le vocabulaire de l'organisation et les particularités des sites.": "What your agents know before they start: the rules to follow, the organization's vocabulary and the specifics of each site.",
    "· tout le monde": "· everyone", "· vous seulement": "· only you",
    "S'applique à toutes les exécutions de l'organisation · modifiable par les administrateurs": "Applies to every run in the organization · editable by administrators",
    "S'applique à toutes les exécutions de l'organisation · lecture seule, modifiable par les administrateurs": "Applies to every run in the organization · read-only, editable by administrators",
    "S'applique seulement à vos exécutions, après le contexte de l'organisation": "Applies only to your runs, after the organization's context",
    "Vocabulaire": "Vocabulary", "· ce que l'agent respecte toujours": "· what the agent always follows", "· sigles, codes dossiers, habitudes": "· acronyms, client codes, habits",
    "· envoyées seulement quand la tâche concerne le site": "· sent only when the task is about the site",
    "aucune règle": "no rules", "aucun mot": "no words", "aucune note": "no notes",
    "Nouvelle règle": "New rule", "Ajouter une règle, puis Entrée…": "Add a rule, then Enter…", "Règles conseillées": "Suggested rules",
    "Règles conseillées pour démarrer": "Suggested rules to get started", "Tout ajouter": "Add all",
    "Mot": "Word", "Mot (ex. FNP)": "Word (e.g. FNP)", "Ce que ça veut dire (ex. factures non parvenues)": "What it means (e.g. invoices not yet received)",
    "Rechercher dans le vocabulaire…": "Search the vocabulary…", "Rechercher dans le vocabulaire": "Search the vocabulary",
    "Exemple : « app.pennylane.com : les factures fournisseurs sont dans Achats › Factures ».": "Example: “app.pennylane.com: supplier invoices are under Purchases › Invoices”.",
    "Ce que l'agent lira": "What the agent will read", "Poids du contexte": "Context weight", "Vide": "Empty", "Léger": "Light", "Moyen": "Medium", "Lourd": "Heavy",
    "Relu à chaque étape de l'agent : plus c'est court, moins c'est coûteux.": "Re-read at every agent step: the shorter, the cheaper.",
    "Tester avec une consigne": "Test with an instruction", "Voir le texte exact envoyé": "See the exact text sent", "Masquer le texte exact": "Hide the exact text",
    "Pour l'instant, l'agent ne reçoit que la consigne de la tâche. Commencez par les règles conseillées, puis ajoutez une ligne chaque fois qu'un agent se trompe.": "For now, the agent only receives the task's instructions. Start with the suggested rules, then add a line each time an agent gets something wrong.",
    "Cette règle existe déjà.": "This rule already exists.",
    "Son nom s'affiche sous le logo, sur la page de connexion et sur le contexte commun à tous.": "Its name appears under the logo, on the sign-in page and on the context shared by everyone.",
    "Nom de l'organisation": "Organization name", "Nom de votre cabinet ou entreprise": "Name of your firm or company",
    "Nom de l'organisation enregistré.": "Organization name saved.",
    "Les règles dépassent 4 000 caractères : raccourcissez-en avant d'en ajouter.": "The rules exceed 4,000 characters: shorten some before adding more.",
    // --- connections
    "Connectez-vous une fois à vos sites dans le navigateur de vos agents : vos sessions sont gardées pour leurs prochaines exécutions.": "Sign in once to your sites in your agents' browser: your sessions are kept for their next runs.",
    "Terminer": "Done", "Mes sites": "My sites", "Ajouter une connexion": "Add a connection",
    "Une de vos exécutions utilise votre navigateur en ce moment. Vous pourrez l'ouvrir dès qu'elle sera terminée.": "One of your runs is using your browser right now. You can open it as soon as it's finished.",
    "Aucune connexion pour l'instant. Ajoutez les sites sur lesquels vos agents doivent être connectés, par exemple :": "No connections yet. Add the sites your agents must be signed in to, for example:",
    "Vous tapez vos identifiants directement sur le site, comme dans votre navigateur habituel : l'application ne les voit pas et ne les enregistre pas. Navigateur :": "You type your credentials directly on the site, as in your usual browser: the application neither sees nor stores them. Browser:",
    "Réinitialiser mon navigateur": "Reset my browser", "Réinitialiser": "Reset",
    "Déconnecte tous vos sites et efface les données de navigation de vos agents. Utile si vous changez d'accès ou quittez l'organisation.": "Signs you out of all your sites and erases your agents' browsing data. Useful if your access changes or you leave the organization.",
"Jamais ouverte": "Never opened", "Suggestions": "Suggestions", "Adresse de la page de connexion": "Sign-in page address",
    "Banque pro": "Organization's bank", "Tous les sites suggérés sont déjà dans votre liste.": "All suggested sites are already in your list.",
    "Navigateur de vos agents": "Your agents' browser", "Page précédente": "Previous page", "Adresse": "Address",
    "Page du site : cliquez puis tapez au clavier": "Site page: click, then type", "Page affichée par le navigateur de vos agents": "Page displayed by your agents' browser",
    "Cliquez dans la page pour taper au clavier": "Click in the page to type",
    "Cliquez sur un champ puis tapez au clavier ; Ctrl+V colle votre texte. La molette fait défiler la page. Une fois connecté, cliquez sur « Terminer » : vos agents utiliseront cette session. Le navigateur se ferme seul après 10 min sans action.":
      "Click a field, then type; Ctrl+V pastes your text. The mouse wheel scrolls the page. Once signed in, click “Done”: your agents will use this session. The browser closes by itself after 10 minutes of inactivity.",
    "Ouverture du navigateur…": "Opening the browser…", "Navigateur fermé : vos agents utiliseront ces connexions.": "Browser closed: your agents will use these connections.",
    "Navigateur réinitialisé : reconnectez vos sites.": "Browser reset: sign in to your sites again.", "Le navigateur est fermé. Rouvrez-le.": "The browser is closed. Open it again.",
    "Réinitialiser votre navigateur ? Tous vos sites seront déconnectés pour vos agents.": "Reset your browser? You'll be signed out of all sites for your agents.",
    "Fermez le navigateur et attendez la fin de vos exécutions avant de le réinitialiser.": "Close the browser and wait for your runs to finish before resetting it.",
    "Votre navigateur est utilisé par une exécution en cours. Réessayez quand elle sera terminée.": "Your browser is being used by a running task. Try again when it's finished.",
    "Adresse refusée : les adresses internes ne sont pas accessibles depuis le navigateur des agents.": "Address refused: internal addresses can't be reached from the agents' browser.",
    "Adresse invalide : saisissez l'adresse d'un site web, par exemple https://www.exemple.fr": "Invalid address: enter a website address, for example https://www.example.com",
    "Connexion introuvable": "Connection not found",
    // --- account / password
    "Choisissez votre mot de passe": "Choose your password", "Mot de passe provisoire": "Temporary password", "Mot de passe actuel": "Current password",
    "Nouveau mot de passe": "New password", "Confirmer le nouveau mot de passe": "Confirm the new password", "10 caractères minimum.": "10 characters minimum.",
    "Enregistrer le mot de passe": "Save password", "Mot de passe enregistré.": "Password saved.",
    "Votre mot de passe a été défini par un administrateur. Remplacez-le par un mot de passe que vous seul connaissez pour continuer.": "Your password was set by an administrator. Replace it with a password only you know to continue.",
    "Les deux nouveaux mots de passe ne correspondent pas.": "The two new passwords don't match.", "Mot de passe actuel incorrect.": "Incorrect current password.",
    "Le nouveau mot de passe doit être différent de l'actuel.": "The new password must be different from the current one.",
    // --- files
    "Type de fichier non accepté (PDF, images, Excel/CSV, Word, texte, XML, ZIP, OFX/QIF).": "File type not accepted (PDF, images, Excel/CSV, Word, text, XML, ZIP, OFX/QIF).",
    "Le fichier est vide.": "The file is empty.", "25 Mo au maximum": "25 MB maximum", "20 pièces jointes au maximum par agent.": "20 attachments maximum per agent.",
    "Fichier introuvable": "File not found", "envoi…": "uploading…",
    // --- developers
    "Pilotez l'assistant depuis vos outils : API REST, n8n, scripts, ou un assistant IA via MCP.": "Drive the assistant from your tools: REST API, n8n, scripts, or an AI assistant via MCP.",
    "Démarrage": "Getting started", "Référence API": "API reference", "Événements": "Events", "MCP": "MCP",
    "1. Créer une clé d'API": "1. Create an API key", "Nom de la clé": "Key name", "Créer une clé": "Create a key", "Nom (ex. Cursor, n8n)": "Name (e.g. Cursor, n8n)",
    "Une clé agit avec": "A key acts with", "vos": "your", "droits : vos agents, vos exécutions, vos connexions. Ne la partagez pas ; révoquez-la si elle a pu fuiter. Elle remplit automatiquement les exemples de cette page.":
      "rights: your agents, your runs, your connections. Don't share it; revoke it if it may have leaked. It fills in the examples on this page automatically.",
    "Copiez votre clé maintenant : elle ne sera plus jamais affichée.": "Copy your key now: it will never be shown again.",
    "Clé": "Key", "Créée": "Created", "Dernière utilisation": "Last used", "Jamais": "Never", "Révoquer": "Revoke", "Aucune clé pour l'instant.": "No keys yet.",
    "2. Appeler l'API": "2. Call the API", "Adresse de base :": "Base address:", ". Envoyez la clé dans l'en-tête": ". Send the key in the header",
    ". Réponses en JSON ; erreurs au format": ". JSON responses; errors in the format",
    "(400 invalide, 401 non authentifié, 403 interdit, 404 introuvable, 409 conflit, 429 trop de tentatives).": "(400 invalid, 401 unauthenticated, 403 forbidden, 404 not found, 409 conflict, 429 too many attempts).",
    "3. Suivre l'exécution": "3. Follow the run", "Les exécutions sont asynchrones : interrogez": "Runs are asynchronous: poll",
    "jusqu'à un statut final, ou écoutez le flux d'événements (onglet Événements).": "until a final status, or listen to the event stream (Events tab).",
    "Copier": "Copy", "Copié": "Copied", "Copie impossible : sélectionnez le texte à la main.": "Copy failed: select the text manually.",
    "Rechercher (ex. agents, fichier, POST)…": "Search (e.g. agents, file, POST)…", "Rechercher une route": "Search a route", "Routes de l'API": "API routes",
    "Corps de la requête (JSON)": "Request body (JSON)", "Exemple de réponse": "Example response", "Essayer avec votre session": "Try with your session", "Envoyer": "Send",
    "Corps : le fichier brut. En-tête": "Body: the raw file. Header", ": son nom (encodé URL).": ": its name (URL-encoded).",
    "Renseignez les paramètres de l'adresse.": "Fill in the address parameters.", "Aucune route.": "No routes.", "Aucune route ne correspond à la recherche.": "No route matches the search.",
    "Route non documentée": "Undocumented route",
    "Connecter un assistant IA": "Connect an AI assistant", "Adresse :": "Address:", "· transport « Streamable HTTP » (réponses JSON) · authentification": "· “Streamable HTTP” transport (JSON responses) · authentication",
    "· protocole 2025-06-18, 2025-03-26 ou 2024-11-05.": "· protocol 2025-06-18, 2025-03-26 or 2024-11-05.",
    "Outils": "Tools", "Outil": "Tool", "Arguments": "Arguments", "Effet": "Effect", "Nature": "Kind", "lecture": "read", "modifie": "modifies", "agit sur les sites": "acts on sites",
    "Vos agents : consigne, garde-fous, planification, dernière exécution": "Your agents: instructions, guardrails, schedule, last run",
    "Variables utilisables dans une consigne": "Variables usable in instructions", "Crée un agent (sans le lancer)": "Creates an agent (without running it)",
    "Modifie un agent": "Edits an agent", "Lance un agent": "Runs an agent", "Lance une consigne ponctuelle": "Runs one-off instructions",
    "Exécutions récentes": "Recent runs", "Statut, résultat, étapes, fichiers, validation": "Status, result, steps, files, approval",
    "Arrête ou retire de la file": "Stops or removes from the queue", "Vos chaînes et leurs étapes": "Your chains and their steps",
    "Compose une chaîne d'agents existants": "Builds a chain of existing agents", "Modifie une chaîne": "Edits a chain", "Lance une chaîne": "Runs a chain",
    "Progression étape par étape": "Step-by-step progress", "Arrête la chaîne": "Stops the chain",
    "Répond à une validation — avec la décision de l'utilisateur": "Answers an approval — with the user's decision",
    "agent_id + champs à changer": "agent_id + fields to change", "chain_id + champs à changer": "chain_id + fields to change",
    "Les résultats arrivent en": "Results come as", "et en texte JSON ; une erreur métier est un résultat": "and as JSON text; a business error is a result with",
    ". « Nature » reprend les annotations MCP : les clients comme Claude Desktop demandent confirmation avant les outils qui agissent sur les sites. Pas de suppression par MCP (à faire dans l'application) ; ce qui est créé ou modifié par MCP est marqué « via MCP ».":
      ". “Kind” mirrors the MCP annotations: clients such as Claude Desktop ask for confirmation before tools that act on sites. No deletion via MCP (do it in the application); what is created or edited via MCP is marked “via MCP”.",
    "Échange type": "Typical exchange", "Statuts d'une exécution": "Run statuses",
    "Dans la file (": "In the queue (", "= rang)": "= position)", "L'agent travaille": "The agent is working", "Attend une réponse à une validation (": "Waiting for an answer to an approval (",
    "Terminée ;": "Finished;", "contient la réponse de l'agent": "contains the agent's answer", "Objectif non atteint ou erreur": "Goal not reached or error",
    "Arrêtée ou retirée de la file": "Stopped or removed from the queue", "Coupée par un redémarrage du serveur": "Cut off by a server restart",
    "Flux GET /api/tasks/{id}/events": "Stream GET /api/tasks/{id}/events",
    "Server-Sent Events : l'historique est rejoué puis les nouveaux événements arrivent en direct ; le flux se ferme après": "Server-Sent Events: the history is replayed, then new events arrive live; the stream closes after",
    ". Un commentaire": ". A comment", "part toutes les 15 s. Chaque message est un objet JSON avec": "is sent every 15 s. Each message is a JSON object with",
    "et": "and", "Champs": "Fields", "(file d'attente, arrêt, site bloqué…)": "(queue, stop, blocked site…)",
    "Clé révoquée.": "Key revoked.",
    // --- admin
    "Comptes de l'organisation et réglages de l'intelligence artificielle.": "The organization's accounts and artificial intelligence settings.",
    "Utilisateurs": "Users", "Intelligence artificielle": "Artificial intelligence", "Créez les comptes de l'organisation et gérez leurs accès.": "Create the organization's accounts and manage their access.",
    "Ajouter un utilisateur": "Add a user", "Comptes": "Accounts", "Identifiant": "Username", "E-mail": "E-mail", "Rôle": "Role", "Admin": "Admin", "Utilisateur": "User",
    "(vous)": "(you)", "Aucun utilisateur.": "No users.", "Nom affiché": "Display name", "Minuscules, chiffres, point, tiret. Sert à se connecter.": "Lowercase letters, digits, dot, dash. Used to sign in.",
    "Permet aussi de se connecter à la place de l'identifiant.": "Can also be used to sign in instead of the username.",
    "Générer": "Generate", "Administrateur (peut gérer les comptes)": "Administrator (can manage accounts)", "Créer le compte": "Create account", "Administrateur": "Administrator",
    "10 caractères minimum. Transmettez-le par un canal sûr : la personne devra le remplacer à sa première connexion.": "10 characters minimum. Share it through a secure channel: the person will have to replace it at first sign-in.",
    "Laisser vide pour ne pas changer": "Leave empty to keep it", "Le changer déconnecte la personne partout ; elle devra le remplacer à sa prochaine connexion.": "Changing it signs the person out everywhere; they'll have to replace it at their next sign-in.",
    "Le mot de passe défini par un administrateur n'a pas encore été remplacé": "The password set by an administrator hasn't been replaced yet",
    "Il ne sera plus affiché : notez-le avant de quitter la page.": "It won't be shown again: write it down before leaving the page.",
    "Enregistré.": "Saved.", "Réservé aux administrateurs.": "Administrators only.", "Compte introuvable.": "Account not found.",
    "Vous ne pouvez pas retirer votre propre rôle administrateur.": "You can't remove your own administrator role.", "Vous ne pouvez pas supprimer votre propre compte.": "You can't delete your own account.",
    "Adresse e-mail invalide.": "Invalid e-mail address.", "Cette adresse e-mail est déjà utilisée par un autre compte.": "This e-mail address is already used by another account.",
    "Identifiant invalide : 2 à 40 caractères parmi a-z, 0-9, point, tiret, tiret bas.": "Invalid username: 2 to 40 characters among a-z, 0-9, dot, dash, underscore.",
    "Fournisseur": "Provider", "Claude (Anthropic)": "Claude (Anthropic)", "Recommandé · lit les captures d'écran": "Recommended · reads screenshots",
    "Hébergé en Europe (France)": "Hosted in Europe (France)", "GPT-4o lit les captures d'écran": "GPT-4o reads screenshots", "Serveurs en Chine": "Servers in China",
    "Attention :": "Warning:", "DeepSeek traite les données sur des serveurs en Chine. Ne l'utilisez pas pour des tâches qui touchent à des données de clients ; préférez Claude ou Mistral.":
      "DeepSeek processes data on servers in China. Don't use it for tasks involving client data; prefer Claude or Mistral.",
    "Modèle": "Model", "Modèle conseillé": "Recommended model", "Envoyer les captures d'écran à l'IA": "Send screenshots to the AI",
    "Plus fiable sur les pages complexes. Uniquement avec un modèle qui lit les images (Claude, GPT-4o).": "More reliable on complex pages. Only with a model that reads images (Claude, GPT-4o).",
    "Adresse de l'API DeepSeek": "DeepSeek API address", "Clés d'API": "API keys",
    "Les clés restent sur le serveur : elles ne sont jamais réaffichées, seules leurs dernières lettres le sont. Laissez un champ vide pour garder la clé actuelle.": "Keys stay on the server: they're never shown again, only their last characters. Leave a field empty to keep the current key.",
    "Aucune clé": "No key", "Sera supprimée": "Will be deleted", "Coller la clé d'API": "Paste the API key", "Nouvelle clé (laisser vide pour garder)": "New key (leave empty to keep)",
    "Tester la connexion": "Test connection", "Test en cours…": "Testing…", "Réglages enregistrés : les prochaines exécutions utiliseront ce fournisseur.": "Settings saved: the next runs will use this provider.",
    "C'est le fournisseur choisi : choisissez-en un autre avant de supprimer sa clé.": "This is the selected provider: choose another one before deleting its key.",
    "L'adresse DeepSeek doit commencer par https://": "The DeepSeek address must start with https://",
    "Pas de réponse du fournisseur après 45 s.": "No answer from the provider after 45 s.",
    "Clé d'API refusée par le fournisseur : vérifiez-la.": "API key rejected by the provider: check it.", "Crédit insuffisant sur le compte du fournisseur.": "Insufficient credit on the provider's account.",

    // --- API reference (Développeurs › Référence API)
    "Session et compte": "Session and account", "Tâches et exécutions": "Tasks and runs", "Agents": "Agents", "Connexions": "Connections",
    "Autres": "Other", "Mes préférences": "My preferences", "Langue de l'interface : fr ou en.": "Interface language: fr or en.",
    "Ouvre une session (cookie). Accepte l'identifiant ou l'e-mail. 5 échecs en 15 min bloquent (429). Pour un script, préférez une clé d'API.":
      "Opens a session (cookie). Accepts the username or e-mail. 5 failures within 15 min lock it (429). For a script, prefer an API key.",
    "Changer mon mot de passe": "Change my password",
    "10 caractères minimum, différent de l'actuel. Déconnecte les autres sessions et renvoie un nouveau cookie.": "10 characters minimum, different from the current one. Signs out other sessions and returns a new cookie.",
    "Réglages visibles par tous": "Settings visible to everyone", "Variables de date disponibles": "Available date variables", "Remplir les variables d'une consigne": "Fill in the variables of instructions",
    "Lister mes exécutions": "List my runs", "Plus récentes d'abord.": "Most recent first.", "Lancer une tâche ponctuelle": "Run a one-off task",
    "Asynchrone : renvoie l'exécution créée (en_attente). Suivez-la avec GET /api/tasks/{id} ou le flux d'événements. attachments = identifiants renvoyés par POST /api/uploads ; rerun_of reprend les pièces jointes d'une exécution.":
      "Asynchronous: returns the created run (en_attente). Follow it with GET /api/tasks/{id} or the event stream. attachments = ids returned by POST /api/uploads; rerun_of reuses a run's attachments.",
    "Détail d'une exécution": "Run details", "Résumé plus la liste complète des événements (onglet Événements).": "Summary plus the full list of events (Events tab).",
    "Arrêter ou retirer de la file": "Stop or remove from the queue",
    "L'agent s'arrête après l'étape en cours ; une exécution en attente quitte la file immédiatement.": "The agent stops after the current step; a queued run leaves the queue immediately.",
    "Répondre à une validation": "Answer an approval", "Pour une exécution au statut a_valider. 409 si aucune validation n'est en attente.": "For a run with status a_valider. 409 if no approval is pending.",
    "Flux d'événements (SSE)": "Event stream (SSE)", "Server-Sent Events : rejoue l'historique puis diffuse en direct jusqu'à « done ». Voir l'onglet Événements.": "Server-Sent Events: replays the history, then streams live until “done”. See the Events tab.",
    "Capture en direct": "Live screenshot", "PNG de l'écran de l'agent (204 si aucune). En-têtes X-Page-Url et X-Page-Title (encodés URL).": "PNG of the agent's screen (204 if none). X-Page-Url and X-Page-Title headers (URL-encoded).",
    "Capture d'une étape": "Step screenshot", "Contexte utilisé par l'exécution": "Context used by the run", "Fichiers d'une exécution": "Run files",
    "source = fourni (pièce jointe) ou telecharge (téléchargé par l'agent).": "source = fourni (attachment) or telecharge (downloaded by the agent).",
    "Télécharger un fichier d'une exécution": "Download a run file", "Lister mes agents": "List my agents",
    "schedule : {kind: daily|weekdays, time} · {kind: weekly, time, days: [0..6]} (0 = lundi) · {kind: monthly, time, monthday: 1..31 ou -1} · null = non planifié.":
      "schedule: {kind: daily|weekdays, time} · {kind: weekly, time, days: [0..6]} (0 = Monday) · {kind: monthly, time, monthday: 1..31 or -1} · null = not scheduled.",
    "Modifier un agent": "Edit an agent", "Envoyez seulement les champs à changer.": "Send only the fields to change.", "Supprimer un agent": "Delete an agent",
    "L'historique de ses exécutions est conservé.": "Its run history is kept.", "Lancer un agent": "Run an agent", "Pièces jointes d'un agent": "An agent's attachments",
    "Ajouter une pièce jointe à un agent": "Add an attachment to an agent",
    "Corps brut du fichier, nom dans l'en-tête X-File-Name (encodé URL). 25 Mo et 20 fichiers au plus.": "Raw file body, name in the X-File-Name header (URL-encoded). 25 MB and 20 files at most.",
    "Retirer une pièce jointe d'un agent": "Remove an attachment from an agent", "Déposer une pièce jointe de tâche": "Upload a task attachment",
    "Corps brut du fichier, nom dans X-File-Name. Renvoie un identifiant à passer dans attachments de POST /api/tasks (valable 24 h). Types : PDF, images, Excel/CSV, Word, texte, XML, ZIP, OFX/QIF ; 25 Mo.":
      "Raw file body, name in X-File-Name. Returns an id to pass in attachments of POST /api/tasks (valid 24 h). Types: PDF, images, Excel/CSV, Word, text, XML, ZIP, OFX/QIF; 25 MB.",
    "Lister mes chaînes": "List my chains",
    "Les agents s'exécutent dans l'ordre. Chacun reçoit le résultat du précédent dans la variable {resultat_precedent} et ses fichiers téléchargés en pièces jointes. on_failure : stop (arrêter la chaîne, par défaut) ou continue. schedule : même format que pour un agent.":
      "Agents run in order. Each receives the previous one's result in the {resultat_precedent} variable and its downloaded files as attachments. on_failure: stop (stop the chain, default) or continue. schedule: same format as for an agent.",
    "Modifier une chaîne": "Edit a chain", "Supprimer une chaîne": "Delete a chain", "Lancer une chaîne": "Run a chain", "Asynchrone ; 409 si la chaîne est déjà en cours.": "Asynchronous; 409 if the chain is already running.",
    "Lister mes exécutions de chaînes": "List my chain runs", "Progression d'une exécution de chaîne": "Chain run progress",
    "Statut de la chaîne (en_cours, termine, echec, arrete, interrompu) et de chaque étape (a_venir, en_attente, en_cours, a_valider, termine, echec, arrete, ignore), avec run_id pour ouvrir l'exécution de l'étape.":
      "Status of the chain (en_cours, termine, echec, arrete, interrompu) and of each step (a_venir, en_attente, en_cours, a_valider, termine, echec, arrete, ignore), with run_id to open the step's run.",
    "Arrêter une exécution de chaîne": "Stop a chain run", "Arrête l'étape en cours ; les suivantes sont ignorées.": "Stops the current step; the next ones are skipped.",
    "État de mon navigateur": "My browser's status", "Ajouter un site": "Add a site", "Modifier un site": "Edit a site", "Retirer un site": "Remove a site", "Ouvrir mon navigateur": "Open my browser",
    "Sur un site de la liste (site_id) ou une adresse (url). 409 si une exécution l'utilise.": "On a site from the list (site_id) or an address (url). 409 if a run is using it.",
    "Écran de mon navigateur": "My browser's screen", "Agir dans mon navigateur": "Act in my browser",
    "type : click (x, y entre 0 et 1) · type (text) · key (Enter, Tab, Backspace, Escape, flèches…) · scroll (dy) · goto (url) · back.": "type: click (x, y between 0 and 1) · type (text) · key (Enter, Tab, Backspace, Escape, arrows…) · scroll (dy) · goto (url) · back.",
    "Fermer mon navigateur": "Close my browser", "Efface le profil : déconnexion de tous les sites.": "Erases the profile: signs out of all sites.",
    "Lire le contexte": "Read the context", "Enregistrer le contexte de l'organisation": "Save the organization's context", "Enregistrer mon contexte": "Save my context",
    "Aperçu du contexte pour une consigne": "Context preview for instructions", "Mes clés d'API": "My API keys", "Créer une clé d'API": "Create an API key",
    "Le champ token n'est renvoyé qu'ici, une seule fois.": "The token field is only returned here, once.", "Révoquer une clé": "Revoke a key",
    "Spécification OpenAPI": "OpenAPI specification", "Pour générer un client ou importer dans un outil (Postman, Insomnia…).": "To generate a client or import into a tool (Postman, Insomnia…).",
    "Cette référence, au format JSON": "This reference, as JSON", "Lister les comptes": "List accounts", "Créer un compte": "Create an account",
    "Le mot de passe est provisoire : la personne le remplace à sa première connexion.": "The password is temporary: the person replaces it at first sign-in.",
    "Modifier un compte": "Edit an account", "Supprimer un compte": "Delete an account", "Révoque aussi ses clés d'API.": "Also revokes their API keys.",
    "Réglages d'IA": "AI settings", "Les clés des fournisseurs ne sont jamais renvoyées, seulement leurs dernières lettres.": "Provider keys are never returned, only their last characters.",
    "Enregistrer les réglages d'IA": "Save the AI settings", "Tester les réglages d'IA": "Test the AI settings",
    "Réponse : fichier.": "Response: file.", "Réponse : image/jpeg.": "Response: image/jpeg.", "Réponse : image/png.": "Response: image/png.", "Réponse : text/event-stream.": "Response: text/event-stream.",
    "Authorization: Bearer <clé>": "Authorization: Bearer <key>", "Chromium (intégré)": "Chromium (built-in)",
    // rule templates (Contexte › Règles), shown truncated
    "+ Ne supprime jamais de document, de fichier ni …": "+ Never delete a document, file or entry",
    "+ Télécharge toujours les documents au format PDF.": "+ Always download documents as PDF",
    "+ N'envoie aucun e-mail ni message sans que la c…": "+ Never send an e-mail or message unless asked",
    "+ Les dates sont au format JJ/MM/AAAA et les mon…": "+ Dates are DD/MM/YYYY, amounts in euros",
    "+ En cas de doute, arrête-toi et explique ce qui…": "+ When in doubt, stop and explain what blocks",
    "+ Termine par un récapitulatif clair de ce que t…": "+ End with a clear summary of what you did",
  };

  const MONTHS = { janvier: "January", "février": "February", mars: "March", avril: "April", mai: "May", juin: "June", juillet: "July", "août": "August", septembre: "September", octobre: "October", novembre: "November", "décembre": "December" };
  const DAYS = { lundi: "Monday", mardi: "Tuesday", mercredi: "Wednesday", jeudi: "Thursday", vendredi: "Friday", samedi: "Saturday", dimanche: "Sunday" };
  const ordinalEn = (n) => n + (/1[123]$/.test(n) ? "th" : { 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th");
  const plural = (n, word) => `${n} ${word}${+n > 1 ? "s" : ""}`;

  // Relative dates and other fragments that appear inside longer strings.
  function fragments(s) {
    return s
      .replace(/\b[Aa]ujourd'hui (\d\d:\d\d)/g, (m, t) => (m[0] === "A" ? "Today " : "today ") + t)
      .replace(/\b[Hh]ier (\d\d:\d\d)/g, (m, t) => (m[0] === "H" ? "Yesterday " : "yesterday ") + t)
      .replace(/\b[Dd]emain (\d\d:\d\d)/g, (m, t) => (m[0] === "D" ? "Tomorrow " : "tomorrow ") + t)
      .replace(/(\d+) min (\d+) s\b/g, "$1 min $2 s");
  }

  function schedule(s) {
    const at = (t) => t.replace("h", ":");
    let m;
    if ((m = s.match(/^Chaque jour à (\d\dh\d\d)$/))) return `Every day at ${at(m[1])}`;
    if ((m = s.match(/^Du lundi au vendredi à (\d\dh\d\d)$/))) return `Monday to Friday at ${at(m[1])}`;
    if ((m = s.match(/^Chaque (.+) à (\d\dh\d\d)$/))) return `Every ${m[1].split(/, | et /).map(d => DAYS[d] || d).join(", ").replace(/, ([^,]+)$/, " and $1")} at ${at(m[2])}`;
    if ((m = s.match(/^Le dernier jour de chaque mois à (\d\dh\d\d)$/))) return `On the last day of each month at ${at(m[1])}`;
    if ((m = s.match(/^Le (1er|\d+) de chaque mois à (\d\dh\d\d)$/))) return `On the ${ordinalEn(m[1] === "1er" ? 1 : +m[1])} of each month at ${at(m[2])}`;
    return null;
  }


  // "aujourd'hui à 19:49" / "le 10/10/2026 à 19:49" (AI settings page)
  function when(w) {
    const m = /^(?:aujourd'hui|le (.+)) à (\d\d:\d\d)$/.exec(w);
    return !m ? w : m[1] ? `on ${m[1]} at ${m[2]}` : `today at ${m[2]}`;
  }
  const PATTERNS = [
    [/^(\d+) \/ (\d+) étapes?$/, (m, a, b) => `${a} / ${plural(b, "step")}`],
    [/^dont (\d+) planifiées?$/, (m, n) => `including ${n} scheduled`],
    [/^dont (\d+) à valider$/, (m, n) => `including ${n} to approve`],
    [/^(\d+) réussies? · (\d+) échecs?$/, (m, a, b) => `${a} succeeded · ${plural(b, "failure")}`],
    [/^(\d+) exécutions? · (\d+) % réussies$/, (m, n, p) => `${plural(n, "run")} · ${p}% succeeded`],
    [/^(.+) · prochaine (.+)$/, (m, a, b) => `${tr(a)} · next ${fragments(b)}`],
    [/^(.+) · en pause$/, (m, a) => `${tr(a)} · paused`],
    [/^(\d+) exécutions? · dernière (.+)$/, (m, n, d) => `${plural(n, "run")} · last ${fragments(d)}`],
    [/^(\d+) étapes? · (.+)$/, (m, n, rest) => `${plural(n, "step")} · ${tr(rest)}`],
    [/^(\d+) exécutions? à valider$/, (m, n) => `${plural(n, "run")} to approve`],
    [/^Lancée par la planification (.+)$/, (m, r) => `Started by the schedule ${tr(r)}`],
    [/^Lancée (.+)$/, (m, r) => `Started ${tr(r)}`],
    [/^(.+) · (\d+) étapes? sur (\d+)$/, (m, a, n, t) => `${fragments(a)} · ${n} of ${plural(t, "step")}`],
    [/^(.+) · (\d+) étapes?$/, (m, a, n) => `${fragments(a)} · ${plural(n, "step")}`],
    [/^Ajoutée (.+) · démarrera dès que la tâche précédente sera terminée$/, (m, d) => `Added ${fragments(d)} · will start as soon as the previous task is done`],
    [/^En attente · (\d+)(?:re|e) dans la file$/, (m, n) => `Queued · ${ordinalEn(+n)} in line`],
    [/^En attente · (\d+)(?:re|e)$/, (m, n) => `Queued · ${ordinalEn(+n)}`],
    [/^En cours · étape (\d+)(?: \/ (\d+))?$/, (m, a, b) => `Running · step ${a}${b ? " / " + b : ""}`],
    [/^Étape (\d+) \/ (\d+)$/, (m, a, b) => `Step ${a} / ${b}`],
    [/^Étape (\d+)$/, (m, a) => `Step ${a}`],
    [/^Enregistré (.+)$/, (m, r) => `Saved ${fragments(r)}`],
    [/^Ouverte (.+)$/, (m, r) => `Opened ${fragments(r)}`],
    [/^Demandée (.+)\. Sans réponse sous (\d+) min, l'action sera refusée\.$/, (m, d, n) => `Requested ${fragments(d)}. Without an answer within ${n} min, the action will be rejected.`],
    [/^≈ (\d+) jetons · (\d+) caractères$/, (m, a, b) => `≈ ${a} tokens · ${b} characters`],
    [/^Connecté en tant que (.+)\. Changer votre mot de passe déconnecte vos autres sessions\.$/, (m, n) => `Signed in as ${n}. Changing your password signs out your other sessions.`],
    [/^(Monter|Descendre|Retirer) l'étape (\d+)$/, (m, v, n) => `${{ Monter: "Move up", Descendre: "Move down", Retirer: "Remove" }[v]} step ${n}`],
    [/^Agent de l'étape (\d+)$/, (m, n) => `Agent of step ${n}`],
    [/^Si l'étape (\d+) échoue$/, (m, n) => `If step ${n} fails`],
    [/^Activer la planification de (.+)$/, (m, n) => `Enable the schedule of ${n}`],
    [/^Sites autorisés : (.+)$/, (m, n) => `Allowed sites: ${n}`],
    [/^(\d+) pièces? jointes?$/, (m, n) => plural(n, "attachment")],
    [/^· chaîne (.+)$/, (m, n) => `· chain ${n}`],
    [/^· planifiée$/, () => "· scheduled"], [/^· ponctuelle$/, () => "· one-off"], [/^· via MCP$/, () => "· via MCP"],
    [/^(.+) · planifiée$/, (m, n) => `${n} · scheduled`],
    [/^(.+) \(continue si échec\)$/, (m, n) => `${n} (continues on failure)`],
    [/^Chaîne : (.+)$/, (m, n) => `Chain: ${n}`],
    [/^Enregistrée (.+)$/, (m, h) => `Saved ${h}`],
    [/^(\d+) \/ 4000$/, (m, n) => `${n} / 4000`],
    [/^Agent « (.+) » créé\.$/, (m, n) => `Agent “${n}” created.`],
    [/^Compte « (.+) » supprimé\.$/, (m, n) => `Account “${n}” deleted.`],
    [/^Le compte « (.+) » existe déjà\.$/, (m, n) => `The account “${n}” already exists.`],
    [/^« (.+) » est déjà dans le glossaire\.$/, (m, n) => `“${n}” is already in the glossary.`],
    [/^« (.+) » est déjà dans le vocabulaire\.$/, (m, n) => `“${n}” is already in the vocabulary.`],
    [/^(\d+) règles?$/, (m, n) => plural(n, "rule")],
    [/^(\d+) mots?$/, (m, n) => plural(n, "word")],
    [/^(\d+) notes?$/, (m, n) => plural(n, "note")],
    [/^(\d+) règles? de l'organisation$/, (m, n) => `${plural(n, "organization rule")}`],
    [/^Vos (\d+) règles? personnelles?$/, (m, n) => `Your ${plural(n, "personal rule")}`],
    [/^Tout le vocabulaire (de l'organisation|personnel) \((\d+) mots?\)$/, (m, w, n) => `All the ${w === "personnel" ? "personal" : "organization's"} vocabulary (${plural(n, "word")})`],
    [/^(\d+) mots? du vocabulaire (de l'organisation|personnel) sur (\d+) : ceux que la consigne cite$/, (m, a, w, b) => `${a} of ${b} ${w === "personnel" ? "personal" : "organization"} vocabulary words: the ones the instruction mentions`],
    [/^Vocabulaire (de l'organisation|personnel) : aucun mot cité, laissé de côté$/, (m, w) => `${w === "personnel" ? "Personal" : "Organization"} vocabulary: no word mentioned, left out`],
    [/^Note du site (.+) : concerné par la consigne$/, (m, s) => `Site note ${s}: relevant to the instruction`],
    [/^(.+) : pas concerné, laissé de côté$/, (m, s) => `${s}: not relevant, left out`],
    [/^Modifier la règle (\d+)$/, (m, n) => `Edit rule ${n}`],
    [/^Supprimer la règle (\d+)$/, (m, n) => `Delete rule ${n}`],
    [/^Règle (\d+)$/, (m, n) => `Rule ${n}`],
    [/^Ajoutée à la file : (\d+)(?:re|e) position\. Elle démarrera automatiquement\.$/, (m, n) => `Added to the queue: ${ordinalEn(+n)} position. It will start automatically.`],
    [/^Connexion réussie\. Réponse du modèle : « (.*) »\. Pensez à enregistrer\.$/, (m, r) => `Connection succeeded. Model's answer: “${r}”. Remember to save.`],
    [/^Supprimer l'agent « (.+) » \? L'historique de ses exécutions est conservé\.$/, (m, n) => `Delete the agent “${n}”? Its run history is kept.`],
    [/^Supprimer la chaîne « (.+) » \? Les agents et l'historique sont conservés\.$/, (m, n) => `Delete the chain “${n}”? The agents and history are kept.`],
    [/^Supprimer le compte « (.+) » \? La personne ne pourra plus se connecter\.$/, (m, n) => `Delete the account “${n}”? The person will no longer be able to sign in.`],
    [/^Retirer « (.+) » de vos connexions \? Votre session sur ce site n'est pas effacée\.$/, (m, n) => `Remove “${n}” from your connections? Your session on this site is not erased.`],
    [/^Révoquer la clé « (.+) » \? Les outils qui l'utilisent n'auront plus accès\.$/, (m, n) => `Revoke the key “${n}”? Tools using it will lose access.`],
    [/^Compte (.+) créé\. Mot de passe provisoire : (.+)$/, (m, n, p) => `Account ${n} created. Temporary password: ${p}`],
    [/^Nouveau mot de passe de (.+) : (.+)$/, (m, n, p) => `New password for ${n}: ${p}`],
    [/^Le mot de passe doit faire au moins (\d+) caractères\.$/, (m, n) => `The password must be at least ${n} characters long.`],
    [/^Fichier trop volumineux : (\d+) Mo au maximum\.$/, (m, n) => `File too large: ${n} MB maximum.`],
    [/^Vous avez déjà (\d+) tâches en attente\. Attendez qu'elles avancent\.$/, (m, n) => `You already have ${n} queued tasks. Wait for them to progress.`],
    [/^(\d+) clés d'API au maximum : supprimez-en une\.$/, (m, n) => `${n} API keys maximum: delete one.`],
    [/^Saisissez la clé d'API (.+) : c'est le fournisseur choisi\.$/, (m, n) => `Enter the ${n} API key: it's the selected provider.`],
    [/^Aucune clé d'API (.+) : un administrateur doit la saisir dans Administration › Intelligence artificielle\.$/, (m, n) => `No ${n} API key: an administrator must enter it in Administration › Artificial intelligence.`],
    [/^Site invalide : « (.+) »\. Exemple attendu : app\.pennylane\.com$/, (m, n) => `Invalid site: “${n}”. Expected example: app.pennylane.com`],
    [/^Site non autorisé bloqué : (.+)$/, (m, n) => `Blocked non-allowed site: ${n}`],
    [/^Validation demandée\. (.*)$/, (m, n) => `Approval requested. ${n}`],
    [/^Le navigateur n'a pas pu s'ouvrir : (.+)$/, (m, n) => `The browser couldn't open: ${n}`],
    [/^Action impossible : (.+)$/, (m, n) => `Action not possible: ${n}`],
    [/^Échec de la connexion\. Détail : (.+)$/, (m, n) => `Connection failed. Detail: ${n}`],
    [/^(Clé d'API refusée par le fournisseur : vérifiez-la\.|Modèle introuvable chez ce fournisseur : vérifiez son nom \(bouton « Modèle conseillé »\)\.|Crédit insuffisant sur le compte du fournisseur\.) Détail : (.+)$/,
      (m, h, d) => `${h.startsWith("Modèle") ? "Model not found at this provider: check its name (“Recommended model” button)." : tr(h)} Detail: ${d}`],
    [/^(mois en cours|mois précédent) \((\S+) (\d{4})\)$/, (m, w, mo, y) => `${w === "mois en cours" ? "current month" : "previous month"} (${MONTHS[mo] || mo} ${y})`],
    [/^(1er|dernier) jour du mois précédent \((.+)\)$/, (m, w, d) => `${w === "1er" ? "first" : "last"} day of the previous month (${d})`],
    [/^Clé enregistrée (…\S+)$/, (m, h) => `Key saved ${h}`],
    [/^Enregistrée (…\S+)$/, (m, h) => `Saved ${h}`],
    [/^Vérifié (.+)$/, (m, d) => `Checked ${fragments(d)}`],
    [/^· chaîne de (\d+) agents?$/, (m, n) => `· chain of ${plural(n, "agent")}`],
    [/^· (agent)$/, () => "· agent"],
    [/^Étape (\d+)\/(\d+) · (.+)$/, (m, i, n, c) => `Step ${i}/${n} · ${c}`],
    [/^Cet agent est l'étape (\d+) sur (\d+) de la chaîne « (.+) »$/, (m, i, n, c) => `This agent is step ${i} of ${n} of the chain “${c}”`],
    [/^Lancé par la chaîne · (.+)$/, (m, d) => `Run by the chain · ${fragments(d)}`],
    [/^En attente de la validation de (.+)…$/, (m, n) => `Waiting for ${n}'s approval…`],
    [/^Activée depuis le (.+?) · (\d+) codes? de secours restants?( · obligatoire pour votre compte)?$/, (m, d, n, req) => `On since ${d} · ${plural(n, "recovery code")} left${req ? " · required for your account" : ""}`],
    [/^Activée · (\d+) codes? de secours restants?( · obligatoire pour votre compte)?$/, (m, n, req) => `On · ${plural(n, "recovery code")} left${req ? " · required for your account" : ""}`],
    [/^Double authentification obligatoire pour (tout le monde|les administrateurs)\.$/, (m, w) => `Two-factor authentication required for ${w === "tout le monde" ? "everyone" : "administrators"}.`],
    [/^Connexion avec un code de secours : il vous en reste (\d+)\. .+$/, (m, n) => `Signed in with a recovery code: ${n} left. Generate new ones in My account if needed.`],
    [/^Trier : (.+)$/, (m, x) => `Sort: ${tr(x)}`],
    [/^Lancer (.+)$/, (m, n) => `Run ${n}`],
    [/^Seul (.+) peut le lancer ou le modifier$/, (m, n) => `Only ${n} can run or edit it`],
    [/^Lancée par (.+)$/, (m, n) => `Run by ${n}`],
    [/^(.+) · lancée par (.+)$/, (m, a, n) => `${tr(a)} · run by ${n}`],
    [/^(.+) Seul (.+) peut répondre\.$/, (m, a, n) => `${tr(a)} Only ${n} can answer.`],
    [/^(\d+) étapes?$/, (m, n) => plural(n, "step")],
    [/^(\d+) fichiers?$/, (m, n) => plural(n, "file")],
    [/^Captures d'écran : (envoyées|non)$/, (m, v) => `Screenshots: ${v === "non" ? "no" : "sent"}`],
    [/^Données : (.+)$/, (m, d) => `Data: ${tr(d)}`],
    [/^Clé : aucune$/, () => "Key: none"],
    [/^Autres clés enregistrées \((\d+)\)$/, (m, n) => `Other saved keys (${n})`],
    [/^Aucune clé d'API (.+)\. Collez-la ci-dessous puis cliquez sur « Enregistrer et tester »\.$/, (m, p) => `No ${p} API key. Paste it below, then click “Save and test”.`],
    [/^Testé avec succès (.+)\.$/, (m, w) => `Tested successfully ${when(w)}.`],
    [/^(.+) \(((?:aujourd'hui|le .+) à \d\d:\d\d)\)$/, (m, a, w) => `${tr(a)} (${when(w)})`],
    [/^(.+) ne lit pas les images : l'agent travaille avec le texte de la page\.$/, (m, p) => `${p} doesn't read images: the agent works with the page's text.`],
    [/^Enregistré, mais le test a échoué : (.+)$/, (m, d) => `Saved, but the test failed: ${tr(d)}`],
    [/^Enregistré\. Connexion réussie\. Réponse du modèle : « (.*) »\.$/, (m, r) => `Saved. Connection succeeded. Model's answer: “${r}”.`],
    [/^Connexion réussie\. Réponse du modèle : « (.*) »\.$/, (m, r) => `Connection succeeded. Model's answer: “${r}”.`],
    [/^(Clé d'API refusée par le fournisseur : vérifiez-la\.|Échec de la connexion\.|Crédit insuffisant sur le compte du fournisseur\.) Détail : (.+)$/, (m, h, d) => `${tr(h)} Detail: ${d}`],
    [/^(\S+) · conseillé$/, (m, n) => `${n} · recommended`],
    [/^Autoriser « (.+) » \?$/, (m, n) => `Authorize “${n}”?`],
    [/^Révoquer l'accès de « (.+) » \? L'assistant devra être reconnecté\.$/, (m, n) => `Revoke the access of “${n}”? The assistant will have to be reconnected.`],
    [/^Autoriser (.+) · AutoCollab$/, (m, n) => `Authorize ${n} · AutoCollab`],
    [/^Utilisée (.+)$/, (m, d) => `Used ${fragments(d)}`],
    [/^Connecter (.+)$/, (m, n) => `Connect ${n}`],
    [/^Continuer avec (.+)$/, (m, n) => `Continue with ${n}`],
    [/^Tester (.+)$/, (m, n) => `Test ${n}`],
    [/^Déconnecter « (.+) » \? Vos agents ne pourront plus l'utiliser\.$/, (m, n) => `Disconnect “${n}”? Your agents won't be able to use it any more.`],
    [/^Déconnecter (.+)$/, (m, n) => `Disconnect ${n}`],
    [/^Utilisée par mes agents : (.+)$/, (m, n) => `Used by my agents: ${n}`],
    [/^(.+) fonctionne : (\d+) outils? disponibles?\.$/, (m, n, k) => `${n} works: ${plural(k, "tool")} available.`],
    [/^(.+) déconnecté\.$/, (m, n) => `${n} disconnected.`],
    [/^(.+) ajouté\.$/, (m, n) => `${n} added.`],
    [/^(.+) : utilisée par vos agents\.$/, (m, n) => `${n}: used by your agents.`],
    [/^(.+) : en pause\.$/, (m, n) => `${n}: paused.`],
    [/^(.+) est connecté : vos agents peuvent l'utiliser\.$/, (m, n) => `${n} is connected: your agents can use it.`],
    [/^Enregistré (…\S+)$/, (m, h) => `Saved ${h}`],
    [/^(.+) indisponible pour cette exécution : (.+)$/, (m, n, d) => `${n} unavailable for this run: ${d}`],
    [/^(.+) n'est pas encore configuré par un administrateur\.$/, (m, n) => `${n} isn't set up by an administrator yet.`],
    [/^(.+) n'est pas proposé par votre organisation\.$/, (m, n) => `${tr(n)} isn't offered by your organization.`],
    [/^Connexion refusée : (.+)$/, (m, d) => `Sign-in refused: ${d}`],
    [/^Connexion au serveur impossible : (.+)$/, (m, d) => `Can't connect to the server: ${tr(d)}`],
    [/^(Google|Slack) a refusé la connexion : (.+)$/, (m, p, d) => `${p} refused the sign-in: ${d}`],
    [/^Le serveur a répondu (\d+) : (.*)$/, (m, c, d) => `The server answered ${c}: ${d}`],
    [/^(\d+) applications connectées au maximum\.$/, (m, n) => `${n} connected applications at most.`],
    [/^(\d+)–(\d+) sur (\d+)$/, (m, a, b, n) => `${a}–${b} of ${n}`],
    [/^Supprimer la clé (.+)$/, (m, n) => `Delete the ${n} key`],
    [/^Révoquer (.+)$/, (m, n) => `Revoke ${n}`],
    // Generic "verb + name" labels (aria-labels, dialog titles): keep them last.
    [/^Modifier « (.+) »$/, (m, n) => `Edit “${n}”`],
    [/^Modifier (.+)$/, (m, n) => `Edit ${n}`],
    [/^Supprimer (.+)$/, (m, n) => `Delete ${n}`],
    [/^Retirer (.+)$/, (m, n) => `Remove ${n}`],
  ];

  function exactOnly(s) {
    const t = s.trim();
    return t && EN[t] !== undefined ? s.replace(t, EN[t]) : s;
  }

  function tr(s) {
    if (lang !== "en" || !s) return s;
    const trimmed = s.trim();
    if (!trimmed) return s;
    const lead = s.slice(0, s.indexOf(trimmed)), tail = s.slice(s.indexOf(trimmed) + trimmed.length);
    let out = EN[trimmed];
    if (out === undefined) out = schedule(trimmed);
    if (out == null) {
      for (const [re, fn] of PATTERNS) {
        const m = trimmed.match(re);
        if (m) { const r = fn(...m); if (r != null) { out = r; break; } }
      }
    }
    if (out == null) {
      const f = fragments(trimmed);
      out = f !== trimmed ? f : null;
    }
    return out == null ? s : lead + out + tail;
  }

  // User content and code samples are never translated.
  const SKIP = ".org-name,script,style,textarea,pre,code,.agent-text,.res,.task-text,.ctx-preview,.term-list .def,.term-list .term,.site-head span,.chip,.step-text,.result-text,.wurl,#wTitle,#connTitle,.def,.var,.flow .node,.agent-top h2,#runTitle,#crTitle,.history .t,td.main a,.recent .txt,.asst-msg,.asst-conv-open span";
  const ATTRS = ["placeholder", "title", "aria-label", "alt"];

  function translateNode(node) {
    if (node.nodeType === 3) {
      const p = node.parentElement;
      if (!p || p.closest("script,style,textarea")) return;
      // Inside user content (and the agent's answer in .result) only exact UI strings are translated.
      const user = p.closest(SKIP) || p.matches(".result");
      const v = user ? exactOnly(node.nodeValue) : tr(node.nodeValue);
      if (v !== node.nodeValue) node.nodeValue = v;
    } else if (node.nodeType === 1) {
      for (const a of ATTRS) {
        const v = node.getAttribute(a);
        if (v) { const t = tr(v); if (t !== v) node.setAttribute(a, t); }
      }
      if (node.matches("textarea,script,style")) return;
      for (const child of node.childNodes) translateNode(child);
    }
  }

  function start() {
    document.documentElement.lang = lang;
    if (lang !== "en") return;
    document.title = tr(document.title);
    translateNode(document.body);
    new MutationObserver((records) => {
      for (const r of records) {
        if (r.type === "characterData") translateNode(r.target);
        else if (r.type === "attributes") translateNode(r.target);
        else r.addedNodes.forEach(translateNode);
      }
    }).observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS });
    const nativeConfirm = window.confirm.bind(window);
    window.confirm = (msg) => nativeConfirm(tr(String(msg)));
  }

  async function setLang(next, persist = true) {
    try { localStorage.setItem(STORE, next); } catch {}
    if (persist) {
      try { await fetch("/api/me", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ lang: next }) }); } catch {}
    }
    location.reload();
  }

  // After /api/me: follow the language saved in the account (another device may have changed it).
  function sync(accountLang) {
    if (accountLang === "fr" || accountLang === "en") {
      if (accountLang !== lang) setLang(accountLang, false);
    } else if (lang === "en") {
      // No choice saved yet: keep the one made on the sign-in page.
      fetch("/api/me", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ lang }) }).catch(() => {});
    }
  }

  window.I18N = { get lang() { return lang; }, tr, setLang, sync };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
