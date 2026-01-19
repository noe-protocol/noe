"""
context_projection.py - Safe Context Projection (π_safe)

NIP-009 Reference Implementation: Epistemic Context Projection

The 2-Stage Pipeline:
    1. C_rich = merge(C_root, C_domain, C_local)  # Raw annotated evidence
    2. C_safe = π_safe(C_rich, config)            # Conservative safety projection

π_safe applies epistemic thresholds to filter uncertain evidence, producing
a deterministic safety context for runtime evaluation.

Key Invariants:
- **K3 Semantics**: Preserves Strong Kleene (K3) undefined propagation
- **No Fabrication**: Never invents context; only filters existing evidence
- **Deterministic**: Same (C_rich, config) → same C_safe
- **Conservative**: When uncertain, omits literals (undefined > false assumption)

All Noe evaluation operates on C_safe ONLY (never raw C_rich).
"""

from typing import List, Dict, Any, Optional, Tuple, Set, Union
from dataclasses import dataclass, field
import time
import os
import math

# Debug flag
_DEBUG_ENABLED = os.getenv("NOE_DEBUG", "0") == "1"

def _debug_print(*args, **kwargs):
    if _DEBUG_ENABLED:
        print(*args, **kwargs)

# --- CONFIGURATION ---
# Clock skew tolerance for timestamp validation
MAX_CLOCK_SKEW_MS = 200  # Reject timestamps >200ms in the future

# Epistemic thresholds (used by validator for modal fact checking)
EPISTEMIC_THRESHOLDS = {
    "shi": 0.90,  # Knowledge threshold
    "vek": 0.40,  # Belief threshold
}

# --- Data Structures ---

@dataclass(frozen=True)
class AnnotatedLiteral:
    """
    An element of C_rich: a fact with provenance and uncertainty.
    
    NOTE: timestamp is UNIX milliseconds (int) for NIP-009 alignment.
    """
    predicate: str
    value: Any
    timestamp: int  # UNIX milliseconds
    source: str
    confidence: float
    meta: Dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class BareLiteral:
    """
    An element of C_safe: a trusted fact for deterministic evaluation.
    """
    predicate: str
    value: Any

@dataclass
class ProjectionConfig:
    """
    Configuration for the safety projection.
    
    All time values in MILLISECONDS for NIP-009 alignment.
    """
    tau_stale_ms: int = 1000       # Max age in milliseconds before a literal is stale
    theta_thresh: float = 0.8      # Min confidence to be a candidate
    tau_window_ms: int = 100       # Time window (ms) for conflict resolution (simultaneity)
    # Note: min_quorum removed from v1.0 (deferred to v1.1)

# --- Core Logic ---

def is_candidate(l: AnnotatedLiteral, config: ProjectionConfig, now_ms: int, auth_map: Optional[Dict[str, Set[str]]] = None) -> bool:
    """
    Determines if an annotated literal is a candidate for C_safe.
    Checks freshness, confidence, and authority.
    
    Args:
        now_ms: Current time in UNIX milliseconds
    """
    # 1. Freshness
    age_ms = now_ms - l.timestamp
    
    # Reject future timestamps (clock skew protection)
    if age_ms < -MAX_CLOCK_SKEW_MS:
        return False  # Timestamp too far in future
    
    if age_ms > config.tau_stale_ms:
        return False  # Too old
    
    # 2. Confidence
    import math
    if not isinstance(l.confidence, (int, float)) or not math.isfinite(l.confidence):
        return False
        
    if l.confidence < config.theta_thresh:
        return False
        
    # 3. Authority: Enforce source allow-lists if auth_map is active.
    if auth_map is not None:
        allowed_sources = auth_map.get(l.predicate)
        if allowed_sources is not None:
            if l.source not in allowed_sources:
                return False
            
    return True


# --- Compiled Path Helpers ---
CompiledContextPath = Tuple[str, ...]

def compile_path(path: str) -> CompiledContextPath:
    """
    Compiles a dot-separated path string into a tuple of keys for faster lookup.
    Example: "C_local.position.x" -> ("local", "position", "x")
    """
    # Handle explicit layer prefixes by stripping them and using the standard key
    if path.startswith("C_root."):
        return ("root",) + tuple(path[7:].split("."))
    if path.startswith("C_domain."):
        return ("domain",) + tuple(path[9:].split("."))
    if path.startswith("C_local."):
        return ("local",) + tuple(path[8:].split("."))
    
    # If no prefix, split normally (will be searched in all layers if used with _ctx_has)
    # But for optimization, we prefer explicit paths.
    return tuple(path.split("."))

def _ctx_has(ctx: Dict[str, Any], path: Union[str, CompiledContextPath]) -> bool:
    """
    Check if a path exists in the context.
    Supports both string paths (slow) and compiled tuple paths (fast).
    
    Handles both structured and flat contexts for compiled path lookups.
    """
    # 1. Handle Compiled Path (Fast Path)
    if isinstance(path, tuple):
        # Detect if context is structured or flat
        is_structured = isinstance(ctx, dict) and all(k in ctx for k in ["root", "domain", "local"])
        
        # If compiled path starts with layer name but context is flat, skip first key
        if not is_structured and len(path) > 0 and path[0] in ["root", "domain", "local"]:
            # Retry without layer prefix
            path = path[1:]
        
        curr = ctx
        for p in path:
            if isinstance(curr, dict) and p in curr:
                curr = curr[p]
            else:
                return False
        return True

    # 2. Handle String Path (Slow Path - Legacy/Fallback)
    # Detect if context is structured or flat
    is_structured = isinstance(ctx, dict) and all(k in ctx for k in ["root", "domain", "local"])
    
    # Handle explicit layer prefixes
    if path.startswith("C_root."):
        if is_structured:
            return _ctx_has(ctx["root"], path[7:])
        else:
            # Flat context - check directly
            return _ctx_has(ctx, path[7:])
            
    if path.startswith("C_domain."):
        if is_structured:
            return _ctx_has(ctx["domain"], path[9:])
        else:
            return _ctx_has(ctx, path[9:])
            
    if path.startswith("C_local."):
        if is_structured:
            return _ctx_has(ctx["local"], path[8:])
        else:
            return _ctx_has(ctx, path[8:])

    # Check for structured context (search all layers if no prefix)
    if is_structured:
        if _ctx_has(ctx["local"], path): return True
        if _ctx_has(ctx["domain"], path): return True
        if _ctx_has(ctx["root"], path): return True
        return False

    # Flat context - check directly
    parts = path.split(".")
    curr = ctx
    for p in parts:
        if isinstance(curr, dict) and p in curr:
            curr = curr[p]
        else:
            return False
    return True

def is_explained_literal(pred: str, full_context: Dict[str, Any], 
                         required_context_map: Optional[Dict[str, List[str]]] = None,
                         compiled_requirements: Optional[Dict[str, List[CompiledContextPath]]] = None) -> bool:
    """
    Checks if a literal satisfies its required context paths.
    Uses compiled_requirements if available for speed.
    """
    # Check if predicate is a literal (starts with @)
    if not pred.startswith("@"):
        return True

    # Fast Path: Compiled Requirements
    if compiled_requirements:
        reqs = compiled_requirements.get(pred)
        if not reqs:
            return True
        for path in reqs:
            if not _ctx_has(full_context, path):
                return False
        return True

    # Slow Path: String Requirements
    if required_context_map:
        reqs = required_context_map.get(pred)
        if not reqs:
            return True
        for path in reqs:
            if not _ctx_has(full_context, path):
                return False
        return True
        
    return True

def pi_safe(c_rich: List[AnnotatedLiteral], config: ProjectionConfig, now_ms: int, 
            auth_map: Optional[Dict[str, Set[str]]] = None, 
            with_explanations: bool = False, 
            explainable_predicates: Optional[Set[str]] = None,
            full_context: Optional[Dict[str, Any]] = None,
            required_context_map: Optional[Dict[str, List[str]]] = None,
            independence_groups: Optional[Dict[str, str]] = None,
            compiled_requirements: Optional[Dict[str, List[CompiledContextPath]]] = None):
    """
    The Safe Projection Function (pi_safe).
    
    Projects C_rich -> C_safe by:
    1. Filtering candidates (Freshness, Confidence, Authority).
    2. Resolving conflicts via Timestamp Resolution and Mutual Exclusion.
    3. Enforcing Explained Literal Gate (required_context).
    4. Enforcing Independence Group Quorum (deterministic fusion).
    
    Logic:
    - Group candidates by predicate.
    - For each predicate, identify the "Leading Edge" of evidence (newest timestamp).
    - Collect all candidates within 'tau_window' of the leading edge.
    - If all candidates in the leading edge agree on the value, promote to C_safe.
    - If there is disagreement (conflict) in the leading edge, suppress (return nothing for this predicate).

    Returns:
        If with_explanations is False: List[BareLiteral]
        If with_explanations is True: (List[BareLiteral], Dict[str, Any])
    """
    # 1. Filter Candidates
    candidates = [l for l in c_rich if is_candidate(l, config, now_ms, auth_map)]
    _debug_print(f"DEBUG pi_safe: now={now_ms}, candidates={len(candidates)}")
    if candidates:
        _debug_print(f"DEBUG pi_safe candidate[0]: {candidates[0]}")
    
    # 2. Group by Predicate
    by_pred: Dict[str, List[AnnotatedLiteral]] = {}
    for c in candidates:
        if c.predicate not in by_pred:
            by_pred[c.predicate] = []
        by_pred[c.predicate].append(c)
        
    safe_literals: List[BareLiteral] = []
    explanations: Dict[str, Any] = {}
    
    for pred, items in by_pred.items():
        if not items:
            continue
            
        # --- Explained Literal Gate ---
        if full_context is not None:
            # Use compiled requirements if available, else fall back to map
            if not is_explained_literal(pred, full_context, required_context_map, compiled_requirements):
                # Missing required context -> Suppress
                _debug_print(f"DEBUG: Suppressed {pred} due to missing context")
                continue

        # 3. Find Leading Edge
        # Sort descending by timestamp
        items.sort(key=lambda x: x.timestamp, reverse=True)
        
        newest = items[0]
        max_t = newest.timestamp
        
        # 4. Check Consistency in Leading Window
        # Gather all candidates that are "simultaneous" with the newest observation
        leading_edge = [
            item for item in items 
            if (max_t - item.timestamp) <= config.tau_window_ms
        ]
        
        # --- Independence Group Quorum ---
        # Group readings by independence group and check for consensus
        
        # For unhashable values (dict/list), we need to:
        # 1. Canonicalize for equality checking
        # 2. But promote the ORIGINAL value (not the canonicalized string)
        
        # Track both canonical forms (for comparison) and original values
        groups: Dict[str, Set[Any]] = {}  # group_id -> set of keys (type, value) or hash string
        value_map: Dict[Any, Any] = {}  # key -> original value
        
        import json
        
        for item in leading_edge:
            group_id = item.source
            if independence_groups:
                group_id = independence_groups.get(item.source, item.source)
            
            if group_id not in groups:
                groups[group_id] = set()
            
            # Canonicalize value for equality checking
            # V1.0 HARDENING:
            # 1. Use typed tuple for hashables: (type_name, value) to prevent True==1
            # 2. Prevent NaN float values (break equality assumptions)
            # 3. Canonical JSON for unhashables (ensure_ascii=True, allow_nan=False)
            
            group_key = None
            
            try:
                # Try hashable first (fast path)
                hash(item.value)
                
                # Check for NaN float
                if isinstance(item.value, float) and math.isnan(item.value):
                     # Reject NaN values entirely as they break consensus
                     _debug_print(f"DEBUG: Skipping NaN value for {item.predicate}")
                     continue

                # Use Typed Key to distinguish 1 from True
                group_key = (type(item.value).__name__, item.value)
                
            except TypeError:
                # Not hashable - canonicalize as JSON then HASH it
                try:
                    # Explicit deterministic settings
                    canonical_json = json.dumps(
                        item.value, 
                        sort_keys=True, 
                        separators=(',', ':'),
                        ensure_ascii=True,
                        allow_nan=False  # Strict rejection of NaN/Infinity
                    )
                    # Use hash of JSON to avoid storing giant strings in set
                    import hashlib
                    group_key = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
                except (TypeError, ValueError):
                    # Not JSON-serializable (sets, bytes, custom objects) - skip
                    _debug_print(f"DEBUG: Skipping non-serializable value: {type(item.value)}")
                    continue
            
            # Use 'group_key' for consensus check, map back to 'item.value' for result
            groups[group_id].add(group_key)
            value_map[group_key] = item.value
        
        # Check for conflicts across groups AND within groups
        consistent = True
        ref_key = None
        
        for group_id, keys in groups.items():
            if len(keys) > 1:
                consistent = False  # Internal conflict
                break
            
            key = list(keys)[0] if keys else None
            # key can be None? No, we added to set. But set could be empty if continue hit? 
            # groups[group_id] initialized to set(), added to only if skipping logic didn't hit.
            if not keys:
                continue
                
            if ref_key is None:
                ref_key = key
            elif key != ref_key:
                consistent = False  # External conflict
                break
        
        if consistent and ref_key is not None:
            # Promote ORIGINAL value, not canonical string
            ref_value = value_map[ref_key]
            
            # No conflict in the leading window -> Promote
            safe_literals.append(BareLiteral(pred, ref_value))
            
            if with_explanations:
                # Check if explanation is required for this predicate
                should_explain = True
                if explainable_predicates is not None:
                    should_explain = pred in explainable_predicates
                
                if should_explain:
                    # Construct explanation record
                    explanations[pred] = {
                        "literal": pred,
                        "value": ref_value,
                        "evidence": [
                            {
                                "sensor": item.source,
                                "reading": item.meta.get("reading", str(item.value)),
                                "t": item.timestamp,
                                "confidence": item.confidence,
                                "group": independence_groups.get(item.source, item.source) if independence_groups else item.source
                            }
                            for item in leading_edge
                        ],
                        "projection": "pi_safe",
                        "reason": f"consensus across {len(groups)} independent groups",
                        "thresholds": {
                            "freshness_ms": config.tau_stale_ms,
                            "window_ms": config.tau_window_ms
                        }
                    }
        else:
            # Conflict detected -> Suppress (Conservative Safety)
            pass
            
    if with_explanations:
        return safe_literals, explanations
    return safe_literals


def extract_evidence_from_context(C_rich: Dict[str, Any]) -> List[AnnotatedLiteral]:
    """
    Helper to extract annotated evidence from a structured or flat context.
    
    Merge evidence lists per predicate (extend), don't overwrite.
    """
    evidence_map: Dict[str, List[Dict[str, Any]]] = {}
    
    if "root" in C_rich and "domain" in C_rich and "local" in C_rich:
        # Structured context: merge evidence from all layers
        for layer in ["root", "domain", "local"]:
            layer_evidence = C_rich[layer].get("evidence", {})
            if isinstance(layer_evidence, dict):
                # Extend lists per predicate, don't overwrite
                for pred, entries in layer_evidence.items():
                    if pred not in evidence_map:
                        evidence_map[pred] = []
                    if isinstance(entries, list):
                        evidence_map[pred].extend(entries)
    else:
        # Flat context
        evidence_map = C_rich.get("evidence", {})

    if not evidence_map:
        return []
        
    annotated_list = []
    for pred, entries in evidence_map.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict): continue
            
            # Reject evidence if timestamp or confidence missing/invalid (safety requirement)
            timestamp = entry.get("timestamp")
            confidence = entry.get("confidence")
            
            if timestamp is None or confidence is None:
                continue  # Drop invalid evidence - NO FABRICATION
            
            try:
                timestamp_int = int(timestamp)
                confidence_float = float(confidence)
                
                # Validate confidence is finite
                if not math.isfinite(confidence_float):
                    continue
                
                l = AnnotatedLiteral(
                    predicate=pred,
                    value=entry.get("value"),
                    timestamp=timestamp_int,
                    source=entry.get("source", "unknown"),
                    confidence=confidence_float,
                    meta=entry.get("meta", {})
                )
                annotated_list.append(l)
            except (ValueError, TypeError):
                continue
    return annotated_list


# --- Epistemic Projection (REMOVED in v1.0) ---
#
# project_epistemic() removed due to output contract mismatch:
# - pi_safe returns List[BareLiteral] (no confidence field)
# - project_epistemic expected literals[k]["confidence"]
# - These cannot both be true
#
# Epistemic modal sets (knowledge/belief) should be constructed by the runtime
# BEFORE calling pi_safe, not after.
#
# For v1.1: Re-introduce if needed, but align with pi_safe's BareLiteral output.
