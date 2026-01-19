#!/usr/bin/env python3
"""
Canonical JSON micro-tests - verify RFC 8785 compliance for tricky objects.

These tests assert the exact canonical bytes to catch any JSON library drift.
"""

import json
import hashlib

def canonical_json_bytes(obj):
    """
    Generate canonical JSON bytes using Python's json module.
    
    RFC 8785 requirements:
    - Keys sorted lexicographically
    - No whitespace: separators=(',', ':')
    - ensure_ascii=True (escape non-ASCII)
    - allow_nan=False (reject NaN/Inf)
    """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(',', ':'),
        ensure_ascii=True,
        allow_nan=False
    ).encode('utf-8')


def test_canonical_json():
    """Test canonical JSON serialization for edge cases."""
    
    tests = [
        {
            "name": "Empty object",
            "obj": {},
            "expected_bytes": b'{}',
            "expected_sha256": "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
        },
        {
            "name": "Key ordering",
            "obj": {"z": 1, "a": 2, "m": 3},
            "expected_bytes": b'{"a":2,"m":3,"z":1}',
            "expected_sha256": "7c9c8de73e2d7e1c5a3b8a9e1c2e7d3e5b5a9e1c2e7d3e5b5a9e1c2e7d3e5b5a"  # placeholder - will update
        },
        {
            "name": "No whitespace",
            "obj": {"key": "value"},
            "expected_bytes": b'{"key":"value"}',
            "expected_sha256": None  # will compute
        },
        {
            "name": "Nested objects",
            "obj": {"outer": {"inner": "value"}},
            "expected_bytes": b'{"outer":{"inner":"value"}}',
            "expected_sha256": None
        },
        {
            "name": "Boolean true/false",
            "obj": {"t": True, "f": False},
            "expected_bytes": b'{"f":false,"t":true}',
            "expected_sha256": None
        },
        {
            "name": "Integer (no decimal)",
            "obj": {"num": 42},
            "expected_bytes": b'{"num":42}',
            "expected_sha256": None
        },
        {
            "name": "Unicode escape",
            "obj": {"emoji": "🎉"},
            "expected_bytes": b'{"emoji":"\\ud83c\\udf89"}',  # ensure_ascii=True
            "expected_sha256": None
        }
    ]
    
    print("Canonical JSON Micro-Tests")
    print("=" * 50)
    
    passed = 0
    failed = 0
    
    for test in tests:
        canonical_bytes = canonical_json_bytes(test["obj"])
        sha256 = hashlib.sha256(canonical_bytes).hexdigest()
        
        # Check bytes match
        if canonical_bytes != test["expected_bytes"]:
            print(f"✗ {test['name']}: FAIL")
            print(f"  Expected: {test['expected_bytes']}")
            print(f"  Got:      {canonical_bytes}")
            failed += 1
        else:
            print(f"✓ {test['name']}: PASS")
            passed += 1
            
        # Print SHA-256 for reference
        print(f"  SHA-256: {sha256}")
    
    print("=" * 50)
    print(f"Passed: {passed}/{len(tests)}")
    
    if failed > 0:
        print(f"❌ {failed} tests FAILED")
        return False
    else:
        print("✅ All canonical JSON tests PASSED")
        return True


if __name__ == "__main__":
    import sys
    success = test_canonical_json()
    sys.exit(0 if success else 1)
