"""
noe/agent.py

Noe Multi-Agent Context Negotiation Protocol (NIP-019)
------------------------------------------------------

Implements:
    - Agent Identity (AID) structure
    - Negotiated Context Frame (NCF) construction
    - Three-phase handshake: Announce → Match → Bind
    - Session lifecycle management
    - Cross-agent operator and subsystem negotiation

Design principles (NIP-019 §1.1):
    1. Safety preservation: all NIP-009 §4.10 guarantees maintained
    2. Fail-closed: negotiation failure → undefined (V1.0 default)
    3. Hash-based alignment: compare canonical hashes, never raw JSON
    4. Minimal trust: verify capabilities against registry hashes
    5. Composable: pairwise sessions, N-party from pairwise
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Set, Tuple
from enum import Enum

from .canonical import canonical_json
from .provenance import compute_registry_hash, SEMANTICS_VERSION


# =========================================================================
# Error Codes (NIP-019 §4.7)
# =========================================================================

class NegotiationError(Exception):
    """Base class for multi-agent negotiation errors."""
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


# Error code constants
ERR_REGISTRY_MISMATCH    = "ERR_REGISTRY_MISMATCH"
ERR_SEMANTICS_MISMATCH   = "ERR_SEMANTICS_MISMATCH"
ERR_NO_SHARED_OPERATORS  = "ERR_NO_SHARED_OPERATORS"
ERR_NO_SHARED_SUBSYSTEMS = "ERR_NO_SHARED_SUBSYSTEMS"
ERR_NCF_MISMATCH         = "ERR_NCF_MISMATCH"
ERR_SESSION_EXPIRED      = "ERR_SESSION_EXPIRED"
ERR_OPERATOR_NOT_IN_NCF  = "ERR_OPERATOR_NOT_IN_NCF"
ERR_AGENT_UNREACHABLE    = "ERR_AGENT_UNREACHABLE"
ERR_PROVENANCE_INVALID   = "ERR_PROVENANCE_INVALID"
ERR_TEMPORAL_VIOLATION   = "ERR_TEMPORAL_VIOLATION"


# =========================================================================
# Compatibility Classes (NIP-019 §4.2.2 Step 5)
# =========================================================================

class CompatibilityClass(str, Enum):
    FULL    = "full"
    PARTIAL = "partial"
    NONE    = "none"


class SubsystemCompat(str, Enum):
    SHARED    = "shared"
    ONE_SIDED = "one-sided"
    ABSENT    = "absent"


# =========================================================================
# Context Subsystem Names
# =========================================================================

SUBSYSTEM_NAMES = frozenset({
    "delivery", "integrity", "audit", "modal", "temporal", "spatial"
})


# =========================================================================
# Agent Identity (NIP-019 §4.1)
# =========================================================================

@dataclass
class TemporalConfig:
    """Agent temporal configuration parameters."""
    max_skew_ms: int = 200
    tau_stale_ms: int = 1000
    tau_window_ms: int = 100


@dataclass
class AgentIdentity:
    """
    Agent Identity (AID) — NIP-019 §4.1.

    Every agent participating in cross-agent communication MUST maintain
    an AID. The AID declares the agent's capabilities and configuration.
    """
    agent_id: str
    registry_hash: str
    semantics_version: str
    runtime_mode: str
    supported_operators: List[str]
    context_subsystems: Dict[str, bool]
    temporal_config: TemporalConfig
    domain_packs: List[str] = field(default_factory=list)
    protocol_version: str = "NIP-019-v1.0"

    def __post_init__(self):
        if not self.agent_id:
            raise ValueError("agent_id MUST be non-empty")
        if not self.registry_hash:
            raise ValueError("registry_hash MUST be non-empty")
        if not self.semantics_version:
            raise ValueError("semantics_version MUST be non-empty")
        # Validate subsystem keys
        for key in self.context_subsystems:
            if key not in SUBSYSTEM_NAMES:
                raise ValueError(f"Unknown subsystem: {key}")

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        return {
            "agent_id": self.agent_id,
            "registry_hash": self.registry_hash,
            "semantics_version": self.semantics_version,
            "runtime_mode": self.runtime_mode,
            "supported_operators": sorted(self.supported_operators),
            "context_subsystems": self.context_subsystems,
            "temporal_config": {
                "max_skew_ms": self.temporal_config.max_skew_ms,
                "tau_stale_ms": self.temporal_config.tau_stale_ms,
                "tau_window_ms": self.temporal_config.tau_window_ms,
            },
            "domain_packs": sorted(self.domain_packs),
            "protocol_version": self.protocol_version,
        }


def build_agent_identity(
    agent_id: str,
    *,
    registry_hash: Optional[str] = None,
    semantics_version: str = SEMANTICS_VERSION,
    runtime_mode: str = "strict",
    supported_operators: Optional[List[str]] = None,
    context_subsystems: Optional[Dict[str, bool]] = None,
    temporal_config: Optional[TemporalConfig] = None,
    domain_packs: Optional[List[str]] = None,
) -> AgentIdentity:
    """
    Build an AgentIdentity, deriving registry_hash and operator list
    from the local registry if not provided.
    """
    if registry_hash is None:
        registry_hash = compute_registry_hash()
        if not registry_hash:
            raise ValueError("Cannot compute registry_hash: registry.json not found")

    if supported_operators is None:
        supported_operators = _load_operator_list()

    if context_subsystems is None:
        context_subsystems = {
            "delivery": True,
            "integrity": True,
            "audit": True,
            "modal": True,
            "temporal": True,
            "spatial": False,
        }

    if temporal_config is None:
        temporal_config = TemporalConfig()

    return AgentIdentity(
        agent_id=agent_id,
        registry_hash=registry_hash,
        semantics_version=semantics_version,
        runtime_mode=runtime_mode,
        supported_operators=supported_operators,
        context_subsystems=context_subsystems,
        temporal_config=temporal_config,
        domain_packs=domain_packs or [],
    )


def _load_operator_list() -> List[str]:
    """Load supported operator phonetic forms from registry.json."""
    from pathlib import Path
    registry_path = Path(__file__).parent / "registry.json"
    if not registry_path.exists():
        return []
    with open(registry_path, "r") as f:
        data = json.load(f)
    ops = []
    for entry in data.get("glyphs", []):
        phonetic = entry.get("phonetic", "")
        if phonetic:
            ops.append(phonetic)
    return sorted(set(ops))


# =========================================================================
# Match Result (NIP-019 §4.2.2)
# =========================================================================

@dataclass
class MatchResult:
    """Result of the Match phase (NIP-019 §4.2.2)."""
    compatibility: CompatibilityClass
    shared_operators: List[str]
    subsystem_compat: Dict[str, str]
    error_code: Optional[str] = None
    error_message: Optional[str] = None


# =========================================================================
# Negotiated Context Frame (NIP-019 §4.2.3)
# =========================================================================

@dataclass
class NegotiatedContextFrame:
    """
    Negotiated Context Frame (NCF) — NIP-019 §4.2.3.

    A bilateral agreement between two agents specifying which context
    subsystems are shared, what temporal alignment parameters apply,
    and what provenance linking rules govern the session.

    An NCF is immutable once bound.
    """
    ncf_id: str
    session_start_ms: int
    agents: List[str]  # [agent_id_A, agent_id_B]
    registry_hash: str
    semantics_version: str
    shared_operators: List[str]
    subsystems: Dict[str, str]
    temporal: Dict[str, int]
    provenance_linking: bool = True

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to canonical dict (excluding ncf_id for hash computation)."""
        return {
            "ncf_id": self.ncf_id,
            "session_start_ms": self.session_start_ms,
            "agents": sorted(self.agents),
            "registry_hash": self.registry_hash,
            "semantics_version": self.semantics_version,
            "shared_operators": sorted(self.shared_operators),
            "subsystems": self.subsystems,
            "temporal": self.temporal,
            "provenance_linking": self.provenance_linking,
        }

    def has_operator(self, operator: str) -> bool:
        """Check if an operator is in the shared set."""
        return operator in self.shared_operators

    def is_subsystem_shared(self, subsystem: str) -> bool:
        """Check if a subsystem is shared between both agents."""
        return self.subsystems.get(subsystem) == SubsystemCompat.SHARED


# =========================================================================
# Session (NIP-019 §4.8)
# =========================================================================

class SessionState(str, Enum):
    ACTIVE     = "active"
    TERMINATED = "terminated"


@dataclass
class Session:
    """
    Active NCF session between two agents (NIP-019 §4.8).

    Tracks session lifecycle: establishment, maintenance, termination.
    """
    ncf: NegotiatedContextFrame
    state: SessionState = SessionState.ACTIVE
    terminated_at_ms: Optional[int] = None

    @property
    def ncf_id(self) -> str:
        return self.ncf.ncf_id

    @property
    def is_active(self) -> bool:
        return self.state == SessionState.ACTIVE

    def terminate(self, timestamp_ms: Optional[int] = None) -> None:
        """Terminate this session (NIP-019 §4.8.3)."""
        self.state = SessionState.TERMINATED
        self.terminated_at_ms = timestamp_ms or _now_ms()

    def validate_operator(self, operator: str) -> None:
        """
        Validate that an operator is in the NCF shared set.
        Raises NegotiationError if not.
        """
        if not self.is_active:
            raise NegotiationError(
                ERR_SESSION_EXPIRED,
                f"Session {self.ncf_id[:16]}... is terminated"
            )
        if not self.ncf.has_operator(operator):
            raise NegotiationError(
                ERR_OPERATOR_NOT_IN_NCF,
                f"Operator '{operator}' not in NCF shared operators"
            )

    def validate_temporal(self, evidence_timestamp_ms: int) -> None:
        """
        Validate evidence timestamp against NCF temporal parameters.
        Raises NegotiationError on violation.
        """
        if not self.is_active:
            raise NegotiationError(
                ERR_SESSION_EXPIRED,
                f"Session {self.ncf_id[:16]}... is terminated"
            )
        now = _now_ms()
        age_ms = now - evidence_timestamp_ms
        max_skew = self.ncf.temporal["max_skew_ms"]
        tau_stale = self.ncf.temporal["tau_stale_ms"]

        # Future evidence beyond skew tolerance
        if age_ms < -max_skew:
            raise NegotiationError(
                ERR_TEMPORAL_VIOLATION,
                f"Evidence timestamp {evidence_timestamp_ms} is {-age_ms}ms in the "
                f"future (max_skew_ms={max_skew})"
            )
        # Stale evidence
        if age_ms > tau_stale:
            raise NegotiationError(
                ERR_TEMPORAL_VIOLATION,
                f"Evidence age {age_ms}ms exceeds tau_stale_ms={tau_stale}"
            )


# =========================================================================
# Three-Phase Handshake (NIP-019 §4.2)
# =========================================================================


def announce(aid: AgentIdentity) -> Dict[str, Any]:
    """
    Phase 1: Announce (NIP-019 §4.2.1).

    Returns the AID as a serializable dict for transmission.
    No trust is established — announcements are claims, not verified facts.
    """
    return aid.to_dict()


def match(aid_a: AgentIdentity, aid_b: AgentIdentity) -> MatchResult:
    """
    Phase 2: Match (NIP-019 §4.2.2).

    Both agents independently compute the Compatibility Class
    by comparing AIDs. This function performs that computation.

    Returns a MatchResult. On failure, the error_code field is set.
    """
    # Step 1: Registry Alignment (hard gate)
    if aid_a.registry_hash != aid_b.registry_hash:
        return MatchResult(
            compatibility=CompatibilityClass.NONE,
            shared_operators=[],
            subsystem_compat={},
            error_code=ERR_REGISTRY_MISMATCH,
            error_message=(
                f"Registry hash mismatch: "
                f"{aid_a.registry_hash[:16]}... != {aid_b.registry_hash[:16]}..."
            ),
        )

    # Step 2: Semantics Version Alignment (hard gate)
    if aid_a.semantics_version != aid_b.semantics_version:
        return MatchResult(
            compatibility=CompatibilityClass.NONE,
            shared_operators=[],
            subsystem_compat={},
            error_code=ERR_SEMANTICS_MISMATCH,
            error_message=(
                f"Semantics version mismatch: "
                f"{aid_a.semantics_version} != {aid_b.semantics_version}"
            ),
        )

    # Step 3: Operator Intersection
    ops_a = set(aid_a.supported_operators)
    ops_b = set(aid_b.supported_operators)
    shared_ops = sorted(ops_a & ops_b)

    if not shared_ops:
        return MatchResult(
            compatibility=CompatibilityClass.NONE,
            shared_operators=[],
            subsystem_compat={},
            error_code=ERR_NO_SHARED_OPERATORS,
            error_message="No operator intersection between agents",
        )

    # Step 4: Subsystem Matching
    subsystem_compat: Dict[str, str] = {}
    for s in sorted(SUBSYSTEM_NAMES):
        a_has = aid_a.context_subsystems.get(s, False)
        b_has = aid_b.context_subsystems.get(s, False)
        if a_has and b_has:
            subsystem_compat[s] = SubsystemCompat.SHARED
        elif a_has or b_has:
            owner = aid_a.agent_id if a_has else aid_b.agent_id
            subsystem_compat[s] = f"one-sided:{owner}"
        else:
            subsystem_compat[s] = SubsystemCompat.ABSENT

    # Step 5: Compatibility Class
    shared_count = sum(
        1 for v in subsystem_compat.values()
        if v == SubsystemCompat.SHARED
    )

    if shared_count == len(SUBSYSTEM_NAMES):
        compat = CompatibilityClass.FULL
    elif shared_count > 0:
        compat = CompatibilityClass.PARTIAL
    else:
        return MatchResult(
            compatibility=CompatibilityClass.NONE,
            shared_operators=shared_ops,
            subsystem_compat=subsystem_compat,
            error_code=ERR_NO_SHARED_SUBSYSTEMS,
            error_message="No context subsystem intersection",
        )

    return MatchResult(
        compatibility=compat,
        shared_operators=shared_ops,
        subsystem_compat=subsystem_compat,
    )


def _compute_ncf_hash(ncf_dict: Dict[str, Any]) -> str:
    """
    Compute the NCF hash (NIP-019 §4.2.3).

    ncf_id = SHA-256 of canonical JSON of NCF contents, excluding ncf_id itself.
    """
    # Exclude ncf_id from hash computation
    hashable = {k: v for k, v in ncf_dict.items() if k != "ncf_id"}
    payload = canonical_json(hashable).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def bind(
    aid_a: AgentIdentity,
    aid_b: AgentIdentity,
    match_result: MatchResult,
    *,
    session_start_ms: Optional[int] = None,
    provenance_linking: bool = True,
) -> NegotiatedContextFrame:
    """
    Phase 3: Bind (NIP-019 §4.2.3).

    Constructs the NCF from the match result and both agents' configurations.
    Both agents MUST independently call this function and compare ncf_id.

    Args:
        aid_a: Agent A's identity
        aid_b: Agent B's identity
        match_result: Result from match()
        session_start_ms: Session start timestamp (default: now)
        provenance_linking: Enable cross-agent provenance linking

    Returns:
        NegotiatedContextFrame with computed ncf_id

    Raises:
        NegotiationError: If match_result indicates incompatibility
    """
    if match_result.compatibility == CompatibilityClass.NONE:
        raise NegotiationError(
            match_result.error_code or ERR_NO_SHARED_SUBSYSTEMS,
            match_result.error_message or "Cannot bind: incompatible agents",
        )

    if session_start_ms is None:
        session_start_ms = _now_ms()

    # Temporal alignment: stricter rule wins (NIP-009 §4.9.3)
    temporal = {
        "max_skew_ms": min(
            aid_a.temporal_config.max_skew_ms,
            aid_b.temporal_config.max_skew_ms,
        ),
        "tau_stale_ms": min(
            aid_a.temporal_config.tau_stale_ms,
            aid_b.temporal_config.tau_stale_ms,
        ),
        "tau_window_ms": min(
            aid_a.temporal_config.tau_window_ms,
            aid_b.temporal_config.tau_window_ms,
        ),
    }

    # Build NCF dict (without ncf_id) for hash computation
    ncf_body = {
        "session_start_ms": session_start_ms,
        "agents": sorted([aid_a.agent_id, aid_b.agent_id]),
        "registry_hash": aid_a.registry_hash,  # Guaranteed equal after match
        "semantics_version": aid_a.semantics_version,  # Guaranteed equal
        "shared_operators": sorted(match_result.shared_operators),
        "subsystems": match_result.subsystem_compat,
        "temporal": temporal,
        "provenance_linking": provenance_linking,
    }

    ncf_id = _compute_ncf_hash(ncf_body)

    return NegotiatedContextFrame(
        ncf_id=ncf_id,
        session_start_ms=session_start_ms,
        agents=sorted([aid_a.agent_id, aid_b.agent_id]),
        registry_hash=aid_a.registry_hash,
        semantics_version=aid_a.semantics_version,
        shared_operators=sorted(match_result.shared_operators),
        subsystems=match_result.subsystem_compat,
        temporal=temporal,
        provenance_linking=provenance_linking,
    )


def negotiate(
    aid_a: AgentIdentity,
    aid_b: AgentIdentity,
    *,
    session_start_ms: Optional[int] = None,
    provenance_linking: bool = True,
) -> Tuple[Session, Session]:
    """
    Execute the full three-phase handshake (NIP-019 §4.2).

    Convenience function that runs Announce → Match → Bind
    and returns a Session for each agent.

    Returns:
        (session_a, session_b) — one Session object per agent

    Raises:
        NegotiationError: If any phase fails
    """
    # Phase 1: Announce (exchange AIDs)
    _announce_a = announce(aid_a)
    _announce_b = announce(aid_b)

    # Phase 2: Match (both compute independently — here we call once)
    match_result = match(aid_a, aid_b)

    if match_result.compatibility == CompatibilityClass.NONE:
        raise NegotiationError(
            match_result.error_code or ERR_NO_SHARED_SUBSYSTEMS,
            match_result.error_message or "Negotiation failed: incompatible agents",
        )

    # Phase 3: Bind (both compute independently, verify hash match)
    start_ms = session_start_ms or _now_ms()

    ncf_a = bind(aid_a, aid_b, match_result,
                 session_start_ms=start_ms,
                 provenance_linking=provenance_linking)
    ncf_b = bind(aid_a, aid_b, match_result,
                 session_start_ms=start_ms,
                 provenance_linking=provenance_linking)

    # Verify NCF hash agreement (NIP-019 §4.2.3)
    if ncf_a.ncf_id != ncf_b.ncf_id:
        raise NegotiationError(
            ERR_NCF_MISMATCH,
            f"NCF hash mismatch: {ncf_a.ncf_id[:16]}... != {ncf_b.ncf_id[:16]}...",
        )

    session_a = Session(ncf=ncf_a)
    session_b = Session(ncf=ncf_b)

    return session_a, session_b


# =========================================================================
# Cross-Agent Provenance (NIP-019 §4.5)
# =========================================================================

def build_cross_agent_provenance(
    base_provenance: Dict[str, Any],
    *,
    ncf_id: str,
    counterpart_agent_id: str,
    counterpart_provenance_hash: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Extend a standard NIP-010 provenance dict with cross-agent fields.

    These fields create a provenance DAG across agents, enabling
    an auditor to trace the complete chain of evaluations back through
    both agents to the original sensor evidence.
    """
    extended = dict(base_provenance)
    extended["ncf_id"] = ncf_id
    extended["counterpart_agent_id"] = counterpart_agent_id
    if counterpart_provenance_hash is not None:
        extended["counterpart_provenance_hash"] = counterpart_provenance_hash
    return extended


# =========================================================================
# Chain Operator Extraction (for NCF validation)
# =========================================================================

def extract_operators_from_chain(chain: str) -> Set[str]:
    """
    Extract operator phonetic forms referenced in a Noe chain.

    This is a lightweight lexical scan, not a full parse. It identifies
    known operator tokens. Used to pre-validate chains against the NCF
    shared operator set before evaluation.
    """
    ops = _load_operator_list()
    op_set = set(ops)
    tokens = chain.split()
    found = set()
    for token in tokens:
        # Strip @ prefix for literals
        clean = token.lstrip("@")
        if clean in op_set:
            found.add(clean)
    return found


def validate_chain_for_session(
    chain: str,
    session: Session,
) -> None:
    """
    Validate that a chain only references operators in the NCF shared set.

    Raises NegotiationError(ERR_OPERATOR_NOT_IN_NCF) if a chain references
    an operator outside the shared set.

    Also validates session is active.
    """
    if not session.is_active:
        raise NegotiationError(
            ERR_SESSION_EXPIRED,
            f"Session {session.ncf_id[:16]}... is terminated"
        )

    chain_ops = extract_operators_from_chain(chain)
    shared_set = set(session.ncf.shared_operators)

    violations = chain_ops - shared_set
    if violations:
        raise NegotiationError(
            ERR_OPERATOR_NOT_IN_NCF,
            f"Chain references operators not in NCF: {sorted(violations)}"
        )


# =========================================================================
# Helpers
# =========================================================================

def _now_ms() -> int:
    """Current time in milliseconds."""
    return int(time.time() * 1000)
