"""Other MCP servers: a token, no sign-in, or the server's own OAuth sign-in. No network: the servers are faked.

Run with: .venv\Scripts\python.exe -m unittest discover -s tests
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

_sandbox = tempfile.TemporaryDirectory(prefix="autocollab-tests-")
os.environ.update({
    "AUTOCOLLAB_DATA_DIR": str(Path(_sandbox.name) / "data"),
    "AUTOCOLLAB_RUNS_DIR": str(Path(_sandbox.name) / "runs"),
    "AUTOCOLLAB_MASTER_KEY": "isolated-tests-master-key-not-for-production",
    "SESSION_SECRET": "isolated-tests-session-secret",
    "ANONYMIZED_TELEMETRY": "false",
})

from app import integrations  # noqa: E402
from app.mcp_client import MCPAuthError, MCPError  # noqa: E402


class FakeServer:
    """An MCP server for MCPClient: refuses without a token, or answers with no tools; per address."""

    def __init__(self, behaviour: dict):
        self.behaviour, self.url = behaviour, None

    def __call__(self, url, token=None, timeout=60):
        self.url = url
        return self

    async def __aenter__(self):
        outcome = self.behaviour.get(self.url, "missing")
        if outcome == "auth":
            raise MCPAuthError("refusé")
        if outcome == "missing":
            raise MCPError("Le serveur a répondu 405")
        return self

    async def __aexit__(self, *exc):
        pass

    async def list_tools(self):
        return []


class CustomServerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        for patcher in (patch.object(integrations, "admin_config", return_value={"allow_custom": True, "enabled": [], "oauth": {}}),
                        patch.object(integrations.config, "PUBLIC_URL", "")):  # not the PUBLIC_URL of the .env
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_bare_address_then_oauth_sign_in(self):
        server = FakeServer({"https://mcp.example.fr/mcp": "auth"})
        with patch.object(integrations, "MCPClient", server), \
                patch.object(integrations, "_start_custom_sign_in", AsyncMock(return_value="https://auth.example.fr/authorize?x=1")) as start:
            result = await integrations.add_custom("camille", "Exemple", "https://mcp.example.fr", "", True, "https://app.example.fr")
        self.assertEqual(result, {"sign_in_url": "https://auth.example.fr/authorize?x=1"})
        self.assertEqual(start.call_args.args[2], "https://mcp.example.fr/mcp")  # the bare address was completed

    async def test_refused_token_is_not_an_oauth_sign_in(self):
        with patch.object(integrations, "MCPClient", FakeServer({"https://mcp.example.fr/mcp": "auth"})):
            with self.assertRaises(ValueError):
                await integrations.add_custom("camille", "Exemple", "https://mcp.example.fr/mcp", "mauvais", True, "https://app.example.fr")

    def test_well_known_addresses(self):
        self.assertEqual(integrations._well_known("https://mcp.pappers.fr/mcp", "oauth-protected-resource"),
                         ["https://mcp.pappers.fr/.well-known/oauth-protected-resource/mcp",
                          "https://mcp.pappers.fr/.well-known/oauth-protected-resource"])
        self.assertEqual(integrations._well_known("https://auth.pappers.fr", "oauth-authorization-server"),
                         ["https://auth.pappers.fr/.well-known/oauth-authorization-server"])

    async def test_registration_choices(self):
        by_document = await integrations._register({"client_id_metadata_document_supported": True}, "https://app.example.fr")
        self.assertEqual((by_document["client_id"], by_document["auth_method"]),
                         ("https://app.example.fr/api/integrations/client-metadata.json", "none"))
        with self.assertRaises(ValueError):  # neither registration nor client document: a token is needed
            await integrations._register({"authorization_endpoint": "x", "token_endpoint": "y"}, "https://app.example.fr")


if __name__ == "__main__":
    unittest.main()
