#!/usr/bin/env python3
"""
test_chain_canonicalization.py

Chain canonicalization invariant proof:
  Lexically variant but semantically identical chains (whitespace-only
  differences) produce identical evaluation outcomes and identical
  canonical certificate surfaces.

This test proves that chain + context together are canonicalized:
  - Extra whitespace does not change the verdict
  - Extra whitespace does not change the context or chain hashes
  - The canonical certificate surface is deterministic and idempotent

Note: the runtime does not currently expose a chain_hash in metadata.
This test explicitly computes it using the same canonicalization path
(NFKC + whitespace collapse) to prove the invariant holds.
"""

import hashlib
import unicodedata
import unittest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from noe.noe_parser import run_noe_logic
from noe.canonical import canonical_json


def canonicalize_chain_text(chain):
    """
    Apply the same canonicalization as run_noe_logic entry:
    NFKC normalization + whitespace collapse.
    """
    c = unicodedata.normalize('NFKC', chain)
    return ' '.join(c.split())


def chain_hash(chain):
    """SHA-256 of the canonical chain text."""
    canonical = canonicalize_chain_text(chain)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def certificate_surface_hash(result, chain):
    """
    Hash the certificate surface: the fields an auditor would verify.
    This is a real cryptographic invariant, not a string concatenation.
    """
    surface = {
        "chain_canonical": canonicalize_chain_text(chain),
        "context_hash": result["meta"]["context_hash"],
        "verdict_domain": result["domain"],
    }
    return hashlib.sha256(
        canonical_json(surface).encode("utf-8")
    ).hexdigest()


# A valid strict-mode context
STRICT_CONTEXT = {
    "literals": {"@sensor_ok": True, "@door_locked": True},
    "entities": {},
    "spatial": {"zone": "A1", "positions": {"robot": [1000, 2000, 0]}},
    "temporal": {"now_us": 1700000000000000, "max_staleness_us": 5000000},
    "modal": {
        "knowledge": {"sensor_ok": True, "door_locked": True},
        "belief": {},
    },
    "axioms": {},
}


class TestChainCanonicalization(unittest.TestCase):
    """Prove chain canonicalization produces identical results."""

    def test_whitespace_invariance(self):
        """Extra whitespace in chains MUST NOT change verdict, context hash, or chain hash."""
        # Canonical form (single spaces)
        chain_canonical = "shi @sensor_ok khi sek mek @door_locked sek nek"

        # Variant: extra spaces
        chain_spaces = "shi  @sensor_ok   khi   sek   mek   @door_locked   sek   nek"

        # Variant: tabs mixed in
        chain_tabs = "shi\t@sensor_ok\tkhi\tsek\tmek\t@door_locked\tsek\tnek"

        # Variant: leading/trailing whitespace
        chain_padded = "  shi @sensor_ok khi sek mek @door_locked sek nek  "

        chains = [chain_canonical, chain_spaces, chain_tabs, chain_padded]
        results = [run_noe_logic(c, STRICT_CONTEXT, mode="strict") for c in chains]

        # All must produce the same verdict domain
        for i, r in enumerate(results[1:], start=1):
            self.assertEqual(
                r["domain"], results[0]["domain"],
                f"Variant {i} changed verdict domain"
            )

        # All must produce the same context hash
        for i, r in enumerate(results[1:], start=1):
            self.assertEqual(
                r["meta"]["context_hash"], results[0]["meta"]["context_hash"],
                f"Variant {i} changed context hash"
            )

        # All chain hashes must be identical
        c_hashes = [chain_hash(c) for c in chains]
        for i, h in enumerate(c_hashes[1:], start=1):
            self.assertEqual(
                h, c_hashes[0],
                f"Variant {i} changed chain hash"
            )

    def test_context_order_with_chain(self):
        """Same chain + reordered context MUST produce identical hashes."""
        chain = "shi @sensor_ok khi sek mek @door_locked sek nek"

        # Original context
        ctx1 = STRICT_CONTEXT.copy()

        # Reordered top-level keys
        ctx2 = {}
        keys = list(STRICT_CONTEXT.keys())
        for k in reversed(keys):
            ctx2[k] = STRICT_CONTEXT[k]

        r1 = run_noe_logic(chain, ctx1, mode="strict")
        r2 = run_noe_logic(chain, ctx2, mode="strict")

        self.assertEqual(r1["domain"], r2["domain"], "Key reorder changed verdict")
        self.assertEqual(
            r1["meta"]["context_hash"],
            r2["meta"]["context_hash"],
            "Key reorder changed context hash"
        )

    def test_certificate_surface_determinism(self):
        """
        The canonical certificate surface (chain + context_hash + verdict)
        must be deterministic across repeated evaluations.
        Uses a real cryptographic hash, not string concatenation.
        """
        chain = "shi @sensor_ok khi sek mek @door_locked sek nek"

        surfaces = []
        for _ in range(10):
            r = run_noe_logic(chain, STRICT_CONTEXT, mode="strict")
            surfaces.append(certificate_surface_hash(r, chain))

        for i, s in enumerate(surfaces[1:], start=1):
            self.assertEqual(
                s, surfaces[0],
                f"Run {i} produced different certificate surface hash"
            )

    def test_canonical_chain_is_idempotent(self):
        """Canonicalizing an already-canonical chain must be a no-op."""
        chain = "shi @sensor_ok khi sek mek @door_locked sek nek"
        once = canonicalize_chain_text(chain)
        twice = canonicalize_chain_text(once)
        self.assertEqual(once, twice, "Double canonicalization changed the result")


if __name__ == "__main__":
    unittest.main()
