import pytest
import unittest
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from noe.noe_parser import run_noe_logic

def get_valid_context():
    return {
        "root": {"version": "1.0"},
        "domain": {},
        "local": {
            "literals": {"@x": True},
            "entities": {"me": {"type": "agent"}},
            "spatial": {"unit": "generic", "thresholds": {"near": 1.0}},
            "temporal": {"now": 1000.0, "max_skew_ms": 1000.0},
            "modal": {"knowledge": {}, "belief": {}, "certainty": {}},
            "value_system": {"axioms": {"value_system": {"accepted": [], "rejected": []}}},
            "axioms": {"value_system": {"accepted": [], "rejected": []}},
            "rel": {},
            "demonstratives": {"dia": {"entity": "me"}},
            "delivery": {"status": {}},
            "audit": {"log": []}
        }
    }

class TestRuntimeBlockers(unittest.TestCase):
    """Tests for BLOCKER FIXES #1-7"""
    
    def test_inversion_terminal(self):
        """BLOCKER #1: visit_inversion should handle terminal nodes (no IndexError)"""
        ctx = get_valid_context()
        # fel·nei should parse without crash
        res = run_noe_logic("fel·nei", ctx, mode="strict")
        # Should return inverted result (not crash)
        self.assertNotEqual(res.get("code"), "ERR_PARSE_FAILED")
    
    def test_morph_suffix_terminal(self):
        """BLOCKER #2: visit_morph_suffix should handle terminal nodes (no IndexError)"""
        ctx = get_valid_context()
        # fel tok should parse without crash
        res = run_noe_logic("fel tok", ctx, mode="strict")
        # Should return modified glyph (not crash)
        self.assertNotEqual(res.get("code"), "ERR_PARSE_FAILED")
    
    def test_morphology_on_literal(self):
        """v1.0: Validation order enforces ERR_INVALID_LITERAL before ERR_MORPHOLOGY"""
        ctx = get_valid_context()
        # @x·nei is caught as invalid literal before morphology check
        res = run_noe_logic("@x·nei", ctx, mode="strict")
        # v1.0 canonical: validator rejects malformed literal first
        self.assertEqual(res.get("code"), "ERR_INVALID_LITERAL",
                        "v1.0 validation order: invalid literal caught before morphology check")
    
    def test_morphology_on_number(self):
        """BLOCKER #4: Morphology on numbers should error in strict mode"""
        ctx = get_valid_context()
        # 3 tok is invalid (morphology on number)
        res = run_noe_logic("3 tok", ctx, mode="strict")
        # Grammar likely won't allow this, but if it does, should error
        # Skip if parse fails at grammar level
        if res.get("code") != "ERR_PARSE_FAILED":
            self.assertEqual(res.get("code"), "ERR_MORPHOLOGY")
    
    def test_demonstrative_single_path(self):
        """v1.0: Demonstratives return undefined when context lacks complete binding"""
        ctx = get_valid_context()
        # dia returns undefined in strict mode without complete deixis binding
        res = run_noe_logic("dia", ctx, mode="strict")
        # v1.0 canonical: strict mode returns error for incomplete demonstrative resolution
        self.assertIn(res.get("domain"), ["error", "undefined"], 
                     "Strict mode should block incomplete demonstrative binding")
    
    def test_context_isolation(self):
        """BLOCKER #7: Evaluation should not mutate caller's context"""
        ctx = get_valid_context()
        original_keys = set(ctx.keys())
        
        # Run action that creates DAG
        run_noe_logic("mek dia", ctx, mode="strict")
        
        # Context should not gain _action_dag at top level
        self.assertEqual(set(ctx.keys()), original_keys, 
                        "Caller context was mutated with internal keys")

if __name__ == '__main__':
    unittest.main()
