import unittest
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from noe.noe_runtime import NoeRuntime
from noe.context_manager import ContextManager
from noe.noe_validator import DEFAULT_CONTEXT_PARTIAL
from noe.provenance import compute_decision_hash

class TestV1Regression(unittest.TestCase):
    def setUp(self):
        self.cm = ContextManager()
        # Mock a valid context to ensure validation passes (for truth/success tests)
        self.rt = NoeRuntime(context_manager=self.cm, strict_mode=False, debug=True)

    def test_canonicalization_stability(self):
        """Verify whitespace variants produce identical canonical chains and hashes."""
        # Using a simple chain "true"
        chains = ["  true  ", "true", "\ttrue\n"]
        
        # Run first one as reference
        rr_ref, prov_ref = self.rt.evaluate_with_provenance(chains[0])
        self.assertEqual(rr_ref.canonical_chain, "true")
        self.assertEqual(prov_ref.chain, "true")
        
        for c in chains[1:]:
            rr, prov = self.rt.evaluate_with_provenance(c)
            # Chain identity
            self.assertEqual(rr.canonical_chain, rr_ref.canonical_chain)
            self.assertEqual(prov.chain, prov_ref.chain)
            # Hash identity
            self.assertEqual(prov.provenance_hash, prov_ref.provenance_hash)
            # Decision hash identity
            self.assertEqual(prov.decision_hash, prov_ref.decision_hash)
            # Action hash absence
            self.assertIsNone(prov.action_hash)

    def test_decision_vs_action_separation(self):
        """Verify non-action domains populate decision_hash, not action_hash."""
        rr, prov = self.rt.evaluate_with_provenance("true")
        
        self.assertEqual(rr.domain, "truth", f"Expected 'truth', got '{rr.domain}'. Error: {rr.error}, Value: {rr.value}")
        # MUST have decision_hash
        self.assertIsNotNone(prov.decision_hash, "Truth result must have decision_hash")
        # MUST NOT have action_hash
        self.assertIsNone(prov.action_hash, "Truth result must NOT have action_hash")
        
        # Verify decision_hash correctness manually
        expected_hash = compute_decision_hash(
            chain_str="true", 
            h_total=prov.context_hash,
            domain_pack_hash=prov.domain_pack_hash
        )
        self.assertEqual(prov.decision_hash, expected_hash, "Decision hash mismatch")

    def test_failure_modes_hygiene(self):
        """Verify error/blocked paths contain canonical chain but NO execution hashes."""
        # 1. Parse Error
        bad_chain = "((("
        rr, prov = self.rt.evaluate_with_provenance(bad_chain)
        
        self.assertEqual(rr.domain, "error")
        # Canonical chain is set even on parse error
        self.assertEqual(rr.canonical_chain, bad_chain) 
        
        # Provenance hygiene
        self.assertIsNone(prov.provenance_hash, "Error result must have null provenance_hash")
        self.assertIsNone(prov.action_hash, "Error result must have null action_hash")
        self.assertIsNone(prov.decision_hash, "Error result must have null decision_hash")

if __name__ == '__main__':
    unittest.main()
