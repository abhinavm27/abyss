import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from abyss.knowledge import (
    KnowledgeCatalogError,
    SeededHospitalKnowledgeCatalog,
    SQLiteHospitalKnowledgeCatalog,
)


class HospitalKnowledgeCatalogTests(unittest.TestCase):
    def build_catalog(self, path: Path) -> None:
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE hospital (
                id INTEGER PRIMARY KEY, name TEXT, address TEXT, mrf_url TEXT,
                source_page_url TEXT, last_updated_on TEXT, ingested_at TEXT
            );
            CREATE TABLE rate (
                hospital_id INTEGER, code TEXT, code_type TEXT, description TEXT,
                negotiated_dollar REAL, estimable INTEGER
            );
            CREATE TABLE source_manifest (
                id INTEGER PRIMARY KEY, hospital_id INTEGER, retrieved_at TEXT,
                finished_at TEXT, parser_version TEXT, status TEXT
            );
            INSERT INTO hospital VALUES
                (1, 'Hospital A', 'Seattle', 'https://example.test/a.json',
                 'https://example.test/a', '2026-04-01', '2026-07-01T10:00:00+00:00'),
                (2, 'Hospital B', 'Everett', 'https://example.test/b.json',
                 'https://example.test/b', '2026-03-01', '2025-01-01T10:00:00+00:00');
            INSERT INTO source_manifest VALUES
                (1, 1, '2026-07-01T09:00:00+00:00',
                 '2026-07-01T10:00:00+00:00', 'v2', 'success'),
                (2, 1, '2026-08-01T09:00:00+00:00',
                 '2026-08-01T10:00:00+00:00', 'broken', 'failed'),
                (3, 2, '2025-01-01T09:00:00+00:00',
                 '2025-01-01T10:00:00+00:00', 'v1', 'success');
            INSERT INTO rate VALUES
                (1, '73721', 'HCPCS', 'MRI knee', 300, 1),
                (1, '73721', 'HCPCS', 'MRI knee', 500, 1),
                (1, '73721', 'HCPCS', 'formula row', NULL, 0),
                (2, '73721', 'HCPCS', 'MRI knee', 250, 1),
                (2, '70551', 'HCPCS', 'MRI brain', 100, 1);
        """)
        conn.commit()
        conn.close()

    def test_reads_and_ranks_published_rates_without_network_inference(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "knowledge.db"
            self.build_catalog(path)
            rates = SQLiteHospitalKnowledgeCatalog(
                path,
                clock=lambda: datetime(2026, 8, 15, tzinfo=UTC),
            ).prices_for_code("73721")

        self.assertEqual([item.hospital for item in rates], ["Hospital B", "Hospital A"])
        self.assertEqual(rates[1].typical, 400)
        self.assertEqual(rates[1].rate_count, 2)
        self.assertEqual(rates[0].network_status, "unknown")
        self.assertEqual(rates[0].verification_status, "source_backed")
        self.assertEqual(rates[1].source_finished_at, "2026-07-01T10:00:00+00:00")
        self.assertEqual(rates[1].parser_version, "v2")
        self.assertEqual(rates[1].freshness_status, "current")
        self.assertEqual(rates[1].freshness_age_days, 44)
        self.assertEqual(rates[0].freshness_status, "stale")
        self.assertEqual(rates[0].as_dict()["freshness"]["status"], "stale")

    def test_missing_catalog_fails_explicitly(self):
        with self.assertRaises(KnowledgeCatalogError):
            SQLiteHospitalKnowledgeCatalog("/definitely/missing/knowledge.db")

    def test_invalid_catalog_schema_fails_during_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "knowledge.db"
            sqlite3.connect(path).close()
            with self.assertRaisesRegex(KnowledgeCatalogError, "hospital.*missing columns"):
                SQLiteHospitalKnowledgeCatalog(path)

    def test_connection_is_query_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "knowledge.db"
            self.build_catalog(path)
            catalog = SQLiteHospitalKnowledgeCatalog(path)
            with catalog._connect() as conn, self.assertRaises(sqlite3.OperationalError):
                conn.execute("DELETE FROM rate")

    def test_seeded_catalog_is_explicitly_synthetic_and_has_unknown_network(self):
        rates = SeededHospitalKnowledgeCatalog().prices_for_code("73721")
        self.assertEqual(len(rates), 1)
        self.assertEqual(rates[0].network_status, "unknown")
        self.assertIn("synthetic", rates[0].verification_status)
        self.assertIn("synthetic", rates[0].as_dict()["source"]["catalog"])

    def test_custom_freshness_threshold_is_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "knowledge.db"
            self.build_catalog(path)
            rates = SQLiteHospitalKnowledgeCatalog(
                path,
                clock=lambda: datetime(2026, 8, 15, tzinfo=UTC),
                stale_after=timedelta(days=30),
            ).prices_for_code("73721")
        self.assertTrue(all(rate.freshness_status == "stale" for rate in rates))


if __name__ == "__main__":
    unittest.main()
