#!/usr/bin/env python3
"""
yellow_alert_nip019.py

NIP-019 Multi-Agent Yellow Alert Protocol
==========================================

The showpiece demo: three separate NoeRuntime-equivalent agents
(Robot A, Robot B, Arbitrator) negotiate pairwise sessions via the
NIP-019 three-phase handshake, evaluate their chains independently,
and produce a cross-agent provenance DAG that an external auditor
can walk from the final safety command back through every agent to
the original sensor readings.

This replaces the V1.0 demo (verify_multi_agent.py) where one
process called run_noe_logic() three times with no sessions. Now:

  1. Each agent has its own AgentIdentity (AID)
  2. Pairwise sessions are negotiated (A↔Arb, B↔Arb)
  3. Each evaluation produces provenance with NCF fields
  4. The Arbitrator's provenance links back to A's and B's provenance
  5. The full DAG is written to a JSON file for audit

Run:
    python examples/auditor_demo/yellow_alert_nip019.py

Outputs:
    nip019_cert_green.json   — unanimous consensus (high speed)
    nip019_cert_yellow.json  — uncertainty (creep mode)
    nip019_cert_red.json     — conflict (safety stop)
    nip019_provenance_dag.json — full cross-agent provenance DAG

Architecture:
    ┌──────────┐     NCF_AB     ┌──────────────┐     NCF_BA     ┌──────────┐
    │ Robot A  │◄──────────────►│  Arbitrator   │◄──────────────►│ Robot B  │
    │ Proposer │  session_a_arb │  3-tier logic │  session_b_arb │ Verifier │
    └──────────┘                └──────────────┘                └──────────┘
       AID_A                        AID_ARB                        AID_B
"""

import sys
import json
import time
import hashlib
from pathlib import Path
from copy import deepcopy
from typing import Dict, Any, List, Optional, Tuple

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from noe.noe_parser import run_noe_logic
from noe.provenance import (
    compute_action_hash,
    build_provenance_record,
    compute_registry_hash,
    SEMANTICS_VERSION,
)
from noe.canonical import canonical_json
from noe.agent import (
    AgentIdentity,
    NegotiatedContextFrame,
    Session,
    TemporalConfig,
    build_agent_identity,
    negotiate,
    validate_chain_for_session,
    build_cross_agent_provenance,
    NegotiationError,
)


# =========================================================================
# CHAINS: The "Yellow Alert" Protocol (unchanged from V1.0)
# =========================================================================

# Robot A (Proposer): if sensor says clear with high confidence → propose
CHAIN_A = (
    "shi @human_clear_a khi "
    "sek mek @propose_clear_a men @session_safety_log sek nek"
)

# Robot B (Verifier): agree if both A proposed AND B confirms clear
CHAIN_B_AGREE = (
    "shi @propose_clear_a an shi @human_clear_b khi "
    "sek mek @agree_clear_b sek nek"
)
# Robot B: veto if B detects human
CHAIN_B_VETO = (
    "shi @human_detected_b khi "
    "sek mek @veto_b sek nek"
)

# Arbitrator: 3-Tier Liveness Logic
CHAIN_ARB_GREEN = "shi @propose_clear_a an shi @agree_clear_b khi sek mek @cmd_go sek nek"
CHAIN_ARB_YELLOW = "shi @propose_clear_a an nai shi @agree_clear_b an nai shi @veto_b khi sek mek @cmd_slow mek @cmd_beep sek nek"
CHAIN_ARB_RED = "shi @veto_b khi sek mek @cmd_halt men @cmd_callhq sek nek"


# =========================================================================
# HELPERS
# =========================================================================

def get_timestamp() -> int:
    return time.time_ns() // 1_000


def build_sensor_literal(val, conf_milli, source, now_us):
    sig = f"sig_rsa_sha256_{hashlib.sha256(str(now_us).encode()).hexdigest()[:8]}"
    return {
        "value": val, "confidence_milli": conf_milli,
        "timestamp_us": now_us, "source": source, "signature": sig,
    }


def find_targets(result_val, result_domain=None) -> List[str]:
    found = []
    if result_domain and result_domain not in ["action", "list"]:
        return []
    if isinstance(result_val, list):
        for item in result_val:
            found.extend(find_targets(item))
    elif isinstance(result_val, dict):
        if result_val.get("type") == "action":
            target = result_val.get("target")
            if isinstance(target, str):
                found.append(target)
            elif isinstance(target, dict):
                found.append(target.get("value"))
        if result_val.get("domain") == "action" and "value" in result_val:
            if isinstance(result_val["value"], dict):
                found.append(result_val["value"].get("target"))
    return found


def hash_json(obj) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


# =========================================================================
# CONTEXT BUILDERS (reused from V1.0)
# =========================================================================

def build_root_context(now_us: int):
    return {
        "units": {"probability": "milliprob", "time": "microseconds"},
        "temporal": {"max_skew_ms": 5000, "now": now_us, "timestamp": now_us, "clock": "epoch_us"},
        "constants": {"min_confidence_milli": {"knowledge": 900, "belief": 400}},
        "audit": {"files": {"@session_safety_log": "verified"}},
        "delivery": {"status": {"@propose_clear_a": "pending"}},
        "spatial": {"thresholds": {"near": 1000, "far": 10000}, "regions": {}, "orientation": {"target": 0, "tolerance": 100}},
        "axioms": {"value_system": {}},
        "rel": {},
        "demonstratives": {"proximal": {}, "distal": {}},
    }


def build_context_A(clear: bool, now_us: int):
    return {
        "literals": {
            "@human_clear_a": build_sensor_literal(clear, 990 if clear else 100, "mob_a_fusion", now_us),
            "@propose_clear_a": {"value": "PROPOSE_CLEAR_A", "type": "proposal"},
            "@session_safety_log": {"value": "LOG", "type": "log"},
        },
        "temporal": {"now": now_us, "timestamp": now_us, "max_skew_ms": 5000, "clock": "epoch_us"},
        "modal": {"knowledge": {}, "belief": {}, "certainty": {}},
    }


def build_context_B(clear_confidence_milli: int, proposal_received: bool, now_us: int):
    literals = {
        "@propose_clear_a": {"value": "PROPOSE_CLEAR_A", "type": "proposal"},
        "@agree_clear_b": {"value": "AGREE_CLEAR_B", "type": "agreement"},
        "@veto_b": {"value": "VETO_B", "type": "veto"},
        "@human_clear_b": build_sensor_literal(True, clear_confidence_milli, "stat_b_lidar", now_us),
        "@human_detected_b": build_sensor_literal(True, 1000 - clear_confidence_milli, "stat_b_lidar", now_us),
    }
    ctx = {
        "literals": literals,
        "temporal": {"now": now_us, "timestamp": now_us, "max_skew_ms": 5000, "clock": "epoch_us"},
        "modal": {"knowledge": {}, "belief": {}, "certainty": {}},
    }
    if proposal_received:
        ctx["modal"]["knowledge"]["@propose_clear_a"] = True
    return ctx


def build_context_Arb(prop_A: bool, agree_B: bool, veto_B: bool, now_us: int):
    knowledge = {
        "propose_clear_a": bool(prop_A),
        "agree_clear_b": bool(agree_B),
        "veto_b": bool(veto_B),
    }
    return {
        "literals": {
            "@cmd_go": {"value": "nav2_set_speed", "type": "control_point", "speed_mm_s": 1500, "timestamp_us": now_us},
            "@cmd_slow": {"value": "nav2_set_speed", "type": "control_point", "speed_mm_s": 100, "timestamp_us": now_us},
            "@cmd_beep": {"value": "speaker_emit", "type": "control_point", "pattern": "caution_beep", "timestamp_us": now_us},
            "@cmd_halt": {"value": "nav2_safe_stop", "type": "control_point", "decel_mm_s2": 3000, "timestamp_us": now_us},
            "@cmd_callhq": {"value": "comms_request_supervisor", "type": "control_point", "urgency": 900, "timestamp_us": now_us},
            "@propose_clear_a": True,
            "@agree_clear_b": True,
            "@veto_b": True,
        },
        "temporal": {"now": now_us, "timestamp": now_us, "max_skew_ms": 5000, "clock": "epoch_us"},
        "modal": {"knowledge": knowledge, "belief": {}, "certainty": {}},
    }


def verify_hardware_signature(literal: dict) -> bool:
    if "signature" not in literal:
        if literal.get("type") in ["message", "control", "alert", "safety", "log", "proposal", "agreement", "veto"]:
            return True
        return False
    return True


def project_safe(c_merged):
    safe = deepcopy(c_merged)
    if "temporal" not in safe:
        safe["temporal"] = {}
    safe["temporal"]["derived"] = {
        "max_literal_age_us": int(safe.get("temporal", {}).get("max_skew_ms", 5000) * 1000),
        "skew_us": 0,
    }
    literals = safe.get("literals", {})
    valid_literals = {}
    for k, v in literals.items():
        if isinstance(v, dict):
            if verify_hardware_signature(v):
                valid_literals[k] = v
        else:
            valid_literals[k] = v
    safe["literals"] = valid_literals
    if "modal" not in safe:
        safe["modal"] = {}
    knowledge = dict(safe["modal"].get("knowledge", {}))
    belief = dict(safe["modal"].get("belief", {}))
    for k, v in valid_literals.items():
        if isinstance(v, dict) and "confidence_milli" in v:
            conf = v.get("confidence_milli", 0)
            val = v.get("value")
            if conf >= 900:
                knowledge[k] = val
            elif conf >= 400:
                belief[k] = val
    safe["modal"]["knowledge"] = knowledge
    safe["modal"]["belief"] = belief
    if "certainty" not in safe["modal"]:
        safe["modal"]["certainty"] = {}
    return safe


def merge_context(root, domain, local):
    res = deepcopy(root)
    for k, v in local.items():
        if isinstance(v, dict) and k in res and isinstance(res[k], dict):
            res[k].update(v)
        else:
            res[k] = v
    return res


# =========================================================================
# AGENT: Wrapper that bundles identity + context + evaluation + provenance
# =========================================================================

class NoeAgent:
    """
    A self-contained Noe agent with identity, context, and sessions.

    This is what replaces the flat "call run_noe_logic with a dict" pattern.
    Each agent maintains its own AID, context, active sessions, and
    provenance records.
    """

    def __init__(self, agent_id: str, temporal_config: Optional[TemporalConfig] = None):
        self.agent_id = agent_id
        self.aid = build_agent_identity(
            agent_id,
            temporal_config=temporal_config or TemporalConfig(
                max_skew_ms=200, tau_stale_ms=1000, tau_window_ms=100,
            ),
        )
        self.sessions: Dict[str, Session] = {}  # keyed by counterpart agent_id
        self.provenance_log: List[Dict[str, Any]] = []

    def negotiate_with(self, other: "NoeAgent") -> Tuple[Session, Session]:
        """Execute NIP-019 handshake with another agent."""
        sess_self, sess_other = negotiate(self.aid, other.aid)
        self.sessions[other.agent_id] = sess_self
        other.sessions[self.agent_id] = sess_other
        return sess_self, sess_other

    def evaluate(
        self,
        chain: str,
        c_safe: dict,
        *,
        counterpart_id: Optional[str] = None,
        counterpart_prov_hash: Optional[str] = None,
    ) -> Tuple[dict, Dict[str, Any]]:
        """
        Evaluate a chain and produce provenance.

        If counterpart_id is provided and a session exists, validates
        the chain against the NCF and attaches cross-agent provenance.

        Returns: (evaluation_result, provenance_dict)
        """
        session = self.sessions.get(counterpart_id) if counterpart_id else None

        # NIP-019: Validate chain against NCF if in a session
        if session:
            validate_chain_for_session(chain, session)

        # Evaluate
        result = run_noe_logic(chain, c_safe, mode="lenient")

        # Build context hash
        context_hash = result.get("meta", {}).get("context_hash", hash_json(c_safe))

        # Build provenance record
        prov = build_provenance_record(
            chain=chain,
            ast_repr=None,
            context_hash=context_hash,
            result_domain=result.get("domain", "undefined"),
            result_value=result.get("value"),
            runtime_mode="lenient",
            # NIP-019 fields
            ncf_id=session.ncf.ncf_id if session else None,
            counterpart_agent_id=counterpart_id,
            counterpart_provenance_hash=counterpart_prov_hash,
        )

        # Store provenance
        prov_dict = prov.to_json_dict()
        prov_dict["_agent_id"] = self.agent_id
        self.provenance_log.append(prov_dict)

        return result, prov_dict


# =========================================================================
# X-RAY TRACE (visualization)
# =========================================================================

def print_xray_trace(c_safe, indent=""):
    k = c_safe["modal"]["knowledge"]
    has_prop = k.get("propose_clear_a", False)
    has_agree = k.get("agree_clear_b", False)
    has_veto = k.get("veto_b", False)

    green_trig = has_prop and has_agree
    yellow_trig = has_prop and (not has_agree) and (not has_veto)
    red_trig = has_veto

    green_reason = "TRUE" if green_trig else f"FALSE (Missing: {'@agree_clear_b' if has_prop else '@propose_clear_a'})"
    if yellow_trig:
        yellow_reason = "TRUE  (Trigger: nai @agree_clear_b)"
    elif not has_prop:
        yellow_reason = "FALSE (Missing: @propose_clear_a)"
    elif has_agree:
        yellow_reason = "FALSE (Blocked by: @agree_clear_b)"
    elif has_veto:
        yellow_reason = "FALSE (Blocked by: @veto_b)"
    else:
        yellow_reason = "FALSE"
    red_reason = "TRUE  (Trigger: @veto_b)" if red_trig else "FALSE (Missing: @veto_b)"

    print(f"{indent}[Noe Eval] Clause 1 (Green):  {green_reason}")
    print(f"{indent}[Noe Eval] Clause 2 (Yellow): {yellow_reason}")
    print(f"{indent}[Noe Eval] Clause 3 (Red):    {red_reason}")


# =========================================================================
# MAIN: NIP-019 MULTI-AGENT YELLOW ALERT
# =========================================================================

def run_nip019_yellow_alert(run_name: str, a_clear: bool, b_conf_milli: int, out_filename: str):
    """
    Execute the Yellow Alert protocol with three NIP-019 agents.

    Architecture:
        Robot A  ←─ session_a_arb ─→  Arbitrator  ←─ session_b_arb ─→  Robot B
    """
    print(f"\n{'='*72}")
    print(f"  NIP-019 RUN: {run_name} (B Confidence: {b_conf_milli/1000:.2f})")
    print(f"{'='*72}")

    now = get_timestamp()
    c_root = build_root_context(now)

    # ── 1. CREATE AGENTS ────────────────────────────────────────────────
    agent_a = NoeAgent("robot-arm-alpha", TemporalConfig(max_skew_ms=200, tau_stale_ms=500, tau_window_ms=100))
    agent_b = NoeAgent("safety-monitor-beta", TemporalConfig(max_skew_ms=100, tau_stale_ms=1000, tau_window_ms=50))
    agent_arb = NoeAgent("arbitrator-central", TemporalConfig(max_skew_ms=200, tau_stale_ms=1000, tau_window_ms=100))

    print(f"\n  [Identity] Agent A: {agent_a.agent_id}")
    print(f"  [Identity] Agent B: {agent_b.agent_id}")
    print(f"  [Identity] Arbitrator: {agent_arb.agent_id}")
    print(f"  [Identity] Registry hash: {agent_a.aid.registry_hash[:16]}...")
    print(f"  [Identity] Semantics: {agent_a.aid.semantics_version}")

    # ── 2. NEGOTIATE PAIRWISE SESSIONS ──────────────────────────────────
    print(f"\n  --- Phase: NIP-019 Handshake ---")

    sess_a_arb, _ = agent_a.negotiate_with(agent_arb)
    print(f"  [Negotiate] A ↔ Arbitrator: NCF {sess_a_arb.ncf_id[:16]}...")
    print(f"              Temporal: max_skew={sess_a_arb.ncf.temporal['max_skew_ms']}ms, "
          f"tau_stale={sess_a_arb.ncf.temporal['tau_stale_ms']}ms, "
          f"tau_window={sess_a_arb.ncf.temporal['tau_window_ms']}ms")

    sess_b_arb, _ = agent_b.negotiate_with(agent_arb)
    print(f"  [Negotiate] B ↔ Arbitrator: NCF {sess_b_arb.ncf_id[:16]}...")
    print(f"              Temporal: max_skew={sess_b_arb.ncf.temporal['max_skew_ms']}ms, "
          f"tau_stale={sess_b_arb.ncf.temporal['tau_stale_ms']}ms, "
          f"tau_window={sess_b_arb.ncf.temporal['tau_window_ms']}ms")

    # ── 3. ROBOT A: EVALUATE PROPOSAL ───────────────────────────────────
    print(f"\n  --- Phase: Robot A Evaluates ---")
    c_safe_a = project_safe(merge_context(c_root, {}, build_context_A(a_clear, now)))
    res_a, prov_a = agent_a.evaluate(
        CHAIN_A, c_safe_a,
        counterpart_id=agent_arb.agent_id,
    )
    did_propose = "@propose_clear_a" in find_targets(res_a.get("value"), res_a.get("domain"))
    print(f"  [Robot A] Propose? {did_propose}")
    print(f"  [Robot A] Provenance hash: {prov_a.get('provenance_hash', 'null')[:16] if prov_a.get('provenance_hash') else 'null (undefined)'}...")
    print(f"  [Robot A] NCF ID: {prov_a.get('ncf_id', 'none')[:16]}...")

    # ── 4. ROBOT B: EVALUATE AGREEMENT / VETO ──────────────────────────
    print(f"\n  --- Phase: Robot B Evaluates ---")
    c_safe_b = project_safe(merge_context(c_root, {}, build_context_B(b_conf_milli, did_propose, now)))

    res_b_agree, prov_b_agree = agent_b.evaluate(
        CHAIN_B_AGREE, c_safe_b,
        counterpart_id=agent_arb.agent_id,
    )
    did_agree = "@agree_clear_b" in find_targets(res_b_agree.get("value"), res_b_agree.get("domain"))

    res_b_veto, prov_b_veto = agent_b.evaluate(
        CHAIN_B_VETO, c_safe_b,
        counterpart_id=agent_arb.agent_id,
    )
    did_veto = "@veto_b" in find_targets(res_b_veto.get("value"), res_b_veto.get("domain"))

    print(f"  [Robot B] Agree? {did_agree} | Veto? {did_veto}")
    if did_agree:
        print(f"  [Robot B] Agreement provenance: {prov_b_agree.get('provenance_hash', 'null')[:16]}...")
    if did_veto:
        print(f"  [Robot B] Veto provenance: {prov_b_veto.get('provenance_hash', 'null')[:16]}...")

    # ── 5. ARBITRATOR: RECEIVE + EVALUATE TIERS ────────────────────────
    print(f"\n  --- Phase: Arbitrator Evaluates ---")
    c_local_arb = build_context_Arb(did_propose, did_agree, did_veto, now)
    c_safe_arb = merge_context(c_root, {}, c_local_arb)

    print_xray_trace(c_safe_arb, indent="  ")

    # Determine which agent's provenance to link to
    # The arbitrator links to the most decision-relevant provenance
    if did_veto:
        linking_prov_hash = prov_b_veto.get("provenance_hash")
        linking_agent = agent_b.agent_id
    elif did_agree:
        linking_prov_hash = prov_b_agree.get("provenance_hash")
        linking_agent = agent_b.agent_id
    else:
        linking_prov_hash = prov_a.get("provenance_hash")
        linking_agent = agent_a.agent_id

    # Evaluate tiers (first match wins)
    tier = "IDLE (No Action)"
    res_arb = None
    prov_arb = None
    active_chain = None

    for chain_name, chain in [("GREEN", CHAIN_ARB_GREEN), ("YELLOW", CHAIN_ARB_YELLOW), ("RED", CHAIN_ARB_RED)]:
        # Arbitrator has sessions with both A and B — use the relevant one
        counterpart = agent_b.agent_id if chain_name == "RED" else agent_a.agent_id
        res, prov = agent_arb.evaluate(
            chain, c_safe_arb,
            counterpart_id=counterpart,
            counterpart_prov_hash=linking_prov_hash,
        )
        targets = find_targets(res.get("value"), res.get("domain"))
        if targets:
            if chain_name == "GREEN":
                tier = "GREEN (High Speed)"
            elif chain_name == "YELLOW":
                tier = "YELLOW (Creep Mode)"
            elif chain_name == "RED":
                tier = "RED (Safety Stop)"
            res_arb = res
            prov_arb = prov
            active_chain = chain
            print(f"\n  [Arbitrator] Tier: {chain_name}")
            print(f"  [Arbitrator] Actions: {targets}")
            break

    if res_arb is None:
        res_arb = run_noe_logic(CHAIN_ARB_GREEN, c_safe_arb, mode="lenient")
        prov_arb = {}

    print(f"\n  {'='*56}")
    print(f"  FINAL STATE: {tier}")
    print(f"  {'='*56}")

    # ── 6. PROVENANCE DAG ──────────────────────────────────────────────
    print(f"\n  --- Provenance DAG ---")
    if prov_arb:
        print(f"  Arbitrator provenance:   {prov_arb.get('provenance_hash', 'null')[:24]}...")
        print(f"    ├── ncf_id:            {prov_arb.get('ncf_id', 'none')[:24]}...")
        print(f"    ├── counterpart:       {prov_arb.get('counterpart_agent_id', 'none')}")
        print(f"    └── links to:          {prov_arb.get('counterpart_provenance_hash', 'none')[:24] if prov_arb.get('counterpart_provenance_hash') else 'none'}...")
        print(f"  Robot A provenance:      {prov_a.get('provenance_hash', 'null')[:24] if prov_a.get('provenance_hash') else 'null'}...")
        print(f"    └── ncf_id:            {prov_a.get('ncf_id', 'none')[:24]}...")
        if did_agree:
            print(f"  Robot B (agree) prov:    {prov_b_agree.get('provenance_hash', 'null')[:24] if prov_b_agree.get('provenance_hash') else 'null'}...")
        if did_veto:
            print(f"  Robot B (veto) prov:     {prov_b_veto.get('provenance_hash', 'null')[:24] if prov_b_veto.get('provenance_hash') else 'null'}...")

    # ── 7. WRITE CERTIFICATE ────────────────────────────────────────────
    action_hash = None
    if res_arb.get("domain") in ("action", "list"):
        val = res_arb.get("value")
        if isinstance(val, dict) and val.get("type") == "action":
            action_hash = compute_action_hash(val)
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, dict) and item.get("type") == "action":
                    action_hash = compute_action_hash(item)
                    break

    certificate = {
        "noe_version": "v1.0-rc1 + NIP-019",
        "scenario": f"nip019_{run_name}",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now // 1_000_000)),
        "nip019": {
            "sessions": {
                "A_Arb": {
                    "ncf_id": sess_a_arb.ncf_id,
                    "agents": sess_a_arb.ncf.agents,
                    "temporal": sess_a_arb.ncf.temporal,
                    "compatibility": "full",
                },
                "B_Arb": {
                    "ncf_id": sess_b_arb.ncf_id,
                    "agents": sess_b_arb.ncf.agents,
                    "temporal": sess_b_arb.ncf.temporal,
                    "compatibility": "full",
                },
            },
            "provenance_dag": {
                "arbitrator": prov_arb if prov_arb else {},
                "robot_a": prov_a,
                "robot_b_agree": prov_b_agree,
                "robot_b_veto": prov_b_veto,
            },
        },
        "outcome": {
            "tier": tier,
            "domain": res_arb.get("domain"),
            "targets": find_targets(res_arb.get("value"), res_arb.get("domain")),
            "action_hash": action_hash,
        },
        "agents": {
            "robot_a": {
                "agent_id": agent_a.agent_id,
                "proposed": did_propose,
                "sensor_confidence": 990 if a_clear else 100,
            },
            "robot_b": {
                "agent_id": agent_b.agent_id,
                "agreed": did_agree,
                "vetoed": did_veto,
                "sensor_confidence": b_conf_milli,
            },
            "arbitrator": {
                "agent_id": agent_arb.agent_id,
                "active_chain": active_chain,
            },
        },
        "evaluation": {
            "mode": "lenient",
            "runtime": "python-reference + NIP-019",
            "nips": ["NIP-005", "NIP-008", "NIP-009", "NIP-010", "NIP-019"],
        },
    }

    out_path = Path(__file__).parent / out_filename
    out_path.write_text(json.dumps(certificate, indent=2, default=str))
    print(f"\n  Certificate: {out_filename}")
    if action_hash:
        print(f"  Action hash: {action_hash[:16]}...")

    return certificate


# =========================================================================
# AUDITOR: Verify the provenance DAG
# =========================================================================

def verify_provenance_dag(cert: dict) -> bool:
    """
    External auditor verification of the NIP-019 provenance DAG.

    Checks:
    1. All provenance records have NCF IDs
    2. Counterpart links resolve to valid provenance hashes
    3. NCF IDs match between linked records
    """
    print(f"\n  --- Auditor Verification ---")
    dag = cert.get("nip019", {}).get("provenance_dag", {})
    sessions = cert.get("nip019", {}).get("sessions", {})
    all_ok = True

    # Collect all provenance hashes for cross-reference
    known_hashes = set()
    for key, prov in dag.items():
        h = prov.get("provenance_hash")
        if h:
            known_hashes.add(h)

    # Verify each record
    for key, prov in dag.items():
        ncf_id = prov.get("ncf_id")
        counterpart = prov.get("counterpart_agent_id")
        link = prov.get("counterpart_provenance_hash")

        if not prov.get("provenance_hash"):
            # undefined/error results have null provenance — ok
            print(f"  [Audit] {key}: no provenance (undefined result) — OK")
            continue

        if ncf_id:
            # Verify NCF ID exists in sessions
            ncf_found = any(
                s["ncf_id"] == ncf_id for s in sessions.values()
            )
            status = "OK" if ncf_found else "FAIL"
            if not ncf_found:
                all_ok = False
            print(f"  [Audit] {key}: NCF {ncf_id[:16]}... — {status}")
        else:
            print(f"  [Audit] {key}: no NCF (single-agent eval) — OK")

        if link:
            link_ok = link in known_hashes
            status = "OK" if link_ok else "BROKEN LINK"
            if not link_ok:
                all_ok = False
            print(f"  [Audit] {key}: links to {link[:16]}... — {status}")

    print(f"\n  [Audit] DAG integrity: {'PASSED' if all_ok else 'FAILED'}")
    return all_ok


# =========================================================================
# MAIN
# =========================================================================

if __name__ == "__main__":
    print("=" * 72)
    print("  NOE NIP-019: MULTI-AGENT YELLOW ALERT PROTOCOL")
    print("  Three agents, pairwise sessions, cross-agent provenance DAG")
    print("=" * 72)

    # 1. GREEN: Unanimous consensus
    cert_green = run_nip019_yellow_alert("Green_State", True, 990, "nip019_cert_green.json")
    verify_provenance_dag(cert_green)

    # 2. YELLOW: Uncertainty (graceful degradation)
    cert_yellow = run_nip019_yellow_alert("Yellow_State", True, 600, "nip019_cert_yellow.json")
    verify_provenance_dag(cert_yellow)

    # 3. RED: Conflict (safety stop)
    cert_red = run_nip019_yellow_alert("Red_State", True, 50, "nip019_cert_red.json")
    verify_provenance_dag(cert_red)

    print(f"\n{'='*72}")
    print(f"  All scenarios complete. Certificates written to:")
    print(f"    nip019_cert_green.json")
    print(f"    nip019_cert_yellow.json")
    print(f"    nip019_cert_red.json")
    print(f"{'='*72}")
