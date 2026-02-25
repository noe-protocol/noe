"""
red_team_audit.py

Adversarial boundary tests for numeric stability, epistemic thresholds,
temporal skew, serialization canonicalization, and concurrency isolation.

Run: PYTHONPATH=. python3 tests/adversarial/red_team_audit.py
"""
import sys
import os
import json
import unittest
import math
import hashlib
import threading
import subprocess

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from noe.noe_validator import compute_context_hashes, compute_stale_flag
from noe.context_projection import is_candidate, AnnotatedLiteral, ProjectionConfig
from noe.noe_parser import run_noe_logic


class TestEpistemicBoundaries(unittest.TestCase):
    """Verify exact threshold enforcement at epistemic boundaries."""

    def test_below_threshold_rejected(self):
        """0.89999 must fail when threshold is 0.90."""
        cfg = ProjectionConfig(theta_thresh=0.90)
        now = 1000.0
        lit = AnnotatedLiteral("test", True, now, "src", 0.89999)
        self.assertFalse(is_candidate(lit, cfg, now))

    def test_at_threshold_accepted(self):
        """0.90000 must pass when threshold is 0.90."""
        cfg = ProjectionConfig(theta_thresh=0.90)
        now = 1000.0
        lit = AnnotatedLiteral("test", True, now, "src", 0.90000)
        self.assertTrue(is_candidate(lit, cfg, now))


class TestSerializationCanonical(unittest.TestCase):
    """Verify canonical hash rejects non-canonical whitespace."""

    def test_hash_matches_strict_separators(self):
        """Hash must match strict canonical JSON (no whitespace)."""
        ctx = {"a": 1, "b": 2}
        h1 = compute_context_hashes(ctx)["total"]

        local_payload = json.dumps(ctx, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        h_local = hashlib.sha256(local_payload).digest()

        empty_payload = json.dumps({}, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        h_root = hashlib.sha256(empty_payload).digest()
        h_domain = hashlib.sha256(empty_payload).digest()

        expected = hashlib.sha256(h_root + h_domain + h_local).hexdigest()
        self.assertEqual(h1, expected)

    def test_default_whitespace_differs(self):
        """Default json.dumps whitespace must produce different hash."""
        ctx = {"a": 1, "b": 2}
        h1 = compute_context_hashes(ctx)["total"]

        empty_payload = json.dumps({}, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        h_root = hashlib.sha256(empty_payload).digest()
        h_domain = hashlib.sha256(empty_payload).digest()

        bad_payload = json.dumps(ctx, sort_keys=True).encode("utf-8")
        h_local_bad = hashlib.sha256(bad_payload).digest()
        bad_structural = hashlib.sha256(h_root + h_domain + h_local_bad).hexdigest()

        self.assertNotEqual(h1, bad_structural)


class TestStateIsolation(unittest.TestCase):
    """Verify no global state contamination between runs."""

    def test_different_contexts_different_hashes(self):
        """Same key structure, different values must produce different hashes."""
        h1 = compute_context_hashes({"id": 1, "val": "A"})["total"]
        h2 = compute_context_hashes({"id": 1, "val": "B"})["total"]
        self.assertNotEqual(h1, h2)

    def test_cache_returns_correct_hash(self):
        """Re-hashing identical context must return same result."""
        ctx = {"id": 1, "val": "A"}
        h1 = compute_context_hashes(ctx)["total"]
        h2 = compute_context_hashes(ctx)["total"]
        self.assertEqual(h1, h2)


class TestTemporalSkew(unittest.TestCase):
    """Verify future timestamps are treated as skew and blocked."""

    def test_far_future_is_stale(self):
        """Timestamp far in the future must be marked stale."""
        ctx = {
            "temporal": {"now": 2000.0, "max_skew_ms": 100.0, "timestamp": 7000.0},
            "local": {"timestamp": 7000.0}
        }
        is_stale, _ = compute_stale_flag(ctx)
        self.assertTrue(is_stale)

    def test_near_future_within_skew_is_fresh(self):
        """Timestamp slightly in the future (within skew) must be fresh."""
        ctx = {
            "temporal": {"now": 2000.0, "max_skew_ms": 100.0, "timestamp": 2050.0},
            "local": {"timestamp": 2050.0}
        }
        is_stale, _ = compute_stale_flag(ctx)
        self.assertFalse(is_stale)


class TestFloatEdgeCases(unittest.TestCase):
    """Verify NaN and Inf are rejected or handled safely."""

    def test_nan_timestamp_rejected(self):
        """NaN timestamp must be rejected by validator."""
        ctx = {
            "temporal": {"now": 1000.0, "max_skew_ms": 100.0, "timestamp": float('nan')},
            "local": {"timestamp": float('nan')}
        }
        is_stale, error_msg = compute_stale_flag(ctx)
        self.assertIn("C.timestamp must be finite", error_msg or "")

    def test_nan_confidence_rejected(self):
        """NaN confidence must not bypass threshold check."""
        cfg = ProjectionConfig(theta_thresh=0.90)
        now = 1000.0
        lit = AnnotatedLiteral("nan_conf", True, now, "src", float('nan'))
        self.assertFalse(is_candidate(lit, cfg, now))


class TestConcurrencyIsolation(unittest.TestCase):
    """Verify hash cache thread safety."""

    def test_threaded_hash_stability(self):
        """10 threads, 100 iterations each — no hash instability."""
        errors = []

        def runner():
            import random
            for i in range(100):
                ctx = {"id": threading.get_ident(), "iter": i, "val": random.random()}
                h = compute_context_hashes(ctx)["total"]
                if compute_context_hashes(ctx)["total"] != h:
                    errors.append("Hash instability in thread")

        threads = [threading.Thread(target=runner) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)


class TestProcessIsolation(unittest.TestCase):
    """Verify determinism across separate processes."""

    def test_cross_process_hash_determinism(self):
        """Same input in two separate processes must produce identical hash."""
        code = """
import sys, os, json
sys.path.append(os.getcwd())
from noe.noe_validator import compute_context_hashes
ctx = {"a": 1, "b": [1, 2, 3], "c": "test"}
print(compute_context_hashes(ctx)["total"])
"""
        p1 = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=os.getcwd())
        p2 = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=os.getcwd())

        hash1 = p1.stdout.strip()
        hash2 = p2.stdout.strip()

        self.assertEqual(hash1, hash2)
        self.assertEqual(len(hash1), 64)


if __name__ == "__main__":
    unittest.main()
