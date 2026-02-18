import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

from noe.provenance import compute_action_hash, compute_action_lineage_hashes
# Aliased in provenance.py
compute_action_structure_hash = compute_action_hash
import hashlib
import json

# Removed test_action_structure_flattening as internal representation is private

def test_action_hash_stable_under_params_order():
    """Verify parameter dict is sorted by key in hash."""
    a1 = {"verb": "mek", "target": "@t", "params": {"b": 2, "a": 1}}
    a2 = {"verb": "mek", "target": "@t", "params": {"a": 1, "b": 2}}
    
    h1 = compute_action_structure_hash(a1)
    h2 = compute_action_structure_hash(a2)
    
    assert h1 == h2

def test_action_hash_stable_under_field_order():
    # Only applicable if the input dict order doesn't matter for specific fields, 
    # but flatten_action_for_hash helps with modifiers/params.
    # The action dict itself is flattened by explicit field access, so input order doesn't matter.
    a1 = {
        "verb": "mek",
        "target": "@halt",
        "modifiers": ["urgent", "safety"],
        "params": {"speed": 0}
    }
    a2 = {
        "params": {"speed": 0},
        "target": "@halt",
        "verb": "mek",
        "modifiers": ["urgent", "safety"],
    }

    h1 = compute_action_structure_hash(a1)
    h2 = compute_action_structure_hash(a2)

    assert h1 == h2


def test_child_action_hash_differs_from_parent():
    actions = [
        {"verb": "mek", "target": "@start"},
        {"verb": "mek", "target": "@halt"},
    ]

    enriched = compute_action_lineage_hashes(actions)

    assert len(enriched) == 2
    parent = enriched[0]
    child = enriched[1]

    assert parent["child_action_hash"] is None
    assert child["child_action_hash"] is not None
    assert child["child_action_hash"] != child["action_hash"]

if __name__ == "__main__":
    # test_action_structure_flattening() # Removed
    test_action_hash_stable_under_params_order()
    test_action_hash_stable_under_field_order()
    test_child_action_hash_differs_from_parent()
    print("✅ test_provenance_action_hash.py passed")
