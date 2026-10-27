"""Billing per organisation and the back office, on SQLite (always) and PostgreSQL (when TEST_DATABASE_URL is set).

Run with: .venv\Scripts\python.exe -m unittest discover -s tests
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

from app import agents, auth, backoffice, billing, config, db, mcp, settings  # noqa: E402

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "").strip()


class BillingCases:
    """The platform (organisation A, Alice) and one client (organisation B, Bob)."""

    def use_database(self, url: str) -> None:
        self.data_dir = Path(tempfile.mkdtemp(prefix="autocollab-data-"))
        config.DATA_DIR = self.data_dir
        db.DB_FILE = self.data_dir / "app.db"
        db.DATABASE_URL, db.POSTGRES = url, url.startswith(("postgres://", "postgresql://"))
        db.reset_for_tests()
        billing.reset_cache()
        auth._orgs.clear()
        self.stripe_key = config.STRIPE_SECRET_KEY
        config.STRIPE_SECRET_KEY = "sk_test_isolated"  # billing on; no test reaches Stripe
        auth.save_users({"alice": {"name": "Alice", "admin": True}})
        self.platform = db.default_org()
        self.client = "org-client-b"
        with db.connect(system=True) as conn:
            conn.execute("INSERT INTO organisations (id, name, settings, created_at) VALUES (?, 'Client B', '{}', '2026-10-01T10:00:00')",
                         (self.client,))
            conn.execute("INSERT INTO users (username, data, organisation_id) VALUES ('bob', ?, ?)",
                         (json.dumps({"name": "Bob", "admin": True}), self.client))
        auth.forget_orgs()

    def tearDown(self):
        config.STRIPE_SECRET_KEY = self.stripe_key
        billing.reset_cache()
        db.reset_for_tests()

    def add_run(self, owner: str, org: str, credits: float, cost: float = 0.0) -> None:
        with db.connect(system=True) as conn:
            conn.execute("INSERT INTO runs (id, owner, task, status, created_at, credits, cost_usd, organisation_id)"
                         " VALUES (?, ?, 'tâche', 'termine', ?, ?, ?, ?)",
                         (uuid.uuid4().hex, owner, datetime.now().isoformat(timespec="seconds"), credits, cost, org))

    def test_credits_are_counted_per_organisation(self):
        self.add_run("alice", self.platform, 500)
        self.add_run("bob", self.client, 40)
        self.assertEqual(billing.status(self.client)["credits"]["used"], 40)
        self.assertEqual(billing.status(self.platform)["credits"]["used"], 500)
        billing.check_credits(self.client)  # Gratuit: 100 credits, 40 used
        self.add_run("bob", self.client, 60)
        with self.assertRaises(billing.LimitReached):
            billing.check_credits(self.client)
        billing.check_credits(self.platform)  # the platform is never limited

    def test_plan_limits_apply_to_each_client_only(self):
        for i in range(3):  # Gratuit: 3 agents
            agents.create("bob", f"Agent {i}", "Consigne", None)
        with self.assertRaises(billing.LimitReached):
            agents.create("bob", "Un de trop", "Consigne", None)
        for i in range(5):
            agents.create("alice", f"Agent {i}", "Consigne", None)

    def test_manual_plan_and_granted_credits(self):
        billing.manage(self.client, "alice", manual_plan="entreprise", manual_price_usd=300)
        status = billing.status(self.client)
        self.assertEqual((status["plan"], status["source"], status["credits"]["included"]), ("entreprise", "manuel", 80_000))
        self.assertEqual(billing.monthly_revenue_usd(self.client), 300)
        billing.grant_credits(self.client, 500, "alice", "geste commercial")
        self.assertEqual(billing.status(self.client)["credits"]["extra"], 500)
        journal = billing.details(self.client)["journal"]
        self.assertIn("geste commercial", journal[0]["what"])
        self.assertEqual(journal[0]["by"], "alice")
        billing.manage(self.client, "alice", manual_plan=None)
        self.assertEqual(billing.status(self.client)["plan"], "gratuit")

    def test_suspension(self):
        billing.manage(self.client, "alice", suspend=True, reason="Impayé")
        self.assertTrue(billing.suspended(self.client))
        with self.assertRaises(billing.LimitReached):
            billing.check_credits(self.client)
        with self.assertRaises(ValueError):
            billing.manage(self.platform, "alice", suspend=True)
        billing.manage(self.client, "alice", suspend=False)
        self.assertFalse(billing.suspended(self.client))

    def test_subscription_before_billing_per_organisation_moves_to_the_platform(self):
        settings.update_section("billing", {"installation": "inst1", "plan": "solo", "status": "active", "customer": "cus_old"})
        billing.reset_cache()
        self.assertEqual(billing.status(self.platform)["customer"], True)
        self.assertEqual(billing.status(self.client)["customer"], False)
        self.assertEqual(settings.load()["billing"], {"installation": "inst1"})

    def test_webhook_events_reach_their_organisation(self):
        plans = billing.catalog()["plans"]
        plans["solo"]["stripe"] = {"monthly": "price_solo_m", "yearly": ""}
        billing.save_catalog(plans, billing.catalog()["pack"])
        installation = billing._installation()

        def subscription(event_id, metadata, customer="cus_b"):
            return {"id": event_id, "type": "customer.subscription.updated", "data": {"object": {
                "id": "sub_b", "customer": customer, "status": "active", "metadata": metadata,
                "items": {"data": [{"price": {"id": "price_solo_m"}, "current_period_start": 1760000000, "current_period_end": 1762600000}]}}}}

        billing.handle(subscription("evt_other", {"installation": "someone-else", "organisation": self.client}, customer="cus_x"))
        self.assertEqual(billing.status(self.client)["plan"], "gratuit")
        billing.handle(subscription("evt_1", {"installation": installation, "organisation": self.client}))
        status = billing.status(self.client)
        self.assertEqual((status["plan"], status["source"], status["period"]), ("solo", "stripe", "monthly"))
        self.assertEqual(billing.status(self.platform)["plan"], "gratuit")
        # Later events without metadata are found by their Stripe customer.
        cancel = subscription("evt_2", {})
        cancel["type"] = "customer.subscription.deleted"
        billing.handle(cancel)
        self.assertEqual(billing.status(self.client)["plan"], "gratuit")

    def test_catalog_changes_apply(self):
        plans = billing.catalog()["plans"]
        plans["gratuit"]["credits"] = 250
        billing.save_catalog(plans, {"credits": 5000, "usd": 25, "stripe": ""})
        self.assertEqual(billing.status(self.client)["credits"]["included"], 250)
        self.assertEqual(billing.catalog()["pack"]["usd"], 25)

    def test_back_office_creates_and_lists_clients(self):
        created = backoffice.create_client("Cabinet Martin", "jmartin", "Jeanne Martin", "j.martin@example.fr",
                                           "un-mot-de-passe-sur", "alice", manual_plan="equipe", manual_price_usd=129)
        self.assertEqual(auth.org_of("jmartin"), created["id"])
        self.assertTrue(auth.load_users(everywhere=True)["jmartin"]["must_change_password"])
        self.assertEqual(created["users"][0]["username"], "jmartin")
        with self.assertRaises(ValueError):
            backoffice.create_client("Doublon", "jmartin", "", "", "un-mot-de-passe-sur", "alice")
        self.add_run("jmartin", created["id"], 12, cost=4.5)
        listing = backoffice.clients()
        martin = next(c for c in listing["clients"] if c["id"] == created["id"])
        self.assertEqual((martin["label"], martin["month"]["revenue_usd"], martin["month"]["ai_cost_usd"]), ("Équipe", 129, 4.5))
        self.assertEqual(martin["month"]["margin_usd"], 124.5)
        self.assertEqual(listing["totals"]["clients"], 2)  # Client B and Cabinet Martin, not the platform
        self.assertEqual(listing["totals"]["revenue_usd"], 129)

    def call(self, user: str, tool: str, **args) -> dict:
        return mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}}, user, None)

    def test_mcp_back_office_is_for_the_platform_only(self):
        listed = lambda user: {t["name"] for t in mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, user, None)["result"]["tools"]}
        self.assertIn("platform_list_clients", listed("alice"))
        self.assertFalse({n for n in listed("bob") if n.startswith("platform_")})
        self.assertIn("error", self.call("bob", "platform_list_clients"))  # unknown tool for a client
        with self.assertRaises(mcp.ToolError):
            mcp.call_tool("platform_list_clients", {}, "bob", None)  # the in-app assistant's path checks too
        self.assertNotIn("platform_list_clients", {t["name"] for t in mcp.TOOLS})

    def test_mcp_back_office_tools(self):
        created = self.call("alice", "platform_create_client", name="Cabinet Durand", username="pdurand", manual_plan="solo", manual_price_usd=20)
        data = created["result"]["structuredContent"]
        org, password = data["client"]["id"], data["temporary_password"]
        self.assertGreaterEqual(len(password), 10)
        self.assertEqual(auth.org_of("pdurand"), org)
        self.call("alice", "platform_grant_credits", client_id=org, credits=250, note="bienvenue")
        client = self.call("alice", "platform_get_client", client_id=org)["result"]["structuredContent"]["client"]
        self.assertEqual((client["billing"]["plan"], client["billing"]["credits"]["extra"]), ("solo", 250))
        self.assertIn("(MCP)", client["billing"]["journal"][0]["by"])
        self.call("alice", "platform_set_suspension", client_id=org, suspended=True, reason="Impayé")
        self.assertTrue(billing.suspended(org))
        refused = self.call("alice", "platform_update_plan", plan="solo", stripe_monthly="pas-un-prix")
        self.assertTrue(refused["result"]["isError"])
        self.call("alice", "platform_update_plan", plan="solo", credits=4000, agents=None)
        self.assertEqual((billing.plans()["solo"]["credits"], billing.plans()["solo"]["agents"]), (4000, None))
        self.assertTrue(self.call("alice", "platform_delete_client", client_id=org)["result"]["isError"])  # it has an account

    def test_only_an_empty_client_can_be_deleted(self):
        with db.connect(system=True) as conn:
            conn.execute("INSERT INTO organisations (id, name, settings, created_at) VALUES ('org-vide', 'Vide', '{}', '2026-10-14T10:00:00')")
        backoffice.delete_empty("org-vide")
        self.assertFalse(backoffice.exists("org-vide"))
        with self.assertRaises(ValueError):
            backoffice.delete_empty(self.client)  # Bob's account is there
        with self.assertRaises(ValueError):
            backoffice.delete_empty(self.platform)


class SqliteBilling(BillingCases, unittest.TestCase):
    def setUp(self):
        self.use_database("")


@unittest.skipUnless(TEST_DATABASE_URL, "TEST_DATABASE_URL not set: PostgreSQL tests skipped")
class PostgresBilling(BillingCases, unittest.TestCase):
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
