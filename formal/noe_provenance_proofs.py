#!/usr/bin/env python3
"""
Formal Verification of Noe Provenance Chain Properties
using Z3 SMT Solver.

Uses integer-based hash abstraction for tractable SMT solving.
The proofs verify structural properties of the provenance system
independent of the specific hash function used.

Prover: Z3 4.12.2
Domain: Noe Protocol — NIP-007, NIP-010
"""

import z3
import json
from datetime import datetime

# ═══════════════════════════════════════════════════════════════════
# 1. DOMAIN DEFINITIONS
# ═══════════════════════════════════════════════════════════════════

K3, (T, F, U) = z3.EnumSort('K3', ['T', 'F', 'U'])

# Model hashes as integers (abstract — structural properties only)
NULL_HASH = 0

# Hash function: uninterpreted function over integers
# Z3 treats this as an arbitrary function, making no assumptions
# about its internals — proofs hold for ANY hash function.
hash_fn = z3.Function('hash_fn', z3.IntSort(), z3.IntSort(), z3.IntSort(), z3.IntSort())

def prov_hash(chain_h, ctx_h, parent_h, result):
    """Provenance hash: real hash for T/F, null for U"""
    return z3.If(
        z3.Or(result == T, result == F),
        hash_fn(chain_h, ctx_h, parent_h),
        NULL_HASH
    )

def k3_guard(g, a):
    return z3.If(g == T, a, U)

# ═══════════════════════════════════════════════════════════════════
# 2. PROOF HARNESS
# ═══════════════════════════════════════════════════════════════════

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
    if model and len(model) < 200:
        print(f"    COUNTEREXAMPLE: {model}")
    return status == "PROVEN"

# ═══════════════════════════════════════════════════════════════════
# 3. THE PROOFS
# ═══════════════════════════════════════════════════════════════════

print("=" * 70)
print("NOE PROTOCOL — FORMAL PROVENANCE PROOFS (Z3 SMT SOLVER)")
print("=" * 70)
print()

ch = z3.Int('ch')
cx = z3.Int('cx')
ph = z3.Int('ph')
ch2 = z3.Int('ch2')
cx2 = z3.Int('cx2')
ph2 = z3.Int('ph2')
r = z3.Const('r', K3)
g = z3.Const('g', K3)
a = z3.Const('a', K3)

# ── P1: Determinism ─────────────────────────────────────────────
print("── P1: HASH DETERMINISM ───────────────────────────────────")

prove("P1", "Same inputs → same provenance hash (deterministic)",
      z3.ForAll([ch, cx, ph, r],
          prov_hash(ch, cx, ph, r) == prov_hash(ch, cx, ph, r)),
      "NIP-007 §3")

print()

# ── P2: Null Hash on Undefined ───────────────────────────────────
print("── P2: NULL HASH ON UNDEFINED ─────────────────────────────")
print("   (THE critical provenance property)")
print()

prove("P2a", "Undefined result → null hash (for all inputs)",
      z3.ForAll([ch, cx, ph], prov_hash(ch, cx, ph, U) == NULL_HASH),
      "NIP-007 §3 P6")

prove("P2b", "True result → hash_fn output (non-null pathway)",
      z3.ForAll([ch, cx, ph], prov_hash(ch, cx, ph, T) == hash_fn(ch, cx, ph)),
      "NIP-007 §3")

prove("P2c", "False result → hash_fn output (non-null pathway)",
      z3.ForAll([ch, cx, ph], prov_hash(ch, cx, ph, F) == hash_fn(ch, cx, ph)),
      "NIP-007 §3")

print()

# ── P3: Result Partitioning ──────────────────────────────────────
print("── P3: RESULT PARTITIONING ────────────────────────────────")

prove("P3a", "Provenance hash is always either hash_fn(...) or null (complete)",
      z3.ForAll([ch, cx, ph, r],
          z3.Or(
              prov_hash(ch, cx, ph, r) == NULL_HASH,
              prov_hash(ch, cx, ph, r) == hash_fn(ch, cx, ph))),
      "NIP-007 §3")

prove("P3b", "T and F produce the same hash (result not in hash input)",
      z3.ForAll([ch, cx, ph],
          prov_hash(ch, cx, ph, T) == prov_hash(ch, cx, ph, F)),
      "NIP-007 §3")

prove("P3c", "U produces a different hash than T (null vs non-null, assuming hash_fn ≠ 0)",
      z3.ForAll([ch, cx, ph],
          z3.Implies(
              hash_fn(ch, cx, ph) != NULL_HASH,
              prov_hash(ch, cx, ph, U) != prov_hash(ch, cx, ph, T))),
      "NIP-007 §3")

print()

# ── P4: Tamper Detection ─────────────────────────────────────────
print("── P4: TAMPER DETECTION ───────────────────────────────────")
print("   (Given collision-resistant hash, any change is detectable)")
print()

# Model collision resistance as injectivity of hash_fn
inj = z3.ForAll([ch, cx, ph, ch2, cx2, ph2],
    z3.Implies(
        hash_fn(ch, cx, ph) == hash_fn(ch2, cx2, ph2),
        z3.And(ch == ch2, cx == cx2, ph == ph2)))

prove("P4a", "Different chain → different provenance hash (given CR)",
      z3.Implies(inj,
          z3.ForAll([ch, ch2, cx, ph],
              z3.Implies(ch != ch2,
                  hash_fn(ch, cx, ph) != hash_fn(ch2, cx, ph)))),
      "NIP-007 §3")

prove("P4b", "Different context → different provenance hash (given CR)",
      z3.Implies(inj,
          z3.ForAll([ch, cx, cx2, ph],
              z3.Implies(cx != cx2,
                  hash_fn(ch, cx, ph) != hash_fn(ch, cx2, ph)))),
      "NIP-007 §3")

prove("P4c", "Different parent → different provenance hash (given CR)",
      z3.Implies(inj,
          z3.ForAll([ch, cx, ph, ph2],
              z3.Implies(ph != ph2,
                  hash_fn(ch, cx, ph) != hash_fn(ch, cx, ph2)))),
      "NIP-007 §3")

print()

# ── P5: Chain Break on Undefined ─────────────────────────────────
print("── P5: CHAIN BREAK ON UNDEFINED ───────────────────────────")

prove("P5a", "Undefined parent → child's parent_hash is null",
      z3.ForAll([ch, cx, ph, ch2, cx2],
          prov_hash(ch2, cx2, prov_hash(ch, cx, ph, U), T)
          == hash_fn(ch2, cx2, NULL_HASH)),
      "NIP-007 §3 P6")

prove("P5b", "Chain of two undefineds: both produce null hash",
      z3.ForAll([ch, cx, ph, ch2, cx2],
          prov_hash(ch2, cx2, prov_hash(ch, cx, ph, U), U) == NULL_HASH),
      "NIP-007 §3")

print()

# ── P6: Provenance + Guard Integration ───────────────────────────
print("── P6: PROVENANCE + GUARD INTEGRATION ─────────────────────")
print("   (Connecting K3 safety invariant to the audit trail)")
print()

prove("P6a", "Failed guard → null provenance hash",
      z3.ForAll([g, a, ch, cx, ph],
          z3.Implies(g != T,
              prov_hash(ch, cx, ph, k3_guard(g, a)) == NULL_HASH)),
      "NIP-005 §4 + NIP-007 §3")

prove("P6b", "Non-null provenance → guard was True (audit proof)",
      z3.ForAll([g, a, ch, cx, ph],
          z3.Implies(
              z3.And(
                  hash_fn(ch, cx, ph) != NULL_HASH,
                  prov_hash(ch, cx, ph, k3_guard(g, a)) != NULL_HASH),
              g == T)),
      "NIP-005 §4 + NIP-007 §3")

prove("P6c", "True guard provenance = same as action's provenance",
      z3.ForAll([a, ch, cx, ph],
          prov_hash(ch, cx, ph, k3_guard(T, a)) == prov_hash(ch, cx, ph, a)),
      "NIP-005 §4 + NIP-007 §3")

print()

# ── P7: Provenance Completeness ──────────────────────────────────
print("── P7: PROVENANCE COMPLETENESS ────────────────────────────")

prove("P7a", "Every definite evaluation has a provenance record",
      z3.ForAll([ch, cx, ph, r],
          z3.Implies(
              z3.Or(r == T, r == F),
              prov_hash(ch, cx, ph, r) == hash_fn(ch, cx, ph))),
      "NIP-007 §3")

prove("P7b", "Every undefined evaluation has null provenance",
      z3.ForAll([ch, cx, ph],
          prov_hash(ch, cx, ph, U) == NULL_HASH),
      "NIP-007 §3")

prove("P7c", "Provenance function is total (defined for all K3 values)",
      z3.ForAll([ch, cx, ph, r],
          z3.Or(
              prov_hash(ch, cx, ph, r) == hash_fn(ch, cx, ph),
              prov_hash(ch, cx, ph, r) == NULL_HASH)),
      "NIP-007 §3")

print()

# ═══════════════════════════════════════════════════════════════════
# 4. SUMMARY
# ═══════════════════════════════════════════════════════════════════

print("=" * 70)
print(f"RESULTS: {total_passed}/{total_proofs} properties PROVEN")
print("=" * 70)

if total_passed == total_proofs:
    print()
    print("ALL PROVENANCE PROPERTIES VERIFIED.")
    print("Z3 confirms: uncertain results cannot pollute the audit trail.")
else:
    failed = [r for r in results if r["status"] != "PROVEN"]
    print(f"\nFAILURES/TIMEOUTS ({len(failed)}):")
    for f in failed:
        print(f"  - {f['id']}: {f['description']} [{f['status']}]")
        if f['counterexample']:
            print(f"    Counterexample: {f['counterexample']}")

output = {
    "prover": "Z3 4.12.2",
    "protocol": "Noe Protocol",
    "domain": "Provenance Chain Integrity",
    "nips": ["NIP-007", "NIP-010"],
    "timestamp": datetime.utcnow().isoformat() + "Z",
    "total_proofs": total_proofs,
    "total_proven": total_passed,
    "all_proven": total_passed == total_proofs,
    "results": results,
}

with open("/sessions/kind-serene-davinci/noe_provenance_proof_results.json", "w") as f:
    json.dump(output, f, indent=2)

print(f"\nProof results saved to noe_provenance_proof_results.json")
