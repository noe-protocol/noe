#!/usr/bin/env python3
"""
examples/auditor_demo/verify_shipment_stale.py

Demonstrates Safety Enforcement: STALE DATA REJECTION.
Same chain, same logic, but one sensor is STALE.

Flow:
  1. Build context with OLD timestamp for @human_clear.
  2. Project safe context -> Staleness check removes @human_clear.
  3. Evaluate chain -> FAILS because @human_clear is missing.
  4. Certificate proves why (valid audit trail of failure).
"""

import json
import time
from pathlib import Path
from copy import deepcopy

# Import from the main demo to reuse helpers
# Note: we need to import carefully since it's a script
import sys
sys.path.append(str(Path(__file__).parent))

from verify_shipment import (
    build_c_root, 
    build_c_domain, 
    merge_context_layers, 
    project_safe_context,
    evaluate_shipment_decision,
    build_certificate,
    replay_from_certificate,
    SHIPMENT_CHAIN
)

def build_c_local_stale(now_ts: float) -> dict:
    # 3 fresh sensors, 1 STALE sensor
    fresh_ts = int((now_ts - 0.5) * 1_000_000)
    stale_ts = int((now_ts - 600.0) * 1_000_000)  # 10 minutes old!
    
    return {
        "literals": {
            "@temperature_ok": {
                "value": True, "timestamp_us": fresh_ts, "source": "temp_probe_01", "certainty": 0.99
            },
            "@location_ok": {
                "value": True, "timestamp_us": fresh_ts, "source": "dock_rfid_07", "certainty": 0.95
            },
            "@chain_of_custody_ok": {
                "value": True, "timestamp_us": fresh_ts, "source": "custody_ledger", "certainty": 1.0
            },
            # STALE SENSOR
            "@human_clear": {
                "value": True, 
                "timestamp_us": stale_ts, 
                "source": "zone_lidar_02", 
                "certainty": 0.98
            },
            "@release_pallet": {
                "value": "action_target",
                "timestamp_us": fresh_ts,
                "type": "control_point"
            }
        },
        "temporal": {
            "now_us": int(now_ts * 1_000_000),
            "timestamp_us": int(now_ts * 1_000_000),
            "max_skew_us": 100_000
        },
        "spatial": {
            "thresholds": {"near": 2.0, "far": 10.0}, 
            "orientation": {"target": 0.0, "tolerance": 0.1}
        },
        "modal": {
            "knowledge": {
                "@temperature_ok": True, 
                "@location_ok": True, 
                "@chain_of_custody_ok": True, 
                "@human_clear": True
            },
            "belief": {},
            "certainty": {},
        },
        "delivery": {"status": "ready_for_release"},
        "audit": {},
        "rel": {},
        "demonstratives": {},
        "axioms": {}
    }

def main():
    print("=" * 70)
    print("NOE SAFETY DEMO: Staleness Rejection")
    print("=" * 70)
    print()
    
    now_ts = time.time()

    print("1. Building context (One sensor is 10 mins old)...")
    c_root = build_c_root()
    c_domain = build_c_domain()
    c_local_stale = build_c_local_stale(now_ts)

    print("2. Merging context layers...")
    c_merged = merge_context_layers(c_root, c_domain, c_local_stale)
    
    print("3. Projecting safe context (pi_safe)...")
    # This should remove @human_clear because it is stale
    c_safe = project_safe_context(c_merged)
    
    # Verify removal
    if "@human_clear" not in c_safe["literals"]:
        print("   ✅ Safety Kernel Removed Stale Literal: @human_clear")
    else:
        print("   ❌ FAILED: Stale literal was NOT removed!")
        exit(1)

    print("4. Evaluating Noe chain...")
    print(f"   Chain: {SHIPMENT_CHAIN}")
    
    # Needs @human_clear to be TRUE
    decision_result = evaluate_shipment_decision(c_safe)

    print(f"   Result Domain: {decision_result['domain']}")
    
    # Should be ERROR (ERR_EPISTEMIC_MISMATCH) because @human_clear is missing from knowledge
    # Note: pi_safe removes it from literals, but does it remove from modal.knowledge?
    # project_safe_context implementation handles modal.knowledge update too.
    
    if decision_result['domain'] in ("error", "undefined"):
         print(f"   ✅ Chain FAILED safely as expected: {decision_result.get('domain')} {decision_result.get('code', '')}")
         print(f"      Value: {decision_result.get('value')}")
    else:
         print(f"   ❌ FAILED: Chain succeeded but should have failed!")
         exit(1)

    print("5. Generating provenance certificate...")
    cert = build_certificate(
        c_root, c_domain, c_local_stale, c_safe, decision_result
    )

    cert["noe_version"] = "v1.0-rc1"

    out_path = Path(__file__).parent / "shipment_certificate_failure.json"
    out_path.write_text(json.dumps(cert, indent=2, ensure_ascii=False))
    
    print(f"   Written to: {out_path.name}")
    print()

    print("=" * 70)
    print("REPLAY VERIFICATION")
    print("=" * 70)
    print("Attempting to replay decision from certificate...")
    
    ok, msg = replay_from_certificate(out_path)
    print(msg)
    
    if not ok:
        print("❌ INTEGRITY CHECK FAILED")
        raise SystemExit(1)
    
    print()
    print("=" * 70)
    print("✅ SAFETY DEMO COMPLETE")
    print("=" * 70)
    print("This demonstrates:")
    print("  ✅ Safety Kernel (pi_safe) detects and removes stale data")
    print("  ✅ Runtime enforces epistemic Safety Floor (fails if data missing)")
    print("  ✅ Certificate proves EXACTLY why the decision failed")
    print()

if __name__ == "__main__":
    main()
