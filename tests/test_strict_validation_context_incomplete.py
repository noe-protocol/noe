import pytest
from noe.noe_parser import run_noe_logic

def test_strict_missing_literals_shard_returns_error_not_exception():
    chain = "shi @temperature_ok khi sek mek @release_pallet sek nek"

    # Minimal shape that triggers strict validation but has literals=None
    ctx = {
        "temporal": {"now_ms": 0},
        "modal": {"knowledge": {}, "belief": {}},
        "literals": None,   # <- the bug trigger
        "actions": {},
    }

    result = run_noe_logic(chain_text=chain, context_object=ctx, mode="strict")

    assert isinstance(result, dict)
    assert result.get("domain") == "error"
    assert result.get("code") in {"ERR_CONTEXT_INCOMPLETE", "ERR_BAD_CONTEXT"}

if __name__ == "__main__":
    pytest.main([__file__])
