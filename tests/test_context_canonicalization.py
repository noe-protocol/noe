#!/usr/bin/env python3
"""
test_context_canonicalization.py

Canonicalization invariant proof:
  Semantically identical contexts produce byte-identical canonical hashes
  regardless of JSON key order, whitespace, or insertion order.

This test directly attacks the failure mode skeptics worry about:
  "JSON is ambiguous" / "hashes depend on serialization" / "agents could disagree silently"

Uses the actual noe.canonical module — no wrappers, no helpers that hide behavior.
"""

import hashlib
import json
import random
import copy
import unittest

from noe.canonical import canonical_json


def shuffle_dict(d):
    """
    Return a new dict with identical key-value pairs
    but randomized insertion order (recursively).
    """
    items = list(d.items())
    random.shuffle(items)
    out = {}
    for k, v in items:
        if isinstance(v, dict):
            out[k] = shuffle_dict(v)
        elif isinstance(v, list):
            out[k] = [shuffle_dict(x) if isinstance(x, dict) else x for x in v]
        else:
            out[k] = v
    return out


def canon_hash(obj):
    """SHA-256 of canonical JSON bytes. No shortcuts."""
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


class TestContextCanonicalization(unittest.TestCase):
    """Prove canonicalization is order-invariant."""

    # A realistic C_safe-shaped context with nested structure
    BASE_CONTEXT = {
        "temporal": {
            "now_us": 1700000000000000,
            "max_staleness_us": 5000000,
        },
        "spatial": {
            "zone": "warehouse_a1",
            "position_um": [1500000, 2300000, 0],
            "clear": True,
        },
        "modal": {
            "knowledge": {
                "temperature_ok": True,
                "human_clear": True,
                "chain_of_custody_ok": True,
            },
            "belief": {
                "path_clear": True,
            },
        },
        "agent": {
            "id": "robot_7",
            "role": "forklift",
        },
        "root": {
            "units": {
                "temperature": "millicelsius",
                "time": "microseconds",
                "distance": "millimeters",
            },
            "safety": {
                "max_temp_millicelsius": 8000,
                "min_temp_millicelsius": 2000,
            },
        },
    }

    def test_key_order_invariance(self):
        """Shuffled key order MUST produce identical hash."""
        reference = canon_hash(self.BASE_CONTEXT)

        # Variant 1: top-level shuffle
        v1 = shuffle_dict(self.BASE_CONTEXT)
        self.assertEqual(canon_hash(v1), reference, "Top-level key shuffle broke canonicalization")

        # Variant 2: nested shuffle
        v2 = copy.deepcopy(self.BASE_CONTEXT)
        v2["modal"] = shuffle_dict(v2["modal"])
        v2["root"] = shuffle_dict(v2["root"])
        self.assertEqual(canon_hash(v2), reference, "Nested key shuffle broke canonicalization")

        # Variant 3: JSON round-trip (proves no hidden state)
        v3 = json.loads(json.dumps(self.BASE_CONTEXT, sort_keys=False))
        self.assertEqual(canon_hash(v3), reference, "JSON round-trip broke canonicalization")

    def test_stochastic_shuffle_50_rounds(self):
        """50 random shuffles MUST all produce identical hash."""
        random.seed(1337)  # reproducible in CI
        reference = canon_hash(self.BASE_CONTEXT)
        for i in range(50):
            shuffled = shuffle_dict(self.BASE_CONTEXT)
            self.assertEqual(
                canon_hash(shuffled), reference,
                f"Stochastic shuffle round {i} broke canonicalization"
            )

    def test_non_identical_contexts_differ(self):
        """Negative control: different contexts MUST produce different hashes."""
        h1 = canon_hash(self.BASE_CONTEXT)

        # Change a single value
        modified = copy.deepcopy(self.BASE_CONTEXT)
        modified["modal"]["knowledge"]["human_clear"] = False
        h2 = canon_hash(modified)
        self.assertNotEqual(h1, h2, "Different contexts produced identical hash (collision or bug)")

        # Change a nested numeric value
        modified2 = copy.deepcopy(self.BASE_CONTEXT)
        modified2["temporal"]["now_us"] = 1700000000000001
        h3 = canon_hash(modified2)
        self.assertNotEqual(h1, h3, "Single-microsecond change was not detected")

    def test_canonical_json_is_deterministic_string(self):
        """Same input always produces the exact same JSON string."""
        s1 = canonical_json(self.BASE_CONTEXT)
        s2 = canonical_json(shuffle_dict(self.BASE_CONTEXT))
        s3 = canonical_json(shuffle_dict(self.BASE_CONTEXT))
        self.assertEqual(s1, s2)
        self.assertEqual(s2, s3)

        # Verify it has no whitespace (compact form)
        self.assertNotIn(" ", s1, "Canonical JSON contains whitespace")
        self.assertNotIn("\n", s1, "Canonical JSON contains newlines")


if __name__ == "__main__":
    unittest.main()
