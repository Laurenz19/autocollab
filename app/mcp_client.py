"""A small client for remote MCP servers (Streamable HTTP), used by agents during a run.

Just what agents need: open a session, list the tools, call one. Servers may answer
either with plain JSON or with a short event stream (SSE); both are handled.
"""

import json

import httpx

PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "AutoCollab", "version": "1.0"}


class MCPError(Exception):
    pass


class MCPAuthError(MCPError):
    """The server refused the access token (expired, revoked or missing permission)."""


class MCPClient:
    def __init__(self, url: str, token: str | None = None, timeout: float = 60):
        self.url = url
        self.token = token
        self.timeout = timeout
        self.session_id: str | None = None
        self.protocol = PROTOCOL_VERSION
        self._http: httpx.AsyncClient | None = None
        self._next_id = 0

    async def __aenter__(self) -> "MCPClient":
        self._http = httpx.AsyncClient(timeout=self.timeout, follow_redirects=False)
        try:
            result = await self._request("initialize", {
                "protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": CLIENT_INFO,
            })
            self.protocol = result.get("protocolVersion") or PROTOCOL_VERSION
            await self._notify("notifications/initialized")
        except BaseException:
            await self._http.aclose()
            raise
        return self

    async def __aexit__(self, *exc) -> None:
        if self._http:
            if self.session_id:
                try:
                    await self._http.delete(self.url, headers=self._headers())
                except Exception:
                    pass
            await self._http.aclose()

    # --- public API -----------------------------------------------------

    async def list_tools(self) -> list[dict]:
        tools, cursor = [], None
        for _ in range(20):  # pages
            result = await self._request("tools/list", {"cursor": cursor} if cursor else {})
            tools += result.get("tools") or []
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return tools

    async def call_tool(self, name: str, arguments: dict) -> dict:
        return await self._request("tools/call", {"name": name, "arguments": arguments or {}})

    # --- JSON-RPC over HTTP -----------------------------------------------

    def _headers(self) -> dict:
        headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
                   "MCP-Protocol-Version": self.protocol}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        return headers

    async def _notify(self, method: str) -> None:
        await self._post({"jsonrpc": "2.0", "method": method})

    async def _request(self, method: str, params: dict) -> dict:
        self._next_id += 1
        message = await self._post({"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params},
                                   self._next_id)
        if message is None:
            raise MCPError(f"Pas de réponse du serveur à « {method} ».")
        if "error" in message:
            error = message["error"] or {}
            raise MCPError(f"{error.get('message') or 'Erreur du serveur'} (code {error.get('code')})")
        return message.get("result") or {}

    async def _post(self, payload: dict, wanted_id: int | None = None) -> dict | None:
        assert self._http is not None
        response = await self._http.post(self.url, headers=self._headers(), content=json.dumps(payload))
        if response.status_code in (401, 403):
            raise MCPAuthError("Accès refusé par le service : reconnectez-le dans « Mes connexions ».")
        if response.status_code == 404 and self.session_id:
            raise MCPError("Session expirée côté serveur.")
        if response.status_code >= 400:
            raise MCPError(f"Le serveur a répondu {response.status_code} : {response.text[:200]}")
        if "Mcp-Session-Id" in response.headers:
            self.session_id = response.headers["Mcp-Session-Id"]
        if wanted_id is None or response.status_code == 202 or not response.content:
            return None
        if response.headers.get("content-type", "").startswith("text/event-stream"):
            return _from_event_stream(response.text, wanted_id)
        body = response.json()
        if isinstance(body, list):  # a batch: pick our answer
            return next((m for m in body if m.get("id") == wanted_id), None)
        return body


def _from_event_stream(text: str, wanted_id: int) -> dict | None:
    data: list[str] = []
    for line in text.splitlines() + [""]:
        if line.startswith("data:"):
            data.append(line[5:].lstrip())
        elif not line.strip() and data:
            try:
                message = json.loads("\n".join(data))
            except ValueError:
                message = None
            data = []
            if isinstance(message, dict) and message.get("id") == wanted_id:
                return message
    return None


def result_text(result: dict, limit: int = 6000) -> tuple[str, bool]:
    """The tool's answer as text for the agent, and whether it reports an error."""
    parts = []
    for item in result.get("content") or []:
        kind = item.get("type")
        if kind == "text":
            parts.append(item.get("text", ""))
        elif kind == "resource":
            resource = item.get("resource") or {}
            parts.append(resource.get("text") or f"[fichier {resource.get('uri', '')}]")
        elif kind == "resource_link":
            parts.append(f"[lien {item.get('name') or ''} {item.get('uri', '')}]")
        elif kind in ("image", "audio"):
            parts.append(f"[{kind} non affiché]")
    if not parts and result.get("structuredContent") is not None:
        parts.append(json.dumps(result["structuredContent"], ensure_ascii=False))
    text = "\n".join(p for p in parts if p).strip() or "(réponse vide)"
    if len(text) > limit:
        text = text[:limit] + f"\n… (réponse tronquée, {len(text) - limit} caractères de plus)"
    return text, bool(result.get("isError"))
