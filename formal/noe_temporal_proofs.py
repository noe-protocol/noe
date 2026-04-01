#!/usr/bin/env python3
"""
Formal Verification of Noe Temporal Safety Properties
using Z3 SMT Solver.

Proves properties of Noe's temporal safety layer as specified in
NIP-008 and NIP-019. The temporal layer ensures stale and future
evidence is rejected, and multi-agent negotiation takes the
stricter bound.

Prover: Z3 4.12.2
Domain: Noe Protocol — NIP-008, NIP-019
"""

import z3
import json
from datetime import datetime

# ═══════════════════════════════════════════════════════════════════
# 1. DOMAIN DEFINITIONS
# ═══════════════════════════════════════════════════════════════════

K3, (T, F, U) = z3.EnumSort('K3', ['T', 'F', 'U'])

# Temporal constants (milliseconds)
TAU_STALE_MS = 1000       # Evidence older than this is stale
MAX_CLOCK_SKEW_MS = 200   # Evidence from more than this far in the future is rejected

# ═══════════════════════════════════════════════════════════════════
# 2. TEMPORAL MODEL
# ═══════════════════════════════════════════════════════════════════

# Evidence freshness check
def is_fresh(evidence_ts, eval_ts, tau_stale, max_skew):
    """Evidence is fresh iff:
       eval_ts - tau_stale <= evidence_ts <= eval_ts + max_skew"""
    age = eval_ts - evidence_ts
    return z3.And(
        age <= tau_stale,        # not too old
        age >= -max_skew         # not too far in the future (negative age = future)
    )

# Temporal validity → K3 result
def temporal_check(evidence_ts, eval_ts, tau_stale, max_skew, inner_result):
    """If evidence is fresh AND inner evaluates to a definite value, pass through.
       If evidence is stale/future, result is Undefined."""
    return z3.If(
        is_fresh(evidence_ts, eval_ts, tau_stale, max_skew),
        inner_result,
        U  # Stale or future evidence → undefined
    )

# Multi-agent temporal negotiation
def negotiate_tau(tau_a, tau_b):
    """NIP-019: stricter (smaller) bound wins"""
    return z3.If(tau_a <= tau_b, tau_a, tau_b)

def negotiate_skew(skew_a, skew_b):
    """NIP-019: stricter (smaller) bound wins"""
    return z3.If(skew_a <= skew_b, skew_a, skew_b)

# ═══════════════════════════════════════════════════════════════════
# 3. PROOF HARNESS
# ═══════════════════════════════════════════════════════════════════

results = []
total_proofs = 0
total_passed = 0

def prove(name, description, claim, nip_ref=""):
    global total_proofs, total_passed
    total_proofs += 1
    s = z3.Solver()
    s.add(z3.Not(claim))
    result = s.check()
    if result == z3.unsat:
        status = "PROVEN"
        total_passed += 1
        model = None
    elif result == z3.sat:
        status = "REFUTED"
        model = str(s.model())
    else:
        status = "UNKNOWN"
        model = None
    results.append({"id": name, "description": description, "nip_ref": nip_ref, "status": status, "counterexample": model})
    icon = "✓" if status == "PROVEN" else "✗" if status == "REFUTED" else "?"
    print(f"  {icon} {name}: {description} — {status}")
    if model:
        print(f"    COUNTEREXAMPLE: {model}")
    return status == "PROVEN"

# ═══════════════════════════════════════════════════════════════════
# 4. THE PROOFS
# ═══════════════════════════════════════════════════════════════════

print("=" * 70)
print("NOE PROTOCOL — FORMAL TEMPORAL SAFETY PROOFS (Z3 SMT SOLVER)")
print("=" * 70)
print()

# Symbolic variables
ev_ts = z3.Int('evidence_ts')      # when the evidence was created
eval_ts = z3.Int('eval_ts')        # when evaluation happens
tau = z3.Int('tau_stale')           # staleness threshold
skew = z3.Int('max_skew')          # clock skew tolerance
inner = z3.Const('inner_result', K3)

tau_a = z3.Int('tau_a')
tau_b = z3.Int('tau_b')
skew_a = z3.Int('skew_a')
skew_b = z3.Int('skew_b')

# ── T1-T3: Basic Freshness ──────────────────────────────────────
print("── T1-T3: BASIC FRESHNESS ─────────────────────────────────")

prove("T1", "Fresh evidence passes through (age within bounds)",
      z3.ForAll([ev_ts, eval_ts, inner],
          z3.Implies(
              z3.And(eval_ts - ev_ts >= 0,
                     eval_ts - ev_ts <= TAU_STALE_MS),
              temporal_check(ev_ts, eval_ts, TAU_STALE_MS, MAX_CLOCK_SKEW_MS, inner) == inner)),
      "NIP-008 §2")

prove("T2", "Stale evidence is rejected (age > tau_stale)",
      z3.ForAll([ev_ts, eval_ts, inner],
          z3.Implies(
              eval_ts - ev_ts > TAU_STALE_MS,
              temporal_check(ev_ts, eval_ts, TAU_STALE_MS, MAX_CLOCK_SKEW_MS, inner) == U)),
      "NIP-008 §2")

prove("T3", "Future evidence beyond skew is rejected",
      z3.ForAll([ev_ts, eval_ts, inner],
          z3.Implies(
              ev_ts - eval_ts > MAX_CLOCK_SKEW_MS,
              temporal_check(ev_ts, eval_ts, TAU_STALE_MS, MAX_CLOCK_SKEW_MS, inner) == U)),
      "NIP-008 §2")

print()

# ── T4-T5: Concrete Bound Verification ──────────────────────────
print("── T4-T5: CONCRETE BOUNDS ─────────────────────────────────")

prove("T4", "Evidence at exactly tau_stale age is still fresh (≤ not <)",
      z3.ForAll([inner],
          temporal_check(0, TAU_STALE_MS, TAU_STALE_MS, MAX_CLOCK_SKEW_MS, inner) == inner),
      "NIP-008 §2")

prove("T5", "Evidence at tau_stale + 1 is rejected",
      z3.ForAll([inner],
          temporal_check(0, TAU_STALE_MS + 1, TAU_STALE_MS, MAX_CLOCK_SKEW_MS, inner) == U),
      "NIP-008 §2")

prove("T5b", "Evidence at exactly max_skew ahead is still fresh",
      z3.ForAll([inner],
          temporal_check(MAX_CLOCK_SKEW_MS, 0, TAU_STALE_MS, MAX_CLOCK_SKEW_MS, inner) == inner),
      "NIP-008 §2")

prove("T5c", "Evidence at max_skew + 1 ahead is rejected",
      z3.ForAll([inner],
          temporal_check(MAX_CLOCK_SKEW_MS + 1, 0, TAU_STALE_MS, MAX_CLOCK_SKEW_MS, inner) == U),
      "NIP-008 §2")

print()

# ── T6: Temporal + K3 Integration ────────────────────────────────
print("── T6: TEMPORAL + K3 INTEGRATION ──────────────────────────")

prove("T6a", "Stale evidence + True inner = Undefined (temporal overrides truth)",
      z3.ForAll([ev_ts, eval_ts],
          z3.Implies(
              eval_ts - ev_ts > TAU_STALE_MS,
              temporal_check(ev_ts, eval_ts, TAU_STALE_MS, MAX_CLOCK_SKEW_MS, T) == U)),
      "NIP-008 + NIP-005")

prove("T6b", "Fresh evidence + Undefined inner = Undefined (K3 preserved)",
      z3.ForAll([ev_ts, eval_ts],
          z3.Implies(
              z3.And(eval_ts - ev_ts >= 0, eval_ts - ev_ts <= TAU_STALE_MS),
              temporal_check(ev_ts, eval_ts, TAU_STALE_MS, MAX_CLOCK_SKEW_MS, U) == U)),
      "NIP-008 + NIP-005")

prove("T6c", "Temporal rejection is always Undefined, never False",
      z3.ForAll([ev_ts, eval_ts, inner],
          z3.Implies(
              z3.Not(is_fresh(ev_ts, eval_ts, TAU_STALE_MS, MAX_CLOCK_SKEW_MS)),
              temporal_check(ev_ts, eval_ts, TAU_STALE_MS, MAX_CLOCK_SKEW_MS, inner) != F)),
      "NIP-008 §2")

print()

# ── T7: Monotonicity ────────────────────────────────────────────
print("── T7: MONOTONICITY ───────────────────────────────────────")

prove("T7a", "Stricter tau never accepts more than lenient tau",
      z3.ForAll([ev_ts, eval_ts, tau_a, tau_b],
          z3.Implies(
              z3.And(tau_a <= tau_b, tau_a >= 0, tau_b >= 0,
                     is_fresh(ev_ts, eval_ts, tau_a, MAX_CLOCK_SKEW_MS)),
              is_fresh(ev_ts, eval_ts, tau_b, MAX_CLOCK_SKEW_MS))),
      "NIP-008 §2")

prove("T7b", "Stricter skew never accepts more than lenient skew",
      z3.ForAll([ev_ts, eval_ts, skew_a, skew_b],
          z3.Implies(
              z3.And(skew_a <= skew_b, skew_a >= 0, skew_b >= 0,
                     is_fresh(ev_ts, eval_ts, TAU_STALE_MS, skew_a)),
              is_fresh(ev_ts, eval_ts, TAU_STALE_MS, skew_b))),
      "NIP-008 §2")

print()

# ── T8: Multi-Agent Negotiation (NIP-019) ────────────────────────
print("── T8: MULTI-AGENT NEGOTIATION (NIP-019) ──────────────────")

prove("T8a", "Negotiated tau ≤ both agents' tau (stricter wins)",
      z3.ForAll([tau_a, tau_b],
          z3.And(
              negotiate_tau(tau_a, tau_b) <= tau_a,
              negotiate_tau(tau_a, tau_b) <= tau_b)),
      "NIP-019 §4")

prove("T8b", "Negotiated skew ≤ both agents' skew (stricter wins)",
      z3.ForAll([skew_a, skew_b],
          z3.And(
              negotiate_skew(skew_a, skew_b) <= skew_a,
              negotiate_skew(skew_a, skew_b) <= skew_b)),
      "NIP-019 §4")

prove("T8c", "Negotiated tau = min(tau_a, tau_b)",
      z3.ForAll([tau_a, tau_b],
          negotiate_tau(tau_a, tau_b) == z3.If(tau_a <= tau_b, tau_a, tau_b)),
      "NIP-019 §4")

prove("T8d", "Negotiation is commutative: negotiate(a,b) = negotiate(b,a)",
      z3.ForAll([tau_a, tau_b],
          negotiate_tau(tau_a, tau_b) == negotiate_tau(tau_b, tau_a)),
      "NIP-019 §4")

prove("T8e", "Negotiation is associative",
      z3.ForAll([tau_a, tau_b, z3.Int('tau_c')],
          negotiate_tau(negotiate_tau(tau_a, tau_b), z3.Int('tau_c'))
          == negotiate_tau(tau_a, negotiate_tau(tau_b, z3.Int('tau_c')))),
      "NIP-019 §4")

prove("T8f", "Negotiation is idempotent: negotiate(a,a) = a",
      z3.ForAll([tau_a],
          negotiate_tau(tau_a, tau_a) == tau_a),
      "NIP-019 §4")

print()

# ── T9: Negotiated bounds are never LESS safe ────────────────────
print("── T9: NEGOTIATED SAFETY ──────────────────────────────────")
print("   (Negotiation never weakens either agent's safety)")
print()

prove("T9a", "If evidence is fresh under negotiated tau, it's fresh under both agents' tau",
      z3.ForAll([ev_ts, eval_ts, tau_a, tau_b],
          z3.Implies(
              z3.And(tau_a >= 0, tau_b >= 0,
                     is_fresh(ev_ts, eval_ts, negotiate_tau(tau_a, tau_b), MAX_CLOCK_SKEW_MS)),
              z3.And(
                  is_fresh(ev_ts, eval_ts, tau_a, MAX_CLOCK_SKEW_MS),
                  is_fresh(ev_ts, eval_ts, tau_b, MAX_CLOCK_SKEW_MS)))),
      "NIP-019 §4")

prove("T9b", "If evidence is fresh under negotiated skew, it's fresh under both agents' skew",
      z3.ForAll([ev_ts, eval_ts, skew_a, skew_b],
          z3.Implies(
              z3.And(skew_a >= 0, skew_b >= 0,
                     is_fresh(ev_ts, eval_ts, TAU_STALE_MS, negotiate_skew(skew_a, skew_b))),
              z3.And(
                  is_fresh(ev_ts, eval_ts, TAU_STALE_MS, skew_a),
                  is_fresh(ev_ts, eval_ts, TAU_STALE_MS, skew_b)))),
      "NIP-019 §4")

print()

# ── T10: Guard + Temporal Combined Safety ────────────────────────
print("── T10: GUARD + TEMPORAL COMBINED SAFETY ──────────────────")
print("   (The full safety chain: temporal → K3 → guard)")
print()

def k3_guard(g, a):
    return z3.If(g == T, a, U)

g = z3.Const('g', K3)
action = z3.Const('action', K3)

# Full pipeline: temporal check → guard → action
def full_pipeline(ev_ts, eval_ts, tau, skew, guard_val, action_val):
    """Evidence goes through temporal check, then the result is used as guard input."""
    temporally_checked = temporal_check(ev_ts, eval_ts, tau, skew, guard_val)
    return k3_guard(temporally_checked, action_val)

prove("T10a", "Stale guard evidence → no action (full pipeline)",
      z3.ForAll([ev_ts, eval_ts, action],
          z3.Implies(
              eval_ts - ev_ts > TAU_STALE_MS,
              full_pipeline(ev_ts, eval_ts, TAU_STALE_MS, MAX_CLOCK_SKEW_MS, T, action) == U)),
      "NIP-005 + NIP-008")

prove("T10b", "Future guard evidence → no action (full pipeline)",
      z3.ForAll([ev_ts, eval_ts, action],
          z3.Implies(
              ev_ts - eval_ts > MAX_CLOCK_SKEW_MS,
              full_pipeline(ev_ts, eval_ts, TAU_STALE_MS, MAX_CLOCK_SKEW_MS, T, action) == U)),
      "NIP-005 + NIP-008")

prove("T10c", "Action requires BOTH fresh evidence AND true guard",
      z3.ForAll([ev_ts, eval_ts, g, action],
          z3.Implies(
              full_pipeline(ev_ts, eval_ts, TAU_STALE_MS, MAX_CLOCK_SKEW_MS, g, action) != U,
              z3.And(
                  is_fresh(ev_ts, eval_ts, TAU_STALE_MS, MAX_CLOCK_SKEW_MS),
                  g == T))),
      "NIP-005 + NIP-008 + NIP-019")

print()

# ═══════════════════════════════════════════════════════════════════
# 5. SUMMARY
# ═══════════════════════════════════════════════════════════════════

print("=" * 70)
print(f"RESULTS: {total_passed}/{total_proofs} properties PROVEN")
print("=" * 70)

if total_passed == total_proofs:
    print()
    print("ALL TEMPORAL SAFETY PROPERTIES VERIFIED.")
    print("Z3 confirms: stale/future evidence never authorizes action.")
else:
    failed = [r for r in results if r["status"] != "PROVEN"]
    print(f"\nFAILURES ({len(failed)}):")
    for f in failed:
        print(f"  - {f['id']}: {f['description']}")
        if f['counterexample']:
            print(f"    Counterexample: {f['counterexample']}")

output = {
    "prover": "Z3 4.12.2",
    "protocol": "Noe Protocol",
    "domain": "Temporal Safety",
    "nips": ["NIP-008", "NIP-019"],
    "timestamp": datetime.utcnow().isoformat() + "Z",
    "total_proofs": total_proofs,
    "total_proven": total_passed,
    "all_proven": total_passed == total_proofs,
    "results": results,
}

with open("/sessions/kind-serene-davinci/noe_temporal_proof_results.json", "w") as f:
    json.dump(output, f, indent=2)

print(f"\nProof results saved to noe_temporal_proof_results.json")
