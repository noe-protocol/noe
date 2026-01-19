"""
Noe Operator Lexicon (Single Source of Truth)

This module defines all operator sets for the Noe language.
Both the parser grammar and validator MUST import from this module
to ensure perfect token alignment.

Extracted from noe_parser.py grammar (lines 633-662).
"""

# Action verbs (from action_event rule)
ACTION_OPS = {"mek", "men"}

# Unary operators (from unary_op rule)
UNARY_OPS = {
    "nai", "nex",           # Logic: NOT, XOR
    "shi", "vek", "sha",    # Epistemic: knowledge, belief, certainty
    "tor", "da",            # Modal: possibility, necessity
    "nau", "ret", "tri",    # Temporal: now, past, future
    "qer", "eni", "sem",    # Deontic: permitted, obligatory, forbidden
    "mun", "fiu",           # Normative: value alignment
    "vus", "vel"            # Delivery: send, receive
}

# Conjunction-level binary operators (from conjunction_op rule)
CONJUNCTION_OPS = {
    "an",                           # Logical AND
    "ur",                           # Logical OR (lower precedence, but needs to be detectable)
    "kos", "til", "nel", "tel", "xel",  # Temporal comparisons
    "en",                           # Spatial: within
    "kra",                          # Bridge (logical sequence)
    "tra", "fra",                   # Velocity
    "noq",                          # Request operator
    "lef", "rai", "sup", "bel", "fai", "ban",  # Spatial axis
    "rel",                          # Relational
    "<", ">", "<=", ">=", "="       # Numeric comparisons
}

# Demonstrative operators (from demonstrative rule)
DEMONSTRATIVE_OPS = {"dia", "doq"}

# Guard/Scope keywords (not operators, but needed for validation)
GUARD_OPS = {"khi", "sek"}

# Morphology operators (fusion, inversion, suffix) - Critical for tokenizer
MORPH_OPS = {".", "·", "nei", "tok"}

# Derived sets for validator categorization
LOGIC_OPS = {
    "an", "ur", "nai", "nex",       # Core logic
    "khi", "kra", "sek",            # Guards and sequences
    "shi", "vek", "sha",            # Epistemic
    "tor", "da",                    # Modal
    "nau", "ret", "tri",            # Temporal logic
    "qer", "eni", "sem",            # Deontic
    "mun", "fiu"                    # Normative
}

COMP_OPS = {
    "<", ">", "<=", ">=", "=",                      # Numeric
    "kos", "til", "nel", "tel", "xel",              # Temporal
    "en", "tra", "fra",                             # Spatial/Velocity
    "lef", "rai", "sup", "bel", "fai", "ban",      # Spatial axis
    "rel"                                           # Relational
}

# Delivery operators (subset of unary + conjunction)
DELIVERY_OPS = {"vus", "vel", "noq"}

# Audit operators (subset of action + conjunction)
AUDIT_OPS = {"men", "kra"}

# All operators (for tokenization)
ALL_OPS = ACTION_OPS | UNARY_OPS | CONJUNCTION_OPS | DEMONSTRATIVE_OPS | GUARD_OPS | MORPH_OPS
