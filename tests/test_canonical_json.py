#!/usr/bin/env python3
"""
Canonical JSON micro-tests — verify RFC 8785 compliance for tricky objects.

Asserts exact canonical bytes to catch any JSON library drift.
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


CASES = [
    ("{}", {}, b'{}'),
    ("key ordering", {"z": 1, "a": 2, "m": 3}, b'{"a":2,"m":3,"z":1}'),
    ("no whitespace", {"key": "value"}, b'{"key":"value"}'),
    ("nested objects", {"outer": {"inner": "value"}}, b'{"outer":{"inner":"value"}}'),
    ("boolean true/false", {"t": True, "f": False}, b'{"f":false,"t":true}'),
    ("integer (no decimal)", {"num": 42}, b'{"num":42}'),
    ("unicode escape", {"emoji": "🎉"}, b'{"emoji":"\\ud83c\\udf89"}'),
]

# Frozen SHA-256 for stability proof (computed once, asserted forever)
KNOWN_HASHES = {
    "{}": "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
}


def test_canonical_bytes():
    """Each object must serialize to the exact expected bytes."""
    for name, obj, expected in CASES:
        canonical = canonical_json_bytes(obj)
        assert canonical == expected, (
            f"{name}: bytes mismatch\n"
            f"  expected={expected!r}\n"
            f"  got     ={canonical!r}"
        )


def test_canonical_hashes():
    """Frozen SHA-256 values must remain stable across runs."""
    for name, obj, _ in CASES:
        if name in KNOWN_HASHES:
            h = hashlib.sha256(canonical_json_bytes(obj)).hexdigest()
            assert h == KNOWN_HASHES[name], (
                f"{name}: SHA-256 mismatch\n"
                f"  expected={KNOWN_HASHES[name]}\n"
                f"  got     ={h}"
            )


def test_nan_rejected():
    """NaN must raise ValueError (allow_nan=False)."""
    import pytest
    with pytest.raises(ValueError):
        canonical_json_bytes({"x": float('nan')})


def test_inf_rejected():
    """Inf must raise ValueError (allow_nan=False)."""
    import pytest
    with pytest.raises(ValueError):
        canonical_json_bytes({"x": float('inf')})
