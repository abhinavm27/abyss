import tempfile
import unittest
from pathlib import Path

from abyss.knowledge import (
    KnowledgeCatalogError,
    SeededHospitalKnowledgeCatalog,
)
from services.api.app.config import hospital_knowledge_catalog


class HospitalKnowledgeConfigurationTests(unittest.TestCase):
    def test_unset_path_uses_only_explicit_synthetic_fallback(self):
        catalog = hospital_knowledge_catalog({})
        self.assertIsInstance(catalog, SeededHospitalKnowledgeCatalog)
        self.assertIn("synthetic", catalog.source_name)

    def test_blank_path_is_treated_as_unconfigured(self):
        self.assertIsInstance(
            hospital_knowledge_catalog({"ABYSS_KNOWLEDGE_DB": "  "}),
            SeededHospitalKnowledgeCatalog,
        )

    def test_configured_missing_path_is_not_replaced_by_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.db"
            with self.assertRaisesRegex(KnowledgeCatalogError, "not found"):
                hospital_knowledge_catalog({"ABYSS_KNOWLEDGE_DB": str(missing)})


if __name__ == "__main__":
    unittest.main()
