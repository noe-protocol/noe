"""
Adversarial tests for final correctness fixes (Batch 5).
Tests nested merge, action hash invariance, question hash canonicalization.
"""
import unittest
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from noe.noe_parser import merge_layers_for_validation, compute_question_hash, run_noe_logic

class TestNestedMerge(unittest.TestCase):
    """CRITICAL FIX #1: Test deep merge preserves nested shard keys"""
    
    def test_spatial_thresholds_merge(self):
        """Root sets near=1, far=10; Domain overwrites far=20; Expect both preserved"""
        ctx = {
            "root": {
                "spatial": {
                    "thresholds": {"near": 1.0, "far": 10.0}
                }
            },
            "domain": {
                "spatial": {
                    "thresholds": {"far": 20.0}
                }
            },
            "local": {}
        }
        
        merged = merge_layers_for_validation(ctx)
        
        # CRITICAL: Both near and far must be present
        self.assertEqual(merged["spatial"]["thresholds"]["near"], 1.0,
                        "Deep merge lost root.spatial.thresholds.near")
        self.assertEqual(merged["spatial"]["thresholds"]["far"], 20.0,
                        "Deep merge didn't override with domain.spatial.thresholds.far")
    
    def test_modal_knowledge_merge(self):
        """Test modal.knowledge preserves both layers"""
        ctx = {
            "root": {
                "modal": {
                    "knowledge": {"@fact1": True}
                }
            },
            "local": {
                "modal": {
                    "knowledge": {"@fact2": True}
                }
            }
        }
        
        merged = merge_layers_for_validation(ctx)
        
        self.assertIn("@fact1", merged["modal"]["knowledge"])
        self.assertIn("@fact2", merged["modal"]["knowledge"])


class TestQuestionHashCanonical(unittest.TestCase):
    """CRITICAL FIX #4: Test question hash is whitespace/format invariant"""
    
    def test_whitespace_invariance(self):
        """Same chain with different whitespace should have same hash"""
        chain1 = "mek dia"
        chain2 = "mek  dia"  # Extra space
        chain3 = "mek\tdia"  # Tab
        
        ctx_hash = "abc123"
        timestamp = 1000.0
        
        hash1 = compute_question_hash(chain1, ctx_hash, timestamp)
        hash2 = compute_question_hash(chain2, ctx_hash, timestamp)
        hash3 = compute_question_hash(chain3, ctx_hash, timestamp)
        
        self.assertEqual(hash1, hash2, "Whitespace should be normalized")
        self.assertEqual(hash1, hash3, "Tab should normalize to space")
    
    def test_unicode_normalization(self):
        """Unicode variants should normalize"""
        # é can be represented as single char or e + combining accent
        chain1 = "café"  # Composed
        chain2 = "café"  # Decomposed (if editor allows)
        
        ctx_hash = "abc123"
        timestamp = 1000.0
        
        hash1 = compute_question_hash(chain1, ctx_hash, timestamp)
        hash2 = compute_question_hash(chain2, ctx_hash, timestamp)
        
        # NFKC should normalize both
        self.assertEqual(hash1, hash2, "Unicode should be NFKC normalized")
    
    def test_integer_timestamp(self):
        """Timestamp should be integer milliseconds, not float string"""
        chain = "mek dia"
        ctx_hash = "abc123"
        
        # Same timestamp as float and int
        hash1 = compute_question_hash(chain, ctx_hash, 1000.0)
        hash2 = compute_question_hash(chain, ctx_hash, 1000)
        
        self.assertEqual(hash1, hash2, "Float and int timestamps should match")


class TestActionHashProposalOnly(unittest.TestCase):
    """CRITICAL FIX #3: action_hash should be proposal-only, not outcome-dependent"""
    
    def test_action_hash_ignores_status(self):
        """Same action with different status should have same action_hash"""
        from noe.noe_parser import compute_action_hash
        
        action1 = {"type": "action", "verb": "mek", "target": "dia", "status": "pending"}
        action2 = {"type": "action", "verb": "mek", "target": "dia", "status": "completed"}
        
        hash1 = compute_action_hash(action1)
        hash2 = compute_action_hash(action2)
        
        self.assertEqual(hash1, hash2, "action_hash should ignore status field")
    
    def test_action_hash_ignores_verified(self):
        """action_hash should ignore audit result"""
        from noe.noe_parser import compute_action_hash
        
        action1 = {"type": "action", "verb": "mek", "target": "dia", "verified": True}
        action2 = {"type": "action", "verb": "mek", "target": "dia", "verified": False}
        
        hash1 = compute_action_hash(action1)
        hash2 = compute_action_hash(action2)
        
        self.assertEqual(hash1, hash2, "action_hash should ignore verified field")


if __name__ == '__main__':
    unittest.main()
