"""SQLite storage for agents and task runs (data/app.db).

Events and screenshots stay on disk in runs/<id>/; the database holds what
lists and history pages need, so nothing is lost when the server restarts.
"""

import sqlite3
import threading
from contextlib import contextmanager

from . import config

DB_FILE = config.DATA_DIR / "app.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    id           TEXT PRIMARY KEY,
    owner        TEXT NOT NULL,
    name         TEXT NOT NULL,
    instructions TEXT NOT NULL,
    max_steps    INTEGER,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS agents_owner ON agents(owner);

CREATE TABLE IF NOT EXISTS runs (
    id          TEXT PRIMARY KEY,
    owner       TEXT NOT NULL,
    agent_id    TEXT,
    agent_name  TEXT,            -- copied at launch: history stays readable if the agent is renamed or deleted
    task        TEXT NOT NULL,   -- the instructions exactly as sent, variables already filled in
    status      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    finished_at TEXT,
    result      TEXT,
    steps       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS runs_owner ON runs(owner, created_at);

-- "Mes connexions": the sites each user logs in to for their agents
CREATE TABLE IF NOT EXISTS sites (
    id             TEXT PRIMARY KEY,
    owner          TEXT NOT NULL,
    name           TEXT NOT NULL,
    url            TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    last_opened_at TEXT
);
CREATE INDEX IF NOT EXISTS sites_owner ON sites(owner);

-- Applications connected through MCP ("Mes connexions"); secret = encrypted tokens, see app/integrations.py
CREATE TABLE IF NOT EXISTS integrations (
    id           TEXT PRIMARY KEY,
    owner        TEXT NOT NULL,
    kind         TEXT NOT NULL,          -- gmail | drive | ... | custom
    name         TEXT NOT NULL,
    url          TEXT NOT NULL,          -- the MCP server
    secret       TEXT,
    read_only    INTEGER NOT NULL DEFAULT 1,
    enabled      INTEGER NOT NULL DEFAULT 1,   -- 0 = kept but not given to the agents
    account      TEXT NOT NULL DEFAULT '',     -- e.g. the Google address or the Slack workspace
    created_at   TEXT NOT NULL,
    last_used_at TEXT,
    last_error   TEXT
);
CREATE INDEX IF NOT EXISTS integrations_owner ON integrations(owner);

-- OAuth for MCP clients (claude.ai, ChatGPT...): see app/oauth.py; codes and tokens are SHA-256 hashes
CREATE TABLE IF NOT EXISTS oauth_clients (
    client_id    TEXT PRIMARY KEY,
    secret_hash  TEXT,                  -- NULL for public clients (PKCE only)
    name         TEXT NOT NULL,
    redirect_uris TEXT NOT NULL,        -- JSON list
    auth_method  TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    last_used_at TEXT
);
CREATE TABLE IF NOT EXISTS oauth_codes (
    code_hash    TEXT PRIMARY KEY,
    client_id    TEXT NOT NULL,
    owner        TEXT NOT NULL,
    redirect_uri TEXT NOT NULL,
    challenge    TEXT NOT NULL,
    resource     TEXT NOT NULL DEFAULT '',
    expires_at   REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS oauth_grants (       -- one per user and application they approved
    id           TEXT PRIMARY KEY,
    client_id    TEXT NOT NULL,
    owner        TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    last_used_at TEXT
);
CREATE INDEX IF NOT EXISTS oauth_grants_owner ON oauth_grants(owner);
CREATE TABLE IF NOT EXISTS oauth_tokens (
    token_hash   TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,         -- access | refresh
    grant_id     TEXT NOT NULL,
    client_id    TEXT NOT NULL,
    owner        TEXT NOT NULL,
    expires_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS oauth_tokens_grant ON oauth_tokens(grant_id);

-- Personal API keys (Authorization: Bearer ...) for scripts, n8n and MCP clients; only a hash is kept
CREATE TABLE IF NOT EXISTS api_tokens (
    id           TEXT PRIMARY KEY,
    owner        TEXT NOT NULL,
    name         TEXT NOT NULL,
    token_hash   TEXT NOT NULL UNIQUE,
    prefix       TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    last_used_at TEXT
);
CREATE INDEX IF NOT EXISTS api_tokens_owner ON api_tokens(owner);

-- Chains: agents run one after another; each passes its result and downloaded files to the next
CREATE TABLE IF NOT EXISTS chains (
    id               TEXT PRIMARY KEY,
    owner            TEXT NOT NULL,
    name             TEXT NOT NULL,
    steps            TEXT NOT NULL,   -- JSON [{"agent_id", "on_failure": "stop" | "continue"}]
    schedule         TEXT,
    schedule_enabled INTEGER NOT NULL DEFAULT 0,
    next_run_at      TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS chains_owner ON chains(owner);

CREATE TABLE IF NOT EXISTS chain_runs (
    id          TEXT PRIMARY KEY,
    owner       TEXT NOT NULL,
    chain_id    TEXT NOT NULL,
    chain_name  TEXT NOT NULL,
    status      TEXT NOT NULL,
    trigger     TEXT NOT NULL DEFAULT 'manuel',
    created_at  TEXT NOT NULL,
    finished_at TEXT,
    steps       TEXT NOT NULL      -- JSON [{"agent_id", "agent_name", "on_failure", "run_id", "status", "result"}]
);
CREATE INDEX IF NOT EXISTS chain_runs_owner ON chain_runs(owner, created_at);

-- Context added to agents' instructions: "cabinet" (administrators) or "user:<username>"
CREATE TABLE IF NOT EXISTS contexts (
    scope      TEXT PRIMARY KEY,
    data       TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by TEXT NOT NULL
);

-- In-app assistant (side panel, app/assistant.py): each user's conversations, private to them
CREATE TABLE IF NOT EXISTS assistant_conversations (
    id         TEXT PRIMARY KEY,
    owner      TEXT NOT NULL,
    title      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS assistant_conversations_owner ON assistant_conversations(owner, updated_at);
CREATE TABLE IF NOT EXISTS assistant_messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    role            TEXT NOT NULL,                -- user | assistant
    content         TEXT NOT NULL,
    tools           TEXT NOT NULL DEFAULT '[]',   -- JSON: names of the tools the assistant used for this answer
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS assistant_messages_conversation ON assistant_messages(conversation_id, id);
"""

# Columns added after the first release: (table, column, definition). Added on startup when missing.
_MIGRATIONS = [
    ("agents", "allowed_domains", "TEXT NOT NULL DEFAULT '[]'"),   # JSON list; empty = no restriction
    ("agents", "approval_mode", "INTEGER NOT NULL DEFAULT 0"),     # 1 = ask a human before irreversible actions
    ("agents", "schedule", "TEXT"),                                # JSON, see app/schedule.py; NULL = not scheduled
    ("agents", "schedule_enabled", "INTEGER NOT NULL DEFAULT 0"),
    ("agents", "notify", "INTEGER NOT NULL DEFAULT 1"),            # unused since e-mails were removed; kept for old databases
    ("agents", "next_run_at", "TEXT"),
    ("runs", "trigger", "TEXT NOT NULL DEFAULT 'manuel'"),         # manuel | planifie
    ("runs", "chain_run_id", "TEXT"),                              # set when the run is a step of a chain
    ("agents", "created_via", "TEXT NOT NULL DEFAULT 'app'"),      # app | mcp: where it was created / last edited
    ("agents", "updated_via", "TEXT NOT NULL DEFAULT 'app'"),
    ("chains", "created_via", "TEXT NOT NULL DEFAULT 'app'"),
    ("chains", "updated_via", "TEXT NOT NULL DEFAULT 'app'"),
    ("runs", "chain_name", "TEXT"),
    ("runs", "provider", "TEXT"),                                   # AI provider and model used, set when the run starts
    ("runs", "model", "TEXT"),
    ("sites", "signed_in", "INTEGER"),                             # 1 / 0, last seen by "Mes connexions" or an agent; NULL = unknown
    ("sites", "checked_at", "TEXT"),
    # Tokens billed by the AI provider (app/usage.py), their cost and the credits they make (app/pricing.py)
    ("runs", "input_tokens", "INTEGER NOT NULL DEFAULT 0"),
    ("runs", "output_tokens", "INTEGER NOT NULL DEFAULT 0"),
    ("runs", "cache_read_tokens", "INTEGER NOT NULL DEFAULT 0"),
    ("runs", "cache_write_tokens", "INTEGER NOT NULL DEFAULT 0"),
    ("runs", "cost_usd", "REAL"),                                  # NULL: model missing from the price table
    ("runs", "credits", "REAL NOT NULL DEFAULT 0"),
]

_lock = threading.Lock()
_initialized = False


def _migrate(conn: sqlite3.Connection) -> None:
    for table, column, definition in _MIGRATIONS:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


@contextmanager
def connect():
    """One short-lived connection per operation, serialized: plenty for a small office."""
    global _initialized
    with _lock:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        try:
            if not _initialized:
                conn.executescript(_SCHEMA)
                _migrate(conn)
                _initialized = True
            yield conn
            conn.commit()
        finally:
            conn.close()
