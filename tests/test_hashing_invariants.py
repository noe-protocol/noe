
import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

from noe.provenance import compute_action_hash

class TestHashingInvariants(unittest.TestCase):
    
    def test_outcome_sensitivity(self):
        """
        Action hash should be stable (ignoring outcomes).
        Event hash should be sensitive to outcomes (status, verified, audit_status).
        """
        
        # Base proposal
        base = {
            "type": "action",
            "verb": "mek", 
            "target": "foo"
        }
        
        h_base = compute_action_hash(base)
        
        # With Outcome (status)
        with_outcome = base.copy()
        with_outcome["status"] = "failed"
        
        h_with_outcome = compute_action_hash(with_outcome)
        
        # Invariants:
        # 1. Action hash (computed without flag) should hide outcomes
        self.assertEqual(h_base, h_with_outcome, "Action hash must ignore outcomes (status)")

        # With Outcome (audit_status)
        with_audit = base.copy()
        with_audit["audit_status"] = "flagged" 
        
        h_with_audit = compute_action_hash(with_audit)
        self.assertEqual(h_base, h_with_audit, "Action hash must ignore outcomes (audit_status)")

        
        # 2. Event Hash Integrity (Outcomes Included)
        # Use special flag to simulate event hashing via the same function
        obj1 = {"verb": "mek", "target": "foo", "status": "completed", "audit_status": "ok"}
        obj2 = {"verb": "mek", "target": "foo", "status": "failed", "audit_status": "flagged"}
        
        obj1_evt = obj1.copy()
        obj1_evt["_include_outcome_in_hash"] = True
        
        obj2_evt = obj2.copy()
        obj2_evt["_include_outcome_in_hash"] = True
        
        h_evt1 = compute_action_hash(obj1_evt)
        h_evt2 = compute_action_hash(obj2_evt)
        
        self.assertNotEqual(h_evt1, h_evt2, "Event hash (with flag) must include outcomes")
        
        # Also check normal action hash is same
        h_act1 = compute_action_hash(obj1)
        h_act2 = compute_action_hash(obj2)
        self.assertEqual(h_act1, h_act2, "Normal action hash must remain stable")

if __name__ == "__main__":
    unittest.main()
