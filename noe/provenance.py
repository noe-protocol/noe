"""
provenance.py

Noe Provenance v1.0
-------------------

Defines a canonical provenance record and hashing scheme for Noe actions.

Features:
    - Canonical chain normalization (spacing + Unicode NFKC).
    - Stable SHA-256 hashes for chain, AST, and action provenance.
    - Explicit parent_action_hash for action DAGs.
    - JSON-serializable ProvenanceRecord for audit and certificates.
"""

from __future__ import annotations

import hashlib
import json
import time
import os
from pathlib import Path

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple
from noe.canonical import canonical_json, canonicalize_chain

# Semantics version (NIP-005 K3 logic + operator definitions)
SEMANTICS_VERSION = "NIP-005-v1.0"

def compute_registry_hash() -> str:
    """
    Compute SHA-256 hash of the operator registry to bind operator semantics.
    Returns empty string if registry.json not found.
    """
    registry_path = Path(__file__).parent / "registry.json"
    if not registry_path.exists():
        return ""
    
    with open(registry_path, 'r') as f:
        registry_data = json.load(f)
    
    # Canonical JSON to ensure deterministic hash
    registry_canonical = canonical_json(registry_data)
    return hashlib.sha256(registry_canonical.encode('utf-8')).hexdigest()


# ==========================================
# 1. HELPERS
# ==========================================






def _sha256_hex(data: str) -> str:
    """Return SHA-256 hex digest of the given string (UTF-8 encoded)."""
    h = hashlib.sha256()
    h.update(data.encode("utf-8"))
    return h.hexdigest()


# canonical_json imported from noe.canonical to ensure consistency


def flatten_action_for_hash(action: Dict[str, Any]) -> str:
    """
    Produce a canonical, hashable representation of an action.

    The goal is that two actions which are semantically identical
    produce identical flattened strings, regardless of Python dict
    ordering or internal representation.

    Standard fields:
      - verb:      action["verb"]            (str)
      - target:    action.get("target")      (literal or None)
      - modifiers: sorted list of modifiers  (list[str])
      - params:    canonical JSON of params  (dict)

    Unknown extra fields are ignored for hashing so that
    implementations can add metadata without breaking determinism.
    """

    verb = action.get("verb")
    target = action.get("target")

    # Modifiers: default to empty list, always sorted to ensure stability.
    modifiers_raw = action.get("modifiers", [])
    if modifiers_raw is None:
        modifiers_raw = []
    if isinstance(modifiers_raw, (set, tuple)):
        modifiers = sorted(list(modifiers_raw))
    else:
        modifiers = sorted(list(modifiers_raw))

    # Params: any extra structured data attached to the action.
    params_raw = action.get("params", {})
    if params_raw is None:
        params_raw = {}

    # Canonical structure that we actually hash.
    canonical_struct: List[Tuple[str, Any]] = [
        ("verb", verb),
        ("target", target),
        ("modifiers", modifiers),
        ("params", params_raw),
    ]

    return canonical_json(canonical_struct)


def compute_action_hash(action: Dict[str, Any]) -> str:
    """
    Compute the canonical SHA256 hash of a single action structure.
    (Matches noe_parser expectation).
    """
    flattened = flatten_action_for_hash(action).encode("utf-8")
    return hashlib.sha256(flattened).hexdigest()

# Alias for internal clarity if needed
compute_action_structure_hash = compute_action_hash


def compute_action_lineage_hashes(
    actions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Given a list of action objects, compute structure hashes.
    (Updated to use compute_action_structure_hash).
    """
    parent_action_hash: Optional[str] = None
    enriched: List[Dict[str, Any]] = []

    for action in actions:
        # Make a shallow copy so we do not mutate the original dicts.
        a = dict(action)

        a_hash = compute_action_structure_hash(a)

        if parent_action_hash is None:
            child_hash = None
        else:
            h = hashlib.sha256()
            h.update(parent_action_hash.encode("utf-8"))
            h.update(a_hash.encode("utf-8"))
            child_hash = h.hexdigest()

        a["action_hash"] = a_hash
        a["child_action_hash"] = child_hash

        enriched.append(a)
        parent_action_hash = a_hash

    return enriched


# ==========================================
# 3. NEW PROVENANCE HASHING (NIP-010/014)
# ==========================================

def compute_execution_request_hash(chain_str: str,
                                   h_total: str,
                                   domain_pack_hash: str) -> str:
    """
    (Renamed from compute_action_hash to avoid conflict).
    (Renamed from compute_action_hash to avoid conflict).
    Computes hash of the REQUEST to execute a chain.
    """
    if chain_str != canonicalize_chain(chain_str):
        raise ValueError("ERR_CHAIN_NOT_CANONICAL: Input must be already canonicalized.")
    chain_norm = chain_str
    
    # CHANGED: Use JSON structure instead of raw concatenation
    payload_list = [
        "noe.action.v1",
        chain_norm,
        h_total,
        domain_pack_hash
    ]
    payload = canonical_json(payload_list).encode("utf-8")
    
    return hashlib.sha256(payload).hexdigest()


def compute_decision_hash(chain_str: str,
                          h_total: str,
                          domain_pack_hash: str) -> str:
    """
    Compute hash of a non-action DECISION (truth, numeric, etc).
    Prefix: noe.decision.v1
    """
    if chain_str != canonicalize_chain(chain_str):
        raise ValueError("ERR_CHAIN_NOT_CANONICAL: Input must be already canonicalized.")

    payload_list = [
        "noe.decision.v1",
        chain_str,
        h_total,
        domain_pack_hash
    ]
    payload = canonical_json(payload_list).encode("utf-8")
    
    return hashlib.sha256(payload).hexdigest()

def compute_child_action_hash(parent_action_hash: str,
                              chain_str: str,
                              h_total: str,
                              domain_pack_hash: str) -> str:
    """
    Compute the canonical Child Action Hash.
    
    Formula:
        child_action_hash = H("noe.child_action.v1" || parent_action_hash || chain_str || H_total || H_domain_pack)
    """
    if chain_str != canonicalize_chain(chain_str):
        raise ValueError("ERR_CHAIN_NOT_CANONICAL: Input must be already canonicalized.")
    chain_norm = chain_str
    
    payload_list = [
        "noe.child_action.v1",
        parent_action_hash,
        chain_norm,
        h_total,
        domain_pack_hash
    ]
    payload = canonical_json(payload_list).encode("utf-8")
    
    return hashlib.sha256(payload).hexdigest()


# ==========================================
# 2. DATA STRUCTURES
# ==========================================


@dataclass
class ProvenanceResult:
    """
    Result payload stored inside a provenance record.

    Args:
        domain: truth | numeric | action | list | undefined | error
        value: Underlying Python value (must be JSON-serializable).
    """
    domain: str
    value: Any


@dataclass
class ProvenanceRecord:
    """
    Canonical provenance record for a single Noe chain evaluation.

    Anti-Axiom Security (v1.0):
        - registry_hash: Binds operator semantics (prevents silent redefinition)
        - semantics_version: Binds K3 logic version (NIP-005)
        - runtime_mode: Records strict/lenient execution context
        - context_snapshot: Full C_safe for deterministic replay (optional)

    Attributes:
        version: Provenance schema version.
        chain: Canonicalized Noe chain string.
        chain_hash: SHA-256 hash of canonical chain.
        ast_repr: Human-readable AST representation (optional).
        ast_hash: SHA-256 hash of ast_repr (or zeros).
        context_hash: Hash of the Context snapshot.
        context_snapshot: Full context dict (C_safe) for replay (optional).
        result: Evaluation outcome (domain + value).
        epistemic_basis: List of literal keys justifying the action.
        value_system_basis: List of normative policy IDs justifying the action.
        parent_action_hash: Hash of parent action (if applicable).
        provenance_hash: Unique SHA-256 identifier for this provenance record.
        created_ts_ms: Creation timestamp (UTC ms).
        registry_hash: SHA-256 hash of operator registry (reproducibility).
        semantics_version: NIP version identifier (e.g., "NIP-005-v1.0").
        runtime_mode: Execution mode ("strict" or "lenient").
    """
    version: str
    chain: str
    chain_hash: str
    ast_repr: Optional[str]
    ast_hash: str
    context_hash: str
    result: ProvenanceResult
    epistemic_basis: List[str]
    value_system_basis: List[str]
    parent_action_hash: Optional[str]
    provenance_hash: Optional[str]
    created_ts_ms: int

    # Anti-Axiom Security (v1.0)
    registry_hash: str = ""
    semantics_version: str = SEMANTICS_VERSION
    runtime_mode: str = "strict"
    context_snapshot: Optional[Dict[str, Any]] = None

    explained_literals: Optional[Dict[str, Any]] = None
    # v1.0 Hash Fields
    action_hash: Optional[str] = None
    child_action_hash: Optional[str] = None
    decision_hash: Optional[str] = None
    domain_pack_hash: Optional[str] = None

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------

    def to_json_dict(self) -> Dict[str, Any]:
        """
        Convert to a JSON-serializable dict.

        Note: this is stable but not used for hashing directly; the hashing
        uses a canonical internal dict (see build_provenance_record).
        """
        # asdict handles nested dataclasses
        return asdict(self)

    def to_json_str(self) -> str:
        """Serialize the record as a canonical JSON string."""
        return canonical_json(self.to_json_dict())

    @staticmethod
    def from_json_dict(data: Dict[str, Any]) -> "ProvenanceRecord":
        """Reconstruct a ProvenanceRecord from a dict."""
        result = data.get("result", {})
        prov_result = ProvenanceResult(
            domain=result.get("domain", "undefined"),
            value=result.get("value", None),
        )

        return ProvenanceRecord(
            version=data.get("version", "noe-prov-v1"),
            chain=data.get("chain", ""),
            chain_hash=data.get("chain_hash", ""),
            ast_repr=data.get("ast_repr"),
            ast_hash=data.get("ast_hash", ""),
            context_hash=data.get("context_hash", ""),
            result=prov_result,
            epistemic_basis=list(data.get("epistemic_basis", [])),
            value_system_basis=list(data.get("value_system_basis", [])),
            parent_action_hash=data.get("parent_action_hash"),
            provenance_hash=data.get("provenance_hash"),
            created_ts_ms=int(data.get("created_ts_ms", 0)),

            explained_literals=data.get("explained_literals"),
            action_hash=data.get("action_hash"),
            child_action_hash=data.get("child_action_hash"),
            decision_hash=data.get("decision_hash"),
            domain_pack_hash=data.get("domain_pack_hash"),
        )

    @staticmethod
    def from_json_str(s: str) -> "ProvenanceRecord":
        """Reconstruct a ProvenanceRecord from a JSON string."""
        data = json.loads(s)
        return ProvenanceRecord.from_json_dict(data)


# ==========================================
# 3. PROVENANCE BUILDER
# ==========================================


def build_provenance_record(
    *,
    chain: str,
    ast_repr: Optional[str],
    context_hash: str,
    result_domain: str,
    result_value: Any,
    epistemic_basis: Optional[List[str]] = None,
    value_system_basis: Optional[List[str]] = None,
    parent_action_hash: Optional[str] = None,
    version: str = "noe-prov-v1",
    created_ts_ms: Optional[int] = None,
    explained_literals: Optional[Dict[str, Any]] = None,
    # v1.0 Hash Args
    action_hash: Optional[str] = None,
    child_action_hash: Optional[str] = None,
    decision_hash: Optional[str] = None,
    domain_pack_hash: Optional[str] = None,
    # Anti-Axiom Security (v1.0)
    runtime_mode: str = "strict",
) -> ProvenanceRecord:
    """
    Build a ProvenanceRecord and compute its provenance_hash.

    Hashing scheme (canonical):
        provenance_hash = SHA256(JSON({
            "version": ..., "chain_hash": ..., "ast_hash": ...,
            "context_hash": ..., "result": ..., "epistemic_basis": ...,
            "value_system_basis": ..., "parent_action_hash": ...
        }))

    Ensures deterministic JSON serialization (sorted keys, minimal separators).
    """

    # 1. Canonical chain + chain_hash
    chain_canonical = canonicalize_chain(chain)
    chain_hash = _sha256_hex(chain_canonical)

    # 2. AST hashing
    if ast_repr is None:
        ast_hash = "0" * 64
    else:
        ast_hash = _sha256_hex(str(ast_repr))

    # 3. Normalize bases
    ep_basis = sorted(set(epistemic_basis or []))
    vs_basis = sorted(set(value_system_basis or []))

    # 4. Normalize result as a dict for hashing
    result_payload = {
        "domain": result_domain,
        "value": result_value,
    }

    # v1.0 Integrity Enforcement: Action vs Decision vs Blocked
    is_action = (result_domain == "action")
    is_blocked = (result_domain in ("error", "undefined"))

    if is_blocked:
        # Blocked paths must assume NO identity
        action_hash = None
        child_action_hash = None
        decision_hash = None
    elif not is_action:
        # Decision (Truth/Numeric/etc) -> No action hashes
        action_hash = None
        child_action_hash = None
    else:
        # Action -> No decision hash
        decision_hash = None

    # 5. Canonical hash payload
    hash_payload = {
        "version": version,
        "chain_hash": chain_hash,
        "ast_hash": ast_hash,
        "context_hash": context_hash,
        "result": result_payload,
        "epistemic_basis": ep_basis,
        "value_system_basis": vs_basis,
        "parent_action_hash": parent_action_hash,
    }
    
    # v1.0: conditionally include action/decision hashes
    if action_hash:
        hash_payload["action_hash"] = action_hash
    if child_action_hash:
         hash_payload["child_action_hash"] = child_action_hash
    if decision_hash:
         hash_payload["decision_hash"] = decision_hash
    if domain_pack_hash:
         hash_payload["domain_pack_hash"] = domain_pack_hash

    hash_payload_json = canonical_json(hash_payload)
    prov_hash = _sha256_hex(hash_payload_json)

    # 6. Timestamp
    if created_ts_ms is None:
        created_ts_ms = int(time.time() * 1000)

    # 7. Build ProvenanceRecord
    # USER RULE: Blocked paths (error/undefined) must NOT look like execution.
    # explicit null provenance_hash.
    final_prov_hash = prov_hash
    if result_domain in ("error", "undefined"):
        final_prov_hash = None

    prov = ProvenanceRecord(
        version=version,
        chain=chain_canonical,
        chain_hash=chain_hash,
        ast_repr=ast_repr,
        ast_hash=ast_hash,
        context_hash=context_hash,
        result=ProvenanceResult(domain=result_domain, value=result_value),
        epistemic_basis=ep_basis,
        value_system_basis=vs_basis,
        parent_action_hash=parent_action_hash,
        provenance_hash=final_prov_hash,
        created_ts_ms=created_ts_ms,
        # Anti-Axiom Security (v1.0)
        registry_hash=compute_registry_hash(),
        semantics_version=SEMANTICS_VERSION,
        runtime_mode=runtime_mode,
        # v1.0 Hash Fields
        explained_literals=explained_literals,
        action_hash=action_hash,
        child_action_hash=child_action_hash,
        decision_hash=decision_hash,
        domain_pack_hash=domain_pack_hash,
    )
    return prov