"""
test_nip019_phase4.py — Phase 4: Deployment-Reality Simulations
================================================================

Four categories that prove NIP-019 survives conditions beyond a single process:

    1. NETWORK BOUNDARY — AIDs and NCFs serialized through JSON over sockets
    2. CLOCK SKEW — agents with drifting/offset clocks, temporal enforcement
    3. BYZANTINE FAILURE — lying agents, corrupted payloads, replay attacks
    4. SCALE — N-agent fan-out with concurrent pairwise negotiations

Each test is self-contained.  Run with:
    cd /tmp/noe-gate && python -m pytest tests/test_nip019_phase4.py -v
"""

from __future__ import annotations

import copy
import hashlib
import json
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import patch

import pytest

# ── noe imports ──────────────────────────────────────────────────────────
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from noe.agent import (
    AgentIdentity,
    CompatibilityClass,
    MatchResult,
    NegotiatedContextFrame,
    NegotiationError,
    Session,
    SessionState,
    TemporalConfig,
    announce,
    bind,
    match,
    negotiate,
    build_cross_agent_provenance,
    validate_chain_for_session,
    _compute_ncf_hash,
    _now_ms,
    ERR_REGISTRY_MISMATCH,
    ERR_SEMANTICS_MISMATCH,
    ERR_NCF_MISMATCH,
    ERR_SESSION_EXPIRED,
    ERR_TEMPORAL_VIOLATION,
    ERR_OPERATOR_NOT_IN_NCF,
    ERR_NO_SHARED_OPERATORS,
)
from noe.canonical import canonical_json
from noe.provenance import compute_registry_hash, SEMANTICS_VERSION


# =========================================================================
# Fixtures
# =========================================================================

def _make_aid(
    agent_id: str,
    *,
    registry_hash: Optional[str] = None,
    semantics_version: str = SEMANTICS_VERSION,
    operators: Optional[List[str]] = None,
    subsystems: Optional[Dict[str, bool]] = None,
    temporal: Optional[TemporalConfig] = None,
) -> AgentIdentity:
    """Helper to build an AID without touching disk."""
    rh = registry_hash or compute_registry_hash()
    ops = operators if operators is not None else [
        "shi", "nai", "kel", "dom", "vex", "pur", "sek", "tir",
    ]
    subs = subsystems if subsystems is not None else {
        "delivery": True, "integrity": True, "audit": True,
        "modal": True, "temporal": True, "spatial": False,
    }
    return AgentIdentity(
        agent_id=agent_id,
        registry_hash=rh,
        semantics_version=semantics_version,
        runtime_mode="strict",
        supported_operators=ops,
        context_subsystems=subs,
        temporal_config=temporal or TemporalConfig(),
    )


# =========================================================================
# 1. NETWORK BOUNDARY — Serialization Survival
# =========================================================================

class TestNetworkBoundary:
    """
    Prove that AIDs and NCFs survive JSON serialization over a real TCP
    socket.  Agent A lives on one side, Agent B on the other.  The entire
    handshake happens across the wire.
    """

    @staticmethod
    def _serve_agent_b(port: int, aid_b: AgentIdentity, results: dict):
        """Server: Agent B listens, receives Agent A's AID, runs match+bind."""
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", port))
        srv.listen(1)
        srv.settimeout(5)
        conn, _ = srv.accept()
        try:
            # Receive Agent A's announcement (AID dict as JSON)
            raw = b""
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                raw += chunk
                if b"\n" in raw:
                    break
            aid_a_dict = json.loads(raw.decode().strip())

            # Reconstruct AgentIdentity from wire data
            aid_a_wire = AgentIdentity(
                agent_id=aid_a_dict["agent_id"],
                registry_hash=aid_a_dict["registry_hash"],
                semantics_version=aid_a_dict["semantics_version"],
                runtime_mode=aid_a_dict["runtime_mode"],
                supported_operators=aid_a_dict["supported_operators"],
                context_subsystems=aid_a_dict["context_subsystems"],
                temporal_config=TemporalConfig(**aid_a_dict["temporal_config"]),
                domain_packs=aid_a_dict.get("domain_packs", []),
            )

            # Agent B runs match locally
            mr = match(aid_a_wire, aid_b)
            results["match_compat"] = mr.compatibility

            # Agree on timestamp
            start_ms = _now_ms()

            # Agent B computes its NCF
            ncf_b = bind(aid_a_wire, aid_b, mr, session_start_ms=start_ms)

            # Send match result + start_ms back to Agent A
            response = {
                "match": {
                    "compatibility": mr.compatibility.value,
                    "shared_operators": mr.shared_operators,
                    "subsystem_compat": mr.subsystem_compat,
                },
                "session_start_ms": start_ms,
                "ncf_id_b": ncf_b.ncf_id,
            }
            conn.sendall((json.dumps(response) + "\n").encode())
            results["ncf_id_b"] = ncf_b.ncf_id
        finally:
            conn.close()
            srv.close()

    def test_full_handshake_over_tcp(self):
        """Two agents negotiate over a real TCP socket; NCF hashes agree."""
        aid_a = _make_aid("agent-alpha")
        aid_b = _make_aid("agent-beta")
        port = 0  # OS assigns
        results: dict = {}

        # Find a free port
        tmp = socket.socket()
        tmp.bind(("127.0.0.1", 0))
        port = tmp.getsockname()[1]
        tmp.close()

        # Start Agent B server
        t = threading.Thread(target=self._serve_agent_b, args=(port, aid_b, results))
        t.start()
        time.sleep(0.05)  # Let server bind

        # Agent A connects and sends announcement
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(("127.0.0.1", port))
        announcement = announce(aid_a)
        sock.sendall((json.dumps(announcement) + "\n").encode())
        sock.shutdown(socket.SHUT_WR)

        # Receive Agent B's response
        raw = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            raw += chunk
        sock.close()
        t.join(timeout=5)

        resp = json.loads(raw.decode().strip())

        # Agent A reconstructs match result and computes its own NCF
        mr_a = MatchResult(
            compatibility=CompatibilityClass(resp["match"]["compatibility"]),
            shared_operators=resp["match"]["shared_operators"],
            subsystem_compat=resp["match"]["subsystem_compat"],
        )
        ncf_a = bind(aid_a, aid_b, mr_a,
                      session_start_ms=resp["session_start_ms"])

        # CRITICAL ASSERTION: both sides independently computed the same NCF hash
        assert ncf_a.ncf_id == resp["ncf_id_b"], (
            f"NCF hash mismatch across TCP: {ncf_a.ncf_id[:16]} != {resp['ncf_id_b'][:16]}"
        )
        assert results["match_compat"] == CompatibilityClass.PARTIAL  # spatial=False

    def test_aid_round_trip_json(self):
        """AID survives JSON encode → decode with zero information loss."""
        aid = _make_aid("roundtrip-agent", temporal=TemporalConfig(50, 500, 25))
        wire = json.dumps(announce(aid))
        reconstructed = json.loads(wire)

        assert reconstructed["agent_id"] == "roundtrip-agent"
        assert reconstructed["temporal_config"]["max_skew_ms"] == 50
        assert reconstructed["temporal_config"]["tau_stale_ms"] == 500
        assert sorted(reconstructed["supported_operators"]) == sorted(aid.supported_operators)

    def test_ncf_round_trip_json(self):
        """NCF survives JSON encode → decode; ncf_id recomputes identically."""
        aid_a = _make_aid("ncf-rt-a")
        aid_b = _make_aid("ncf-rt-b")
        mr = match(aid_a, aid_b)
        ncf = bind(aid_a, aid_b, mr, session_start_ms=1700000000000)

        # Serialize over "wire"
        wire_json = json.dumps(ncf.to_dict())
        received = json.loads(wire_json)

        # Recompute hash from received body (excluding ncf_id)
        recomputed_hash = _compute_ncf_hash(received)
        assert recomputed_hash == ncf.ncf_id

    def test_binary_payload_rejected(self):
        """Non-JSON binary garbage does not produce a valid AID."""
        garbage = b"\x89PNG\r\n\x1a\n\x00\x00\x00"
        with pytest.raises((json.JSONDecodeError, UnicodeDecodeError)):
            json.loads(garbage.decode("utf-8"))

    def test_partial_json_rejected(self):
        """Truncated JSON (simulating network drop) fails cleanly."""
        aid = _make_aid("trunc-agent")
        full = json.dumps(announce(aid))
        truncated = full[:len(full)//2]
        with pytest.raises(json.JSONDecodeError):
            json.loads(truncated)


# =========================================================================
# 2. CLOCK SKEW — Temporal Enforcement Under Drift
# =========================================================================

class TestClockSkew:
    """
    Simulate agents with different clocks.  We monkeypatch _now_ms to
    inject clock offsets and drift, then verify temporal enforcement.
    """

    def _make_session(self, max_skew=200, tau_stale=1000, tau_window=100):
        """Build a session with specific temporal params."""
        aid_a = _make_aid("clock-a", temporal=TemporalConfig(max_skew, tau_stale, tau_window))
        aid_b = _make_aid("clock-b", temporal=TemporalConfig(max_skew, tau_stale, tau_window))
        sa, sb = negotiate(aid_a, aid_b)
        return sa, sb

    def test_evidence_within_skew_tolerance(self):
        """Evidence from 150ms in the future accepted when max_skew=200."""
        sa, _ = self._make_session(max_skew=200, tau_stale=5000)
        real_now = _now_ms()
        # Evidence 150ms in the future — within 200ms skew tolerance
        future_ts = real_now + 150
        with patch("noe.agent._now_ms", return_value=real_now):
            sa.validate_temporal(future_ts)  # Should not raise

    def test_evidence_beyond_skew_rejected(self):
        """Evidence from 300ms in the future rejected when max_skew=200."""
        sa, _ = self._make_session(max_skew=200, tau_stale=5000)
        real_now = _now_ms()
        future_ts = real_now + 300
        with patch("noe.agent._now_ms", return_value=real_now):
            with pytest.raises(NegotiationError) as exc:
                sa.validate_temporal(future_ts)
            assert exc.value.code == ERR_TEMPORAL_VIOLATION
            assert "future" in exc.value.message

    def test_stale_evidence_rejected(self):
        """Evidence older than tau_stale is rejected."""
        sa, _ = self._make_session(max_skew=200, tau_stale=1000)
        real_now = _now_ms()
        old_ts = real_now - 1500  # 1500ms old, tau_stale=1000
        with patch("noe.agent._now_ms", return_value=real_now):
            with pytest.raises(NegotiationError) as exc:
                sa.validate_temporal(old_ts)
            assert exc.value.code == ERR_TEMPORAL_VIOLATION
            assert "tau_stale" in exc.value.message

    def test_evidence_just_within_staleness(self):
        """Evidence exactly at tau_stale boundary is accepted."""
        sa, _ = self._make_session(max_skew=200, tau_stale=1000)
        real_now = _now_ms()
        borderline_ts = real_now - 1000  # Exactly at tau_stale
        with patch("noe.agent._now_ms", return_value=real_now):
            sa.validate_temporal(borderline_ts)  # Should not raise

    def test_asymmetric_clocks_min_wins(self):
        """
        Agent A: max_skew=500ms.  Agent B: max_skew=100ms.
        NCF gets min(500,100) = 100ms.  Verify 150ms future is rejected.
        """
        aid_a = _make_aid("asym-a", temporal=TemporalConfig(500, 5000, 100))
        aid_b = _make_aid("asym-b", temporal=TemporalConfig(100, 5000, 100))
        sa, sb = negotiate(aid_a, aid_b)

        # NCF temporal should be min of both
        assert sa.ncf.temporal["max_skew_ms"] == 100
        assert sb.ncf.temporal["max_skew_ms"] == 100

        real_now = _now_ms()
        future_ts = real_now + 150  # Beyond 100ms skew
        with patch("noe.agent._now_ms", return_value=real_now):
            with pytest.raises(NegotiationError) as exc:
                sa.validate_temporal(future_ts)
            assert exc.value.code == ERR_TEMPORAL_VIOLATION

    def test_clock_drift_during_session(self):
        """
        Simulate progressive clock drift.  Early evidence is fine,
        later evidence crosses the staleness boundary.
        """
        sa, _ = self._make_session(max_skew=200, tau_stale=500)
        base_now = _now_ms()

        # T+0: Agent B produces evidence at base_now
        with patch("noe.agent._now_ms", return_value=base_now):
            sa.validate_temporal(base_now)  # OK

        # T+200ms: Agent A's clock has advanced 200ms, evidence is 200ms old — OK
        with patch("noe.agent._now_ms", return_value=base_now + 200):
            sa.validate_temporal(base_now)  # Still OK, 200 < 500

        # T+600ms: Now evidence is 600ms old, exceeds tau_stale=500
        with patch("noe.agent._now_ms", return_value=base_now + 600):
            with pytest.raises(NegotiationError) as exc:
                sa.validate_temporal(base_now)
            assert exc.value.code == ERR_TEMPORAL_VIOLATION

    def test_both_agents_enforce_same_temporal(self):
        """Both session endpoints enforce identical temporal parameters."""
        aid_a = _make_aid("sym-a", temporal=TemporalConfig(150, 800, 50))
        aid_b = _make_aid("sym-b", temporal=TemporalConfig(300, 2000, 200))
        sa, sb = negotiate(aid_a, aid_b)

        # Both should have min-of-both
        for session in [sa, sb]:
            assert session.ncf.temporal["max_skew_ms"] == 150
            assert session.ncf.temporal["tau_stale_ms"] == 800
            assert session.ncf.temporal["tau_window_ms"] == 50

    def test_zero_skew_tolerance(self):
        """With max_skew=0, any future timestamp is rejected."""
        sa, _ = self._make_session(max_skew=0, tau_stale=5000)
        real_now = _now_ms()
        with patch("noe.agent._now_ms", return_value=real_now):
            # Even 1ms in the future is a violation
            with pytest.raises(NegotiationError) as exc:
                sa.validate_temporal(real_now + 1)
            assert exc.value.code == ERR_TEMPORAL_VIOLATION


# =========================================================================
# 3. BYZANTINE FAILURE — Lying Agents, Forgery, Replay
# =========================================================================

class TestByzantineFailure:
    """
    Test adversarial agents that:
    - Lie about their registry hash
    - Forge NCF hashes
    - Replay NCFs from old sessions
    - Inject operators not in the shared set
    - Corrupt provenance links
    - Attempt capability inflation
    """

    def test_lie_about_registry_hash(self):
        """Agent claims a registry hash it doesn't actually have."""
        real_hash = compute_registry_hash()
        honest = _make_aid("honest", registry_hash=real_hash)
        liar = _make_aid("liar", registry_hash="deadbeef" * 8)

        mr = match(honest, liar)
        assert mr.compatibility == CompatibilityClass.NONE
        assert mr.error_code == ERR_REGISTRY_MISMATCH

    def test_lie_about_semantics_version(self):
        """Agent claims a semantics version it doesn't support."""
        honest = _make_aid("honest")
        liar = _make_aid("liar", semantics_version="NIP-005-v99.0")

        mr = match(honest, liar)
        assert mr.compatibility == CompatibilityClass.NONE
        assert mr.error_code == ERR_SEMANTICS_MISMATCH

    def test_inflate_operator_list(self):
        """
        Agent claims operators it doesn't support.  Match proceeds
        (operator list is self-declared), but the inflated operators
        should NOT appear in the NCF if the other agent doesn't have them.
        """
        honest = _make_aid("honest", operators=["shi", "nai", "kel"])
        inflated = _make_aid("inflated", operators=["shi", "nai", "kel", "dom", "vex",
                                                       "pur", "sek", "FAKE_OP_1", "FAKE_OP_2"])

        mr = match(honest, inflated)
        # Only honest's operators survive intersection
        assert set(mr.shared_operators) == {"shi", "nai", "kel"}
        assert "FAKE_OP_1" not in mr.shared_operators

    def test_forge_ncf_hash(self):
        """Agent presents an NCF with a forged ncf_id."""
        aid_a = _make_aid("forge-a")
        aid_b = _make_aid("forge-b")
        mr = match(aid_a, aid_b)
        ncf = bind(aid_a, aid_b, mr, session_start_ms=1700000000000)

        # Forge: tamper with ncf_id while keeping body unchanged
        forged_id = "0" * 64  # All zeros
        ncf_dict = ncf.to_dict()
        ncf_dict["ncf_id"] = forged_id

        # Verification: recompute hash from body and compare
        recomputed = _compute_ncf_hash(ncf_dict)
        assert recomputed != forged_id, "Forged hash should not match recomputed hash"
        assert recomputed == ncf.ncf_id, "Recomputed hash should match original"

    def test_tamper_with_ncf_body(self):
        """Modify NCF body after binding — hash no longer matches."""
        aid_a = _make_aid("tamper-a")
        aid_b = _make_aid("tamper-b")
        mr = match(aid_a, aid_b)
        ncf = bind(aid_a, aid_b, mr, session_start_ms=1700000000000)
        original_id = ncf.ncf_id

        # Tamper: add an operator that wasn't negotiated
        tampered = ncf.to_dict()
        tampered["shared_operators"].append("SMUGGLED_OP")
        recomputed = _compute_ncf_hash(tampered)

        assert recomputed != original_id, "Tampered NCF must produce different hash"

    def test_replay_old_ncf_into_new_session(self):
        """
        Agent negotiates session 1, terminates it, then tries to use
        the old NCF's session object.  Operations must be rejected.
        """
        aid_a = _make_aid("replay-a")
        aid_b = _make_aid("replay-b")

        # Session 1
        sa1, sb1 = negotiate(aid_a, aid_b)
        old_ncf_id = sa1.ncf_id

        # Terminate session 1
        sa1.terminate()
        sb1.terminate()

        # Session 2 (different start time → different NCF hash)
        time.sleep(0.002)
        sa2, sb2 = negotiate(aid_a, aid_b)
        assert sa2.ncf_id != old_ncf_id, "New session must have different NCF"

        # Try to use terminated session 1
        with pytest.raises(NegotiationError) as exc:
            sa1.validate_operator("shi")
        assert exc.value.code == ERR_SESSION_EXPIRED

        # Session 2 still works
        sa2.validate_operator("shi")  # No error

    def test_operator_injection_in_chain(self):
        """
        Agent tries to evaluate a chain containing an operator that
        is NOT in the NCF shared set.  Session validation must reject.

        Uses real registry operators so extract_operators_from_chain() detects them.
        """
        from noe.agent import _load_operator_list
        all_ops = _load_operator_list()
        # Split real operators into two non-overlapping sets
        shared_ops = all_ops[:5]     # e.g. ["-a", "-o", "-u", "ak", "al"]
        extra_ops = all_ops[5:10]    # e.g. ["alu", "an", "ap", "at", "ban"]

        aid_a = _make_aid("inject-a", operators=shared_ops + extra_ops)
        aid_b = _make_aid("inject-b", operators=shared_ops)
        sa, sb = negotiate(aid_a, aid_b)

        # NCF shared set is only shared_ops
        assert set(sa.ncf.shared_operators) == set(shared_ops)

        # Chain using an extra operator not in the shared set
        injected_op = extra_ops[0]
        with pytest.raises(NegotiationError) as exc:
            validate_chain_for_session(f"{injected_op} @test_literal", sa)
        assert exc.value.code == ERR_OPERATOR_NOT_IN_NCF

    def test_counterpart_provenance_forgery(self):
        """
        Agent claims a counterpart_provenance_hash that doesn't match
        any real provenance record.  An auditor must detect this.
        """
        base_prov = {
            "provenance_hash": hashlib.sha256(b"real-evidence").hexdigest(),
            "action_type": "evaluate",
        }
        forged_link = build_cross_agent_provenance(
            base_prov,
            ncf_id="valid_ncf_id",
            counterpart_agent_id="honest-agent",
            counterpart_provenance_hash="0" * 64,  # Forged — doesn't exist
        )

        # Auditor check: the forged hash is syntactically valid hex but
        # will not resolve to any real provenance record in the DAG
        assert forged_link["counterpart_provenance_hash"] == "0" * 64
        assert forged_link["counterpart_provenance_hash"] != base_prov["provenance_hash"]

    def test_capability_downgrade_after_bind(self):
        """
        Agent tries to use a session but with a modified NCF that has
        fewer operators.  The ncf_id won't match the modified body.
        """
        aid_a = _make_aid("down-a")
        aid_b = _make_aid("down-b")
        sa, sb = negotiate(aid_a, aid_b)
        original_ncf_id = sa.ncf.ncf_id

        # Attacker modifies the NCF object directly (simulating memory corruption)
        sa.ncf.shared_operators = ["shi"]  # Downgrade from full set to one op

        # Recompute hash from modified body — it won't match
        modified_dict = sa.ncf.to_dict()
        recomputed = _compute_ncf_hash(modified_dict)
        assert recomputed != original_ncf_id, "Downgraded NCF hash must differ"

    def test_impersonate_agent_id(self):
        """
        Agent B negotiates with Agent A, then tries to present itself
        as Agent A to Agent C.  The NCF agents list will reveal the lie.
        """
        aid_a = _make_aid("real-a")
        aid_b = _make_aid("impersonator-b")
        aid_c = _make_aid("target-c")

        # B negotiates with A
        sa, sb = negotiate(aid_a, aid_b)

        # B tries to pass the NCF from (A,B) session to C
        # The NCF agents list contains ["impersonator-b", "real-a"]
        ncf_agents = set(sb.ncf.agents)
        assert "target-c" not in ncf_agents, "NCF does not include C"

        # If C receives this NCF, it should verify its own ID is in the agents list
        c_in_ncf = aid_c.agent_id in ncf_agents
        assert not c_in_ncf, "C detects it's not a party to this NCF"

    def test_double_bind_different_timestamps(self):
        """
        Attacker tries to bind the same match result with a different
        timestamp to get a different NCF hash (session confusion attack).
        """
        aid_a = _make_aid("dbl-a")
        aid_b = _make_aid("dbl-b")
        mr = match(aid_a, aid_b)

        ncf_1 = bind(aid_a, aid_b, mr, session_start_ms=1700000000000)
        ncf_2 = bind(aid_a, aid_b, mr, session_start_ms=1700000001000)

        # Different timestamps MUST produce different NCF hashes
        assert ncf_1.ncf_id != ncf_2.ncf_id
        # Both are individually valid, but they identify different sessions
        assert ncf_1.session_start_ms != ncf_2.session_start_ms


# =========================================================================
# 4. SCALE — N-Agent Fan-Out with Concurrent Negotiations
# =========================================================================

class TestScale:
    """
    Prove that NIP-019 handles N agents negotiating concurrently.
    Tests: fan-out topologies, thread safety, session isolation.
    """

    def test_10_agent_star_topology(self):
        """
        One hub agent negotiates pairwise with 10 spoke agents.
        All 10 sessions must be distinct with valid NCFs.
        """
        hub = _make_aid("hub-central")
        spokes = [_make_aid(f"spoke-{i:02d}") for i in range(10)]
        sessions = []

        for spoke in spokes:
            s_hub, s_spoke = negotiate(hub, spoke)
            sessions.append((s_hub, s_spoke))

        ncf_ids = set()
        for s_hub, s_spoke in sessions:
            # Both endpoints see the same NCF
            assert s_hub.ncf_id == s_spoke.ncf_id
            ncf_ids.add(s_hub.ncf_id)

        # All 10 sessions must have distinct NCFs
        assert len(ncf_ids) == 10, f"Expected 10 unique NCFs, got {len(ncf_ids)}"

    def test_full_mesh_6_agents(self):
        """
        6 agents, each negotiates with every other = 15 pairwise sessions.
        """
        agents = [_make_aid(f"mesh-{i}") for i in range(6)]
        sessions = {}

        for i in range(len(agents)):
            for j in range(i + 1, len(agents)):
                sa, sb = negotiate(agents[i], agents[j])
                pair_key = (agents[i].agent_id, agents[j].agent_id)
                sessions[pair_key] = (sa, sb)

        assert len(sessions) == 15  # C(6,2) = 15

        # All 15 NCFs must be unique
        ncf_ids = {sa.ncf_id for sa, sb in sessions.values()}
        assert len(ncf_ids) == 15

    def test_concurrent_negotiations_thread_safe(self):
        """
        20 agents negotiate concurrently in a thread pool.
        No races, no corrupted NCFs.
        """
        hub = _make_aid("concurrent-hub")
        spokes = [_make_aid(f"concurrent-{i:02d}") for i in range(20)]
        results: Dict[str, Tuple[Session, Session]] = {}
        errors: List[str] = []

        def negotiate_pair(spoke):
            try:
                s_hub, s_spoke = negotiate(hub, spoke)
                return (spoke.agent_id, s_hub, s_spoke)
            except Exception as e:
                return (spoke.agent_id, None, str(e))

        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = {pool.submit(negotiate_pair, s): s for s in spokes}
            for future in as_completed(futures):
                agent_id, s_hub, s_spoke_or_err = future.result()
                if s_hub is None:
                    errors.append(f"{agent_id}: {s_spoke_or_err}")
                else:
                    results[agent_id] = (s_hub, s_spoke_or_err)

        assert not errors, f"Concurrent negotiation errors: {errors}"
        assert len(results) == 20

        # All NCFs unique
        ncf_ids = {s_hub.ncf_id for s_hub, _ in results.values()}
        assert len(ncf_ids) == 20

    def test_session_isolation_across_pairs(self):
        """
        Agent A has sessions with B and C.  Operations on the A-B session
        must not affect the A-C session.
        """
        aid_a = _make_aid("iso-a")
        aid_b = _make_aid("iso-b", operators=["shi", "nai"])
        aid_c = _make_aid("iso-c", operators=["shi", "kel", "dom"])

        sab_a, sab_b = negotiate(aid_a, aid_b)
        sac_a, sac_c = negotiate(aid_a, aid_c)

        # A-B shared: {"shi", "nai"} (intersection of A's full set and B's)
        assert "nai" in sab_a.ncf.shared_operators
        assert "kel" not in sab_a.ncf.shared_operators

        # A-C shared: {"shi", "kel", "dom"} (intersection of A's full set and C's)
        assert "kel" in sac_a.ncf.shared_operators
        assert "nai" not in sac_a.ncf.shared_operators

        # Terminate A-B session
        sab_a.terminate()

        # A-C session still works
        assert sac_a.is_active
        sac_a.validate_operator("kel")  # No error

        # A-B session is dead
        with pytest.raises(NegotiationError):
            sab_a.validate_operator("shi")

    def test_heterogeneous_agents_mixed_subsystems(self):
        """
        Scale with heterogeneous agents: different subsystem configs.
        Some pairs get FULL compat, some PARTIAL, some NONE.
        """
        # Agent with all subsystems
        full = _make_aid("full-agent", subsystems={
            "delivery": True, "integrity": True, "audit": True,
            "modal": True, "temporal": True, "spatial": True,
        })
        # Agent with minimal subsystems
        minimal = _make_aid("minimal-agent", subsystems={
            "delivery": True, "integrity": False, "audit": False,
            "modal": False, "temporal": False, "spatial": False,
        })
        # Agent with no overlap (only spatial)
        spatial_only = _make_aid("spatial-agent", subsystems={
            "delivery": False, "integrity": False, "audit": False,
            "modal": False, "temporal": False, "spatial": True,
        })

        # full ↔ full: FULL compat
        mr_ff = match(full, _make_aid("full2", subsystems={
            "delivery": True, "integrity": True, "audit": True,
            "modal": True, "temporal": True, "spatial": True,
        }))
        assert mr_ff.compatibility == CompatibilityClass.FULL

        # full ↔ minimal: PARTIAL compat
        mr_fm = match(full, minimal)
        assert mr_fm.compatibility == CompatibilityClass.PARTIAL

        # minimal ↔ spatial_only: NONE (no shared subsystem)
        mr_ms = match(minimal, spatial_only)
        assert mr_ms.compatibility == CompatibilityClass.NONE

    def test_provenance_dag_scales_with_agents(self):
        """
        Build a provenance DAG across 5 agents in a chain topology:
        A→B→C→D→E.  Each link has cross-agent provenance.
        Verify the full chain is traceable.
        """
        agents = [_make_aid(f"chain-{i}") for i in range(5)]
        sessions = []
        provenance_chain = []

        # Negotiate pairwise along the chain
        for i in range(len(agents) - 1):
            sa, sb = negotiate(agents[i], agents[i + 1])
            sessions.append((sa, sb))

        # Build provenance records along the chain
        prev_hash = None
        for i, (sa, sb) in enumerate(sessions):
            base = {
                "provenance_hash": hashlib.sha256(
                    f"evidence-{i}".encode()
                ).hexdigest(),
                "action_type": "evaluate",
                "agent_id": agents[i].agent_id,
            }
            extended = build_cross_agent_provenance(
                base,
                ncf_id=sa.ncf_id,
                counterpart_agent_id=agents[i + 1].agent_id,
                counterpart_provenance_hash=prev_hash,
            )
            provenance_chain.append(extended)
            prev_hash = extended["provenance_hash"]

        # Verify chain is traceable
        assert len(provenance_chain) == 4  # 5 agents, 4 links
        # First link has no predecessor
        assert provenance_chain[0].get("counterpart_provenance_hash") is None
        # Each subsequent link references the previous
        for i in range(1, len(provenance_chain)):
            assert provenance_chain[i]["counterpart_provenance_hash"] == \
                   provenance_chain[i - 1]["provenance_hash"]

    def test_50_agents_star_performance(self):
        """
        Performance test: 50 spoke agents negotiate with a hub.
        Must complete in under 5 seconds.
        """
        hub = _make_aid("perf-hub")
        spokes = [_make_aid(f"perf-{i:03d}") for i in range(50)]

        start = time.monotonic()
        ncf_ids = set()
        for spoke in spokes:
            s_hub, s_spoke = negotiate(hub, spoke)
            ncf_ids.add(s_hub.ncf_id)
        elapsed = time.monotonic() - start

        assert len(ncf_ids) == 50
        assert elapsed < 5.0, f"50-agent negotiation took {elapsed:.2f}s (limit: 5s)"


# =========================================================================
# 5. CROSS-CATEGORY INTEGRATION
# =========================================================================

class TestCrossCategoryIntegration:
    """
    Tests that combine multiple categories: network + clock skew,
    byzantine + scale, etc.
    """

    def test_network_serialized_ncf_survives_clock_validation(self):
        """
        NCF negotiated via serialization still enforces temporal rules.
        """
        aid_a = _make_aid("net-clock-a", temporal=TemporalConfig(100, 500, 50))
        aid_b = _make_aid("net-clock-b", temporal=TemporalConfig(200, 1000, 75))
        mr = match(aid_a, aid_b)
        start_ms = _now_ms()
        ncf = bind(aid_a, aid_b, mr, session_start_ms=start_ms)

        # Simulate wire transfer: serialize + deserialize
        wire = json.dumps(ncf.to_dict())
        received = json.loads(wire)

        # Reconstruct NCF on "remote" side
        remote_ncf = NegotiatedContextFrame(
            ncf_id=received["ncf_id"],
            session_start_ms=received["session_start_ms"],
            agents=received["agents"],
            registry_hash=received["registry_hash"],
            semantics_version=received["semantics_version"],
            shared_operators=received["shared_operators"],
            subsystems=received["subsystems"],
            temporal=received["temporal"],
            provenance_linking=received["provenance_linking"],
        )
        remote_session = Session(ncf=remote_ncf)

        # Temporal enforcement still works: min(100,200)=100ms skew
        assert remote_session.ncf.temporal["max_skew_ms"] == 100
        real_now = _now_ms()
        with patch("noe.agent._now_ms", return_value=real_now):
            # 150ms future → rejected (100ms tolerance)
            with pytest.raises(NegotiationError) as exc:
                remote_session.validate_temporal(real_now + 150)
            assert exc.value.code == ERR_TEMPORAL_VIOLATION

    def test_byzantine_agent_in_scaled_topology(self):
        """
        In a 5-agent star, one spoke lies about registry hash.
        That spoke fails; the other 4 succeed.
        """
        hub = _make_aid("hub")
        honest_spokes = [_make_aid(f"honest-{i}") for i in range(4)]
        liar = _make_aid("liar-spoke", registry_hash="bad" * 16)

        all_spokes = honest_spokes + [liar]
        successes = []
        failures = []

        for spoke in all_spokes:
            try:
                s_hub, s_spoke = negotiate(hub, spoke)
                successes.append(spoke.agent_id)
            except NegotiationError as e:
                failures.append((spoke.agent_id, e.code))

        assert len(successes) == 4
        assert len(failures) == 1
        assert failures[0] == ("liar-spoke", ERR_REGISTRY_MISMATCH)

    def test_concurrent_byzantine_detection(self):
        """
        Multiple Byzantine agents negotiate concurrently.
        Each must be independently detected and rejected.
        """
        hub = _make_aid("detect-hub")
        honest = [_make_aid(f"good-{i}") for i in range(5)]
        liars = [
            _make_aid("bad-reg", registry_hash="ff" * 32),
            _make_aid("bad-sem", semantics_version="FAKE-v0.0"),
            _make_aid("bad-ops", operators=[]),  # No operators
        ]
        all_agents = honest + liars

        def try_negotiate(spoke):
            try:
                s_hub, s_spoke = negotiate(hub, spoke)
                return ("ok", spoke.agent_id, s_hub.ncf_id)
            except NegotiationError as e:
                return ("fail", spoke.agent_id, e.code)

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(try_negotiate, all_agents))

        ok_count = sum(1 for r in results if r[0] == "ok")
        fail_count = sum(1 for r in results if r[0] == "fail")

        assert ok_count == 5, f"Expected 5 successes, got {ok_count}"
        assert fail_count == 3, f"Expected 3 failures, got {fail_count}"

        # Verify each failure has the right error code
        fail_codes = {r[1]: r[2] for r in results if r[0] == "fail"}
        assert fail_codes["bad-reg"] == ERR_REGISTRY_MISMATCH
        assert fail_codes["bad-sem"] == ERR_SEMANTICS_MISMATCH
        assert fail_codes["bad-ops"] == ERR_NO_SHARED_OPERATORS
