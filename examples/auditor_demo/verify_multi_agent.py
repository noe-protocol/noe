import sys
import json
import time
import hashlib
from pathlib import Path
from copy import deepcopy
from typing import Dict, Any, List

# Add project root to sys.path
sys.path.append(str(Path(__file__).parent.parent.parent))

from noe.noe_parser import run_noe_logic
from noe.provenance import compute_action_hash
from noe.canonical import canonical_json

def hash_json(obj):
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def compute_context_hashes(c_root, c_domain, c_local, c_safe):
    """Compute hashes for all context layers."""
    return {
        "root": hash_json(c_root),
        "domain": hash_json(c_domain),
        "local": hash_json(c_local),
        "safe": hash_json(c_safe),
    }


def build_certificate(
    scenario_name: str,
    chain_str: str,
    c_root: dict,
    c_domain: dict,
    c_local: dict,
    c_safe: dict,
    result: dict
) -> dict:
    """Refactored certificate builder (Strict Schema Compliance)."""
    # compute_context_hashes removed - use ContextManager
    
    now_ts = c_root["temporal"]["timestamp"]
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_ts))
    
    
    # Compute hashes for all layers
    hashes = compute_context_hashes(c_root, c_domain, c_local, c_safe)
 

    action_hash = None
    if result.get("domain") == "list" and result.get("value"):
        # Extract first action from list
        for item in result["value"]:
            if isinstance(item, dict) and item.get("type") == "action":
                action_hash = compute_action_hash(item)
                break
    elif result.get("domain") == "action" and isinstance(result.get("value"), dict):
        action_hash = compute_action_hash(result["value"])

    return {
        "noe_version": "v1.0-rc1",
        "scenario": scenario_name,
        "chain": chain_str,
        "created_at": now_iso,
        "context_hashes": hashes,
        "context_snapshot": {
            "root": c_root,
            "domain": c_domain,
            "local": c_local,
            "safe": c_safe
        },
        "outcome": {
            "domain": result.get("domain"),
            "value": result.get("value"),
            "action_hash": action_hash
        },
        "evaluation": {
            "mode": "lenient", # Multi-agent uses lenient
            "runtime": "python-reference",
            "nip": ["NIP-005", "NIP-009", "NIP-010", "NIP-014"]
        },
        "signatures": { "validator_signature": "simulated_rsa_sign(action_hash)" }
    }

# ---------------------------------------------------------------------------
# CHAINS: The "Yellow Alert" Protocol
# ---------------------------------------------------------------------------

# Robot A (Proposer)
CHAIN_A = (
    "shi @human_clear_a khi "
    "sek mek @propose_clear_a men @session_safety_log sek nek"
)

# Robot B (Verifier)
# - Validates A's Proposal + Checks Own Sensor
# - Only signs Agreement if HIGH confidence
# - Signs Veto if HIGH confidence of obstacle
CHAIN_B_AGREE = (
    "shi @propose_clear_a an shi @human_clear_b khi "
    "sek mek @agree_clear_b sek nek"
)
CHAIN_B_VETO = (
    "shi @human_detected_b khi "
    "sek mek @veto_b sek nek"
)

# Arbitrator: 3-Tier Liveness Logic
CHAIN_ARB = (
    # TIER 1: GREEN (High Speed)
    # Unanimous Consensus: A Proposes + B Agrees
    "shi @propose_clear_a an shi @agree_clear_b khi sek mek @enable_high_speed sek "
    "shi @propose_clear_a an nai shi @agree_clear_b an nai shi @veto_b khi sek mek @enable_creep_speed mek @emit_warning_signal sek "
    "shi @veto_b khi sek mek @safe_stop men @request_human_supervisor sek "
    "nek"
)

# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def get_timestamp(): return time.time()

def build_sensor_literal(val, conf, source, now_s):
    # HARDENING: Add mock signature to prove where the check happens
    sig = f"sig_rsa_sha256_{hashlib.sha256(str(now_s).encode()).hexdigest()[:8]}"
    return { "value": val, "confidence": conf, "timestamp": now_s, "source": source, "signature": sig }

# Strict Execution Gate (v1.0-rc): Only execute if domain is action or list of actions.
def find_targets(result_val, result_domain=None):
    found = []
    
    # If domain is provided, enforce strict execution gate
    if result_domain and result_domain not in ["action", "list"]:
        # undefined / error / boolean / number / int64 => NO SIDE EFFECTS
        return []
        
    if isinstance(result_val, list):
        for item in result_val:
            # Recursive calls might not pass domain, but the top-level gate handles the main check.
            found.extend(find_targets(item))
    elif isinstance(result_val, dict):
        # Case 1: Raw Action Object (from 'list' domain)
        if result_val.get("type") == "action" and isinstance(result_val.get("target"), dict):
            found.append(result_val["target"].get("value"))
        # Case 2: Domain Object wrapping action (single action domain)
        if result_val.get("domain") == "action" and "value" in result_val:
             if isinstance(result_val["value"], dict):
                  found.append(result_val["value"].get("target"))
    return found

# ---------------------------------------------------------------------------
# CONTEXT BUILDERS
# ---------------------------------------------------------------------------

def build_root_context(now_s: float):
    return {
        "temporal": { "max_skew_ms": 5000, "now": now_s, "timestamp": now_s },
        "constants": { "min_confidence": { "knowledge": 0.90, "belief": 0.40 } },
        "audit": { "files": { "@session_safety_log": "verified" } },
        "delivery": { "status": { "@propose_clear_a": "pending" } },
        "spatial": { "thresholds": {"near": 1.0, "far": 10.0}, "regions": {}, "orientation": {"target":0, "tolerance":0.1} },
        "axioms": { "value_system": {} },
        "rel": {},
        "demonstratives": { "proximal": {}, "distal": {} }
    }

def build_context_A(clear: bool, now_s: float):
    return {
        "literals": {
            "@human_clear_a": build_sensor_literal(clear, 0.99 if clear else 0.1, "mob_a_fusion", now_s),
            "@propose_clear_a": { "value": "PROPOSE_CLEAR_A", "type": "proposal" },
            "@session_safety_log": { "value": "LOG", "type": "log" }
        },
        "temporal": { "now": now_s, "timestamp": now_s, "max_skew_ms": 5000 },
        "modal": { "knowledge": {}, "belief": {}, "certainty": {} }
    }

def build_context_B(clear_confidence: float, proposal_received: bool, now_s: float):
    # Robot B Logic:
    # If confidence > 0.90 -> Knows Clear -> Agree
    # If confidence < 0.10 (implied human) -> Knows Detected -> Veto
    # If confidence 0.40..0.80 -> Uncertain -> Silence (No Agree, No Veto)
    
    literals = {
        "@propose_clear_a": { "value": "PROPOSE_CLEAR_A", "type": "proposal" },
        "@agree_clear_b": { "value": "AGREE_CLEAR_B", "type": "agreement" },
        "@veto_b": { "value": "VETO_B", "type": "veto" },
        # Sensors
        "@human_clear_b": build_sensor_literal(True, clear_confidence, "stat_b_lidar", now_s),
        # Inverse sensor for veto logic (if clear is low, detected is high)
        "@human_detected_b": build_sensor_literal(True, 1.0 - clear_confidence, "stat_b_lidar", now_s)
    }
    
    ctx = {
        "literals": literals,
        "temporal": { "now": now_s, "timestamp": now_s, "max_skew_ms": 5000 },
        "modal": { "knowledge": {}, "belief": {}, "certainty": {} }
    }
    
    if proposal_received:
        ctx["modal"]["knowledge"]["@propose_clear_a"] = True
        
    return ctx

def build_context_Arb(prop_A: bool, agree_B: bool, veto_B: bool, now_s: float):
    knowledge = {
        "@propose_clear_a": bool(prop_A),
        "@agree_clear_b": bool(agree_B),
        "@veto_b": bool(veto_B)
    }

    return {
        "literals": {
            # Actions
            "@enable_high_speed": { "value": "SET_SPEED_1.5", "type": "control" },
            "@enable_creep_speed": { "value": "SET_SPEED_0.1", "type": "control" },
            "@emit_warning_signal": { "value": "BEEP_BEEP", "type": "alert" },
            "@safe_stop": { "value": "STOP_IMMEDIATE", "type": "safety" },
            "@request_human_supervisor": { "value": "CALL_HUMAN", "type": "alert" },
            # Messages
            "@propose_clear_a": { "value": True, "type": "message" }, 
            "@agree_clear_b": { "value": True, "type": "message" },
            "@veto_b": { "value": True, "type": "message" },
        },
        "temporal": { "now": now_s, "timestamp": now_s, "max_skew_ms": 5000 },
        "modal": { "knowledge": knowledge, "belief": {}, "certainty": {} }
    }

# MOCK: In production, this verifies an Ed25519 signature from the TPM
def verify_hardware_signature(literal: dict) -> bool:
    # Strict Mode: All sensors must be signed
    if "signature" not in literal:
        # Allow internal system messages (they are trusted/generated by kernel)
        if literal.get("type") in ["message", "control", "alert", "safety", "log", "proposal", "agreement", "veto"]:
            return True
        return False 
    
    # Simulating the check:
    # return crypto.verify(literal["signature"], literal["value"] + literal["timestamp"])
    return True 

def project_safe(c_merged):
    """
    Safe context projection with hardware signature verification.
    
    v1.0 Update: Inline epistemic projection (project_epistemic removed from API).
    """
    safe = deepcopy(c_merged)
    literals = safe.get("literals", {})
    
    # 1. Hardware Signature Verification (Anti-Gaming)
    valid_literals = {}
    for k, v in literals.items():
        if isinstance(v, dict):
             if not verify_hardware_signature(v):
                 print(f"  [Security] ❌ REJECTED {k}: Invalid Hardware Signature")
             else:
                 sig_frag = v.get("signature", "internal")[:16] + "..."
                 print(f"  [Security] ✅ Verified {k} ({sig_frag})")
                 valid_literals[k] = v
        else:
            valid_literals[k] = v
            
    safe["literals"] = valid_literals
    
    # 2. Epistemic Projection (v1.0 inline implementation)
    # Convert confidence-annotated literals to modal knowledge/belief
    
    # Start with existing modal state (preserve manual additions)
    if "modal" not in safe:
        safe["modal"] = {}
    
    knowledge = dict(safe["modal"].get("knowledge", {}))  # Copy existing
    belief = dict(safe["modal"].get("belief", {}))  # Copy existing
    
    for k, v in valid_literals.items():
        if isinstance(v, dict) and "confidence" in v:
            conf = v.get("confidence", 0.0)
            val = v.get("value")
            
            # Knowledge threshold: 0.90
            if conf >= 0.90:
                knowledge[k] = val
            # Belief threshold: 0.40
            elif conf >= 0.40:
                belief[k] = val
            # Below 0.40: ignored (too uncertain)
    
    # Update modal shard (merge, don't replace)
    safe["modal"]["knowledge"] = knowledge
    safe["modal"]["belief"] = belief
    if "certainty" not in safe["modal"]:
        safe["modal"]["certainty"] = {}
    
    return safe

def merge_context(root, domain, local):
    res = deepcopy(root)
    for k, v in local.items():
        if isinstance(v, dict) and k in res and isinstance(res[k], dict): res[k].update(v)
        else: res[k] = v
    return res

# ---------------------------------------------------------------------------
# MAIN SIMULATION LOOP
# ---------------------------------------------------------------------------

def print_xray_trace(c_safe):
    """
    Shows the 'X-Ray' view of the Noe evaluation.
    Proves which clauses triggered based on the Epistemic State.
    """
    k = c_safe["modal"]["knowledge"]
    
    # 1. Green Logic: shi @propose_clear_a an shi @agree_clear_b
    has_prop = k.get("@propose_clear_a", False)
    has_agree = k.get("@agree_clear_b", False)
    green_trig = has_prop and has_agree
    
    green_reason = "TRUE" if green_trig else f"FALSE (Missing: {'@agree_clear_b' if has_prop else '@propose_clear_a'})"
    
    # 2. Yellow Logic: shi @propose_clear_a an nai (shi @agree_clear_b) an nai (shi @veto_b)
    has_veto = k.get("@veto_b", False)
    # Note: nai(P) is true if P is NOT in Knowledge.
    yellow_trig = has_prop and (not has_agree) and (not has_veto)
    
    yellow_reason = ""
    if yellow_trig:
        yellow_reason = "TRUE  (Trigger: nai @agree_clear_b)"
    else:
        if not has_prop: yellow_reason = "FALSE (Missing: @propose_clear_a)"
        elif has_agree:  yellow_reason = "FALSE (Blocked by: @agree_clear_b)" # Yellow requires ABSENCE of agreement
        elif has_veto:   yellow_reason = "FALSE (Blocked by: @veto_b)"
        
    # 3. Red Logic: shi @veto_b
    red_trig = has_veto
    red_reason = "TRUE  (Trigger: @veto_b)" if red_trig else "FALSE (Missing: @veto_b)"

    print(f"[Noe Eval] Clause 1 (Green):  {green_reason}")
    print(f"[Noe Eval] Clause 2 (Yellow): {yellow_reason}")
    print(f"[Noe Eval] Clause 3 (Red):    {red_reason}")
    print()

def run_yellow_alert_demo(run_name, a_clear, b_confidence, out_filename):
    print(f"\n--- RUN: {run_name} (B Conf: {b_confidence}) ---")
    now = get_timestamp()
    
    # 1. Robot A
    c_root = build_root_context(now)
    c_safe_a = project_safe(merge_context(c_root, {}, build_context_A(a_clear, now)))
    res_a = run_noe_logic(CHAIN_A, c_safe_a, mode="lenient")
    did_propose = "PROPOSE_CLEAR_A" in find_targets(res_a.get("value"), res_a.get("domain"))
    print(f"[Robot A] Propose? {did_propose}")
    
    # 2. Robot B
    c_safe_b = project_safe(merge_context(c_root, {}, build_context_B(b_confidence, did_propose, now)))
    
    # B Check Agreement
    res_b_agree = run_noe_logic(CHAIN_B_AGREE, c_safe_b, mode="lenient")
    did_agree = "AGREE_CLEAR_B" in find_targets(res_b_agree.get("value"), res_b_agree.get("domain"))
    
    # B Check Veto
    res_b_veto = run_noe_logic(CHAIN_B_VETO, c_safe_b, mode="lenient")
    did_veto = "VETO_B" in find_targets(res_b_veto.get("value"), res_b_veto.get("domain"))
    
    print(f"[Robot B] Agree? {did_agree} | Veto? {did_veto}")
    
    # 3. Arbitrator
    c_local_arb = build_context_Arb(did_propose, did_agree, did_veto, now)
    c_safe_arb = merge_context(c_root, {}, c_local_arb)
    
    # [VISUALIZATION] X-Ray Trace
    print_xray_trace(c_safe_arb)
    
    res_arb = run_noe_logic(CHAIN_ARB, c_safe_arb, mode="strict")
    
    outcomes = find_targets(res_arb.get("value"), res_arb.get("domain"))
    print(f"[Arbitrator] Outcome Actions: {outcomes}")
    
    # Determine Tier
    tier = "UNKNOWN"
    if "SET_SPEED_1.5" in outcomes: tier = "GREEN (High Speed)"
    elif "SET_SPEED_0.1" in outcomes: tier = "YELLOW (Creep Mode)"
    elif "STOP_IMMEDIATE" in outcomes: tier = "RED (Safety Stop)"
    else: tier = "IDLE (No Action)"
    
    print(f"✅ FINAL STATE: {tier}")
    
    cert = build_certificate(f"arb_{run_name}", CHAIN_ARB, c_root, {}, c_local_arb, c_safe_arb, res_arb)
    Path(__file__).parent.joinpath(out_filename).write_text(json.dumps(cert, indent=2))
    print(f"   Written to: {out_filename}")
    if cert.get("outcome") and cert["outcome"].get("action_hash"):
         print(f"   action_hash: {cert['outcome']['action_hash'][:16]}...")

if __name__ == "__main__":
    print("========================================================================")
    print(" NOE LIVENESS POLICY: THE 'YELLOW ALERT' PROTOCOL")
    print("========================================================================")
    
    # 1. GREEN: Unanimous
    run_yellow_alert_demo("Green_State", True, 0.99, "cert_green.json")
    
    # 2. YELLOW: Uncertainty (Graceful Degradation)
    # A sees clear, B is unsure (0.60) -> No Agree, No Veto -> Creep
    run_yellow_alert_demo("Yellow_State", True, 0.60, "cert_yellow.json")
    
    # 3. RED: Conflict (Safe Stop)
    # A sees clear, B sees Human (Conf 0.05 on Clear -> 0.95 on Detected)
    run_yellow_alert_demo("Red_State", True, 0.05, "cert_red.json")
