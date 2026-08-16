"""SQLite schema and connection handling.

One file, no server. The schema is written so it ports to Postgres later without
reshaping: no SQLite-specific column types, and the only SQLite-only object is
the FTS5 index, which pgvector/tsvector would replace.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "abyss.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS hospital (
  id              INTEGER PRIMARY KEY,
  name            TEXT NOT NULL,
  ein             TEXT,
  address         TEXT,
  domain          TEXT,
  source_page_url TEXT,
  -- One health system publishes many hospitals from a single domain, so the
  -- file itself is the identity, not the domain.
  mrf_url         TEXT UNIQUE,
  last_updated_on TEXT,
  ingested_at     TEXT
);

CREATE TABLE IF NOT EXISTS rate (
  id                INTEGER PRIMARY KEY,
  hospital_id       INTEGER NOT NULL REFERENCES hospital(id) ON DELETE CASCADE,
  code              TEXT,
  code_type         TEXT,     -- HCPCS | APR-DRG | MS-DRG | NDC | CDM | ...
  description       TEXT,
  setting           TEXT,     -- inpatient | outpatient | both
  billing_class     TEXT,     -- facility | professional
  payer_name        TEXT,
  plan_name         TEXT,
  methodology       TEXT,
  negotiated_dollar REAL,     -- NULL when the charge is not expressible in dollars
  gross_charge      REAL,
  discounted_cash   REAL,
  min_rate          REAL,
  max_rate          REAL,
  estimable         INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_rate_code      ON rate(code, code_type);
CREATE INDEX IF NOT EXISTS idx_rate_hospital  ON rate(hospital_id);
-- Deliberately no index on `estimable`. It is a near-boolean over 25M rows, so
-- it is useless for filtering, and its presence actively hurt: with no
-- statistics collected SQLite preferred it over idx_rate_code and a price
-- lookup took 96 seconds instead of 0.6.

CREATE VIRTUAL TABLE IF NOT EXISTS rate_fts
  USING fts5(description, content='rate', content_rowid='id', tokenize='porter');

CREATE TABLE IF NOT EXISTS user (
  id            INTEGER PRIMARY KEY,
  email         TEXT NOT NULL UNIQUE,
  -- scrypt, with a per-user salt. See app/auth.py.
  password_hash TEXT NOT NULL,
  salt          TEXT NOT NULL,
  created_at    TEXT NOT NULL
);

-- Only the SHA-256 of the bearer token is kept, so reading this table does not
-- yield a usable session.
CREATE TABLE IF NOT EXISTS session (
  token_hash TEXT PRIMARY KEY,
  user_id    INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_session_user ON session(user_id);

CREATE TABLE IF NOT EXISTS plan (
  id              INTEGER PRIMARY KEY,
  -- Nullable so the pre-accounts row survives the migration; the first account
  -- created adopts it. Every query filters on it.
  user_id         INTEGER REFERENCES user(id) ON DELETE CASCADE,
  -- A member can hold several parsed plans at once to compare them; exactly one
  -- is active and drives estimates.
  is_active       INTEGER NOT NULL DEFAULT 1,
  label           TEXT,
  payer_name      TEXT,
  -- When set, the member picked a real marketplace plan and per-service cost
  -- sharing comes from plan_benefit. Otherwise they typed their benefits by
  -- hand and only the blended deductible/coinsurance below is available.
  qhp_plan_id     TEXT REFERENCES qhp_plan(plan_id),
  deductible      REAL NOT NULL DEFAULT 0,
  deductible_met  REAL NOT NULL DEFAULT 0,
  coinsurance_pct REAL NOT NULL DEFAULT 0,
  copay           REAL,
  oop_max         REAL NOT NULL DEFAULT 0,
  oop_met         REAL NOT NULL DEFAULT 0
);

-- Marketplace plans from the CMS QHP Plan Attributes PUF.
CREATE TABLE IF NOT EXISTS qhp_plan (
  plan_id          TEXT PRIMARY KEY,
  state            TEXT,
  issuer_id        TEXT,
  issuer_name      TEXT,
  marketing_name   TEXT,
  metal_level      TEXT,
  plan_type        TEXT,     -- HMO | PPO | EPO | POS
  hsa_eligible     INTEGER,
  deductible       REAL,
  deductible_family REAL,
  oop_max          REAL,
  oop_max_family   REAL,
  business_year    TEXT
);
CREATE INDEX IF NOT EXISTS idx_qhp_state ON qhp_plan(state, metal_level);

-- Per-service cost sharing from the Benefits and Cost Sharing PUF. One plan has
-- many rows: a plan does not have a single coinsurance rate, it has a different
-- rule per service category.
CREATE TABLE IF NOT EXISTS plan_benefit (
  plan_id          TEXT NOT NULL,
  category         TEXT NOT NULL,   -- pcp | specialist | advanced_imaging | ...
  kind             TEXT NOT NULL,   -- copay | coinsurance | no_charge | not_covered | unknown
  amount           REAL NOT NULL DEFAULT 0,  -- dollars for copay, fraction for coinsurance
  after_deductible INTEGER NOT NULL DEFAULT 0,
  covered          INTEGER NOT NULL DEFAULT 1,
  excluded_from_oop INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (plan_id, category)
);

-- Questions the member has asked, so the home screen can offer them again.
-- Server-side rather than in browser storage because voice lookups go through
-- the WebSocket bridge, not the REST route — the app's primary input would
-- otherwise leave no trace.
CREATE TABLE IF NOT EXISTS lookup_history (
  id          INTEGER PRIMARY KEY,
  user_id     INTEGER REFERENCES user(id) ON DELETE CASCADE,
  query       TEXT NOT NULL,
  code        TEXT,
  description TEXT,
  low         REAL,
  high        REAL,
  asked_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_asked ON lookup_history(asked_at DESC);

-- Appointments the member booked themselves, by phone. ABYSS has no scheduling
-- integration and does not pretend to: this records what you arranged and what
-- it is expected to cost, so the estimate does not evaporate after the call.
CREATE TABLE IF NOT EXISTS appointment (
  id             INTEGER PRIMARY KEY,
  appointment_id TEXT UNIQUE,
  user_id        INTEGER REFERENCES user(id) ON DELETE CASCADE,
  journey_id     TEXT,
  slot_id        TEXT,
  hospital_id    INTEGER REFERENCES hospital(id),
  code           TEXT,
  description    TEXT,
  booked_for     TEXT,     -- ISO date the member gave
  estimated_cost REAL,
  note           TEXT,
  status         TEXT NOT NULL DEFAULT 'confirmed',
  source         TEXT NOT NULL DEFAULT 'member_reported',
  updated_at     TEXT,
  created_at     TEXT NOT NULL
);
-- The index on (user_id, booked_for) is created by migrate(), not here: on a
-- database that predates accounts the table already exists without those
-- columns, and executescript runs in full before any ALTER could add them.

-- Per-file ingest provenance. Records what was skipped, so a thin result is
-- visibly a thin result rather than looking like complete coverage.
CREATE TABLE IF NOT EXISTS ingest_run (
  id             INTEGER PRIMARY KEY,
  hospital_id    INTEGER REFERENCES hospital(id),
  mrf_url        TEXT,
  bytes_          INTEGER,
  rows_written   INTEGER,
  rows_skipped   INTEGER,
  skip_reasons   TEXT,
  started_at     TEXT,
  finished_at    TEXT
);

-- Durable user-scoped journey index. snapshot_json is an auditable sandbox
-- projection; deterministic domain objects remain the action authority.
CREATE TABLE IF NOT EXISTS care_journey (
  journey_id    TEXT PRIMARY KEY,
  user_id       INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
  title         TEXT NOT NULL,
  stage         TEXT NOT NULL,
  status        TEXT NOT NULL,
  snapshot_json TEXT NOT NULL,
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_care_journey_user
  ON care_journey(user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS care_agent_trace (
  utterance_id   TEXT PRIMARY KEY,
  correlation_id TEXT NOT NULL,
  user_id        INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
  journey_id     TEXT,
  intent         TEXT NOT NULL,
  plan_json      TEXT NOT NULL,
  message        TEXT NOT NULL,
  channel        TEXT NOT NULL DEFAULT 'chat',
  status         TEXT NOT NULL DEFAULT 'completed',
  error          TEXT,
  created_at     TEXT NOT NULL,
  completed_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_care_agent_trace_user
  ON care_agent_trace(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_care_agent_trace_correlation
  ON care_agent_trace(correlation_id, created_at);

-- Durable, append-oriented member memory. Agents may append sourced facts and
-- read a redacted snapshot; verification remains owned by deterministic flows.
CREATE TABLE IF NOT EXISTS user_memory_fact (
  id                  INTEGER PRIMARY KEY,
  user_id             INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
  fact_name           TEXT NOT NULL,
  value_json          TEXT NOT NULL,
  source              TEXT NOT NULL,
  observed_at         TEXT NOT NULL,
  confidence          REAL NOT NULL,
  verification_status TEXT NOT NULL,
  consent_requirement TEXT,
  superseded_by       INTEGER REFERENCES user_memory_fact(id),
  created_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_user_memory_fact_current
  ON user_memory_fact(user_id, fact_name, superseded_by, id DESC);

CREATE TABLE IF NOT EXISTS agent_memory_event (
  id          INTEGER PRIMARY KEY,
  user_id     INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
  agent_role  TEXT NOT NULL,
  event_type  TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  related_ref TEXT,
  created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_memory_event_user
  ON agent_memory_event(user_id, id DESC);

CREATE TABLE IF NOT EXISTS messaging_preference (
  user_id            INTEGER PRIMARY KEY REFERENCES user(id) ON DELETE CASCADE,
  channel            TEXT NOT NULL,
  destination_label  TEXT NOT NULL,
  enabled            INTEGER NOT NULL DEFAULT 0,
  consent_scope      TEXT,
  consented_at       TEXT,
  updated_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messaging_receipt (
  id                     INTEGER PRIMARY KEY,
  user_id                INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
  channel                TEXT NOT NULL,
  destination_redacted   TEXT NOT NULL,
  message_kind           TEXT NOT NULL,
  result_ref             TEXT NOT NULL,
  confirmation_reference TEXT NOT NULL,
  sandbox                INTEGER NOT NULL DEFAULT 1,
  consent_scope          TEXT NOT NULL,
  created_at             TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messaging_receipt_user
  ON messaging_receipt(user_id, id DESC);
"""


def connect(db_path: str | os.PathLike[str] | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else Path(os.environ.get("ABYSS_DB", DEFAULT_DB_PATH))
    path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: FastAPI runs sync endpoints in a threadpool, and
    # the test client shares one connection across threads. Each request still
    # gets its own connection in production, so nothing is concurrently shared.
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    migrate(conn)
    conn.commit()


# Columns added after a table already existed in the wild. `CREATE TABLE IF NOT
# EXISTS` silently does nothing to an existing table, so accounts would appear to
# work on a fresh database and fail on the developer's — which holds 39.6M rates
# that are not going to be re-ingested.
_ADDED_COLUMNS = {
    "plan": [("user_id", "INTEGER"), ("is_active", "INTEGER NOT NULL DEFAULT 1")],
    "lookup_history": [("user_id", "INTEGER")],
    "appointment": [
        ("appointment_id", "TEXT"),
        ("user_id", "INTEGER"),
        ("journey_id", "TEXT"),
        ("slot_id", "TEXT"),
        ("booked_for", "TEXT"),
        ("estimated_cost", "REAL"),
        ("note", "TEXT"),
        ("status", "TEXT NOT NULL DEFAULT 'confirmed'"),
        ("source", "TEXT NOT NULL DEFAULT 'member_reported'"),
        ("updated_at", "TEXT"),
    ],
}


def migrate(conn: sqlite3.Connection) -> None:
    """Bring an existing database up to the current schema, preserving data."""
    for table, columns in _ADDED_COLUMNS.items():
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if not existing:
            continue  # table not created yet; SCHEMA already has the columns
        for name, decl in columns:
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")

    trace_columns = {
        row["name"]: row for row in conn.execute("PRAGMA table_info(care_agent_trace)")
    }
    # Early builds made correlation_id the primary key. A voice session uses
    # one correlation ID for many utterances, so the second turn collided with
    # the first. Rebuild once with utterance_id as the per-turn identity while
    # preserving every existing trace.
    utterance_column = trace_columns.get("utterance_id")
    if trace_columns and (
        utterance_column is None or utterance_column["pk"] != 1
        or "channel" not in trace_columns
        or "status" not in trace_columns
    ):
        conn.executescript("""
            CREATE TABLE care_agent_trace_next (
              utterance_id   TEXT PRIMARY KEY,
              correlation_id TEXT NOT NULL,
              user_id        INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
              journey_id     TEXT,
              intent         TEXT NOT NULL,
              plan_json      TEXT NOT NULL,
              message        TEXT NOT NULL,
              channel        TEXT NOT NULL DEFAULT 'chat',
              status         TEXT NOT NULL DEFAULT 'completed',
              error          TEXT,
              created_at     TEXT NOT NULL,
              completed_at   TEXT
            );
            INSERT OR IGNORE INTO care_agent_trace_next
              (utterance_id,correlation_id,user_id,journey_id,intent,plan_json,
               message,channel,status,error,created_at,completed_at)
            SELECT utterance_id,correlation_id,user_id,journey_id,intent,plan_json,
                   message,'chat','completed',NULL,created_at,created_at
            FROM care_agent_trace;
            DROP TABLE care_agent_trace;
            ALTER TABLE care_agent_trace_next RENAME TO care_agent_trace;
            CREATE INDEX idx_care_agent_trace_user
              ON care_agent_trace(user_id, created_at DESC);
            CREATE INDEX idx_care_agent_trace_correlation
              ON care_agent_trace(correlation_id, created_at);
        """)

    # The rows left behind by the booking feature that was removed are not real
    # appointments — they are the fabricated fixed slot it invented. Now that
    # appointments are shown to the member as things they arranged themselves,
    # leaving these would put five invented bookings on that screen.
    # `status` only exists on the pre-removal table, so this is also the test for
    # whether there is anything to clean up at all.
    if "status" in {r["name"] for r in conn.execute("PRAGMA table_info(appointment)")}:
        conn.execute("DELETE FROM appointment WHERE booked_for IS NULL AND status = 'requested'")

    # Safe now that the columns above exist on both fresh and migrated databases.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_appt_user ON appointment(user_id, booked_for)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_appt_external ON appointment(appointment_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_appt_journey ON appointment(journey_id, status)")
    conn.commit()


def record_lookup(
    conn: sqlite3.Connection,
    query: str,
    code: str | None,
    description: str | None,
    low: float | None,
    high: float | None,
    user_id: int | None = None,
) -> None:
    """Remember a question that produced a price.

    Called from both the REST route and the voice bridge. Failures are swallowed
    on purpose: history is a convenience, and losing it must never break the
    answer the member actually asked for.
    """
    from datetime import datetime, timezone

    try:
        conn.execute(
            """INSERT INTO lookup_history (user_id, query, code, description, low, high, asked_at)
               VALUES (?,?,?,?,?,?,?)""",
            (user_id, query, code, description, low, high,
             datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )
        conn.commit()
    except sqlite3.Error:
        pass


def recent_lookups(conn: sqlite3.Connection, limit: int = 5, user_id: int | None = None) -> list[dict]:
    """Most recent distinct questions, newest first.

    Grouped by code so asking about the same MRI three times occupies one slot
    rather than filling the home screen.
    """
    # Ordered by id, not asked_at: the timestamp has second precision, so two
    # lookups in the same second tie and the order becomes arbitrary. The id is
    # the true insertion order. MAX(id) also selects the most recent row's
    # columns for each code, so the query text shown is the latest phrasing.
    rows = conn.execute(
        """SELECT query, code, description, low, high, asked_at, MAX(id) AS id
           FROM lookup_history
           WHERE code IS NOT NULL AND user_id IS ?
           GROUP BY code
           ORDER BY id DESC
           LIMIT ?""",
        (user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def approximate_rate_count(conn: sqlite3.Connection) -> int:
    """Row count for `rate`, read from the planner's statistics.

    `SELECT COUNT(*) FROM rate` is a full scan — 32 seconds over 39.6M rows,
    which made the health check the slowest thing in the app and timed out the
    dev proxy on every load. ANALYZE already records the row count as the first
    field of each index's `stat`, so this reads it instead. It is only as fresh
    as the last ingest, which is exactly right for a figure that changes only
    when data is ingested.
    """
    try:
        row = conn.execute(
            "SELECT stat FROM sqlite_stat1 WHERE tbl = 'rate' LIMIT 1"
        ).fetchone()
        if row and row[0]:
            return int(str(row[0]).split()[0])
    except sqlite3.Error:
        pass
    return 0


def analyze(conn: sqlite3.Connection) -> None:
    """Refresh query-planner statistics.

    Not optional at this size: without them SQLite prefers the low-selectivity
    `estimable` index over the code index, and a price lookup goes from under a
    second to a minute and a half.
    """
    conn.execute("ANALYZE")
    conn.commit()


def rebuild_fts(conn: sqlite3.Connection) -> None:
    """Rebuild the FTS index from the rate table.

    Cheaper than maintaining triggers during a bulk load of ~100k rows.
    """
    conn.execute("INSERT INTO rate_fts(rate_fts) VALUES('rebuild')")
    conn.commit()
