import unittest
from noe.noe_parser import run_noe_logic

def get_valid_strict_context():
    """Return a minimal context that passes strict NIP-009 validation."""
    return {
        "literals": {},
        "entities": {"me": {"type": "agent"}},
        "spatial": {
            "unit": "generic",
            "thresholds": {"near": 1.0, "far": 5.0, "contact": 0.1, "direction": 0.1},
            "orientation": {"target": 0.0, "tolerance": 5.0},
        },
        "regions": {"origin": [0, 0, 0]},
        "temporal": {"now": 1000.0, "max_skew_ms": 1000.0},
        "modal": {
            "knowledge": {},
            "belief": {},
            "certainty": {},
            "certainty_threshold": 0.8
        },
        "value_system": {
            "axioms": {
                "value_system": {
                    "accepted": [],
                    "rejected": []
                }
            }
        },
        "axioms": {
            "value_system": {
                "accepted": [],
                "rejected": []
            }
        },
        "rel": {},
        "demonstratives": {
            "dia": {"entity": "me"},
            "doq": {"entity": "you"},
            "proximal": {"entity": "me"},
            "distal": {"entity": "you"}
        },
        "delivery": {"status": {}},
        "audit": {"log": []},
        "timestamp": 1000.0,
        "_action_dag": {}
    }

class TestStrictActions(unittest.TestCase):
    def run_parser(self, chain, mode="strict"):
        ctx = get_valid_strict_context()
        return run_noe_logic(chain, ctx, mode=mode)

    def test_undefined_target_strict(self):
        """Strict mode: Undefined target -> ERR_UNDEFINED_TARGET"""
        # @missing is not in context
        res = self.run_parser("mek @missing", mode="strict")
        self.assertEqual(res.get("domain"), "error")
        # v1.0: Validator enforces literal existence via ERR_LITERAL_MISSING (Priority 4)
        # ERR_UNDEFINED_TARGET was strict runtime error, but validator catches it first now.
        self.assertEqual(res.get("code"), "ERR_LITERAL_MISSING")

    def test_undefined_target_lax(self):
        """Lax mode: Undefined target -> undefined (no error)"""
        # @missing is not in context
        res = self.run_parser("mek @missing", mode="lax")
        # Should return action object with undefined target, or just undefined?
        # Current behavior for missing literal is {"domain": "undefined"}
        # So action target becomes that dict.
        # The action itself should be valid, just pointing to undefined.
        # v1.0: Lax mode -> Runtime returns undefined if target not found (cannot act on nothing)
        # Old behavior (implicit creation) removed for safety.
        self.assertEqual(res.get("domain"), "undefined")


    def test_invalid_target_type(self):
        """Strict mode: Invalid target type (e.g. boolean) -> ERR_INVALID_ACTION"""
        # mek true -> nonsensical
        res = self.run_parser("mek true", mode="strict")
        self.assertEqual(res.get("domain"), "error")
        self.assertEqual(res.get("code"), "ERR_INVALID_ACTION")

        # mek 123 -> nonsensical
        res = self.run_parser("mek 123", mode="strict")
        self.assertEqual(res.get("domain"), "error")
        self.assertEqual(res.get("code"), "ERR_INVALID_ACTION")

    def test_valid_action(self):
        """Valid action should pass"""
        # mek @x (assuming @x is defined or we mock it)
        # Actually, let's use a defined entity or literal if possible,
        # or just rely on the fact that if we don't define it, it's undefined.
        # But we want to test VALID case.
        # Let's inject a literal into context manually if needed, 
        # but run_parser re-creates context.
        # We can use a self-reference or something?
        # Or just use 'me' (dia)? 'mek dia'?
        # 'dia' resolves to entity 'me'.
        res = self.run_parser("mek dia", mode="strict")
        self.assertEqual(res.get("domain"), "action")
        self.assertEqual(res.get("value", {}).get("verb"), "mek")

if __name__ == "__main__":
    unittest.main()
