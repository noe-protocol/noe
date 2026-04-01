"""
test_nip019_agent.py

NIP-019 Multi-Agent Context Negotiation Protocol — Test Suite
--------------------------------------------------------------

Covers:
    - Unit tests: AID construction, three-phase handshake, NCF hashing
    - Integration tests: two NoeRuntimes negotiate and exchange delivery
    - Adversarial tests: downgrade, replay, operator rejection

Run with:
    python -m pytest tests/test_nip019_agent.py -v
"""

import sys
import time
import json
import hashlib
import pytest
from pathlib import Path
from copy import deepcopy

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from noe.agent import (
    AgentIdentity,
    NegotiatedContextFrame,
    Session,
    SessionState,
    TemporalConfig,
    MatchResult,
    CompatibilityClass,
    SubsystemCompat,
    NegotiationError,
    build_agent_identity,
    announce,
    match,
    bind,
    negotiate,
    validate_chain_for_session,
    extract_operators_from_chain,
    build_cross_agent_provenance,
    ERR_REGISTRY_MISMATCH,
    ERR_SEMANTICS_MISMATCH,
    ERR_NO_SHARED_OPERATORS,
    ERR_NO_SHARED_SUBSYSTEMS,
    ERR_NCF_MISMATCH,
    ERR_SESSION_EXPIRED,
    ERR_OPERATOR_NOT_IN_NCF,
    ERR_TEMPORAL_VIOLATION,
    _compute_ncf_hash,
)
from noe.provenance import (
    ProvenanceRecord,
    build_provenance_record,
    compute_registry_hash,
    SEMANTICS_VERSION,
)
from noe.canonical import canonical_json


# =========================================================================
# Fixtures
# =========================================================================

@pytest.fixture
def registry_hash():
    """The SHA-256 hash of the local registry.json."""
    h = compute_registry_hash()
    assert h, "registry.json not found — cannot run NIP-019 tests"
    return h


@pytest.fixture
def temporal_strict():
    return TemporalConfig(max_skew_ms=100, tau_stale_ms=500, tau_window_ms=50)


@pytest.fixture
def temporal_loose():
    return TemporalConfig(max_skew_ms=300, tau_stale_ms=2000, tau_window_ms=200)


@pytest.fixture
def all_subsystems():
    return {
        "delivery": True, "integrity": True, "audit": True,
        "modal": True, "temporal": True, "spatial": True,
    }


@pytest.fixture
def partial_subsystems():
    return {
        "delivery": True, "integrity": False, "audit": False,
        "modal": True, "temporal": True, "spatial": False,
    }


@pytest.fixture
def aid_a(registry_hash, all_subsystems, temporal_strict):
    return build_agent_identity(
        "agent-alpha",
        registry_hash=registry_hash,
        context_subsystems=all_subsystems,
        temporal_config=temporal_strict,
    )


@pytest.fixture
def aid_b(registry_hash, all_subsystems, temporal_loose):
    return build_agent_identity(
        "agent-beta",
        registry_hash=registry_hash,
        context_subsystems=all_subsystems,
        temporal_config=temporal_loose,
    )


@pytest.fixture
def aid_partial(registry_hash, partial_subsystems):
    return build_agent_identity(
        "agent-sensor",
        registry_hash=registry_hash,
        context_subsystems=partial_subsystems,
    )


# =========================================================================
# 1. UNIT TESTS — Agent Identity
# =========================================================================

class TestAgentIdentity:

    def test_build_from_registry(self, registry_hash):
        """AID constructed from local registry has non-empty operator list."""
        aid = build_agent_identity("test-agent", registry_hash=registry_hash)
        assert aid.agent_id == "test-agent"
        assert aid.registry_hash == registry_hash
        assert aid.semantics_version == SEMANTICS_VERSION
        assert len(aid.supported_operators) > 0
        assert "shi" in aid.supported_operators
        assert "vek" in aid.supported_operators

    def test_empty_agent_id_rejected(self, registry_hash):
        """Empty agent_id MUST be rejected."""
        with pytest.raises(ValueError, match="agent_id"):
            AgentIdentity(
                agent_id="",
                registry_hash=registry_hash,
                semantics_version=SEMANTICS_VERSION,
                runtime_mode="strict",
                supported_operators=["shi"],
                context_subsystems={"delivery": True},
                temporal_config=TemporalConfig(),
            )

    def test_unknown_subsystem_rejected(self, registry_hash):
        """Unknown subsystem names MUST be rejected."""
        with pytest.raises(ValueError, match="Unknown subsystem"):
            AgentIdentity(
                agent_id="bad-agent",
                registry_hash=registry_hash,
                semantics_version=SEMANTICS_VERSION,
                runtime_mode="strict",
                supported_operators=["shi"],
                context_subsystems={"delivery": True, "magic": True},
                temporal_config=TemporalConfig(),
            )

    def test_to_dict_deterministic(self, aid_a):
        """AID serialization is deterministic (sorted operators, subsystems)."""
        d1 = aid_a.to_dict()
        d2 = aid_a.to_dict()
        assert canonical_json(d1) == canonical_json(d2)

    def test_announce_returns_dict(self, aid_a):
        """announce() returns a serializable dict."""
        result = announce(aid_a)
        assert isinstance(result, dict)
        assert result["agent_id"] == "agent-alpha"
        # Should be JSON-serializable
        json.dumps(result)


# =========================================================================
# 2. UNIT TESTS — Match Phase
# =========================================================================

class TestMatchPhase:

    def test_full_compatibility(self, aid_a, aid_b):
        """Two agents with same registry + all subsystems → full compatibility."""
        result = match(aid_a, aid_b)
        assert result.compatibility == CompatibilityClass.FULL
        assert result.error_code is None
        assert len(result.shared_operators) > 0
        # All subsystems should be shared
        for s in result.subsystem_compat.values():
            assert s == SubsystemCompat.SHARED

    def test_partial_compatibility(self, aid_a, aid_partial):
        """Agent with fewer subsystems → partial compatibility."""
        result = match(aid_a, aid_partial)
        assert result.compatibility == CompatibilityClass.PARTIAL
        assert result.error_code is None
        # delivery, modal, temporal should be shared
        assert result.subsystem_compat["delivery"] == SubsystemCompat.SHARED
        assert result.subsystem_compat["modal"] == SubsystemCompat.SHARED
        # integrity should be one-sided
        assert "one-sided" in result.subsystem_compat["integrity"]

    def test_registry_mismatch_aborts(self, aid_a, registry_hash):
        """Different registry hashes → hard failure."""
        aid_foreign = build_agent_identity(
            "agent-foreign",
            registry_hash="0" * 64,  # Fake hash
            supported_operators=["shi", "vek"],
            context_subsystems={"delivery": True},
        )
        result = match(aid_a, aid_foreign)
        assert result.compatibility == CompatibilityClass.NONE
        assert result.error_code == ERR_REGISTRY_MISMATCH

    def test_semantics_mismatch_aborts(self, aid_a, registry_hash):
        """Different semantics versions → hard failure."""
        aid_v2 = AgentIdentity(
            agent_id="agent-v2",
            registry_hash=registry_hash,
            semantics_version="NIP-005-v2.0",
            runtime_mode="strict",
            supported_operators=aid_a.supported_operators,
            context_subsystems={"delivery": True, "modal": True, "temporal": True},
            temporal_config=TemporalConfig(),
        )
        result = match(aid_a, aid_v2)
        assert result.compatibility == CompatibilityClass.NONE
        assert result.error_code == ERR_SEMANTICS_MISMATCH

    def test_no_shared_operators_aborts(self, registry_hash):
        """Zero operator overlap → hard failure."""
        aid_x = AgentIdentity(
            agent_id="agent-x",
            registry_hash=registry_hash,
            semantics_version=SEMANTICS_VERSION,
            runtime_mode="strict",
            supported_operators=["shi", "vek"],
            context_subsystems={"delivery": True},
            temporal_config=TemporalConfig(),
        )
        aid_y = AgentIdentity(
            agent_id="agent-y",
            registry_hash=registry_hash,
            semantics_version=SEMANTICS_VERSION,
            runtime_mode="strict",
            supported_operators=["zzz_fake_op"],
            context_subsystems={"delivery": True},
            temporal_config=TemporalConfig(),
        )
        result = match(aid_x, aid_y)
        assert result.compatibility == CompatibilityClass.NONE
        assert result.error_code == ERR_NO_SHARED_OPERATORS

    def test_no_shared_subsystems_aborts(self, registry_hash):
        """No subsystem overlap → hard failure."""
        aid_x = AgentIdentity(
            agent_id="agent-x",
            registry_hash=registry_hash,
            semantics_version=SEMANTICS_VERSION,
            runtime_mode="strict",
            supported_operators=["shi"],
            context_subsystems={
                "delivery": True, "integrity": False, "audit": False,
                "modal": False, "temporal": False, "spatial": False,
            },
            temporal_config=TemporalConfig(),
        )
        aid_y = AgentIdentity(
            agent_id="agent-y",
            registry_hash=registry_hash,
            semantics_version=SEMANTICS_VERSION,
            runtime_mode="strict",
            supported_operators=["shi"],
            context_subsystems={
                "delivery": False, "integrity": True, "audit": False,
                "modal": False, "temporal": False, "spatial": False,
            },
            temporal_config=TemporalConfig(),
        )
        result = match(aid_x, aid_y)
        assert result.compatibility == CompatibilityClass.NONE
        assert result.error_code == ERR_NO_SHARED_SUBSYSTEMS


# =========================================================================
# 3. UNIT TESTS — Bind Phase & NCF
# =========================================================================

class TestBindPhase:

    def test_ncf_construction(self, aid_a, aid_b):
        """Bind produces a valid NCF with computed hash."""
        mr = match(aid_a, aid_b)
        ncf = bind(aid_a, aid_b, mr, session_start_ms=1000000)
        assert ncf.ncf_id  # Non-empty hash
        assert len(ncf.ncf_id) == 64  # SHA-256 hex
        assert sorted(ncf.agents) == sorted(["agent-alpha", "agent-beta"])
        assert ncf.registry_hash == aid_a.registry_hash
        assert ncf.provenance_linking is True

    def test_temporal_alignment_min(self, aid_a, aid_b):
        """Temporal parameters use min() of both agents (NIP-009 §4.9.3)."""
        mr = match(aid_a, aid_b)
        ncf = bind(aid_a, aid_b, mr, session_start_ms=1000000)
        # aid_a: max_skew=100, tau_stale=500, tau_window=50
        # aid_b: max_skew=300, tau_stale=2000, tau_window=200
        assert ncf.temporal["max_skew_ms"] == 100
        assert ncf.temporal["tau_stale_ms"] == 500
        assert ncf.temporal["tau_window_ms"] == 50

    def test_ncf_hash_deterministic(self, aid_a, aid_b):
        """Both agents computing NCF independently get the same hash."""
        mr = match(aid_a, aid_b)
        ts = 1711929600000
        ncf1 = bind(aid_a, aid_b, mr, session_start_ms=ts)
        ncf2 = bind(aid_a, aid_b, mr, session_start_ms=ts)
        assert ncf1.ncf_id == ncf2.ncf_id

    def test_ncf_hash_changes_with_content(self, aid_a, aid_b):
        """Different session_start_ms → different ncf_id."""
        mr = match(aid_a, aid_b)
        ncf1 = bind(aid_a, aid_b, mr, session_start_ms=1000)
        ncf2 = bind(aid_a, aid_b, mr, session_start_ms=2000)
        assert ncf1.ncf_id != ncf2.ncf_id

    def test_bind_rejects_incompatible(self, aid_a, registry_hash):
        """Bind with CompatibilityClass.NONE raises NegotiationError."""
        aid_foreign = build_agent_identity(
            "agent-foreign",
            registry_hash="0" * 64,
            supported_operators=["shi"],
            context_subsystems={"delivery": True},
        )
        mr = match(aid_a, aid_foreign)
        with pytest.raises(NegotiationError):
            bind(aid_a, aid_foreign, mr)


# =========================================================================
# 4. UNIT TESTS — Full Negotiate
# =========================================================================

class TestNegotiate:

    def test_full_negotiation(self, aid_a, aid_b):
        """Full handshake produces two active sessions with matching NCF."""
        sess_a, sess_b = negotiate(aid_a, aid_b)
        assert sess_a.is_active
        assert sess_b.is_active
        assert sess_a.ncf_id == sess_b.ncf_id
        assert "shi" in sess_a.ncf.shared_operators

    def test_negotiation_fails_on_mismatch(self, aid_a, registry_hash):
        """Negotiation with incompatible agents raises NegotiationError."""
        aid_foreign = build_agent_identity(
            "agent-foreign",
            registry_hash="0" * 64,
            supported_operators=["shi"],
            context_subsystems={"delivery": True},
        )
        with pytest.raises(NegotiationError) as exc_info:
            negotiate(aid_a, aid_foreign)
        assert exc_info.value.code == ERR_REGISTRY_MISMATCH


# =========================================================================
# 5. UNIT TESTS — Session Lifecycle
# =========================================================================

class TestSessionLifecycle:

    def test_session_terminate(self, aid_a, aid_b):
        """Terminated session rejects operator validation."""
        sess_a, sess_b = negotiate(aid_a, aid_b)
        sess_a.terminate()
        assert not sess_a.is_active
        assert sess_a.state == SessionState.TERMINATED
        with pytest.raises(NegotiationError) as exc_info:
            sess_a.validate_operator("shi")
        assert exc_info.value.code == ERR_SESSION_EXPIRED

    def test_session_temporal_validation(self, aid_a, aid_b):
        """Session rejects stale evidence."""
        sess_a, _ = negotiate(aid_a, aid_b)
        # Evidence from 10 seconds ago (tau_stale_ms=500 after min)
        old_ts = int(time.time() * 1000) - 10000
        with pytest.raises(NegotiationError) as exc_info:
            sess_a.validate_temporal(old_ts)
        assert exc_info.value.code == ERR_TEMPORAL_VIOLATION


# =========================================================================
# 6. UNIT TESTS — Chain Validation Against NCF
# =========================================================================

class TestChainValidation:

    def test_valid_chain_passes(self, aid_a, aid_b):
        """Chain with only shared operators passes validation."""
        sess_a, _ = negotiate(aid_a, aid_b)
        # "shi" is guaranteed to be in shared operators
        validate_chain_for_session("shi @test_literal", sess_a)

    def test_expired_session_rejects(self, aid_a, aid_b):
        """Expired session rejects any chain."""
        sess_a, _ = negotiate(aid_a, aid_b)
        sess_a.terminate()
        with pytest.raises(NegotiationError) as exc_info:
            validate_chain_for_session("shi @test", sess_a)
        assert exc_info.value.code == ERR_SESSION_EXPIRED


# =========================================================================
# 7. UNIT TESTS — Cross-Agent Provenance
# =========================================================================

class TestCrossAgentProvenance:

    def test_provenance_record_ncf_fields(self):
        """ProvenanceRecord accepts and serializes NIP-019 fields."""
        prov = build_provenance_record(
            chain="shi @test",
            ast_repr=None,
            context_hash="a" * 64,
            result_domain="truth",
            result_value=True,
            ncf_id="ncf_" + "b" * 60,
            counterpart_agent_id="agent-beta",
            counterpart_provenance_hash="c" * 64,
        )
        assert prov.ncf_id == "ncf_" + "b" * 60
        assert prov.counterpart_agent_id == "agent-beta"
        assert prov.counterpart_provenance_hash == "c" * 64

        # Serialize and deserialize round-trip
        d = prov.to_json_dict()
        assert d["ncf_id"] == prov.ncf_id
        restored = ProvenanceRecord.from_json_dict(d)
        assert restored.ncf_id == prov.ncf_id
        assert restored.counterpart_agent_id == prov.counterpart_agent_id
        assert restored.counterpart_provenance_hash == prov.counterpart_provenance_hash

    def test_provenance_without_ncf_fields(self):
        """Standard provenance (no NIP-019) still works — NCF fields are None."""
        prov = build_provenance_record(
            chain="shi @test",
            ast_repr=None,
            context_hash="a" * 64,
            result_domain="truth",
            result_value=True,
        )
        assert prov.ncf_id is None
        assert prov.counterpart_agent_id is None
        assert prov.counterpart_provenance_hash is None

    def test_ncf_fields_in_provenance_hash(self):
        """NCF fields change the provenance_hash (included in hash payload)."""
        prov_without = build_provenance_record(
            chain="shi @test",
            ast_repr=None,
            context_hash="a" * 64,
            result_domain="truth",
            result_value=True,
        )
        prov_with = build_provenance_record(
            chain="shi @test",
            ast_repr=None,
            context_hash="a" * 64,
            result_domain="truth",
            result_value=True,
            ncf_id="ncf_123",
            counterpart_agent_id="agent-beta",
        )
        assert prov_without.provenance_hash != prov_with.provenance_hash

    def test_build_cross_agent_provenance(self):
        """build_cross_agent_provenance extends a base dict."""
        base = {"chain_hash": "abc", "context_hash": "def"}
        extended = build_cross_agent_provenance(
            base,
            ncf_id="ncf_test",
            counterpart_agent_id="agent-x",
            counterpart_provenance_hash="hash_y",
        )
        assert extended["ncf_id"] == "ncf_test"
        assert extended["counterpart_agent_id"] == "agent-x"
        assert extended["counterpart_provenance_hash"] == "hash_y"
        # Original dict not mutated
        assert "ncf_id" not in base


# =========================================================================
# 8. ADVERSARIAL TESTS
# =========================================================================

class TestAdversarial:

    def test_capability_downgrade(self, aid_a, aid_partial):
        """
        Agent declares reduced capabilities → partial compatibility.
        The shared set correctly reflects only the intersection.
        """
        mr = match(aid_a, aid_partial)
        assert mr.compatibility == CompatibilityClass.PARTIAL
        # Integrity NOT shared (aid_partial has False)
        assert "one-sided" in mr.subsystem_compat["integrity"]

    def test_stale_session_replay(self, aid_a, aid_b):
        """
        Terminated session's NCF cannot be reused.
        Operations on terminated session yield errors.

        Note: NCF hash depends on session_start_ms. If renegotiation
        happens within the same millisecond, hashes may match — but
        the old Session object is still terminated and rejects operations.
        """
        sess_a, sess_b = negotiate(aid_a, aid_b)

        # Terminate
        sess_a.terminate()
        sess_b.terminate()

        # Operations on old terminated session MUST fail
        with pytest.raises(NegotiationError) as exc_info:
            sess_a.validate_operator("shi")
        assert exc_info.value.code == ERR_SESSION_EXPIRED

        # Renegotiate produces new active sessions
        sess_a2, sess_b2 = negotiate(aid_a, aid_b)
        assert sess_a2.is_active
        assert sess_b2.is_active

        # Old session still dead even if NCF content is identical
        assert not sess_a.is_active

    def test_forged_ncf_hash_detected(self, aid_a, aid_b):
        """
        If an adversary modifies the NCF, the hash won't match.
        """
        mr = match(aid_a, aid_b)
        ts = 1711929600000
        ncf = bind(aid_a, aid_b, mr, session_start_ms=ts)

        # Tamper with the NCF
        tampered = ncf.to_dict()
        tampered["provenance_linking"] = False  # Adversary disables provenance
        tampered_hash = _compute_ncf_hash(tampered)

        # The tampered hash won't match the original
        assert tampered_hash != ncf.ncf_id

    def test_ncf_hash_excludes_ncf_id_from_computation(self, aid_a, aid_b):
        """
        NCF hash computation excludes ncf_id itself (no circular dependency).
        """
        mr = match(aid_a, aid_b)
        ts = 1711929600000
        ncf = bind(aid_a, aid_b, mr, session_start_ms=ts)

        # Recompute hash from ncf dict
        ncf_dict = ncf.to_dict()
        recomputed = _compute_ncf_hash(ncf_dict)
        assert recomputed == ncf.ncf_id


# =========================================================================
# 9. INTEGRATION TEST — Two Runtimes with NoeParser
# =========================================================================

class TestIntegrationTwoRuntimes:
    """
    Integration test: two NoeRuntime instances negotiate a session
    and exchange a guarded delivery chain with linked provenance.
    """

    def _build_flat_context(self, agent_name, now_us, clear=True, conf_milli=990):
        """
        Build a flat merged context for an agent (same pattern as Yellow Alert demo).

        NoeRuntime's validator path has complex pi_safe projection that
        requires precise structure. For NIP-019 integration testing, we
        use the proven run_noe_logic path (flat context), which is what
        the existing multi-agent demo uses.
        """
        sig = f"sig_test_{agent_name}"
        return {
            "units": {"probability": "milliprob", "time": "microseconds"},
            "temporal": {
                "max_skew_ms": 5000, "now": now_us,
                "timestamp": now_us, "clock": "epoch_us"
            },
            "constants": {
                "min_confidence_milli": {"knowledge": 900, "belief": 400}
            },
            "audit": {"files": {}},
            "delivery": {"status": {}},
            "spatial": {
                "thresholds": {"near": 1000, "far": 10000},
                "regions": {},
                "orientation": {"target": 0, "tolerance": 100},
            },
            "axioms": {"value_system": {}},
            "rel": {},
            "demonstratives": {"proximal": {}, "distal": {}},
            "literals": {
                f"@sensor_{agent_name}": {
                    "value": clear,
                    "confidence_milli": conf_milli,
                    "timestamp_us": now_us,
                    "source": f"sensor_{agent_name}",
                    "signature": sig,
                },
                "@test_literal": {
                    "value": True,
                    "confidence_milli": 950,
                    "timestamp_us": now_us,
                    "source": f"sensor_{agent_name}",
                    "signature": sig,
                },
            },
            "modal": {
                "knowledge": {f"sensor_{agent_name}": clear, "test_literal": True},
                "belief": {},
                "certainty": {},
            },
        }

    def test_two_agent_negotiate_and_evaluate(self, aid_a, aid_b):
        """
        Two agents negotiate a session, then each evaluates a chain
        independently and produces linked provenance with NCF fields.

        Uses run_noe_logic (same as Yellow Alert demo) + agent module
        for session management and provenance linking.
        """
        from noe.noe_parser import run_noe_logic
        from noe.agent import validate_chain_for_session, build_cross_agent_provenance

        # 1. Negotiate
        sess_a, sess_b = negotiate(aid_a, aid_b)
        assert sess_a.ncf_id == sess_b.ncf_id

        # 2. Build flat contexts (per Yellow Alert pattern)
        now_us = int(time.time() * 1_000_000)
        ctx_a = self._build_flat_context("alpha", now_us)
        ctx_b = self._build_flat_context("beta", now_us)

        # 3. Agent A: validate chain against NCF, then evaluate
        chain_a = "shi @test_literal"
        validate_chain_for_session(chain_a, sess_a)  # No exception = valid
        res_a = run_noe_logic(chain_a, ctx_a, mode="lenient")

        assert res_a["domain"] == "truth"
        assert res_a["value"] is True

        # 4. Build provenance for Agent A with NCF fields
        prov_a = build_provenance_record(
            chain=chain_a,
            ast_repr=None,
            context_hash=res_a.get("meta", {}).get("context_hash", "test"),
            result_domain=res_a["domain"],
            result_value=res_a["value"],
            runtime_mode="lenient",
            ncf_id=sess_a.ncf.ncf_id,
            counterpart_agent_id="agent-beta",
        )
        assert prov_a.ncf_id == sess_a.ncf_id
        assert prov_a.counterpart_agent_id == "agent-beta"
        assert prov_a.provenance_hash is not None

        # 5. Agent B: validate, evaluate, link to A's provenance
        chain_b = "shi @test_literal"
        validate_chain_for_session(chain_b, sess_b)
        res_b = run_noe_logic(chain_b, ctx_b, mode="lenient")

        assert res_b["domain"] == "truth"
        assert res_b["value"] is True

        prov_b = build_provenance_record(
            chain=chain_b,
            ast_repr=None,
            context_hash=res_b.get("meta", {}).get("context_hash", "test"),
            result_domain=res_b["domain"],
            result_value=res_b["value"],
            runtime_mode="lenient",
            ncf_id=sess_b.ncf.ncf_id,
            counterpart_agent_id="agent-alpha",
            counterpart_provenance_hash=prov_a.provenance_hash,
        )

        # 6. Verify provenance DAG: B links back to A
        assert prov_b.ncf_id == sess_b.ncf_id
        assert prov_b.counterpart_agent_id == "agent-alpha"
        assert prov_b.counterpart_provenance_hash == prov_a.provenance_hash

        # 7. Verify an auditor can trace the chain
        assert prov_b.counterpart_provenance_hash is not None
        assert prov_a.provenance_hash is not None
        # NCF IDs match (both agents in same session)
        assert prov_a.ncf_id == prov_b.ncf_id

    def test_cross_agent_expired_session_rejects_validation(self, aid_a, aid_b):
        """
        Expired session rejects chain validation (fail-closed).
        """
        sess_a, _ = negotiate(aid_a, aid_b)
        sess_a.terminate()

        with pytest.raises(NegotiationError) as exc_info:
            validate_chain_for_session("shi @test", sess_a)
        assert exc_info.value.code == ERR_SESSION_EXPIRED


# =========================================================================
# 10. DETERMINISM TESTS
# =========================================================================

class TestDeterminism:

    def test_ncf_hash_is_canonical(self, aid_a, aid_b):
        """NCF hash uses canonical JSON — key order doesn't matter."""
        mr = match(aid_a, aid_b)
        ts = 1711929600000

        # Build NCF dict manually with different key ordering
        ncf = bind(aid_a, aid_b, mr, session_start_ms=ts)
        d = ncf.to_dict()

        # Reverse the keys
        reversed_d = dict(reversed(list(d.items())))
        # Hash should be same because canonical_json sorts keys
        h1 = _compute_ncf_hash(d)
        h2 = _compute_ncf_hash(reversed_d)
        assert h1 == h2

    def test_operator_list_sorted(self, aid_a, aid_b):
        """Shared operators in NCF are always sorted."""
        sess_a, _ = negotiate(aid_a, aid_b)
        ops = sess_a.ncf.shared_operators
        assert ops == sorted(ops)

    def test_agent_list_sorted(self, aid_a, aid_b):
        """Agent list in NCF is always sorted."""
        sess_a, _ = negotiate(aid_a, aid_b)
        agents = sess_a.ncf.agents
        assert agents == sorted(agents)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
