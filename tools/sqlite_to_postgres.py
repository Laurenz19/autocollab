"""Copies an installation's SQLite database (and its accounts and settings) into PostgreSQL.

    set DATABASE_URL=postgresql://autocollab:<mot de passe>@localhost:5432/autocollab
    .venv\\Scripts\\python.exe tools\\sqlite_to_postgres.py               # data/app.db
    .venv\\Scripts\\python.exe tools\\sqlite_to_postgres.py chemin\\app.db

The target must be empty: the script creates the tables, copies every row, then checks the counts.
Accounts and settings still in data/users.json and data/settings.json (versions before PostgreSQL)
are imported on the way. Nothing is changed in the SQLite file; screenshots and files stay in runs/,
the encryption key stays where it is (the same key must be used by the new server).
"""

import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> None:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url.startswith(("postgres://", "postgresql://")):
        raise SystemExit("DATABASE_URL doit désigner la base PostgreSQL cible (postgresql://...).")
    from app import config, db

    source = Path(sys.argv[1]) if len(sys.argv) > 1 else config.DATA_DIR / "app.db"
    if not source.exists():
        raise SystemExit(f"Base SQLite introuvable : {source}")

    with db.connect() as conn:  # creates the tables, imports users.json / settings.json if still there
        filled = [t for t in ("runs", "agents", "chains") if conn.execute(f"SELECT 1 FROM {t} LIMIT 1").fetchone()]
    if filled:
        raise SystemExit(f"La base cible contient déjà des données ({', '.join(filled)}) : rien n'a été copié.")

    lite = sqlite3.connect(source)
    lite.row_factory = sqlite3.Row
    tables = [r[0] for r in lite.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    report = []
    with db.connect() as conn:
        for table in tables:
            target = db._columns(conn, table)
            if not target:
                print(f"  {table} : absente de PostgreSQL, ignorée")
                continue
            columns = [c for c in (r[1] for r in lite.execute(f"PRAGMA table_info({table})")) if c in target]
            rows = lite.execute(f"SELECT {', '.join(columns)} FROM {table}").fetchall()
            if table in ("users", "app_settings"):  # may already hold what was imported from the JSON files
                conn.execute(f"DELETE FROM {table}")
            insert = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})"
            for row in rows:
                conn.execute(insert, tuple(row))
            report.append((table, len(rows)))
        # Generated ids continue after the copied ones.
        conn.execute("SELECT setval(pg_get_serial_sequence('assistant_messages', 'id'), COALESCE((SELECT MAX(id) FROM assistant_messages), 0) + 1, false)")

    with db.connect() as conn:
        for table, count in report:
            copied = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            flag = "ok" if copied == count else f"ÉCART : {copied} dans PostgreSQL"
            print(f"  {table:24s} {count:6d}  {flag}")
    print("Copie terminée. Lancez le serveur avec la même DATABASE_URL et la même clé de chiffrement.")


if __name__ == "__main__":
    main()
