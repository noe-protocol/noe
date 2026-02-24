#!/usr/bin/env python3
"""
Demo Artifact Generator
========================

Produces a canonical decision object artifact for a demo.
Captures: canonical_chain, context_hash, domain_pack_hash, provenance.
"""

import json
import platform
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from noe.noe_parser import run_noe_logic
from noe.canonical import canonicalize_chain

def main():
    # Build a canonical demo context
    demo_context = {
        "literals": {
            "@safe_zone": True,
            "@robot_ready": True
        },
        "entities": {
            "me": {"type": "agent", "status": "active"}
        },
        "spatial": {
            "unit": "meters",
            "thresholds": {"near": 2.0, "far": 10.0},
            "cone": {"v_min": 0.1, "d_min": 0.1, "cos_theta": 0.707}
        },
        "temporal": {
            "now": 1000.0,
            "max_skew_ms": 100.0
        },
        "modal": {
            "knowledge": {},
            "belief": {},
            "certainty": {},
            "certainty_threshold": 0.8
        },
        "axioms": {
            "value_system": {
                "accepted": [],
                "rejected": []
            }
        },
        "value_system": {
            "axioms": {
                "value_system": {
                    "accepted": [],
                    "rejected": []
                }
            }
        },
        "rel": {},
        "demonstratives": {
            "dia": {"entity": "me"}
        },
        "delivery": {"status": {}},
        "audit": {"log": []}
    }
    
    # Test chains demonstrating v1.0 capabilities
    test_chains = [
        "@safe_zone an @robot_ready",  # K3 Logic
        "shi @safe_zone",               # Epistemic operator
        "mek dia",                       # Action with demonstrative
    ]
    
    print("=" * 60)
    print("NOE v1.0 DEMO ARTIFACT")
    print("=" * 60)
    print(f"Python: {platform.python_version()}")
    print(f"Platform: {platform.platform()}")
    print(f"Mode: strict")
    print(f"Debug: off")
    print("=" * 60)
    print()
    
    artifacts = []
    
    for chain in test_chains:
        result = run_noe_logic(chain, demo_context, mode="strict")
        
        # Extract canonical data
        canonical = canonicalize_chain(chain)
        
        artifact = {
            "input_chain": chain,
            "canonical_chain": canonical,
            "domain": result.get("domain"),
            "value": str(result.get("value"))[:100],  # Truncate for readability
            "meta": {
                "context_hash": result.get("meta", {}).get("context_hash"),
                "mode": result.get("meta", {}).get("mode"),
                "context_hashes": result.get("meta", {}).get("context_hashes")
            }
        }
        
        artifacts.append(artifact)
        
        print(f"Chain: {chain}")
        print(f"  Canonical: {canonical}")
        print(f"  Domain: {result.get('domain')}")
        print(f"  Value: {str(result.get('value'))[:80]}")
        print(f"  Context Hash: {result.get('meta', {}).get('context_hash', 'N/A')[:16]}...")
        print()
    
    # Write artifact file
    artifact_file = "demo_artifact.json"
    with open(artifact_file, 'w') as f:
        json.dump({
            "runtime": "Noe v1.0-rc1",
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "mode": "strict",
            "test_cases": artifacts
        }, f, indent=2)
    
    print("=" * 60)
    print(f"✓ Artifact saved to: {artifact_file}")
    print("=" * 60)

if __name__ == "__main__":
    main()
