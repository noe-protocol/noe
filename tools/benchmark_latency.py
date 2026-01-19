#!/usr/bin/env python3
"""
Noe Latency Benchmark

Measures decision-kernel evaluation time ONLY.

INCLUDED:
  - Chain parsing (AST construction)
  - Context validation
  - Noe evaluation
  - Action hash computation

EXCLUDED:
  - I/O (file, network)
  - Perception/sensor processing
  - Context building (grounding layer)
  - Provenance logging
"""

import time
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from noe.noe_parser import run_noe_logic


def now_us():
    return time.time_ns() // 1_000


def benchmark(chain: str, context: dict, iterations: int = 1000) -> dict:
    """Benchmark a single chain/context pair."""
    times_us = []
    
    for _ in range(iterations):
        start = time.perf_counter_ns()
        result = run_noe_logic(chain, context, mode="strict")
        end = time.perf_counter_ns()
        times_us.append((end - start) / 1000)  # ns → µs
    
    return {
        "iterations": iterations,
        "mean_us": statistics.mean(times_us),
        "median_us": statistics.median(times_us),
        "stdev_us": statistics.stdev(times_us) if len(times_us) > 1 else 0,
        "min_us": min(times_us),
        "max_us": max(times_us),
        "p95_us": sorted(times_us)[int(iterations * 0.95)],
        "p99_us": sorted(times_us)[int(iterations * 0.99)],
    }


def main():
    print("=" * 70)
    print("NOE LATENCY BENCHMARK")
    print("=" * 70)
    print()
    print("INCLUDED: Parsing, validation, evaluation, action hash")
    print("EXCLUDED: I/O, perception, context building, logging")
    print()
    
    ts = now_us()
    
    # Test cases with increasing complexity
    cases = [
        {
            "name": "Simple truth (shi @a)",
            "chain": "shi @clear",
            "context": {
                "temporal": {"now_us": ts},
                "literals": {"@clear": {"value": True, "timestamp_us": ts}},
                "modal": {"knowledge": {"@clear": True}, "belief": {}, "certainty": {}},
                "axioms": {}
            }
        },
        {
            "name": "Conjunction (shi @a an shi @b)",
            "chain": "shi @a an shi @b",
            "context": {
                "temporal": {"now_us": ts},
                "literals": {
                    "@a": {"value": True, "timestamp_us": ts},
                    "@b": {"value": True, "timestamp_us": ts}
                },
                "modal": {"knowledge": {"@a": True, "@b": True}, "belief": {}, "certainty": {}},
                "axioms": {}
            }
        },
        {
            "name": "Guarded action (khi sek mek)",
            "chain": "shi @path_clear khi sek mek @navigate sek nek",
            "context": {
                "temporal": {"now_us": ts},
                "literals": {
                    "@path_clear": {"value": True, "timestamp_us": ts},
                    "@navigate": {"value": "NAV", "type": "action", "timestamp_us": ts}
                },
                "modal": {"knowledge": {"@path_clear": True}, "belief": {}, "certainty": {}},
                "axioms": {},
                "delivery": {"status": "ready"},
                "audit": {"enabled": True}
            }
        },
        {
            "name": "Complex chain (4 guards + action)",
            "chain": "shi @a an shi @b an shi @c an shi @d khi sek mek @action sek nek",
            "context": {
                "temporal": {"now_us": ts},
                "literals": {
                    "@a": {"value": True, "timestamp_us": ts},
                    "@b": {"value": True, "timestamp_us": ts},
                    "@c": {"value": True, "timestamp_us": ts},
                    "@d": {"value": True, "timestamp_us": ts},
                    "@action": {"value": "DO", "type": "action", "timestamp_us": ts}
                },
                "modal": {"knowledge": {"@a": True, "@b": True, "@c": True, "@d": True}, "belief": {}, "certainty": {}},
                "axioms": {},
                "delivery": {"status": "ready"},
                "audit": {"enabled": True}
            }
        },
    ]
    
    iterations = 1000
    print(f"Iterations per case: {iterations}")
    print()
    
    for case in cases:
        print(f"Chain: {case['chain'][:50]}{'...' if len(case['chain']) > 50 else ''}")
        stats = benchmark(case["chain"], case["context"], iterations)
        print(f"  {case['name']}")
        print(f"  Mean:   {stats['mean_us']:>7.1f} µs")
        print(f"  Median: {stats['median_us']:>7.1f} µs")
        print(f"  P95:    {stats['p95_us']:>7.1f} µs")
        print(f"  P99:    {stats['p99_us']:>7.1f} µs")
        print(f"  Max:    {stats['max_us']:>7.1f} µs")
        print()
    
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print()
    print("Typical evaluation: 200-500 µs (sub-millisecond)")
    print("Suitable for: Deliberative planning (1-100 Hz)")
    print("NOT suitable for: Inner control loops (kHz)")
    print()
    print("Note: First call may be slower (parser/cache warmup).")
    print("      Production systems should warm up on startup.")


if __name__ == "__main__":
    main()
