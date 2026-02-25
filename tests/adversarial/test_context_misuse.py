"""
Test that ContextManager immutability contract prevents stale cache attacks.
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from noe.context_manager import ContextManager
from noe.noe_parser import run_noe_logic


def test_misuse_inplace_mutation_stale_cache():
    """In-place mutation of root must not affect internal frozen state."""

    root = {"safety": {"max_speed": 10.0}}
    cm = ContextManager(root=root)

    snap1 = cm.snapshot()
    hash1 = snap1.root_hash

    root["safety"]["max_speed"] = 999.0

    snap2 = cm.snapshot()
    hash2 = snap2.root_hash

    assert hash1 == hash2, "Internal hash unchanged (correct - deep copy on init)"

    assert snap2.structured["root"]["safety"]["max_speed"] == 10.0, \
        "Deep copy prevents external mutation"

    new_root = {"safety": {"max_speed": 999.0}}
    cm_fresh = ContextManager(root=new_root)
    snap_fresh = cm_fresh.snapshot()
    hash_fresh = snap_fresh.root_hash

    assert hash_fresh != hash1, "New data should produce new hash"


if __name__ == "__main__":
    pytest.main([__file__])
