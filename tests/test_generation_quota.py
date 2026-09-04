"""Failure classification for the paid generation boundary."""
import unittest
from unittest.mock import Mock

from scripts.generate_weekly import gen_json


class QuotaError(Exception):
    code = "insufficient_quota"


class GenerationQuotaTests(unittest.TestCase):
    def test_exhausted_credit_is_named_and_does_not_try_fallback(self):
        client = Mock()
        client.chat.completions.create.side_effect = QuotaError("credit_balance_exhausted")
        with self.assertRaisesRegex(RuntimeError, "credits exhausted"):
            gen_json(client, "system", ["user"], 1)
        self.assertEqual(client.chat.completions.create.call_count, 1)


if __name__ == "__main__":
    unittest.main()
