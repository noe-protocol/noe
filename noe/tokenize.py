
"""
noe/tokenize.py

Shared tokenizer and canonicalization logic for Noe.
Single source of truth for text normalization and operator extraction.
"""

import re
from typing import List, Set
from noe.canonical import canonicalize_chain



def extract_ops(chain_text: str, ops: Set[str]) -> List[str]:
    """
    Extract operator tokens from chain text using strict word boundaries.
    
    Args:
        chain_text: The chain string (should be canonicalized).
        ops: Set of valid operator strings defined by the lexicon.
        
    Returns:
        List of operators found, in order of appearance.
    """
    if not chain_text or not ops:
        return []

    # 1. Sort by length descending to match 'mek' before 'me' overlap (if any)
    sorted_ops = sorted(list(ops), key=len, reverse=True)
    escaped_ops = [re.escape(op) for op in sorted_ops]
    
    # 2. Build Regex
    # (?<![\w@]) -> Negative Lookbehind: Not preceded by word char or @
    # (?: ... )  -> Non-capturing group of alternatives
    # (?![\w])   -> Negative Lookahead: Not followed by word char
    ops_pattern = f"(?<![\\w@])(?:{'|'.join(escaped_ops)})(?![\\w])"
    
    # 3. Scan
    flags = re.UNICODE
    found_ops = []
    for m in re.finditer(ops_pattern, chain_text, flags=flags):
        found_ops.append(m.group(0))
        
    return found_ops

def extract_ops_safe(chain_text: str, ops: Set[str]) -> Set[str]:
    """
    Wrapper for validator usage: extract unique set of operators.
    """
    # Canonicalize first? Or assume caller did?
    # Safe to do it again.
    canon = canonicalize_chain(chain_text)
    tokens = extract_ops(canon, ops)
    return set(tokens)
