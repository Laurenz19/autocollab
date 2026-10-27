"""Storage for agents, runs, chains, accounts and settings: PostgreSQL, or SQLite (data/app.db).

Several organisations share one server: every table carries organisation_id. On PostgreSQL each
request runs inside the organisation of the person making it (current_org, set by the middleware in
app/main.py): row-level security then only lets that organisation's rows through, whatever the query,
and new rows get its id. Without an organisation (sign-in, scheduler, tools) the code sees everything,
as it needs to; new rows then take their owner's organisation. SQLite serves a single organisation.

DATABASE_URL picks the database: postgresql://... for a server shared by several clients, nothing
for a single installation (SQLite, as before). The rest of the app does not see the difference:
connect() yields a connection whose execute() takes the same SQL, with ? or :name placeholders,
and returns rows read by position or by column name, like sqlite3.Row.

Events and screenshots stay on disk in runs/<id>/; the database holds what lists and history pages
need, so nothing is lost when the server restarts. The encryption key stays a file (app/vault.py),
never in the database.
"""

import contextvars
import json
import re
import sqlite3
import threading
import uuid
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import datetime

from . import config

DB_FILE = config.DATA_DIR / "app.db"
DATABASE_URL = config.DATABASE_URL
POSTGRES = DATABASE_URL.startswith(("postgres://", "postgresql://"))

# The organisation the current request (or background run) acts for; None = no organisation.
current_org: contextvars.ContextVar[str | None] = contextvars.ContextVar("autocollab_org", default=None)

# Tables whose rows belong to an organisation; those with an owner column take its organisation by default.
OWNER_TABLES = ["agents", "runs", "sites", "integrations", "oauth_codes", "oauth_grants", "oauth_tokens", "api_tokens",
                "chains", "chain_runs", "assistant_conversations"]
ORG_TABLES = ["users", "contexts", "assistant_messages", *OWNER_TABLES]
TENANT_ROLE = "autocollab_tenant"

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

-- Organisations sharing the server (clients). settings: per-organisation choices (two-factor policy...)
CREATE TABLE IF NOT EXISTS organisations (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    settings   TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

-- Accounts (formerly data/users.json): one row per user, the account itself as JSON (see app/auth.py)
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    data     TEXT NOT NULL
);

-- Settings of the installation (formerly data/settings.json); secrets inside stay encrypted (app/vault.py)
CREATE TABLE IF NOT EXISTS app_settings (
    key        TEXT PRIMARY KEY,
    data       TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
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
    ("runs", "guided", "INTEGER NOT NULL DEFAULT 0"),               # 1 = guided session: the agent waits for messages
    # Several organisations on one server: every row belongs to one (filled in on startup for older rows)
    *[(table, "organisation_id", "TEXT") for table in ORG_TABLES],
]

_lock = threading.Lock()
_initialized = False
_pool = None
_tenant_role = False   # PostgreSQL: the restricted role that requests switch to (see _pg_tenancy)
_default_org = None


class Row:
    """A result row read by position (row[0]), by column (row["name"]) or as dict(row), like sqlite3.Row."""
    __slots__ = ("_values", "_index")

    def __init__(self, values, index):
        self._values, self._index = values, index

    def __getitem__(self, key):
        return self._values[self._index[key]] if isinstance(key, str) else self._values[key]

    def keys(self):
        return list(self._index)

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def __repr__(self):
        return f"Row({dict(zip(self._index, self._values))})"


# --- PostgreSQL -------------------------------------------------------------------------

_NAMED = re.compile(r"(?<![:\w]):([A-Za-z_]\w*)")


def _pg_sql(sql: str, named: bool) -> str:
    """SQLite placeholders (? and :name) to psycopg's (%s and %(name)s); a literal % is doubled."""
    sql = sql.replace("%", "%%")
    return _NAMED.sub(r"%(\1)s", sql) if named else sql.replace("?", "%s")


def _pg_schema(script: str) -> str:
    return (script.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY")
                  .replace(" REAL", " DOUBLE PRECISION"))


def _row_factory(cursor):
    index = {c.name: i for i, c in enumerate(cursor.description or [])}
    return lambda values: Row(values, index)


def _get_pool():
    global _pool
    if _pool is None:
        from psycopg.types.numeric import IntDumper
        from psycopg_pool import ConnectionPool

        class BoolAsInt(IntDumper):  # flags are INTEGER columns, as in SQLite
            def dump(self, obj):
                return super().dump(int(obj))

        def configure(conn):
            conn.adapters.register_dumper(bool, BoolAsInt)
            conn.row_factory = _row_factory

        _pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=config.DATABASE_POOL_SIZE, configure=configure, open=True)
    return _pool


class _PgConnection:
    """What the app uses of a sqlite3 connection: execute(sql, params) with SQLite placeholders."""

    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql: str, params=None):
        if params is None:
            return self.raw.execute(sql)
        return self.raw.execute(_pg_sql(sql, isinstance(params, Mapping)), params)


# --- schema, first start ------------------------------------------------------------------

def _columns(conn, table: str) -> set[str]:
    if POSTGRES:
        rows = conn.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = ?",
                            (table,)).fetchall()
        return {row[0] for row in rows}
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _migrate(conn) -> None:
    for table, column, definition in _MIGRATIONS:
        if column not in _columns(conn, table):
            if POSTGRES:
                definition = definition.replace("REAL", "DOUBLE PRECISION")
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _import_files(conn) -> None:
    """Accounts and settings kept in data/*.json by earlier versions move into the database, once."""
    now = datetime.now().isoformat(timespec="seconds")
    users_file, settings_file = config.DATA_DIR / "users.json", config.DATA_DIR / "settings.json"
    if users_file.exists() and not conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
        for username, user in json.loads(users_file.read_text(encoding="utf-8")).items():
            conn.execute("INSERT INTO users (username, data) VALUES (?, ?)", (username, json.dumps(user, ensure_ascii=False)))
        users_file.replace(users_file.with_name("users.json.importe"))
    if settings_file.exists() and not conn.execute("SELECT 1 FROM app_settings WHERE key = 'settings'").fetchone():
        conn.execute("INSERT INTO app_settings (key, data, updated_at) VALUES ('settings', ?, ?)",
                     (settings_file.read_text(encoding="utf-8"), now))
        settings_file.replace(settings_file.with_name("settings.json.importe"))


def _setup_organisations(conn) -> None:
    """The installation's own organisation (recorded once, never guessed), and older rows attached to theirs."""
    global _default_org
    recorded = conn.execute("SELECT data FROM app_settings WHERE key = 'platform_organisation'").fetchone()
    row = recorded and conn.execute("SELECT id FROM organisations WHERE id = ?", (recorded["data"],)).fetchone()
    row = row or conn.execute("SELECT id FROM organisations ORDER BY created_at, id LIMIT 1").fetchone()
    if row:
        default = row["id"]
    else:
        stored = conn.execute("SELECT data FROM app_settings WHERE key = 'settings'").fetchone()
        name = (json.loads(stored["data"]).get("organisation") or {}).get("name", "") if stored else ""
        default = "org-" + uuid.uuid4().hex[:12]
        conn.execute("INSERT INTO organisations (id, name, settings, created_at) VALUES (?, ?, '{}', ?)",
                     (default, (name or config.ORG_NAME or "Mon organisation").strip(), datetime.now().isoformat(timespec="seconds")))
    _default_org = default
    if not recorded:
        conn.execute("INSERT INTO app_settings (key, data, updated_at) VALUES ('platform_organisation', ?, ?)",
                     (default, datetime.now().isoformat(timespec="seconds")))
    missing = "organisation_id IS NULL OR organisation_id = ''"
    conn.execute(f"UPDATE users SET organisation_id = ? WHERE {missing}", (default,))
    for table in OWNER_TABLES:
        conn.execute(f"UPDATE {table} SET organisation_id = COALESCE((SELECT u.organisation_id FROM users u WHERE u.username = {table}.owner), ?)"
                     f" WHERE {missing}", (default,))
    # The organisation's shared context was the single "cabinet" scope: it becomes "cabinet:<organisation>".
    conn.execute("UPDATE contexts SET scope = ? WHERE scope = 'cabinet'", (f"cabinet:{default}",))
    conn.execute("UPDATE contexts SET organisation_id = CASE WHEN scope LIKE 'cabinet:%' THEN substr(scope, 9)"
                 " ELSE COALESCE((SELECT u.organisation_id FROM users u WHERE 'user:' || u.username = contexts.scope), ?) END"
                 f" WHERE {missing}", (default,))
    conn.execute("UPDATE assistant_messages SET organisation_id = COALESCE((SELECT c.organisation_id FROM assistant_conversations c"
                 f" WHERE c.id = assistant_messages.conversation_id), ?) WHERE {missing}", (default,))


_FILL_ORG = """
CREATE OR REPLACE FUNCTION autocollab_fill_org() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.organisation_id IS NULL OR NEW.organisation_id = '' THEN
    NEW.organisation_id := NULLIF(current_setting('app.org_id', true), '');
  END IF;
  IF (NEW.organisation_id IS NULL OR NEW.organisation_id = '') AND TG_ARGV[0] = 'owner' THEN
    NEW.organisation_id := (SELECT organisation_id FROM users WHERE username = NEW.owner);
  END IF;
  IF NEW.organisation_id IS NULL OR NEW.organisation_id = '' THEN
    NEW.organisation_id := (SELECT data FROM app_settings WHERE key = 'platform_organisation');
  END IF;
  RETURN NEW;
END $$;
"""
_IN_ORG = "COALESCE(current_setting('app.org_id', true), '') = '' OR {column} = current_setting('app.org_id', true)"


def _pg_tenancy(conn) -> None:
    """New rows take the organisation of the request (else of their owner), and each organisation only sees its rows.

    Requests switch to a restricted role, so the isolation holds even when the app connects as a superuser
    (superusers skip row-level security). Without the right to create that role, FORCE ROW LEVEL SECURITY
    still applies to the table owner the app connects as.
    """
    global _tenant_role
    conn.execute(_FILL_ORG)
    for table in ORG_TABLES:
        conn.execute(f"DROP TRIGGER IF EXISTS autocollab_org ON {table}")
        conn.execute(f"CREATE TRIGGER autocollab_org BEFORE INSERT ON {table} FOR EACH ROW"
                     f" EXECUTE FUNCTION autocollab_fill_org('{'owner' if table in OWNER_TABLES else 'none'}')")
    for table, column in [*((t, "organisation_id") for t in ORG_TABLES), ("organisations", "id")]:
        conn.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        conn.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        conn.execute(f"DROP POLICY IF EXISTS autocollab_org ON {table}")
        rule = _IN_ORG.format(column=column)
        conn.execute(f"CREATE POLICY autocollab_org ON {table} USING ({rule}) WITH CHECK ({rule})")
    try:
        with conn.raw.transaction():  # savepoint: without the right to create roles, carry on without it
            conn.execute(f"""DO $$ BEGIN
              IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{TENANT_ROLE}') THEN CREATE ROLE {TENANT_ROLE} NOLOGIN; END IF;
              EXECUTE format('GRANT {TENANT_ROLE} TO %I', current_user);
              EXECUTE format('GRANT USAGE ON SCHEMA %I TO {TENANT_ROLE}', current_schema());
              EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA %I TO {TENANT_ROLE}', current_schema());
              EXECUTE format('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA %I TO {TENANT_ROLE}', current_schema());
            END $$""")
        _tenant_role = True
    except Exception:
        _tenant_role = False


def _sqlite_fill_org(conn) -> None:
    """SQLite has no row-level security, but new rows still take their owner's organisation (else the
    platform's), as on PostgreSQL: what is counted per organisation (credits, plan limits) needs it."""
    platform = "(SELECT data FROM app_settings WHERE key = 'platform_organisation')"
    for table in ["users", *OWNER_TABLES]:
        value = platform if table == "users" else f"COALESCE((SELECT u.organisation_id FROM users u WHERE u.username = NEW.owner), {platform})"
        conn.execute(f"DROP TRIGGER IF EXISTS autocollab_org_{table}")
        conn.execute(f"CREATE TRIGGER autocollab_org_{table} AFTER INSERT ON {table}"
                     f" WHEN NEW.organisation_id IS NULL OR NEW.organisation_id = ''"
                     f" BEGIN UPDATE {table} SET organisation_id = {value} WHERE rowid = NEW.rowid; END")


def default_org() -> str:
    """The installation's own organisation (app_settings 'platform_organisation'): its administrators run the platform."""
    if _default_org is None:
        with connect(system=True):
            pass
    return _default_org


def run_in_org(org: str | None) -> contextvars.Context:
    """A context for a background task acting for an organisation (asyncio.create_task(..., context=...))."""
    ctx = contextvars.copy_context()
    ctx.run(current_org.set, org)
    return ctx


def _init(conn) -> None:
    if POSTGRES:
        conn.execute("SELECT pg_advisory_xact_lock(?)", (870142,))  # several server processes: one creates the tables
        conn.execute(_pg_schema(_SCHEMA))
    else:
        conn.executescript(_SCHEMA)
    _migrate(conn)
    _import_files(conn)
    _setup_organisations(conn)
    if POSTGRES:
        _pg_tenancy(conn)
    else:
        _sqlite_fill_org(conn)


@contextmanager
def connect(system: bool = False, org: str | None = None):
    """One connection per operation, committed at the end (rolled back on error).

    PostgreSQL: taken from a pool, operations run side by side, inside the organisation of `org`, else
    of the current request; system=True looks across organisations. SQLite: serialized, as before.
    """
    global _initialized
    if POSTGRES:
        with _get_pool().connection() as raw:
            conn = _PgConnection(raw)
            if not _initialized:
                _init(conn)
                raw.commit()
                _initialized = True
            scope = None if system else (org or current_org.get())
            if scope:
                conn.execute("SELECT set_config('app.org_id', ?, true)", (scope,))
                if _tenant_role:
                    raw.execute(f"SET LOCAL ROLE {TENANT_ROLE}")
            yield conn
        return
    with _lock:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        try:
            if not _initialized:
                _init(conn)
                conn.commit()
                _initialized = True
            yield conn
            conn.commit()
        finally:
            conn.close()


def reset_for_tests() -> None:
    """Forget the pool and the first-start state (tests switch databases)."""
    global _pool, _initialized, _default_org, _tenant_role
    if _pool is not None:
        _pool.close()
    _pool, _initialized, _default_org, _tenant_role = None, False, None, False
