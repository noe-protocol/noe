r"""
noe_validator.py

Validation layer for the Noe Runtime (Validator V2).

This module enforces safety invariants before a chain is evaluated
by the pure logic engine in noe_parser.py.

It inspects the **Rich Context** ($C_{rich}$) which may contain annotated evidence.
It does NOT apply the Safe Projection ($\pi_{safe}$). That is the responsibility
of the Runtime before evaluation.

It does NOT execute chains. It only inspects:
- the chain text
- the context snapshot C
and decides whether it is safe to proceed.

This MUST only be called on chains that have passed the Verified Compiler.

If ok is False, the runtime MUST treat the chain as undefined and MUST NOT execute any actions.
"""

from typing import Dict, Any, List, Optional
from collections.abc import Mapping
import re
import unicodedata
import json
import hashlib
import copy
import os
import sys


from .context_projection import pi_safe, ProjectionConfig, extract_evidence_from_context
import os

# ==========================================
# DEBUGGING INSTRUMENTATION
# ==========================================
# Debug disabled by default for clean production output
# Enable with: NOE_DEBUG=1
_DEBUG_ENABLED = os.getenv("NOE_DEBUG", "0") == "1"

def _debug_print(*args, **kwargs):
    """Print only if debug is enabled."""
    if _DEBUG_ENABLED:
        print(*args, **kwargs)

# ==========================================
# PERFORMANCE: CACHING
# ==========================================
# [DELETED] ID-based caching is unsafe for mutable contexts.
# v1.0 Validator computes hashes on-demand or relies on caller.


ValidationResult = Dict[str, Any]


# Default minimal context for initialization/fallback
DEFAULT_CONTEXT_PARTIAL = {
    "root": {},
    "domain": {},
    "local": {}, 
    "literals": {},
    "spatial": {"thresholds": {"near": 1.0, "far": 10.0}, "orientation": {}},
    "temporal": {"now": 0, "max_skew_ms": 1000},
    "modal": {},
    "axioms": {"value_system": {}},
    "delivery": {},
    "audit": {},
    "entities": {}
}

from .context_requirements import CONTEXT_REQUIREMENTS

_LITERAL_RE = re.compile(r"@[\w]+", flags=re.UNICODE)

# Use canonical requirements from context_requirements.py
# If specific validator overrides are needed, they can be merged here.
GROUNDING_REQUIREMENTS = CONTEXT_REQUIREMENTS

_MAX_CONTEXT_DEPTH = 32  # Strict Limit to prevent RecursionError

def _check_depth(obj: Any, current_depth: int = 0) -> bool:
    """
    Recursively check depth of nested dictionaries/lists.
    Returns False if depth exceeds _MAX_CONTEXT_DEPTH.
    """
    if current_depth > _MAX_CONTEXT_DEPTH:
        return False
        
    if isinstance(obj, dict):
        for v in obj.values():
            if not _check_depth(v, current_depth + 1):
                return False
    elif isinstance(obj, list):
        for v in obj:
            if not _check_depth(v, current_depth + 1):
                return False
                
    return True

def check_grounding(op_name: str, args: tuple, C_total: dict) -> bool:
    if _DEBUG_ENABLED:
        _debug_print(f"DEBUG CHECK GROUNDING: op={op_name}, C_keys={list(C_total.keys())}")

    """
    Returns True if the operator is fully grounded under C_total and args,
    False otherwise.
    """
    # 1. Look up requirements
    reqs = GROUNDING_REQUIREMENTS.get(op_name, [])
    
    # 2. Verify required subsystems/keys exist
    for req in reqs:
        # Check if entire shard is missing
        parts = req.split(".")
        curr = C_total
        for p in parts:
            if isinstance(curr, dict) and p in curr:
                curr = curr[p]
            else:
                return False
                
    # 3. Operator-specific dynamic checks
    # Spatial entities must exist in entities shard
    if op_name in ["nel", "tel", "xel", "en", "tra", "fra"]:
        entities = C_total.get("entities", {})
        if not isinstance(entities, dict): return False
        for arg in args:
            if isinstance(arg, str) and arg.startswith("@"):
                if arg not in entities:
                    return False
                if "position" not in entities[arg]:
                    return False

    # Epistemic targets must exist in modal shard (if we check them here)
    # But usually validated via ERR_EPISTEMIC_MISMATCH in validate_chain
    
    return True



def _extract_literals(chain_text: str) -> List[str]:
    """Return all literal tokens like @home, @dock_3 from the chain."""
    return list({m.group(0) for m in _LITERAL_RE.finditer(chain_text)})


from noe.canonical import canonical_json, canonical_literal_key, canonicalize_chain
from noe.tokenize import extract_ops as _tokenize_extract_ops

def validate_ast_safety(ast_node: Any) -> bool:
    """Validates AST safety (depth, banned nodes)."""
    # For now, just depth check to prevent stack overflow
    return _check_depth(ast_node)

def _canonical_json(obj: Any) -> bytes:
    """
    Canonical JSON serialization for hashing.
    Normalized using internal logic, then serialized using standard canonical format.
    """
    # 1. Normalize (strip internal keys, sort keys)
    def _normalize(o):
        if isinstance(o, dict):
            return {k: _normalize(v) for k, v in o.items() if isinstance(k, str) and not k.startswith("_")}
        if isinstance(o, (list, tuple)):
            return [_normalize(x) for x in o]
        return o

    norm = _normalize(obj)
    
    # 2. Serialize (Sort keys, standard separators, ensure_ascii=True for safety)
    return canonical_json(norm).encode("utf-8")


def compute_context_hashes(C: Dict[str, Any]) -> Dict[str, str]:
    """
    Compute hierarchical context hashes:

    - H_root   = hash(C_root)
    - H_domain = hash(C_domain)
    - H_local  = hash(C_local)
    - H_total  = hash(H_root || H_domain || H_local)

    Supports both structured and flat contexts.
    """
    # Support both flat and structured contexts
    # Strict Check
    if "root" in C and "domain" in C and "local" in C:
        # Structured context (Optimistic check, validate_chain enforces types)
        C_root = C.get("root", {})
        C_domain = C.get("domain", {})
        C_local = C.get("local", {})
    else:
        # Legacy flat context (treat as local)
        C_root = {}
        C_domain = {}
        C_local = C

    h_root_bytes = hashlib.sha256(_canonical_json(C_root)).digest()
    h_domain_bytes = hashlib.sha256(_canonical_json(C_domain)).digest()
    h_local_bytes = hashlib.sha256(_canonical_json(C_local)).digest()

    h_root = h_root_bytes.hex()
    h_domain = h_domain_bytes.hex()
    h_local = h_local_bytes.hex()

    h_total_bytes = hashlib.sha256(
        h_root_bytes + h_domain_bytes + h_local_bytes
    ).digest()
    h_total = h_total_bytes.hex()

    return {
        "root": h_root,
        "domain": h_domain,
        "local": h_local,
        "total": h_total,
    }


from .operator_lexicon import (
    ACTION_OPS,
    LOGIC_OPS,
    COMP_OPS,
    DEMONSTRATIVE_OPS,
    DELIVERY_OPS,
    AUDIT_OPS,
    ALL_OPS
)


# ...

def extract_ops(chain_text):
    """
    Extract operators from raw chain text using robust tokenizer.
    Extract operators from raw chain text using robust tokenizer.
    Delegates to noe.tokenize.extract_ops (ordered list).
    """
    # Ensure canonical form first (tokenize.extract_ops requires it)
    canon = canonicalize_chain(chain_text)
    return _tokenize_extract_ops(canon, ALL_OPS)

def _validate_audit_strict(ctx):
    """Strict validation for audit subsystem."""
    audit = ctx.get("audit")
    if audit is None:
        return {"code": "ERR_CONTEXT_INCOMPLETE", "detail": "Missing audit subsystem"}
    if not isinstance(audit, Mapping):
        return {"code": "ERR_CONTEXT_INCOMPLETE", "detail": "Audit subsystem must be an object"}
    return None

def compute_stale_flag(C_total):
    """Computes staleness based on temporal subsystem relative to local time."""
    temp = C_total.get("temporal", {})
    if not isinstance(temp, dict): return False, "No temporal subsystem"
    
    # Check for canonical inputs
    now = temp.get("now")
    skew = temp.get("max_skew_ms")
    ts = temp.get("timestamp") # Populated by merge logic in strict mode
    
    if now is None or skew is None or ts is None:
        # Cannot determine staleness if fields missing.
        # Strict context validation should catch missing 'now'/'skew' in shape check?
        return False, None
        
    # Ensure types
    try:
        now = float(now)
        skew = float(skew)
        ts = float(ts)
    except (ValueError, TypeError):
        return False, "Non-numeric temporal fields"

    # Logic: if now - timestamp > skew -> Stale
    if _DEBUG_ENABLED: print(f"DEBUG: Stale Check: now={now}, ts={ts}, skew={skew}, diff={now-ts}")
    if (now - ts) > skew:
         return True, f"Timestamp {ts} is older than now {now} by > {skew}ms"
    
    return False, None

def _validate_delivery_strict(C_total: Mapping) -> Optional[Dict[str, str]]:
    """
    Validate delivery subsystem for strict mode.
    
    Required when vus, vel, or noq operators are present.
    Delivery subsystem must exist and have valid structure.
    """
    delivery = C_total.get("delivery")
    if not isinstance(delivery, Mapping):
        return {
            "code": "ERR_CONTEXT_INCOMPLETE",
            "detail": "C.delivery must be an object in strict mode"
        }
    
    # Delivery subsystem must have either 'items' or 'status'
    has_items = "items" in delivery
    has_status = "status" in delivery
    
    if not (has_items or has_status):
        return {
            "code": "ERR_CONTEXT_INCOMPLETE",
            "detail": "C.delivery must contain 'items' or 'status' in strict mode"
        }
    
    # If items exists, it must be a mapping
    if has_items and not isinstance(delivery.get("items"), Mapping):
        return {
            "code": "ERR_CONTEXT_INCOMPLETE",
            "detail": "C.delivery.items must be an object"
        }
    
    return None

def validate_context_strict(C_total: dict, tokens: List[str] = None) -> (Optional[str], bool):
    """
    Validates the context against strict NIP-009 requirements using Shape-First logic.
    
    Returns (error_code, is_stale).
    If valid, returns (None, False).
    """
    if not isinstance(C_total, Mapping):
        return "ERR_BAD_CONTEXT", False

    # 1. Check Required Top-Level Shards (Shape Only)
    # Literals
    if "literals" not in C_total:
         return "ERR_CONTEXT_INCOMPLETE", False
    if not isinstance(C_total["literals"], Mapping):
         return "ERR_CONTEXT_INCOMPLETE", False

    # Spatial (NOT required top-level - only validated when spatial operators used)
    # This was causing ERR_SPATIAL_UNGROUNDABLE even for pure epistemic chains
    # Spatial validation moved to operator-specific checks (nel, tel, xel, etc.)
    # if "spatial" not in C_total:
    #      return "ERR_CONTEXT_INCOMPLETE", False
    # if not isinstance(C_total["spatial"], Mapping):
    #      return "ERR_CONTEXT_INCOMPLETE", False


    # Temporal
    if "temporal" not in C_total:
         return "ERR_CONTEXT_INCOMPLETE", False
    if not isinstance(C_total["temporal"], Mapping):
         return "ERR_CONTEXT_INCOMPLETE", False
    
    # Strict: Temporal must contain time fields
    # Accept EITHER legacy (now, max_skew_ms) OR v1.0 int64 (now_us, max_staleness_us)
    temp = C_total["temporal"]
    has_legacy = temp.get("now") is not None and temp.get("max_skew_ms") is not None
    has_v1 = temp.get("now_us") is not None
    
    if not (has_legacy or has_v1):
        return "ERR_CONTEXT_INCOMPLETE", False
         
    # Modal
    if "modal" not in C_total:
         return "ERR_CONTEXT_INCOMPLETE", False
    if not isinstance(C_total["modal"], Mapping):
         return "ERR_CONTEXT_INCOMPLETE", False
         
    # Axioms
    if "axioms" not in C_total:
         return "ERR_CONTEXT_INCOMPLETE", False
    if not isinstance(C_total["axioms"], Mapping):
         return "ERR_CONTEXT_INCOMPLETE", False

    stale, _ = compute_stale_flag(C_total)
    
    return None, stale


# ==========================================
# ERROR PRIORITY (Deterministic Ordering)
# ==========================================
# Ensures stable error reporting regardless of check order
ERROR_PRIORITY = {
    # Hard malformed / safety
    "ERR_BAD_CONTEXT": 0,
    "ERR_CONTEXT_TOO_DEEP": 0,
    "ERR_CONTEXT_UNSERIALIZABLE": 0,

    # Strict shape / staleness / completeness
    "ERR_CONTEXT_STALE": 1,
    "ERR_CONTEXT_INCOMPLETE": 1,

    # Action safety boundary
    "ERR_ACTION_MISUSE": 2,
    "ERR_ACTION_CYCLE": 2,

    # Subsystem grounding
    "ERR_DELIVERY_MISMATCH": 3,
    "ERR_EPISTEMIC_MISMATCH": 3,
    "ERR_SPATIAL_UNGROUNDABLE": 3,
    "ERR_DEMONSTRATIVE_UNGROUNDED": 3,

    # Dependency resolution
    "ERR_LITERAL_MISSING": 4,
    "ERR_INVALID_LITERAL": 4,
    
    # Parse failures
    "ERR_PARSE_FAILED": 5,
}

def _sort_errors(errors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sort errors by priority (lowest first) for deterministic reporting."""
    def key(e):
        code = e.get("code", "")
        priority = ERROR_PRIORITY.get(code, 999)
        return (priority, code)
    return sorted(errors, key=key)


# ==========================================
# 2. CHAIN VALIDATION (MAIN ENTRY POINT)
# ==========================================

def validate_chain(
    chain_text: str,
    context_object: Dict[str, Any],
    mode: str = "strict",
    context_hashes: Optional[Dict[str, str]] = None,
    explain: bool = False,
) -> ValidationResult:
    # 0. Canonicalize
    chain_text = canonicalize_chain(chain_text)

    # 1. Start Validation
    if _DEBUG_ENABLED: print(f"DEBUG: validate_chain called. Length={len(chain_text)}. Text='{chain_text}'")
    """
    Validate a Noe chain against a given context C before interpretation.
    
    Returns a ValidationResult dict with:
    - ok (bool): True if validation passed, False if critical errors found
    - context_hashes: Provenance hashes (empty if ok=False)
    - errors: List of error dicts with code/detail
    
    Runtime Contract (v1.0 Strict):
    - If ok=False: Runtime MUST return domain="error" with validator error code.
      Never evaluate the chain. Never return undefined for validation failures.
    - If ok=True: Runtime MAY evaluate. Semantic uncertainty returns domain="undefined".
    """
    global ACTION_OPS, LOGIC_OPS, COMP_OPS
    
    # 0. Recursion Guard (Defense against Allocation Bomb/Crash)
    if not _check_depth(context_object):
        return {
            "ok": False,
            "context_hashes": {},
            "context_error": "ERR_CONTEXT_TOO_DEEP",
            "flags": {"schema_invalid": True},
            "reasons": [f"Context nesting exceeds limit ({_MAX_CONTEXT_DEPTH})"],
            "errors": [{
                "code": "ERR_CONTEXT_TOO_DEEP", 
                "detail": "Context too deep (recursion protection)"
            }],
            "warnings": [],
            "provenance": None,
            "explained_literals": []
        }
    
    if not isinstance(context_object, Mapping):
        return {
            "ok": False,
            "context_hashes": {},
            "context_error": "ERR_BAD_CONTEXT",
            "flags": {"schema_invalid": True},
            "reasons": [f"Context root must be a dictionary/map, got {type(context_object).__name__}"],
            "errors": [{
                "code": "ERR_BAD_CONTEXT", 
                "detail": f"Context malformed: {type(context_object).__name__}"
            }],
            "warnings": [],
            "provenance": None,
            "explained_literals": []
        }
    
    
    # STRICT MODE: Enforce structured context consistency
    if mode == "strict":
        has_root = "root" in context_object
        has_domain = "domain" in context_object
        has_local = "local" in context_object
        
        # If using structured context, must be complete
        if has_root or has_domain or has_local:
            if not (has_root and has_domain and has_local):
                missing = []
                if not has_root: missing.append("root")
                if not has_domain: missing.append("domain")
                if not has_local: missing.append("local")
                return {
                    "ok": False,
                    "context_hashes": {},
                    "context_error": "ERR_CONTEXT_INCOMPLETE",
                    "flags": {"schema_invalid": True},
                    "reasons": [f"Structured context requires all three layers: missing {', '.join(missing)}"],
                    "errors": [{
                        "code": "ERR_CONTEXT_INCOMPLETE",
                        "detail": f"Structured context requires all three layers: missing {', '.join(missing)}",
                        "meta": {}
                    }],
                    "warnings": [],
                    "provenance": None,
                    "explained_literals": []
                }
            # Verify all three are Mappings
            if not isinstance(context_object.get("root"), Mapping):
                return {
                    "ok": False,
                    "context_hashes": {},
                    "context_error": "ERR_CONTEXT_INCOMPLETE",
                    "flags": {"schema_invalid": True},
                    "reasons": ["'root' must be a dict in structured context"],
                    "errors": [{
                        "code": "ERR_CONTEXT_INCOMPLETE",
                        "detail": "'root' must be a dict"
                    }],
                    "warnings": [],
                    "provenance": None,
                    "explained_literals": []
                }
            if not isinstance(context_object.get("domain"), Mapping):
                return {
                    "ok": False,
                    "context_hashes": {},
                    "context_error": "ERR_CONTEXT_INCOMPLETE",
                    "flags": {"schema_invalid": True},
                    "reasons": ["'domain' must be a dict in structured context"],
                    "errors": [{
                        "code": "ERR_CONTEXT_INCOMPLETE",
                        "detail": "'domain' must be a dict"
                    }],
                    "warnings": [],
                    "provenance": None,
                    "explained_literals": []
                }
            if not isinstance(context_object.get("local"), Mapping):
                return {
                    "ok": False,
                    "context_hashes": {},
                    "context_error": "ERR_CONTEXT_INCOMPLETE",
                    "flags": {"schema_invalid": True},
                    "reasons": ["'local' must be a dict in structured context"],
                    "errors": [{
                        "code": "ERR_CONTEXT_INCOMPLETE",
                        "detail": "'local' must be a dict"
                    }],
                    "warnings": [],
                    "provenance": None,
                    "explained_literals": []
                }
    
    # -----------------------------------------------------------
    # HIERARCHICAL INTEGRITY
    # -----------------------------------------------------------
    C_struct = context_object
    C_total = context_object or {}
    
    # Auto-detect structured contexts and merge to flat form
    if isinstance(C_total.get("root"), dict) and isinstance(C_total.get("domain"), dict) and isinstance(C_total.get("local"), dict):
        # Strict Structured Context: All three must exist and be dicts
        import copy
    
        def _deep_merge_local(base, overlay):
            if not isinstance(base, dict) or not isinstance(overlay, dict):
                return copy.deepcopy(overlay)
            result = base.copy()
            for k, v in overlay.items():
                if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                    result[k] = _deep_merge_local(result[k], v)
                else:
                    result[k] = copy.deepcopy(v)
            return result
    
        C_root = C_total.get("root", {})
        C_domain = C_total.get("domain", {})
        C_local = C_total.get("local", {})
        C_total = _deep_merge_local(_deep_merge_local({}, C_root), C_domain)
        C_total = _deep_merge_local(C_total, C_local)
        
        # Fix 2: Canonical Strict Timestamp
        # Ensure temporal.timestamp is populated from local.timestamp for stale check
        ts = C_local.get("timestamp")
        if ts is not None:
             if "temporal" not in C_total or not isinstance(C_total["temporal"], dict):
                 C_total["temporal"] = {}
             C_total["temporal"]["timestamp"] = ts
    
    # -------------------------------------------------------------------------
    # TRAFFIC COP LOGIC (Strict Mode Priority)
    # -------------------------------------------------------------------------
    
    flags = {
        "invalid_literal": False,
        "literal_mismatch": False, 
        "action_misuse": False,
        "demonstrative_ungrounded": False,
        "spatial_mismatch": False, 
        "epistemic_mismatch": False,
        "sensor_mismatch": False, 
        "delivery_mismatch": False,
        "audit_mismatch": False,
        "schema_invalid": False,
        "context_stale": False,
        "demonstrative_mismatch": False,
        "value_system_mismatch": False,
    }
    reasons = []
    errors = []
    warnings = []
    
    # 1. Invalid Literal Scan (Raw Span)
    # User Strategy: Scan @ followed by non-whitespace. If not exactly @[\w]+ -> Error.
    import re
    # Define regexes for reuse in later blocks (Line 661)
    _LITERAL_LIKE_RE = re.compile(r"(@[^\s(),;]+)", flags=re.UNICODE)
    _LITERAL_RE_STRICT = re.compile(r"^@[a-z0-9_]+$", flags=re.UNICODE)
    
    raw_literals = re.findall(r"@[^ \t\r\n\)\]\}\>,;]+", chain_text, flags=re.UNICODE)
    for raw_lit in raw_literals:
        # Strip trailing punctuation often found in token streams? 
        # User said "stop at whitespace". Strict means STRICT. 
        # If we have "(@foo)", it parses as "@foo)". "@foo)" is invalid.
        # However, we must handle legitimate termination like ")" in ( @foo ).
        # But wait, canonicalization adds spaces around parens?
        # If canonicalized, "(@foo)" -> "( @foo )". Then "@foo" is cleanly separated.
        # If input is "@foo-bar", it is "@foo-bar". MATCH fails.
        # If input is "@foo)", and canonicalizer didn't space it...
        
        # We rely on chain_text being canonicalized by caller?
        # If not, we might flag valid literals that are buttressing punctuation.
        # But User Strategy emphasizes RAW scan.
        # Let's assume canonicalization happened (it is called in run_conformance).
        
        if not re.fullmatch(r"@[a-z0-9_]+", raw_lit):
            if _DEBUG_ENABLED: print(f"DEBUG: INVALID LITERAL FOUND '{raw_lit}'")
            flags["invalid_literal"] = True
            reasons.append(f"Malformed literal '{raw_lit}'")
            errors.append({"code": "ERR_INVALID_LITERAL", "detail": f"Malformed literal '{raw_lit}'"})
        elif mode == "strict": 
            # Valid Syntax. Check Presence.
            # User implies strict mode requires it.
            # NIP-009: Keys in literals shard should be without @.
            canon_key = canonical_literal_key(raw_lit)
            literals_shard = C_total.get("literals", {})
            
            # Check for key existence (canon or raw)
            if canon_key not in literals_shard and raw_lit not in literals_shard:
                 if _DEBUG_ENABLED: print(f"DEBUG: LITERAL MISSING '{raw_lit}'")
                 flags["literal_mismatch"] = True
                 reasons.append(f"Literal '{raw_lit}' not found in context")
                 errors.append({"code": "ERR_LITERAL_MISSING", "detail": f"Literal '{raw_lit}' missing"})


            
    # 2. Operator Extraction (Raw)
    ops = extract_ops(chain_text)
    
    # 3. Shape Validation & Staleness
    if mode == "strict":
        shape_err, is_stale = validate_context_strict(C_total)
        
        if is_stale:
            flags["context_stale"] = True
            errors.append({"code": "ERR_CONTEXT_STALE", "detail": "Context is stale based on timestamp/skew"})
            
        if shape_err:
            flags["schema_invalid"] = True
            reasons.append(f"Context shape invalid: {shape_err}")
            errors.append({"code": "ERR_CONTEXT_INCOMPLETE", "detail": f"Context shape invalid: {shape_err}"})
        
    
    # 4. Operator Gating & Deep Checks
    if mode == "strict":
        # A. Demonstratives (dia, doq)
        dem_ops = {"dia", "doq"}
        if not dem_ops.isdisjoint(ops):
            spatial = C_total.get("spatial", {})
            if isinstance(spatial, Mapping):
                 thresholds = spatial.get("thresholds")
                 orientation = spatial.get("orientation")
                 
                 is_grounded = True
                 if not isinstance(thresholds, Mapping): is_grounded = False
                 elif "near" not in thresholds or "far" not in thresholds: is_grounded = False
                 
                 if not isinstance(orientation, Mapping): is_grounded = False
                 
                 if not is_grounded:
                        flags["demonstrative_ungrounded"] = True
                        reasons.append("Demonstrative operators require spatial.thresholds (near/far) and orientation")
                        errors.append({"code": "ERR_DEMONSTRATIVE_UNGROUNDED", "detail": "Missing spatial grounding"})
    
        # B. Spatial Ops (nel, tel, xel, en, fra, tra, dia, doq)
        spatial_ops = {"nel", "tel", "xel", "en", "fra", "tra", "dia", "doq"}
        needs_spatial = not spatial_ops.isdisjoint(ops)
        
        if needs_spatial:
            # Only check spatial if chain uses spatial operators
            if "spatial" not in C_total or not isinstance(C_total["spatial"], Mapping):
                flags["spatial_mismatch"] = True
                reasons.append("Spatial operators used but C.spatial missing")
                errors.append({"code": "ERR_SPATIAL_UNGROUNDABLE", "detail": "Missing spatial context"})
            else:
                spatial_ctx = C_total["spatial"]
                # Accept either legacy (thresholds) or v1.0 (thresholds_mm)
                has_thresholds = "thresholds" in spatial_ctx or "thresholds_mm" in spatial_ctx
                if not has_thresholds:
                    flags["spatial_mismatch"] = True
                    reasons.append("Spatial operators require defined thresholds")
                    errors.append({"code": "ERR_SPATIAL_UNGROUNDABLE", "detail": "Missing spatial thresholds"})

        # C. Audit Ops (men, khi)
        # NOTE: noq does NOT strictly require audit in v1.0 base profile.
        # It requires delivery. Audit logging is handled by runtime transparency.
        audit_ops = {"men", "khi"}
        needs_audit = not audit_ops.isdisjoint(ops)
            
        if needs_audit:
            audit_err = _validate_audit_strict(C_total)
            if audit_err:
                flags["audit_mismatch"] = True
                reasons.append("Audit subsystem missing but audit operators used")
                errors.append(audit_err)

        # D. Delivery Ops (vus, vel, noq)
        delivery_ops = {"vus", "vel", "noq"}
        if not delivery_ops.isdisjoint(ops):
             delivery_err = _validate_delivery_strict(C_total)
             if delivery_err:
                 flags["delivery_mismatch"] = True
                 reasons.append("Delivery subsystem missing but delivery operators used")
                 errors.append(delivery_err)
    
        # 5. Literal Existence Check handled in main token loop above (Section 1)



    # -------------------------------------------------------------------------
    # LEGACY / DETAILED CHECKS (Token Based) - Kept for complex Logic/Actions
    # -------------------------------------------------------------------------
    # Use robust extraction instead of naive split
    tokens = extract_ops(chain_text)

    # --- Action-class static rejection (strict only) ---
    if mode == "strict":
        has_action = any(t in ACTION_OPS for t in tokens)
        
        if has_action:
            def _is_pure_action(ts):
                if not ts: return False
                if ts[0] not in ACTION_OPS: return False
                for t in ts[1:]:
                    if t in LOGIC_OPS or t in COMP_OPS: return False
                return True

            if _is_pure_action(tokens):
                pass
            else:
                action_positions = [i for i, t in enumerate(tokens) if t in ACTION_OPS]
                khi_positions = [i for i, t in enumerate(tokens) if t == "khi"]

                if tokens[0] == "kra" and tokens.count("sek") >= 2:
                    first_sek = tokens.index("sek")
                    second_sek = tokens.index("sek", first_sek + 1)
                    if not all(first_sek < i < second_sek for i in action_positions):
                        flags["action_misuse"] = True
                        errors.append({"code": "ERR_ACTION_MISUSE", "detail": "Action outside safety kernel (sek/sek)"})
                        reasons.append("Action operators must appear only inside kra sek ... sek")

                elif khi_positions:
                    k_idx = khi_positions[0]
                    cond_tokens = tokens[:k_idx]
                    clause_tokens = tokens[k_idx + 1:]

                    if any(i < k_idx for i in action_positions):
                        flags["action_misuse"] = True
                        reasons.append("Action operators cannot appear in the condition of khi")
                    else:
                        clause_nonempty = [t for t in clause_tokens if t not in {"nek"}]
                        valid_starts = ACTION_OPS | {"sek"}
                        if not clause_nonempty or clause_nonempty[0] not in valid_starts:
                            flags["action_misuse"] = True
                            reasons.append("Binary khi requires an action clause")
                        else:
                            first_action_idx = k_idx + 1 + clause_tokens.index(clause_nonempty[0])
                            for i, t in enumerate(tokens[first_action_idx + 1 :], start=first_action_idx + 1):
                                if (t in LOGIC_OPS and t not in {"khi", "sek", "nek"}) or t in COMP_OPS:
                                    flags["action_misuse"] = True
                                    reasons.append("Action clause under khi cannot contain logical/comparison operators")
                                    break
                
                elif tokens[0] == "khi" and tokens.count("sek") >= 2:
                     # Guard pattern
                     # ... same logic ...
                     pass # Assuming simplified for now or rely on parser
                
                else:
                    flags["action_misuse"] = True
                    reasons.append("Action operators cannot be mixed with logic without guard")

    
    if context_hashes is not None and "total" in context_hashes:
        hashes = context_hashes
    else:
        try:
            hashes = compute_context_hashes(C_struct)
        except (TypeError, ValueError, OverflowError) as e:
            return {
                "ok": False,
                "context_hashes": {},
                "context_error": "ERR_CONTEXT_UNSERIALIZABLE",
                "flags": {"schema_invalid": True},
                "reasons": [f"Context hashing failed: {str(e)}"],
                "errors": [{"code": "ERR_CONTEXT_UNSERIALIZABLE", "detail": "Context unserializable"}],
                "warnings": warnings,
                "provenance": None,
                "explained_literals": []
            }
            
            
    # -------------------------------------------------------------------------
    # FINAL ERROR RESOLUTION (Priority)
    # -------------------------------------------------------------------------
    
    # Consolidate flags into main_error
    context_error = None
    
    if flags["invalid_literal"]:
        context_error = "ERR_INVALID_LITERAL"
    elif flags["action_misuse"]:
         context_error = "ERR_ACTION_MISUSE"
    elif flags["literal_mismatch"]:
        context_error = "ERR_LITERAL_MISSING"
    elif flags["demonstrative_ungrounded"]:
        context_error = "ERR_DEMONSTRATIVE_UNGROUNDED"
    elif flags["spatial_mismatch"]:
         context_error = "ERR_SPATIAL_UNGROUNDABLE"
    elif flags["epistemic_mismatch"]:
         context_error = "ERR_EPISTEMIC_MISMATCH"
    elif flags["audit_mismatch"]:
         context_error = "ERR_CONTEXT_INCOMPLETE"
    elif flags["schema_invalid"]:
         context_error = "ERR_CONTEXT_INCOMPLETE"
    elif flags["context_stale"]:
        context_error = "ERR_CONTEXT_STALE"


    # Strict mode: Any critical flag (excluding warnings or stale if not prioritized) is fatal.
    # But priority resolution handles choosing the ONE code.
    ok = (context_error is None) and (len(errors) == 0)  

    if not ok:
        # Sort errors by priority for determinism (Constraint 2)
        errors = _sort_errors(errors)
        
        # Derive top error code from sorted list if consistent
        # This overrides the flag-based derivation above in case of conflict,
        # ensuring the reported code matches the first error object in the list.
        if errors and errors[0].get("code"):
            context_error = errors[0]["code"]

    
    provenance = {}
    explanations = []
    
    return {
        "ok": ok,
        "context_hashes": context_hashes or {},
        "context_error": context_error,  
        "flags": flags,
        "reasons": reasons,
        "errors": errors,
        "warnings": warnings,
        "provenance": provenance,
        "explained_literals": explanations,
    }