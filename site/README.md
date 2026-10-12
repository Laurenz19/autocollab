# Site vitrine AutoCollab

Une seule page statique, sans outil de build : `index.html` (styles et script inclus) et `favicon.svg`.
Français par défaut, anglais avec le bouton FR / EN (le choix est retenu dans le navigateur).

## Voir le site en local

Ouvrir `site/index.html` dans le navigateur, ou servir le dossier :

```powershell
.venv\Scripts\python.exe -m http.server 8000 --directory site
```

puis http://localhost:8000.

## Guide d'utilisation

`site/guide/` est une copie publique du guide de l'application (`static/guide.html` et ses captures), liée
depuis le menu et le pied de page. Après chaque modification du guide dans l'application, la régénérer :

```powershell
.venv\Scripts\python.exe site\build_guide.py
```

Quand un écran montré dans le guide change, refaire les captures. Le script lance une instance de démonstration
à part (organisation fictive « Exemple & Associés », aucune donnée réelle), prend les 24 captures, puis
régénère `site/guide/` :

```powershell
.venv\Scripts\python.exe tools\guide_screenshots.py              # toutes
.venv\Scripts\python.exe tools\guide_screenshots.py execution    # seulement certaines
```

## Documentation développeurs

`site/developpeurs/index.html` : tutoriel de connexion MCP (claude.ai, ChatGPT, Claude Code, Claude Desktop,
Cursor, VS Code, n8n), clés d'API, outils, dépannage et aperçu de l'API REST. Page écrite à la main (pas
générée) : elle reprend la feuille de style du guide (`../guide/app.css`, donc lancer `build_guide.py` au moins
une fois). Le visiteur saisit l'adresse de son serveur et tous les exemples se remplissent. À tenir à jour avec
`DEVELOPERS.md` (§ 6) et les configurations de la page Développeurs de l'application (`renderSnippets` dans
`static/index.html`) quand un outil MCP ou un client change.

## Mettre en ligne

Le dossier `site/` se dépose tel quel chez n'importe quel hébergeur de pages statiques :

- **Netlify** : app.netlify.com › Add new site › Deploy manually, glisser le dossier `site`.
- **Cloudflare Pages** : Workers & Pages › Create › Pages › Upload assets, choisir le dossier `site`.
- **OVHcloud (hébergement web)** : envoyer `index.html` et `favicon.svg` dans le dossier `www` par FTP.

Ensuite, relier le nom de domaine dans l'interface de l'hébergeur (HTTPS est fourni automatiquement).

## Modifier

- **Textes** : en français directement dans le HTML ; la traduction anglaise est dans le tableau `T.en`
  du script, en bas de la page (même clé `data-t`).
- **Prix et crédits** : les montants sont dans `data-m` (mensuel) et `data-y` (annuel) des balises `.amount b`.
- **Adresse de contact** : `laurenziosambany@gmail.com` (attribut `data-to` du formulaire et lien sous le bouton),
  à remplacer par une adresse dédiée quand le domaine existera.
- **Formulaire de démo** : tant que `data-endpoint` est vide, il ouvre la messagerie du visiteur avec la demande
  pré-remplie. Pour recevoir les demandes directement, créer un formulaire gratuit sur formspree.io et coller son
  adresse (`https://formspree.io/f/…`) dans `data-endpoint` du `<form id="demoForm">`.
