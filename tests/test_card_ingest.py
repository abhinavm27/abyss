import unittest

from services.api.app.ingest.card import parse, parse_text


class InsuranceCardIngestTests(unittest.TestCase):
    def test_parses_only_labeled_card_fields(self) -> None:
        result = parse_text("""
            PREMERA BLUE CROSS
            Plan: Heritage Plus
            PPO
            Member ID: ABC123456
            Group Number: 7654321
            Rx BIN: 610014
            Office Visit Copay $25
        """)
        self.assertEqual(result.payer_name.lower(), "premera blue cross")
        self.assertEqual(result.plan_name, "Heritage Plus")
        self.assertEqual(result.plan_type, "PPO")
        self.assertEqual(result.member_id, "ABC123456")
        self.assertEqual(result.group_number, "7654321")
        self.assertEqual(result.rx_bin, "610014")
        self.assertEqual(result.copays["Office Visit Copay"], 25.0)

    def test_image_without_ocr_does_not_call_or_invent_a_model_result(self) -> None:
        result = parse(b"synthetic-image", extracted_text=None)
        self.assertIsNone(result.member_id)
        self.assertIn("no readable", result.warnings[0].lower())

    def test_unlabeled_numbers_are_not_treated_as_plan_benefits(self) -> None:
        result = parse_text("Premera Blue Cross\nMember ID: TEST123\n6300\n8900")

        self.assertEqual(result.member_id, "TEST123")
        self.assertEqual(result.copays, {})
        self.assertFalse(result.as_dict()["provides_cost_sharing"])


if __name__ == "__main__":
    unittest.main()
