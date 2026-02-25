"""
Adversarial correctness tests.
Tests nested merge, action hash invariance, question hash canonicalization.
"""
import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from noe.noe_parser import merge_layers_for_validation, compute_question_hash, run_noe_logic


class TestNestedMerge(unittest.TestCase):
    """Test deep merge preserves nested shard keys."""

    def test_spatial_thresholds_merge(self):
        """Root sets near=1, far=10; Domain overwrites far=20; both preserved."""
        ctx = {
            "root": {"spatial": {"thresholds": {"near": 1.0, "far": 10.0}}},
            "domain": {"spatial": {"thresholds": {"far": 20.0}}},
            "local": {}
        }

        merged = merge_layers_for_validation(ctx)

        self.assertEqual(merged["spatial"]["thresholds"]["near"], 1.0)
        self.assertEqual(merged["spatial"]["thresholds"]["far"], 20.0)

    def test_modal_knowledge_merge(self):
        """modal.knowledge preserves both layers."""
        ctx = {
            "root": {"modal": {"knowledge": {"@fact1": True}}},
            "local": {"modal": {"knowledge": {"@fact2": True}}}
        }

        merged = merge_layers_for_validation(ctx)

        self.assertIn("@fact1", merged["modal"]["knowledge"])
        self.assertIn("@fact2", merged["modal"]["knowledge"])


class TestQuestionHashCanonical(unittest.TestCase):
    """Question hash must be whitespace/format invariant."""

    def test_whitespace_invariance(self):
        """Same chain with different whitespace produces same hash."""
        ctx_hash = "abc123"
        timestamp = 1000.0

        h1 = compute_question_hash("mek dia", ctx_hash, timestamp)
        h2 = compute_question_hash("mek  dia", ctx_hash, timestamp)
        h3 = compute_question_hash("mek\tdia", ctx_hash, timestamp)

        self.assertEqual(h1, h2, "Whitespace should be normalized")
        self.assertEqual(h1, h3, "Tab should normalize to space")

    def test_unicode_normalization(self):
        """Unicode variants normalize via NFKC."""
        ctx_hash = "abc123"
        timestamp = 1000.0

        h1 = compute_question_hash("café", ctx_hash, timestamp)
        h2 = compute_question_hash("café", ctx_hash, timestamp)

        self.assertEqual(h1, h2, "Unicode should be NFKC normalized")

    def test_integer_timestamp(self):
        """Float and int timestamps produce same hash."""
        h1 = compute_question_hash("mek dia", "abc123", 1000.0)
        h2 = compute_question_hash("mek dia", "abc123", 1000)

        self.assertEqual(h1, h2, "Float and int timestamps should match")


class TestActionHashProposalOnly(unittest.TestCase):
    """action_hash must be proposal-only, not outcome-dependent."""

    def test_action_hash_ignores_status(self):
        """Same action with different status produces same action_hash."""
        from noe.noe_parser import compute_action_hash

        action1 = {"type": "action", "verb": "mek", "target": "dia", "status": "pending"}
        action2 = {"type": "action", "verb": "mek", "target": "dia", "status": "completed"}

        self.assertEqual(compute_action_hash(action1), compute_action_hash(action2))

    def test_action_hash_ignores_verified(self):
        """action_hash ignores audit result."""
        from noe.noe_parser import compute_action_hash

        action1 = {"type": "action", "verb": "mek", "target": "dia", "verified": True}
        action2 = {"type": "action", "verb": "mek", "target": "dia", "verified": False}

        self.assertEqual(compute_action_hash(action1), compute_action_hash(action2))


if __name__ == '__main__':
    unittest.main()
