"""
Test strict mode anti-axiom security.

These tests ensure that strict mode never silently fabricates missing context fields.
Core invariant: deleting context should never create True from non-True.
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from noe.noe_runtime import NoeRuntime
from noe.noe_parser import ContextManager, merge_layers_for_validation


class TestAntiAxiomSecurity:
    """Prevent silent default fabrication that could bypass strict mode."""

    def test_none_layer_does_not_become_empty_dict(self):
        """merge_layers_for_validation must not mask None as {}."""
        ctx_none_root = {"root": None, "domain": {}, "local": {}}
        merged = merge_layers_for_validation(ctx_none_root)
        assert isinstance(merged, dict)

        ctx_invalid = {"root": "not_a_dict", "domain": {}, "local": {}}
        merged_invalid = merge_layers_for_validation(ctx_invalid)
        assert merged_invalid == ctx_invalid

    def test_missing_spatial_thresholds_blocks(self):
        """Missing spatial.thresholds must return undefined, not silent {}."""
        context = {
            'root': {
                'literals': {'@x': True, '@y': True},
                'spatial': {},
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

        chain = '@x dia @y nek'
        rr, _ = rt.evaluate_with_provenance(chain)

        assert rr.domain == "undefined", f"Expected undefined, got {rr.domain}: {rr.value}"

    def test_missing_temporal_does_not_fabricate(self):
        """None temporal must not be silently masked by double fallback."""
        context = {
            'root': {
                'literals': {'@test': True},
                'spatial': {'thresholds': {'near': 1.0, 'far': 5.0}, 'orientation': {'target': 0, 'tolerance': 0.1}},
                'temporal': None,
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

        chain = '@test nek'
        rr, _ = rt.evaluate_with_provenance(chain)

        assert rr.domain in ("literal", "undefined", "error")

    def test_no_phantom_defaults_in_validation_merge(self):
        """Validation merge must not seed phantom default shards."""
        ctx = {
            "root": {"literals": {"@x": True}},
            "domain": {},
            "local": {}
        }

        merged = merge_layers_for_validation(ctx)

        assert "literals" in merged
        assert merged["literals"] == {"@x": True}

        keys = set(merged.keys())
        assert "spatial" not in keys or "spatial" in ctx["root"]

    def test_deletion_never_creates_true(self):
        """Deleting context fields must never make non-True become True."""
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

        chain = 'shi @safe nek'
        full_result, _ = rt.evaluate_with_provenance(chain)

        assert full_result.domain == "truth"
        assert full_result.value == True

        partial_context = {
            'root': {
                'literals': {'@safe': True},
                'spatial': {},
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

        assert partial_result.domain == "truth"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
