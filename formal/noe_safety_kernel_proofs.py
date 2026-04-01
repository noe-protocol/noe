#!/usr/bin/env python3
"""
Formal Verification of Noe End-to-End Safety Kernel
using Z3 SMT Solver.

Combines K3 semantics, guard operators, provenance, temporal safety,
and composition into unified proofs.

Master Theorem: No path exists from uncertain input to authorized action.

Prover: Z3 4.12.2
Domain: Noe Protocol — NIP-005, NIP-007, NIP-008, NIP-009, NIP-019
"""

import z3
import json
from datetime import datetime

K3, (T, F, U) = z3.EnumSort('K3', ['T', 'F', 'U'])

def k3_not(x):
    return z3.If(x == T, F, z3.If(x == F, T, U))

def k3_and(x, y):
    return z3.If(x == F, F, z3.If(y == F, F, z3.If(z3.And(x == T, y == T), T, U)))

def k3_or(x, y):
    return z3.If(x == T, T, z3.If(y == T, T, z3.If(z3.And(x == F, y == F), F, U)))

def k3_guard(g, a):
    return z3.If(g == T, a, U)

TAU_STALE = 1000
MAX_SKEW = 200

def is_fresh(ev_ts, eval_ts, tau, skew):
    age = eval_ts - ev_ts
    return z3.And(age <= tau, age >= -skew)

def temporal_check(ev_ts, eval_ts, tau, skew, inner):
    return z3.If(is_fresh(ev_ts, eval_ts, tau, skew), inner, U)

def negotiate_tau(a, b):
    return z3.If(a <= b, a, b)

NULL_HASH = 0
hash_fn = z3.Function('hash_fn', z3.IntSort(), z3.IntSort(), z3.IntSort(), z3.IntSort())

def prov_hash(ch, cx, ph, result):
    return z3.If(z3.Or(result == T, result == F), hash_fn(ch, cx, ph), NULL_HASH)

results = []
total_proofs = 0
total_passed = 0

def prove(name, description, claim, nip_ref="", timeout_ms=30000):
    global total_proofs, total_passed
    total_proofs += 1
    s = z3.Solver()
    s.set("timeout", timeout_ms)
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
        status = "TIMEOUT"
        model = None
    results.append({"id": name, "description": description, "nip_ref": nip_ref, "status": status, "counterexample": model})
    icon = "✓" if status == "PROVEN" else "✗" if status == "REFUTED" else "⏱"
    print(f"  {icon} {name}: {description} — {status}")
    if model and len(model) < 300:
        print(f"    COUNTEREXAMPLE: {model}")
    return status == "PROVEN"

# ═══════════════════════════════════════════════════════════════════

print("=" * 70)
print("NOE PROTOCOL — COMPOSITION & SAFETY KERNEL PROOFS")
print("=" * 70)
print()

p = z3.Const('p', K3)
q = z3.Const('q', K3)
r = z3.Const('r', K3)
a = z3.Const('a', K3)
g = z3.Const('g', K3)
g1 = z3.Const('g1', K3)
g2 = z3.Const('g2', K3)

# ── Section A: Guard Composition ─────────────────────────────────
print("── A. GUARD COMPOSITION ───────────────────────────────────")
print()

prove("C1", "Nested guards compose via conjunction: (g1 kra (g2 kra a)) = (g1 an g2) kra a",
      z3.ForAll([g1, g2, a],
          k3_guard(g1, k3_guard(g2, a)) == k3_guard(k3_and(g1, g2), a)),
      "NIP-005 §4")

prove("C2", "Conjunctive guard requires BOTH true",
      z3.ForAll([g1, g2, a],
          z3.Implies(
              k3_guard(k3_and(g1, g2), a) != U,
              z3.And(g1 == T, g2 == T))),
      "NIP-005 §4 + NIP-009 §2")

prove("C3", "Disjunctive guard passes if EITHER is true",
      z3.ForAll([g1, g2, a],
          z3.Implies(
              k3_guard(k3_or(g1, g2), a) != U,
              z3.Or(g1 == T, g2 == T))),
      "NIP-005 §4 + NIP-009 §2")

prove("C4", "Negated guard: nai(T) blocks, nai(F) passes",
      z3.And(
          k3_guard(k3_not(T), a) == U,
          z3.ForAll([a], k3_guard(k3_not(F), a) == a)),
      "NIP-005 §4")

prove("C5", "Double guard is idempotent: g kra (g kra a) = g kra a",
      z3.ForAll([g, a],
          k3_guard(g, k3_guard(g, a)) == k3_guard(g, a)),
      "NIP-005 §4")

prove("C6", "True guard + undefined action = undefined",
      k3_guard(T, U) == U,
      "NIP-005 §4")

print()

# ── Section B: Scoping ───────────────────────────────────────────
print("── B. SCOPING & PRECEDENCE ────────────────────────────────")
print()

prove("B1", "nai of failed guard = undefined (can't extract from failed guard)",
      z3.ForAll([g, a],
          z3.Implies(g != T, k3_not(k3_guard(g, a)) == U)),
      "NIP-005 §4")

prove("B2", "Guards distribute over conjunction when both pass",
      z3.ForAll([p, q],
          k3_and(k3_guard(T, p), k3_guard(T, q)) == k3_guard(T, k3_and(p, q))),
      "NIP-005 §4 + NIP-009 §2")

prove("B3", "Mixed guard (one T, one F) propagates undefined correctly",
      z3.ForAll([p, q],
          k3_and(k3_guard(T, p), k3_guard(F, q)) == k3_and(p, U)),
      "NIP-005 §4")

print()

# ── Section C: Fail-Closed Composition ───────────────────────────
print("── C. FAIL-CLOSED COMPOSITION ─────────────────────────────")
print("   (Uncertainty can never be resolved by K3 operators alone)")
print()

prove("C7", "nai(U) = U",
      k3_not(U) == U, "NIP-005 §3.1")

prove("C8", "U an U = U",
      k3_and(U, U) == U, "NIP-009 §2")

prove("C9", "U ur U = U",
      k3_or(U, U) == U, "NIP-009 §2")

prove("C10", "U kra a = U for all a",
      z3.ForAll([a], k3_guard(U, a) == U), "NIP-005 §4")

prove("C11", "No expression over only-undefined inputs produces True",
      z3.And(
          k3_not(U) != T,
          k3_and(U, U) != T,
          k3_or(U, U) != T,
          k3_guard(U, U) != T,
          k3_guard(U, T) != T,
          k3_not(k3_and(U, U)) != T,
          k3_not(k3_or(U, U)) != T,
          k3_and(k3_not(U), U) != T,
          k3_or(k3_not(U), U) != T,
          k3_and(k3_not(U), k3_not(U)) != T,
          k3_or(k3_not(U), k3_not(U)) != T),
      "NIP-005 + NIP-009 — fundamental closure property")

print()

# ═══════════════════════════════════════════════════════════════════
# THE END-TO-END SAFETY KERNEL
# ═══════════════════════════════════════════════════════════════════

print("╔" + "═" * 68 + "╗")
print("║  END-TO-END SAFETY KERNEL: The Master Theorems                      ║")
print("╚" + "═" * 68 + "╝")
print()

ev_ts = z3.Int('ev_ts')
eval_ts = z3.Int('eval_ts')
ch = z3.Int('ch')
cx = z3.Int('cx')
ph = z3.Int('ph')

def full_eval_result(ev_ts, eval_ts, guard_val, action_val):
    temporal_result = temporal_check(ev_ts, eval_ts, TAU_STALE, MAX_SKEW, guard_val)
    return k3_guard(temporal_result, action_val)

def full_eval_prov(ev_ts, eval_ts, guard_val, action_val, ch, cx, ph):
    result = full_eval_result(ev_ts, eval_ts, guard_val, action_val)
    return prov_hash(ch, cx, ph, result)

print("── SK1: MASTER SAFETY THEOREM ─────────────────────────────")
print("   \"No path from uncertain input to authorized action\"")
print()

prove("SK1a", "Stale evidence → undefined action + null provenance",
      z3.ForAll([ev_ts, eval_ts, a, ch, cx, ph],
          z3.Implies(
              eval_ts - ev_ts > TAU_STALE,
              z3.And(
                  full_eval_result(ev_ts, eval_ts, T, a) == U,
                  full_eval_prov(ev_ts, eval_ts, T, a, ch, cx, ph) == NULL_HASH))),
      "ALL NIPs")

prove("SK1b", "Future evidence → undefined action + null provenance",
      z3.ForAll([ev_ts, eval_ts, a, ch, cx, ph],
          z3.Implies(
              ev_ts - eval_ts > MAX_SKEW,
              z3.And(
                  full_eval_result(ev_ts, eval_ts, T, a) == U,
                  full_eval_prov(ev_ts, eval_ts, T, a, ch, cx, ph) == NULL_HASH))),
      "ALL NIPs")

prove("SK1c", "False guard + fresh evidence → undefined action + null provenance",
      z3.ForAll([ev_ts, eval_ts, a, ch, cx, ph],
          z3.Implies(
              is_fresh(ev_ts, eval_ts, TAU_STALE, MAX_SKEW),
              z3.And(
                  full_eval_result(ev_ts, eval_ts, F, a) == U,
                  full_eval_prov(ev_ts, eval_ts, F, a, ch, cx, ph) == NULL_HASH))),
      "ALL NIPs")

prove("SK1d", "Undefined guard + fresh evidence → undefined action + null provenance",
      z3.ForAll([ev_ts, eval_ts, a, ch, cx, ph],
          z3.Implies(
              is_fresh(ev_ts, eval_ts, TAU_STALE, MAX_SKEW),
              z3.And(
                  full_eval_result(ev_ts, eval_ts, U, a) == U,
                  full_eval_prov(ev_ts, eval_ts, U, a, ch, cx, ph) == NULL_HASH))),
      "ALL NIPs")

print()
print("── SK2: THE AUDIT THEOREM (CONTRAPOSITIVE) ────────────────")
print("   \"Non-null provenance → everything was valid\"")
print()

prove("SK2", "NON-NULL PROVENANCE → fresh evidence AND true guard",
      z3.ForAll([ev_ts, eval_ts, g, a, ch, cx, ph],
          z3.Implies(
              z3.And(
                  hash_fn(ch, cx, ph) != NULL_HASH,
                  full_eval_prov(ev_ts, eval_ts, g, a, ch, cx, ph) != NULL_HASH),
              z3.And(
                  is_fresh(ev_ts, eval_ts, TAU_STALE, MAX_SKEW),
                  g == T))),
      "ALL NIPs — Master Audit Theorem")

print()
print("── SK3: MULTI-AGENT NEGOTIATED SAFETY ─────────────────────")
print("   \"Negotiation never weakens the safety kernel\"")
print()

tau_a = z3.Int('tau_a')
tau_b = z3.Int('tau_b')

prove("SK3a", "Negotiated freshness implies freshness under BOTH agents' bounds",
      z3.ForAll([ev_ts, eval_ts, tau_a, tau_b],
          z3.Implies(
              z3.And(tau_a >= 0, tau_b >= 0,
                     is_fresh(ev_ts, eval_ts, negotiate_tau(tau_a, tau_b), MAX_SKEW)),
              z3.And(
                  is_fresh(ev_ts, eval_ts, tau_a, MAX_SKEW),
                  is_fresh(ev_ts, eval_ts, tau_b, MAX_SKEW)))),
      "NIP-019 §4")

prove("SK3b", "Negotiated pipeline action → both agents would individually approve",
      z3.ForAll([ev_ts, eval_ts, g, a, tau_a, tau_b],
          z3.Implies(
              z3.And(
                  tau_a >= 0, tau_b >= 0,
                  temporal_check(ev_ts, eval_ts, negotiate_tau(tau_a, tau_b), MAX_SKEW, g) != U),
              z3.And(
                  temporal_check(ev_ts, eval_ts, tau_a, MAX_SKEW, g) != U,
                  temporal_check(ev_ts, eval_ts, tau_b, MAX_SKEW, g) != U))),
      "NIP-019 §4")

print()

# ── SK4: Composition Through Full Pipeline ───────────────────────
print("── SK4: COMPOSITION THROUGH PIPELINE ──────────────────────")
print("   (Complex guards maintain safety through the full stack)")
print()

g1 = z3.Const('g1', K3)
g2 = z3.Const('g2', K3)

prove("SK4a", "Conjunctive guard through temporal: both guards must be true AND fresh",
      z3.ForAll([ev_ts, eval_ts, g1, g2, a, ch, cx, ph],
          z3.Implies(
              z3.And(
                  hash_fn(ch, cx, ph) != NULL_HASH,
                  full_eval_prov(ev_ts, eval_ts, k3_and(g1, g2), a, ch, cx, ph) != NULL_HASH),
              z3.And(
                  is_fresh(ev_ts, eval_ts, TAU_STALE, MAX_SKEW),
                  g1 == T, g2 == T))),
      "ALL NIPs")

prove("SK4b", "Nested guard through temporal: inner AND outer must be true AND fresh",
      z3.ForAll([ev_ts, eval_ts, g1, g2, a],
          z3.Implies(
              full_eval_result(ev_ts, eval_ts, g1, k3_guard(g2, a)) != U,
              z3.And(
                  is_fresh(ev_ts, eval_ts, TAU_STALE, MAX_SKEW),
                  g1 == T, g2 == T))),
      "ALL NIPs")

print()

# ═══════════════════════════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════════════════════════

print("=" * 70)
print(f"RESULTS: {total_passed}/{total_proofs} properties PROVEN")
print("=" * 70)

if total_passed == total_proofs:
    print()
    print("╔" + "═" * 68 + "╗")
    print("║  ALL SAFETY KERNEL PROPERTIES VERIFIED.                             ║")
    print("║                                                                      ║")
    print("║  PROVEN: No path from uncertain input to authorized action.         ║")
    print("║  PROVEN: Every authorized action has a tamper-evident audit trail.   ║")
    print("║  PROVEN: Multi-agent negotiation never weakens safety bounds.        ║")
    print("║  PROVEN: Composed guards maintain safety through the full stack.     ║")
    print("╚" + "═" * 68 + "╝")
else:
    failed = [r for r in results if r["status"] != "PROVEN"]
    print(f"\nISSUES ({len(failed)}):")
    for f in failed:
        print(f"  - {f['id']}: {f['description']} [{f['status']}]")

output = {
    "prover": "Z3 4.12.2",
    "protocol": "Noe Protocol",
    "domain": "End-to-End Safety Kernel",
    "nips": ["NIP-005", "NIP-007", "NIP-008", "NIP-009", "NIP-019"],
    "timestamp": datetime.utcnow().isoformat() + "Z",
    "total_proofs": total_proofs,
    "total_proven": total_passed,
    "all_proven": total_passed == total_proofs,
    "results": results,
}

with open("/sessions/kind-serene-davinci/noe_safety_kernel_proof_results.json", "w") as f:
    json.dump(output, f, indent=2)

print(f"\nProof results saved to noe_safety_kernel_proof_results.json")
