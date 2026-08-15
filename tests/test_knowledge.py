import sqlite3
import tempfile
import unittest
from pathlib import Path

from abyss.knowledge import KnowledgeCatalogError, SQLiteHospitalKnowledgeCatalog


class HospitalKnowledgeCatalogTests(unittest.TestCase):
    def build_catalog(self, path: Path) -> None:
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE hospital (
                id INTEGER PRIMARY KEY, name TEXT, address TEXT, mrf_url TEXT,
                source_page_url TEXT, last_updated_on TEXT
            );
            CREATE TABLE rate (
                hospital_id INTEGER, code TEXT, code_type TEXT, description TEXT,
                negotiated_dollar REAL, estimable INTEGER
            );
            INSERT INTO hospital VALUES
                (1, 'Hospital A', 'Seattle', 'https://example.test/a.json',
                 'https://example.test/a', '2026-04-01'),
                (2, 'Hospital B', 'Everett', 'https://example.test/b.json',
                 'https://example.test/b', '2026-03-01');
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
            rates = SQLiteHospitalKnowledgeCatalog(path).prices_for_code("73721")

        self.assertEqual([item.hospital for item in rates], ["Hospital B", "Hospital A"])
        self.assertEqual(rates[1].typical, 400)
        self.assertEqual(rates[1].rate_count, 2)
        self.assertEqual(rates[0].network_status, "unknown")
        self.assertEqual(rates[0].verification_status, "source_backed")

    def test_missing_catalog_fails_explicitly(self):
        with self.assertRaises(KnowledgeCatalogError):
            SQLiteHospitalKnowledgeCatalog("/definitely/missing/knowledge.db").prices_for_code("73721")


if __name__ == "__main__":
    unittest.main()
