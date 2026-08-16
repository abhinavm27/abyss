import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.api.app import db


class ApiDatabaseMigrationTests(unittest.TestCase):
    def test_trace_migration_allows_multiple_utterances_per_correlation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.db"
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            conn.executescript("""
                CREATE TABLE user (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  email TEXT NOT NULL UNIQUE,
                  password_hash TEXT NOT NULL,
                  salt TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                INSERT INTO user (email,password_hash,salt,created_at)
                  VALUES ('demo@example.test','x','y','2026-08-15T00:00:00Z');
                CREATE TABLE care_agent_trace (
                  correlation_id TEXT PRIMARY KEY,
                  utterance_id TEXT NOT NULL,
                  user_id INTEGER NOT NULL,
                  journey_id TEXT,
                  intent TEXT NOT NULL,
                  plan_json TEXT NOT NULL,
                  message TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                INSERT INTO care_agent_trace VALUES
                  ('correlation-one','utterance-one',1,NULL,'new_care_request','{}',
                   'book an MRI','2026-08-15T00:00:00Z');
            """)
            db.init_db(conn)
            conn.execute(
                """INSERT INTO care_agent_trace
                   (utterance_id,correlation_id,user_id,journey_id,intent,plan_json,
                    message,channel,status,error,created_at,completed_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                ("utterance-two", "correlation-one", 1, None, "continue_journey",
                 "{}", "August 30", "voice", "completed", None,
                 "2026-08-15T00:01:00Z", "2026-08-15T00:01:00Z"),
            )
            rows = conn.execute(
                "SELECT * FROM care_agent_trace WHERE correlation_id=?",
                ("correlation-one",),
            ).fetchall()
            self.assertEqual(len(rows), 2)
            self.assertEqual({row["utterance_id"] for row in rows}, {
                "utterance-one", "utterance-two",
            })
            conn.close()


if __name__ == "__main__":
    unittest.main()
