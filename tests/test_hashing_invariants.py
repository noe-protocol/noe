
import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

from noe.noe_parser import compute_action_hash

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
        with_outcome["_include_outcome_in_hash"] = True # simulate event hash computation
        
        h_event_1 = compute_action_hash(with_outcome)
        
        # With Outcome (audit_status)
        with_audit = base.copy()
        with_audit["audit_status"] = "flagged" 
        with_audit["_include_outcome_in_hash"] = True
        
        h_event_2 = compute_action_hash(with_audit)
        
        # Invariants:
        # 1. Action hash (computed without flag) should hide outcomes
        # Manual check: normalize base vs with_audit WITHOUT flag
        
        from noe.noe_parser import _normalize_action
        
        # Verify normalization without flag drops outcomes
        norm_base = _normalize_action(base)
        norm_audit_no_flag = _normalize_action(with_audit.copy()) # copy because _normalize modifies? no it returns new
        # Wait, _normalize_action takes a dict.
        
        # We need to ensure that compute_action_hash (which sets the flag internally for event hash?)
        # compute_action_hash computes ACTION hash by default.
        # It computes EVENT hash if we pass that context or if we manually invoke normalization?
        
        # Let's test _normalize_action directly as it's the source of truth
        
        # 1. Action Hash Integrity (Outcomes Ignored)
        obj1 = {"verb": "mek", "target": "foo", "status": "completed", "audit_status": "ok"}
        obj2 = {"verb": "mek", "target": "foo", "status": "failed", "audit_status": "flagged"}
        
        norm1 = _normalize_action(obj1)
        norm2 = _normalize_action(obj2)
        
        self.assertEqual(norm1, norm2, "Action normalization must ignore outcomes")
        self.assertNotIn("status", norm1)
        self.assertNotIn("audit_status", norm1)
        
        # 2. Event Hash Integrity (Outcomes Included)
        obj1_evt = obj1.copy()
        obj1_evt["_include_outcome_in_hash"] = True
        
        obj2_evt = obj2.copy()
        obj2_evt["_include_outcome_in_hash"] = True
        
        norm1_evt = _normalize_action(obj1_evt)
        norm2_evt = _normalize_action(obj2_evt)
        
        self.assertNotEqual(norm1_evt, norm2_evt, "Event normalization must include outcomes")
        self.assertIn("status", norm1_evt)
        self.assertIn("audit_status", norm1_evt)
        
        print("\nHashing Invariants Verified:")
        print(f"Action Norm: {norm1}")
        print(f"Event Norm 1: {norm1_evt}")
        print(f"Event Norm 2: {norm2_evt}")

if __name__ == "__main__":
    unittest.main()
