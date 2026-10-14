"""Agent templates: ready-made drafts for the firm's common tasks.

A template is an agent draft (name, instructions, allowed sites, approval mode) that opens the
"Nouvel agent" form pre-filled: the person fills in what is marked [À COMPLÉTER : …], then saves.
Nothing here runs by itself. The assistant reads them through the list_templates tool and starts
from one rather than writing an instruction from scratch.

Each template carries an estimate in credits for the model the agents currently use: its typical
number of steps (a first guess for a short list: adjust it once real runs are known) and, at most,
max_steps.
"""

import math

from . import pricing, settings

TODO = "[À COMPLÉTER"  # marks what the person has to fill in before saving

CATEGORIES = [
    {"id": "compta", "label": "Comptabilité"},
    {"id": "fiscal", "label": "Fiscal et social"},
    {"id": "fournisseurs", "label": "Factures fournisseurs"},
    {"id": "veille", "label": "Veille clients"},
]

TEMPLATES = [
    {
        "id": "justificatifs-manquants",
        "category": "compta",
        "name": "Justificatifs manquants du mois",
        "summary": "Liste les transactions bancaires de Pennylane sans justificatif sur le mois précédent.",
        "instructions": (
            "Sur Pennylane, ouvre le dossier [À COMPLÉTER : nom du client].\n"
            "Dans les transactions bancaires, filtre la période du {debut_mois_precedent} au {fin_mois_precedent} "
            "et garde celles qui n'ont pas de justificatif.\n"
            "Ne modifie rien.\n"
            "Rends un tableau : date, libellé, montant, compte bancaire. Termine par le nombre de transactions "
            "et le montant total concerné."
        ),
        "allowed_domains": ["*.pennylane.com"],
        "approval_mode": False,
        "max_steps": 40,
        "typical_steps": 15,
    },
    {
        "id": "relance-pieces",
        "category": "compta",
        "name": "Relance des pièces manquantes",
        "summary": "Repère les justificatifs manquants dans Pennylane et prépare un brouillon de relance dans Gmail.",
        "instructions": (
            "1. Sur Pennylane, dans le dossier [À COMPLÉTER : nom du client], liste les transactions du "
            "{debut_mois_precedent} au {fin_mois_precedent} sans justificatif (date, libellé, montant).\n"
            "2. Dans Gmail, prépare un brouillon à [À COMPLÉTER : adresse e-mail du client], objet « Pièces "
            "manquantes – {mois_precedent} ». Message court et cordial qui reprend la liste et demande les "
            "justificatifs avant le 15 du mois.\n"
            "N'envoie pas le message : laisse-le en brouillon.\n"
            "Rends la liste des transactions et le texte du brouillon."
        ),
        "allowed_domains": ["*.pennylane.com", "mail.google.com"],
        "approval_mode": True,
        "max_steps": 60,
        "typical_steps": 25,
    },
    {
        "id": "documents-impots",
        "category": "fiscal",
        "name": "Documents fiscaux sur impots.gouv",
        "summary": "Télécharge l'avis de CFE et les accusés de réception de TVA depuis l'espace professionnel.",
        "instructions": (
            "Sur impots.gouv.fr, connecte-toi à l'espace professionnel et ouvre le dossier de l'entreprise "
            "SIREN [À COMPLÉTER : numéro SIREN].\n"
            "Télécharge en PDF :\n"
            "- l'avis de CFE {annee} (rubrique Avis CFE) ;\n"
            "- les accusés de réception des déclarations de TVA déposées en {mois_precedent} (rubrique Déclarer TVA "
            "ou Messagerie).\n"
            "Ne dépose, ne modifie et ne paie rien.\n"
            "Rends la liste des fichiers téléchargés et signale ce qui n'était pas disponible."
        ),
        "allowed_domains": ["*.impots.gouv.fr"],
        "approval_mode": True,
        "max_steps": 50,
        "typical_steps": 20,
    },
    {
        "id": "attestation-urssaf",
        "category": "fiscal",
        "name": "Attestation de vigilance URSSAF",
        "summary": "Télécharge l'attestation de vigilance du mois depuis l'espace employeur URSSAF.",
        "instructions": (
            "Sur urssaf.fr, connecte-toi à l'espace employeur de [À COMPLÉTER : raison sociale ou SIRET].\n"
            "Dans Documents › Attestations, télécharge l'attestation de vigilance la plus récente en PDF.\n"
            "Ne modifie rien et ne lance aucun paiement.\n"
            "Rends le nom du fichier et sa date de délivrance. Si l'attestation n'est pas délivrable, recopie le "
            "message affiché."
        ),
        "allowed_domains": ["*.urssaf.fr"],
        "approval_mode": True,
        "max_steps": 30,
        "typical_steps": 12,
    },
    {
        "id": "factures-portails",
        "category": "fournisseurs",
        "name": "Factures fournisseurs sur leurs portails",
        "summary": "Récupère les factures du mois sur les espaces clients des fournisseurs (énergie, télécom, hébergement…).",
        "instructions": (
            "Pour chaque fournisseur ci-dessous, connecte-toi à son espace client et télécharge en PDF les factures "
            "émises en {mois_precedent} :\n"
            "[À COMPLÉTER : un fournisseur par ligne, par exemple EDF, Orange, OVHcloud]\n"
            "Renomme chaque fichier « Fournisseur_AAAA-MM_numéro.pdf » si le site le permet.\n"
            "Ne modifie aucun moyen de paiement ni aucun contrat.\n"
            "Rends un tableau : fournisseur, numéro, date, montant TTC, fichier. Signale les fournisseurs sans "
            "facture ce mois-ci."
        ),
        "allowed_domains": ["*.edf.fr", "*.orange.fr", "*.ovhcloud.com", "*.ovh.com"],
        "approval_mode": False,
        "max_steps": 80,
        "typical_steps": 30,
    },
    {
        "id": "import-pennylane",
        "category": "fournisseurs",
        "name": "Dépôt des factures dans Pennylane",
        "summary": "Dépose dans Pennylane les factures téléchargées par l'étape précédente d'une chaîne.",
        "instructions": (
            "Ce que l'étape précédente a trouvé : {resultat_precedent}\n\n"
            "Sur Pennylane, dans le dossier [À COMPLÉTER : nom du client], dépose comme factures fournisseurs les "
            "fichiers PDF téléchargés à l'étape précédente.\n"
            "Ne dépose pas une facture déjà présente (même fournisseur, même numéro).\n"
            "Rends la liste des factures déposées et de celles écartées, avec la raison."
        ),
        "allowed_domains": ["*.pennylane.com"],
        "approval_mode": True,
        "max_steps": 60,
        "typical_steps": 25,
    },
    {
        "id": "veille-bodacc",
        "category": "veille",
        "name": "Veille BODACC des clients",
        "summary": "Cherche les annonces BODACC du mois (procédures collectives, cessions, radiations) pour une liste de SIREN.",
        "instructions": (
            "Sur bodacc.fr, pour chaque SIREN ci-dessous, cherche les annonces publiées depuis le "
            "{debut_mois_precedent} :\n"
            "[À COMPLÉTER : un SIREN par ligne, avec le nom de l'entreprise]\n"
            "Rends un tableau : entreprise, SIREN, date, type d'annonce, résumé en une phrase. Mets en tête les "
            "procédures collectives (sauvegarde, redressement, liquidation). Termine par les SIREN sans annonce."
        ),
        "allowed_domains": ["*.bodacc.fr"],
        "approval_mode": False,
        "max_steps": 60,
        "typical_steps": 20,
    },
    {
        "id": "fiche-entreprise",
        "category": "veille",
        "name": "Fiche entreprise des clients",
        "summary": "Vérifie l'état, les dirigeants et l'adresse des clients sur l'Annuaire des entreprises.",
        "instructions": (
            "Sur annuaire-entreprises.data.gouv.fr, pour chaque SIREN ci-dessous :\n"
            "[À COMPLÉTER : un SIREN par ligne]\n"
            "relève la dénomination, l'état (en activité ou cessée), l'adresse du siège, le code NAF, les "
            "dirigeants et la date des derniers comptes déposés.\n"
            "Rends un tableau, une ligne par entreprise, et signale en tête les entreprises cessées ou dont "
            "l'adresse ou les dirigeants semblent avoir changé."
        ),
        "allowed_domains": ["annuaire-entreprises.data.gouv.fr"],
        "approval_mode": False,
        "max_steps": 40,
        "typical_steps": 15,
    },
]


def catalog() -> dict:
    """Categories and templates, each flagged with whether it still has something to fill in,
    and with its estimated credits per run for the current model."""
    current = settings.load()
    per_step = pricing.estimate_per_step(current["provider"], current["model"])
    return {"categories": CATEGORIES, "credits_per_step": per_step,
            "templates": [{**t, "to_complete": TODO in t["instructions"],
                           "estimate": {"credits": math.ceil(t["typical_steps"] * per_step),
                                        "max_credits": math.ceil(t["max_steps"] * per_step)}} for t in TEMPLATES]}
