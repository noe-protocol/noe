#!/usr/bin/env python3
"""
test_certificate_replay.py

Certificate replay invariant proof:
  Given a frozen chain + context, re-evaluation produces a byte-identical
  verdict and canonical certificate surface (context hash + action hashes).

This is the central replayability claim of Noe as a safety kernel.
Scoped to local (single-process) replay determinism; cross-architecture
and cross-language replay are deferred to CI and future test layers.

Note: the runtime does not currently expose a chain_hash in metadata.
Chain text is treated as canonical input; chain hashing is deferred to
the certificate layer (see test_chain_canonicalization.py).
"""

import copy
import hashlib
import unicodedata
import unittest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from noe.noe_parser import run_noe_logic
from noe.canonical import canonical_json


def canonicalize_chain_text(chain):
    """Same canonicalization as run_noe_logic entry."""
    c = unicodedata.normalize('NFKC', chain)
    return ' '.join(c.split())


# Frozen context — represents a captured C_safe snapshot
FROZEN_CONTEXT = {
    "literals": {
        "@temperature_ok": True,
        "@human_clear": True,
        "@release_pallet": True,
    },
    "entities": {},
    "spatial": {"zone": "warehouse_a1", "positions": {"forklift": [1500, 2300, 0]}},
    "temporal": {"now_us": 1700000000000000, "max_staleness_us": 5000000},
    "modal": {
        "knowledge": {
            "temperature_ok": True,
            "human_clear": True,
        },
        "belief": {},
    },
    "axioms": {},
}

# Frozen chain — the policy that was evaluated
FROZEN_CHAIN = "shi @temperature_ok an shi @human_clear khi sek mek @release_pallet sek nek"


def _generate_certificate(chain, context):
    """
    Run evaluation and produce a certificate with an explicit
    cryptographic surface hash — not a string concatenation.
    """
    result = run_noe_logic(chain, copy.deepcopy(context), mode="strict")

    # Capture action hashes if verdict is a list of actions
    action_hashes = []
    if result["domain"] == "list" and isinstance(result.get("value"), list):
        action_hashes = [
            a.get("action_hash") for a in result["value"]
            if isinstance(a, dict) and "action_hash" in a
        ]

    # Certificate surface: the canonical object an auditor would verify
    surface = {
        "chain_canonical": canonicalize_chain_text(chain),
        "context_hash": result["meta"]["context_hash"],
        "verdict_domain": result["domain"],
        "action_hashes": action_hashes,
    }

    cert = {
        "chain": chain,
        "context": copy.deepcopy(context),
        "verdict_domain": result["domain"],
        "context_hash": result["meta"]["context_hash"],
        "context_hashes": result["meta"].get("context_hashes", {}),
        "action_hashes": action_hashes,
        "certificate_hash": hashlib.sha256(
            canonical_json(surface).encode("utf-8")
        ).hexdigest(),
    }
    return cert


class TestCertificateReplay(unittest.TestCase):
    """Prove local certificate replay produces identical results."""

    def test_replay_produces_identical_certificate_hash(self):
        """Replaying must produce an identical certificate surface hash."""
        cert = _generate_certificate(FROZEN_CHAIN, FROZEN_CONTEXT)
        replay_cert = _generate_certificate(cert["chain"], cert["context"])

        self.assertEqual(
            replay_cert["certificate_hash"], cert["certificate_hash"],
            "Replay certificate hash mismatch"
        )

    def test_replay_produces_identical_verdict(self):
        """Replaying a frozen chain+context must produce the same verdict."""
        cert = _generate_certificate(FROZEN_CHAIN, FROZEN_CONTEXT)
        replay_cert = _generate_certificate(cert["chain"], cert["context"])

        self.assertEqual(
            replay_cert["verdict_domain"], cert["verdict_domain"],
            f"Replay verdict mismatch: {replay_cert['verdict_domain']} != {cert['verdict_domain']}"
        )

    def test_replay_produces_identical_context_hash(self):
        """Replaying must produce the same context hash."""
        cert = _generate_certificate(FROZEN_CHAIN, FROZEN_CONTEXT)
        replay_cert = _generate_certificate(cert["chain"], cert["context"])

        self.assertEqual(
            replay_cert["context_hash"], cert["context_hash"],
            "Replay context hash mismatch"
        )

    def test_replay_produces_identical_action_hashes(self):
        """Replaying must produce the same action hashes."""
        cert = _generate_certificate(FROZEN_CHAIN, FROZEN_CONTEXT)
        replay_cert = _generate_certificate(cert["chain"], cert["context"])

        self.assertEqual(
            replay_cert["action_hashes"], cert["action_hashes"],
            "Replay action hashes mismatch"
        )

    def test_replay_10_rounds_identical(self):
        """10 consecutive replays must all produce identical certificate hashes."""
        cert = _generate_certificate(FROZEN_CHAIN, FROZEN_CONTEXT)

        for i in range(10):
            replay_cert = _generate_certificate(cert["chain"], cert["context"])
            self.assertEqual(
                replay_cert["certificate_hash"], cert["certificate_hash"],
                f"Round {i}: certificate hash mismatch"
            )

    def test_modified_context_breaks_replay(self):
        """Negative control: changing context MUST produce different certificate hash."""
        cert = _generate_certificate(FROZEN_CHAIN, FROZEN_CONTEXT)

        # Tamper: change a single knowledge value
        tampered = copy.deepcopy(FROZEN_CONTEXT)
        tampered["modal"]["knowledge"]["human_clear"] = False

        tampered_cert = _generate_certificate(FROZEN_CHAIN, tampered)

        self.assertNotEqual(
            tampered_cert["certificate_hash"], cert["certificate_hash"],
            "Tampered context produced same certificate hash"
        )
        self.assertNotEqual(
            tampered_cert["context_hash"], cert["context_hash"],
            "Tampered context produced same context hash"
        )


if __name__ == "__main__":
    unittest.main()
