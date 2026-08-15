import json
import unittest

from abyss.agent import explain


class FakeHermes:
    def __init__(self):
        self.messages = None

    def chat(self, messages, **kwargs):
        self.messages = messages
        return "The estimate is $612; it is not a guarantee."


class AgentTests(unittest.TestCase):
    def test_evidence_is_supplied_as_authoritative_json(self):
        client = FakeHermes()
        reply = explain("What will I pay?", {"expected": 612}, client=client)
        self.assertIn("$612", reply)
        prompt = client.messages[1]["content"]
        self.assertIn(json.dumps({"expected": 612}, separators=(",", ":")), prompt)
        self.assertIn("authoritative JSON", prompt)


if __name__ == "__main__":
    unittest.main()
