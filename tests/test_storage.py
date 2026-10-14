"""Storage on both databases: SQLite (always) and PostgreSQL (when TEST_DATABASE_URL is set).

Run with: .venv\Scripts\python.exe -m unittest discover -s tests
PostgreSQL: set TEST_DATABASE_URL=postgresql://user:password@host:5432/db first; each test class
works in its own throwaway schema, dropped at the end.
"""
import json
import os
import tempfile
import unittest
import uuid
from datetime import datetime
from pathlib import Path

_sandbox = tempfile.TemporaryDirectory(prefix="autocollab-tests-")
os.environ.update({
    "AUTOCOLLAB_DATA_DIR": str(Path(_sandbox.name) / "data"),
    "AUTOCOLLAB_RUNS_DIR": str(Path(_sandbox.name) / "runs"),
    "AUTOCOLLAB_MASTER_KEY": "isolated-tests-master-key-not-for-production",
    "SESSION_SECRET": "isolated-tests-session-secret",
    "ANONYMIZED_TELEMETRY": "false",
})

from app import agents, auth, config, context, db, settings, usage  # noqa: E402

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "").strip()


class StorageCases:
    """The same checks, whatever the database."""

    def use_database(self, url: str) -> None:
        self.data_dir = Path(tempfile.mkdtemp(prefix="autocollab-data-"))
        config.DATA_DIR = self.data_dir
        db.DB_FILE = self.data_dir / "app.db"
        db.DATABASE_URL, db.POSTGRES = url, url.startswith(("postgres://", "postgresql://"))
        db.reset_for_tests()

    def tearDown(self):
        db.reset_for_tests()

    def test_files_of_earlier_versions_are_imported_once(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "users.json").write_text(json.dumps({"ancien": {"name": "Ancien compte", "admin": True}}), encoding="utf-8")
        (self.data_dir / "settings.json").write_text(json.dumps({"provider": "anthropic", "model": "m", "api_keys": {}}), encoding="utf-8")
        self.assertEqual(auth.load_users()["ancien"]["name"], "Ancien compte")
        self.assertEqual(settings.load()["provider"], "anthropic")
        self.assertFalse((self.data_dir / "users.json").exists())
        self.assertTrue((self.data_dir / "users.json.importe").exists())

    def test_accounts_are_replaced_as_a_whole(self):
        auth.save_users({"camille": {"name": "Camille", "admin": True}, "julie": {"name": "Julie", "admin": False}})
        self.assertEqual(set(auth.load_users()), {"camille", "julie"})
        auth.save_users({"camille": {"name": "Camille D.", "admin": True}})
        self.assertEqual(auth.load_users(), {"camille": {"name": "Camille D.", "admin": True}})

    def test_settings_keep_secrets_encrypted(self):
        settings.update({"model": "claude-sonnet-5-5", "api_keys": {"anthropic": "sk-ant-very-secret"}})
        self.assertEqual(settings.load()["model"], "claude-sonnet-5-5")
        self.assertEqual(settings.load()["api_keys"]["anthropic"], "sk-ant-very-secret")
        with db.connect() as conn:
            stored = conn.execute("SELECT data FROM app_settings WHERE key = 'settings'").fetchone()["data"]
        self.assertNotIn("sk-ant-very-secret", stored)

    def test_agents_flags_order_and_delete(self):
        agents.create("camille", "beta", "Consigne B", None, ["app.pennylane.com"], approval_mode=True)
        first = agents.create("camille", "Alpha", "Consigne A", 30)
        listed = agents.list_for("camille")
        self.assertEqual([a["name"] for a in listed], ["Alpha", "beta"])
        self.assertTrue(listed[1]["approval_mode"])
        self.assertEqual(listed[1]["allowed_domains"], ["app.pennylane.com"])
        self.assertTrue(agents.delete(first["id"], "camille"))
        self.assertFalse(agents.delete(first["id"], "camille"))

    def test_named_parameters_upsert_and_usage_report(self):
        run_id, now = uuid.uuid4().hex, datetime.now().isoformat(timespec="seconds")
        sql = ("INSERT INTO runs (id, owner, task, status, created_at, provider, model, input_tokens, credits, cost_usd)"
               " VALUES (:id, :owner, :task, :status, :created_at, :provider, :model, :tokens, :credits, :cost)"
               " ON CONFLICT(id) DO UPDATE SET status = :status, credits = :credits")
        values = {"id": run_id, "owner": "camille", "task": "Relevés à 100 %", "status": "en_cours", "created_at": now,
                  "provider": "anthropic", "model": "m", "tokens": 1200, "credits": 1.5, "cost": 0.0015}
        with db.connect() as conn:
            conn.execute(sql, values)
            conn.execute(sql, {**values, "status": "termine", "credits": 2.5})
            row = conn.execute("SELECT status, credits, task FROM runs WHERE id = ?", (run_id,)).fetchone()
        self.assertEqual((row["status"], row["credits"], row["task"]), ("termine", 2.5, "Relevés à 100 %"))
        report = usage.monthly_report(now[:7])
        self.assertEqual(report["total"]["credits"], 2.5)
        json.dumps(report)  # numbers come back as plain int / float, ready for the API

    def test_context_upsert(self):
        context.save("cabinet", {"instructions": "Règle 1", "glossary": [], "sites": []}, "camille")
        context.save("cabinet", {"instructions": "Règle 2", "glossary": [], "sites": []}, "julie")
        loaded = context.load("cabinet")
        self.assertEqual((loaded["instructions"], loaded["updated_by"]), ("Règle 2", "julie"))

    def test_generated_ids_and_rowcount(self):
        with db.connect() as conn:
            for text in ("un", "deux"):
                conn.execute("INSERT INTO assistant_messages (conversation_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                             ("c1", "user", text, "2026-10-14T10:00:00"))
            ids = [r["id"] for r in conn.execute("SELECT id FROM assistant_messages WHERE conversation_id = ? ORDER BY id", ("c1",)).fetchall()]
            gone = conn.execute("DELETE FROM assistant_messages WHERE conversation_id = ?", ("c1",)).rowcount
        self.assertEqual(len(ids), 2)
        self.assertLess(ids[0], ids[1])
        self.assertEqual(gone, 2)

    def test_literal_percent_and_rows(self):
        with db.connect() as conn:
            row = conn.execute("SELECT '5%' AS fixed, ? AS given", ("50%",)).fetchone()
        self.assertEqual((row["fixed"], row[1], dict(row)), ("5%", "50%", {"fixed": "5%", "given": "50%"}))


class SqliteStorage(StorageCases, unittest.TestCase):
    def setUp(self):
        self.use_database("")


@unittest.skipUnless(TEST_DATABASE_URL, "TEST_DATABASE_URL not set: PostgreSQL tests skipped")
class PostgresStorage(StorageCases, unittest.TestCase):
    def setUp(self):
        import psycopg
        self.schema = "t_" + uuid.uuid4().hex[:10]
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
            conn.execute(f"CREATE SCHEMA {self.schema}")
        sep = "&" if "?" in TEST_DATABASE_URL else "?"
        self.use_database(f"{TEST_DATABASE_URL}{sep}options=-csearch_path%3D{self.schema}")

    def tearDown(self):
        super().tearDown()
        import psycopg
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
            conn.execute(f"DROP SCHEMA {self.schema} CASCADE")


if __name__ == "__main__":
    unittest.main()
