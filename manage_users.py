"""Manage the accounts that can log in to the assistant.

    python manage_users.py ajouter <identifiant> [--nom "Prénom Nom"] [--email adresse] [--admin] [--organisation <id>]
    python manage_users.py admin <identifiant>
    python manage_users.py mot-de-passe <identifiant>
    python manage_users.py supprimer <identifiant>
    python manage_users.py liste
    python manage_users.py organisation "Nom du client"      # a new organisation (client) on a shared server
    python manage_users.py organisations

Administrators can also manage accounts from the Administration page. A new client: create its
organisation, then its first administrator with --organisation; they create the other accounts.
Passwords are typed at a hidden prompt, never on the command line.
"""

import argparse
import getpass
import sys
import uuid
from datetime import datetime

from app import auth, db


def ask_password() -> str:
    while True:
        password = getpass.getpass("Mot de passe : ")
        if error := auth.password_error(password):
            print(error)
            continue
        if getpass.getpass("Confirmez : ") != password:
            print("Les deux saisies ne correspondent pas.")
            continue
        return password


def main() -> int:
    parser = argparse.ArgumentParser(description="Comptes AutoCollab")
    sub = parser.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("ajouter", help="créer un compte")
    add.add_argument("identifiant")
    add.add_argument("--nom", default="", help="nom affiché dans l'interface")
    add.add_argument("--email", default="", help="adresse e-mail, utilisable pour se connecter")
    add.add_argument("--admin", action="store_true", help="peut gérer les comptes depuis la page Administration")
    add.add_argument("--organisation", default="", help="identifiant de l'organisation (voir « organisations ») ; par défaut celle de l'installation")
    sub.add_parser("admin", help="donner le rôle administrateur").add_argument("identifiant")
    sub.add_parser("mot-de-passe", help="changer le mot de passe").add_argument("identifiant")
    sub.add_parser("supprimer", help="supprimer un compte").add_argument("identifiant")
    sub.add_parser("liste", help="lister les comptes")
    sub.add_parser("organisation", help="créer une organisation (un client)").add_argument("nom")
    sub.add_parser("organisations", help="lister les organisations")
    args = parser.parse_args()

    if args.cmd == "organisation":
        org = "org-" + uuid.uuid4().hex[:12]
        with db.connect(system=True) as conn:
            conn.execute("INSERT INTO organisations (id, name, settings, created_at) VALUES (?, ?, '{}', ?)",
                         (org, " ".join(args.nom.split())[:80], datetime.now().isoformat(timespec="seconds")))
        print(f"Organisation « {args.nom} » créée : {org}")
        print(f"Premier administrateur : python manage_users.py ajouter <identifiant> --email <adresse> --admin --organisation {org}")
        return 0
    if args.cmd == "organisations":
        with db.connect(system=True) as conn:
            rows = conn.execute("SELECT o.id, o.name, (SELECT COUNT(*) FROM users u WHERE u.organisation_id = o.id) AS n"
                                " FROM organisations o ORDER BY o.created_at").fetchall()
        platform = db.default_org()
        for row in rows:
            print(f"{row['id']}	{row['name']}	{row['n']} compte(s){chr(9) + '(plateforme)' if row['id'] == platform else ''}")
        return 0

    users = auth.load_users(everywhere=True)

    if args.cmd == "liste":
        if not users:
            print("Aucun compte. Créez-en un avec : python manage_users.py ajouter <identifiant> --admin")
        for username, user in sorted(users.items()):
            role = "\t(admin)" if user.get("admin") else ""
            print(f"{username}\t{user.get('name', '')}\t{user.get('email', '')}{role}")
        return 0

    username = auth.normalize_username(args.identifiant)

    if args.cmd == "ajouter":
        if error := auth.username_error(username):
            print(error)
            return 1
        if username in users:
            print(f"Le compte « {username} » existe déjà.")
            return 1
        org = args.organisation.strip() or db.default_org()
        with db.connect(system=True) as conn:
            if not conn.execute("SELECT 1 FROM organisations WHERE id = ?", (org,)).fetchone():
                print(f"Aucune organisation « {org} » : voir python manage_users.py organisations")
                return 1
        email = auth.normalize_email(args.email)
        if error := auth.email_error(email, users):
            print(error)
            return 1
        users[username] = {
            "name": args.nom.strip() or username,
            "email": email,
            "password": auth.hash_password(ask_password()),
            "admin": args.admin,
        }
        auth.save_users(users)
        with db.connect(system=True) as conn:
            conn.execute("UPDATE users SET organisation_id = ? WHERE username = ?", (org, username))
        print(f"Compte « {username} » créé{' (administrateur)' if args.admin else ''}, organisation {org}.")
        return 0

    if username not in users:
        print(f"Aucun compte « {username} ».")
        return 1

    if args.cmd == "admin":
        users[username]["admin"] = True
        auth.save_users(users)
        print(f"« {username} » est maintenant administrateur.")
    elif args.cmd == "mot-de-passe":
        users[username]["password"] = auth.hash_password(ask_password())
        auth.save_users(users)
        print("Mot de passe changé. Les sessions ouvertes de ce compte sont déconnectées.")
    elif args.cmd == "supprimer":
        del users[username]
        auth.save_users(users)
        print(f"Compte « {username} » supprimé.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
