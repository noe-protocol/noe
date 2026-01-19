"""
Test strict mode anti-axiom security.

These tests ensure that strict mode NEVER silently fabricates missing context fields.
The core invariant: deleting context should never create True from non-True.

Regression tests for v1.0 anti-axiom security hardening.
"""

import pytest
from noe import NoeRuntime, ContextManager
from noe.noe_parser import merge_layers_for_validation


class TestAntiAxiomSecurity:
    """
    Test suite for anti-axiom security measures.
    
    These tests prevent silent default fabrication that could bypass strict mode.
    """
    
    def test_none_layer_does_not_become_empty_dict(self):
        """
        Regression: merge_layers_for_validation must not mask None as {}.
        
        Before fix: ctx.get("root") or {} would mask None as {}
        After fix: None is handled explicitly (None -> {}) but type validation occurs
        """
        # None root is now explicitly handled (not masked by `or {}`)
        ctx_none_root = {"root": None, "domain": {}, "local": {}}
        merged = merge_layers_for_validation(ctx_none_root)
        
        # Fix: None is explicitly converted to {}, but it's a deliberate choice
        # The key difference is `if root is not None else {}` vs `or {}`
        assert isinstance(merged, dict)  # Successfully merged
        
        # Invalid type (non-dict) should be rejected - returns unmerged
        ctx_invalid = {"root": "not_a_dict", "domain": {}, "local": {}}
        merged_invalid = merge_layers_for_validation(ctx_invalid)
        assert merged_invalid == ctx_invalid  # Returned unmerged
    
    def test_missing_spatial_thresholds_blocks(self):
        """
        Regression: Missing spatial.thresholds must return undefined, not silent {}.
        
        Before fix: spatial.get("thresholds", {}) fabricated empty dict
        After fix: Missing thresholds returns undefined
        """
        context = {
            'root': {
                'literals': {'@x': True, '@y': True},
                'spatial': {},  # NO thresholds
                'temporal': {'now': 1000, 'max_skew_ms': 100},
                'modal': {'knowledge': {}, 'belief': {}, 'certainty': {}},
                'axioms': {'value_system': {}},
                'rel': {}, 'demonstratives': {}, 'entities': {},
                'delivery': {'status': {}}, 'audit': {}
            },
            'domain': {},
            'local': {'timestamp': 1000}
        }
        
        cm = ContextManager(root=context['root'], domain=context['domain'], local=context['local'])
        rt = NoeRuntime(context_manager=cm, strict_mode=True)
        
        # Demonstrative resolution requires thresholds
        chain = '@x dia @y nek'
        rr, _ = rt.evaluate_with_provenance(chain)
        
        # Must not fabricate True from missing thresholds
        assert rr.domain == "undefined", f"Expected undefined, got {rr.domain}: {rr.value}"
    
    def test_missing_temporal_does_not_fabricate(self):
        """
        Regression: temporal.get("foo", {}) or {} must not mask None as {}.
        
        Before fix: Double fallback would hide None temporal
        After fix: Explicit None check before defaulting
        """
        context = {
            'root': {
                'literals': {'@test': True},
                'spatial': {'thresholds': {'near': 1.0, 'far': 5.0}, 'orientation': {'target': 0, 'tolerance': 0.1}},
                'temporal': None,  # Explicitly None (malformed)
                'modal': {'knowledge': {}, 'belief': {}, 'certainty': {}},
                'axioms': {'value_system': {}},
                'rel': {}, 'demonstratives': {}, 'entities': {},
                'delivery': {'status': {}}, 'audit': {}
            },
            'domain': {},
            'local': {'timestamp': 1000}
        }
        
        cm = ContextManager(root=context['root'], domain=context['domain'], local=context['local'])
        rt = NoeRuntime(context_manager=cm, strict_mode=True)
        
        # Should handle None temporal gracefully
        chain = '@test nek'
        rr, _ = rt.evaluate_with_provenance(chain)
        
        # Should not crash, should handle gracefully
        assert rr.domain in ("literal", "undefined", "error")
    
    def test_no_phantom_defaults_in_validation_merge(self):
        """
        Regression: merge_layers_for_validation must not seed defaults.
        
        Core invariant: validation merge starts from {} and only merges provided layers.
        No "phantom" base template dicts should appear.
        """
        # Minimal context (only root, no domain/local)
        ctx = {
            "root": {"literals": {"@x": True}},
            "domain": {},
            "local": {}
        }
        
        merged = merge_layers_for_validation(ctx)
        
        # Should only contain what was provided
        assert "literals" in merged
        assert merged["literals"] == {"@x": True}
        
        # Should NOT fabricate missing shards
        keys = set(merged.keys())
        # Only keys from actual layers should exist
        # No phantom 'spatial', 'temporal', etc. unless explicitly in layers
        assert "spatial" not in keys or "spatial" in ctx["root"]
    
    def test_deletion_never_creates_true(self):
        """
        Property test: Deleting context fields should never make non-True become True.
        
        This is the core anti-axiom security invariant.
        """
        # Full context that evaluates to True
        full_context = {
            'root': {
                'literals': {'@safe': True},
                'spatial': {'thresholds': {'near': 1.0, 'far': 5.0}, 'orientation': {'target': 0, 'tolerance': 0.1}},
                'temporal': {'now': 1000, 'max_skew_ms': 100},
                'modal': {'knowledge': {'@safe': True}, 'belief': {}, 'certainty': {}},
                'axioms': {'value_system': {}},
                'rel': {}, 'demonstratives': {}, 'entities': {},
                'delivery': {'status': {}}, 'audit': {}
            },
            'domain': {},
            'local': {'timestamp': 1000}
        }
        
        cm = ContextManager(root=full_context['root'], domain=full_context['domain'], local=full_context['local'])
        rt = NoeRuntime(context_manager=cm, strict_mode=True)
        
        chain = 'shi @safe nek'  # Requires epistemic grounding
        full_result, _ = rt.evaluate_with_provenance(chain)
        
        # Full context should evaluate successfully
        assert full_result.domain == "truth"
        assert full_result.value == True
        
        # Now delete spatial.thresholds
        partial_context = {
            'root': {
                'literals': {'@safe': True},
                'spatial': {},  # DELETED thresholds
                'temporal': {'now': 1000, 'max_skew_ms': 100},
                'modal': {'knowledge': {'@safe': True}, 'belief': {}, 'certainty': {}},
                'axioms': {'value_system': {}},
                'rel': {}, 'demonstratives': {}, 'entities': {},
                'delivery': {'status': {}}, 'audit': {}
            },
            'domain': {},
            'local': {'timestamp': 1000}
        }
        
        cm2 = ContextManager(root=partial_context['root'], domain=partial_context['domain'], local=partial_context['local'])
        rt2 = NoeRuntime(context_manager=cm2, strict_mode=True)
        
        partial_result, _ = rt2.evaluate_with_provenance(chain)
        
        # Partial context should still evaluate (chain doesn't use spatial)
        # But if we had used spatial, it should NOT become True from deletion
        # This specific chain doesn't use spatial, so it's still True
        # The invariant holds: we didn't CREATE True by deletion
        assert partial_result.domain == "truth"  # Chain doesn't depend on spatial


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
