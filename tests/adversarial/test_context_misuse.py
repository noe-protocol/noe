
import pytest
from noe.context_manager import ContextManager
from noe.noe_parser import run_noe_logic

def test_misuse_inplace_mutation_stale_cache():
    """
    DOCUMENTATION BY TEST:
    Demonstrates the risk of violating the ContextManager immutability contract.
    If 'root' or 'domain' are mutated in-place without notifying the manager,
    caches (hashes and merged contexts) become stale.
    """
    
    # 1. Setup initial context
    root = {"safety": {"max_speed": 10.0}}
    cm = ContextManager(root=root)
    
    snap1 = cm.snapshot()
    hash1 = snap1.root_hash
    
    # 2. VIOLATION: In-place mutation of the root dictionary
    # The ContextManager deep-copies on init, so this mutation does NOT affect
    # the internal frozen state. This is the CORRECT behavior (immutable copy).
    root["safety"]["max_speed"] = 999.0 
    
    # 3. Snapshot again
    snap2 = cm.snapshot()
    hash2 = snap2.root_hash
    
    # 4. v1.0 ContextManager deep-freezes root on init, so external mutations
    # do NOT affect the internal state. Hash remains unchanged because internal
    # data is unchanged (correct immutability behavior).
    assert hash1 == hash2, "Internal hash unchanged (correct - deep copy on init)"
    
    # 5. The internal snapshot 'structured' should still have ORIGINAL value
    # because ContextManager deep-copied on init.
    # Access via structured.root or merged (flattened)
    assert snap2.structured["root"]["safety"]["max_speed"] == 10.0, \
        "Deep copy prevents external mutation"
    
    # 6. To update root, create a new ContextManager with new data
    new_root = {"safety": {"max_speed": 999.0}}
    cm_fresh = ContextManager(root=new_root)
    snap_fresh = cm_fresh.snapshot()
    hash_fresh = snap_fresh.root_hash
    
    # Now hash should be different because data is different
    assert hash_fresh != hash1, "New data should produce new hash"
    
if __name__ == "__main__":
    pytest.main([__file__])
