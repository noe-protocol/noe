"""
noe/canonical.py - Shared Canonicalization Logic
"""
import unicodedata
import json
from typing import Any

def canonical_literal_key(literal: str) -> str:
    """
    Normalize literal for dictionary lookup (e.g., '@foo' -> 'foo').
    
    Standard:
    - NFKC Unicode normalization
    - Trim whitespace
    - Lowercase
    - Strip leading '@' if present
    
    Used by: Parser, Validator, Adapters
    """
    # 1. Strip and Normalized
    k = literal.strip()
    k = unicodedata.normalize("NFKC", k)
    
    # 2. Lowercase (Strict NIP-011)
    k = k.lower()
    
    # 3. Strip leading '@' for keys
    if k.startswith("@"):
        return k[1:]
    return k

def canonicalize_chain(chain_text: str) -> str:
    """
    Canonicalize a Noe chain for hashing purposes.

    Rules:
        - Unicode NFKC normalization.
        - Collapse whitespace runs to single ASCII space.
        - Strip leading/trailing whitespace.

    Ensures semantically identical chains map to the same chain_hash.
    """
    if chain_text is None:
        return ""

    # Unicode normalization (NFKC to match system-wide standard)
    normalized = unicodedata.normalize("NFKC", chain_text)

    # Collapse whitespace to single spaces and strip
    parts = normalized.split()
    canonical = " ".join(parts)
    return canonical

def canonical_json(obj: Any) -> str:
    """
    Canonical JSON serialization:
        - UTF-8 (ensure_ascii=True for safety)
        - sorted keys
        - no whitespace separation
        - reject NaN/Infinity (allow_nan=False)
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
