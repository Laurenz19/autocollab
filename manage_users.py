"""Manage the accounts that can log in to the assistant.

    python manage_users.py ajouter <identifiant> [--nom "Prénom Nom"] [--email adresse] [--admin]
    python manage_users.py admin <identifiant>
    python manage_users.py mot-de-passe <identifiant>
    python manage_users.py supprimer <identifiant>
    python manage_users.py liste

Administrators can also manage accounts from the Administration page.
Passwords are typed at a hidden prompt, never on the command line.
"""

import argparse
import getpass
import sys

from app import auth


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
    sub.add_parser("admin", help="donner le rôle administrateur").add_argument("identifiant")
    sub.add_parser("mot-de-passe", help="changer le mot de passe").add_argument("identifiant")
    sub.add_parser("supprimer", help="supprimer un compte").add_argument("identifiant")
    sub.add_parser("liste", help="lister les comptes")
    args = parser.parse_args()

    users = auth.load_users()

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
        print(f"Compte « {username} » créé{' (administrateur)' if args.admin else ''}.")
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
