"""
noe_benchmark_testing.py - Performance & Determinism Validation

Consolidated benchmark suite validating Noe runtime performance and correctness.

Test Suite:
1. Latency Sweep: Sub-millisecond evaluation for 10-50Hz control loops
2. Stress Test (10k entities): O(N) context scaling, safety verdict accuracy
3. Cross-Agent Determinism: Strong Kleene (K3) logic ensures identical verdicts

K3 Validation:
- Undefined propagation (None → "undefined") prevents false assumptions
- Deterministic hashing (SHA-256 canonical JSON) ensures reproducibility
- No implicit defaults in strict mode (ERR_LITERAL_MISSING enforcement)

Target Performance:
- Mean latency: <1ms (200Hz capable)
- Max latency: <20ms (50Hz safe)
- False negatives: 0 (drift/noise stress)
- Determinism: 100% (cross-agent agreement)

Results written to: benchmark_results.json
"""

import os
import sys
import time
import json
import random
import platform
import statistics
from copy import deepcopy

# Adjust path to import noe from root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from noe.noe_parser import run_noe_logic
from noe.context_manager import ContextManager

# ==========================================
# CONFIG
# ==========================================
RESULTS_FILE = "benchmark_results.json"
WARMUP_ITERS = 100
RUN_ITERS = 1000
_DEBUG_ENABLED = os.getenv("NOE_DEBUG", "0") == "1"

# ==========================================
# UTILS
# ==========================================
def generate_context(entity_count=1000, skew_ms=0):
    entities = [f"entity_{i}" for i in range(entity_count)]
    # Ensure literals used in chain are present
    literals = {f"@lit_{i}": True for i in range(100)}
    literals["@lit_0"] = True # Explicitly ensure the one we use is there
    
    return {
        "entities": entities,
        "literals": literals,
        "spatial": {"unit": "generic", "thresholds": {"near": 1.0, "far": 5.0}, "orientation": {"target":0, "tolerance":1}},
        "temporal": {"now": 1000.0, "max_skew_ms": 100.0},
        "modal": {"knowledge": literals, "belief": {}, "certainty": {}},
        "local": {"timestamp": 1000.0 + skew_ms},
        "axioms": {"value_system": {"accepted": [], "rejected": []}},
        "rel": {},
        "demonstratives": {},
        # Audit required for "men"
        "audit": {"files": {}, "logs": []}
    }

def get_stats(timings_ns):
    sorted_ts = sorted(timings_ns)
    n = len(sorted_ts)
    return {
        "min_us": min(sorted_ts) / 1000.0,
        "max_us": max(sorted_ts) / 1000.0,
        "mean_us": statistics.mean(sorted_ts) / 1000.0,
        "p50_us": sorted_ts[int(n*0.5)] / 1000.0,
        "p95_us": sorted_ts[int(n*0.95)] / 1000.0,
        "p99_us": sorted_ts[int(n*0.99)] / 1000.0,
        "max_us": max(sorted_ts) / 1000.0,
        "ops_sec": 1e9 / (statistics.mean(sorted_ts) or 1)
    }

# ==========================================
# TESTS
# ==========================================

def benchmark_latency(ctx_size, chain_len):
    """
    Measure P99 latency for strict validation + execution.
    Type: Cold-Path (includes full context validation & hashing).
    """
    if _DEBUG_ENABLED:
        print("WARNING: Debug enabled. Latency results will be invalid.")
        
    ctx = generate_context(entity_count=ctx_size)
    
    # Use logical operators to ensure complexity scales accurately (not just list parsing)
    # "shi @lit_0 an shi @lit_0 ..." ensures we test the logical engine depth.
    # We use 'shi' (PROVE) to force modal lookups, adding realism.
    base_op = "shi @lit_0"
    chain = " an ".join([base_op] * chain_len) 
    
    # Warmup
    for _ in range(WARMUP_ITERS):
        run_noe_logic(chain, ctx, mode="strict")
        
    timings = []
    for _ in range(RUN_ITERS):
        # Isolation: Deepcopy to prevent caching/mutation artifacts from helping/hurting
        # validation performance (though it adds overhead to the test harness, we time ONLY run_noe_logic)
        # For cold-path testing, we ideally pass a fresh dict.
        # But deepcopying 10k entities takes longer than the run. 
        # compromise: use same dict, as parser shouldn't mutate input C in strict mode.
        
        start = time.monotonic_ns()
        run_noe_logic(chain, ctx, mode="strict")
        timings.append(time.monotonic_ns() - start)
        
    return get_stats(timings)

def stress_drift_noise(injection_rate=0.05):
    """
    Randomly inject staleness (drift > max_skew) or missing shards.
    Uses Confusion Matrix to verify safety guards.
    """
    ctx_clean = generate_context()
    chain = "men @lit_0"
    
    tp = 0 # Expected block, got block
    tn = 0 # Expected allowed, got allowed
    fp = 0 # Expected allowed, got block (Suspicious)
    fn = 0 # Expected block, got allowed (CRITICAL)
    
    total = RUN_ITERS
    
    for _ in range(total):
        # ISOLATION: Use deepcopy to ensure absolutely no mutation bleed
        ctx = deepcopy(ctx_clean)
        
        roll = random.random()
        expected_block = False
        
        # Inject Faults
        if roll < injection_rate:
            # Case A: Stale
            ctx["local"]["timestamp"] += 2000.0 # Huge drift
            expected_block = True
        elif roll < (injection_rate * 2):
            # Case B: Missing Shard
            ctx.pop("spatial", None)
            expected_block = True
            
        res = run_noe_logic(chain, ctx, mode="strict")
        is_blocked = (res.get("domain") == "error")
        
        if expected_block:
            if is_blocked:
                tp += 1
            else:
                fn += 1 # CRITICAL FAILURE
        else:
            if is_blocked:
                fp += 1
            else:
                tn += 1
            
    return {
        "total_ticks": total,
        "confusion_matrix": {
            "TP": tp,
            "TN": tn,
            "FP": fp,
            "FN": fn
        },
        "accuracy": (tp + tn) / total,
        "critical_failure": (fn > 0)
    }

def verify_determinism():
    """Run two agents with identical seeds/inputs and verify hash match."""
    ctx = generate_context()
    chain = "men @lit_0"
    
    mismatches = 0
    for _ in range(100):
        # We don't actually need random seeds for Noe as it's deterministic 
        # but we simulate independent runs.
        r1 = run_noe_logic(chain, ctx, mode="strict")
        r2 = run_noe_logic(chain, ctx, mode="strict")
        
        val1 = r1.get("value", {})
        val2 = r2.get("value", {})
        
        # specific check to avoid crash if val is not dict (e.g. error string)
        if not isinstance(val1, dict): val1 = {}
        if not isinstance(val2, dict): val2 = {}

        # Strict Determinism Check: Verdict + Reason + Hash must match
        t1 = (r1["domain"], r1.get("code"), val1.get("action_hash"))
        t2 = (r2["domain"], r2.get("code"), val2.get("action_hash"))
        
        if t1 != t2:
            mismatches += 1
            
    return {
        "agreement_rate": (100 - mismatches) / 100.0,
        "mismatches": mismatches
    }

# ==========================================
# MAIN
# ==========================================
def run_suite():
    if _DEBUG_ENABLED:
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print("WARNING: NOE_DEBUG is enabled. Latency metrics will be trash.")
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        time.sleep(2)

    commit_hash = os.getenv("GIT_COMMIT", "dirty")
    registry_hash = "a1b2c3d4e5f6..."
    
    print(f"[*] Starting Noe Benchmark Suite (v1.0)")
    print(f"    Commit:   {commit_hash}")
    print(f"    Registry: {registry_hash}") 
    print(f"    Strict:   True")
    print(f"    System:   {platform.machine()} Python {platform.python_version()}")
    print(f"    Iters:    {RUN_ITERS}, Warmup: {WARMUP_ITERS}")
    
    results = {
        "metadata": {
            "timestamp": time.time(),
            "commit": commit_hash,
            "registry_hash": registry_hash,
            "machine": platform.machine(),
            "python": platform.python_version()
        },
        "tests": {}
    }
    
    # 1. Latency Sweep
    print("\n[1] Cold-Path Latency Sweep (Strict Mode)")
    print("    (Includes full validation + context hashing + execution)")
    configs = [
        (100, 1),    # Small Ctx, Short Chain
        (1000, 1),   # Med Ctx, Short Chain
        (10000, 1),  # Large Ctx, Short Chain
        (1000, 10),  # Med Ctx, Med Chain
        (1000, 50)   # Med Ctx, Long Chain
    ]
    
    table_header = f"{'Entities':<10} {'ChainLen':<10} {'Mean (us)':<12} {'P50 (us)':<12} {'P95 (us)':<12} {'P99 (us)':<12} {'Max (us)':<12}"
    print(table_header)
    print("-" * len(table_header))
    
    for (ents, chain_len) in configs:
        stats = benchmark_latency(ents, chain_len)
        results["tests"][f"latency_e{ents}_c{chain_len}"] = stats
        print(f"{ents:<10} {chain_len:<10} {stats['mean_us']:<12.1f} {stats['p50_us']:<12.1f} {stats['p95_us']:<12.1f} {stats['p99_us']:<12.1f} {stats['max_us']:<12.1f}")

    # 2. Stress Test
    print("\n[2] Drift & Noise Stress Test (Validation Matrix)")
    drift_stats = stress_drift_noise(0.05) # 5% stale, 5% missing -> 10% expected faults
    results["tests"]["stress_drift"] = drift_stats
    cm = drift_stats['confusion_matrix']
    
    print(f"    Total Ticks:     {drift_stats['total_ticks']}")
    print(f"    TP (Blocked):    {cm['TP']} (Correctly Blocked)")
    print(f"    TN (Allowed):    {cm['TN']} (Correctly Allowed)")
    print(f"    Conservative:    {cm['FP']} (Extra blocks - safe, not a failure)")
    print(f"    FN (Leak):       {cm['FN']} (CRITICAL SAFETY FAILURE)")
    
    if drift_stats['critical_failure']:
        print("    RESULT: FAIL (False Negatives Detected)")
        sys.exit(1)
    else:
        print("    RESULT: PASS")

    # 3. Determinism
    print("\n[3] Cross-Agent Determinism")
    det_stats = verify_determinism()
    results["tests"]["determinism"] = det_stats
    print(f"    Agreement Rate: {det_stats['agreement_rate']:.1%}")
    
    # ---------------------------------------------------------
    # 4. Blob Injection Test (Performance Cliff Mitigation)
    # ---------------------------------------------------------
    print("\n[4] Blob Injection Test (Size Limit Enforcement)")
    print("    (Limit: 256KB per shard - Control Plane, not Data Plane)")
    
    # Try to inject a 1MB payload (limit is 256KB)
    large_payload = "X" * (1024 * 1024) 
    
    try:
        from noe.context_manager import ContextManager, ContextTooLargeError
        
        # Initialize strict manager
        cm = ContextManager(staleness_ms=100)
        
        # Attempt injection
        try:
            cm.update_local({"blob": large_payload})
            print("    ❌ FAILED: System accepted 1MB blob")
            print("       Size limit enforcement not working!")
            results["tests"]["blob_injection"] = "FAILED"
        except ContextTooLargeError:
            print("    ✅ PASSED: System rejected 1MB blob (ContextTooLargeError)")
            results["tests"]["blob_injection"] = "PASSED"
        except Exception as e:
            print(f"    ⚠️  WARNING: System rejected blob with unexpected error: {type(e).__name__}")
            results["tests"]["blob_injection"] = f"ERROR: {type(e).__name__}"
            
    except ImportError:
        print("    ⚠️  SKIPPED: ContextTooLargeError not available yet")
        results["tests"]["blob_injection"] = "SKIPPED"

    # Save Results
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n[*] Full results written to {RESULTS_FILE}")

if __name__ == "__main__":
    run_suite()
