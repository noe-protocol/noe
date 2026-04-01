#!/usr/bin/env python3
"""
Formal Verification of Noe K3 (Strong Kleene) Evaluation Semantics
using Z3 SMT Solver.

This script formally proves properties of Noe's three-valued logic
as specified in NIP-005 and NIP-009. Each property is encoded as an
SMT formula and Z3 proves it holds universally (for ALL possible inputs).

A Z3 proof of UNSAT means: "there is NO counterexample" — i.e., the
property holds for every possible input. This is a complete, exhaustive,
machine-checked proof over the entire domain.

Prover: Z3 4.12.2
Logic:  QF_DT (Quantifier-Free Datatypes) + QF_UF
Domain: Noe Protocol — NIP-005, NIP-009, NIP-011
"""

import z3
import sys
import json
from datetime import datetime

# ═══════════════════════════════════════════════════════════════════
# 1. DEFINE THE K3 DOMAIN AS A Z3 DATATYPE
# ═══════════════════════════════════════════════════════════════════
# K3 (Strong Kleene) has exactly three values: T, F, U
# We define this as an algebraic datatype — Z3 knows these are
# the ONLY possible values, enabling exhaustive reasoning.

K3, (T, F, U) = z3.EnumSort('K3', ['T', 'F', 'U'])

# ═══════════════════════════════════════════════════════════════════
# 2. DEFINE K3 OPERATORS AS Z3 FUNCTIONS
# ═══════════════════════════════════════════════════════════════════

def k3_not(x):
    """K3 negation: nai"""
    return z3.If(x == T, F, z3.If(x == F, T, U))

def k3_and(x, y):
    """K3 Strong Kleene conjunction: an
    Key property: F dominates (F ∧ U = F)"""
    return z3.If(x == F, F,
           z3.If(y == F, F,
           z3.If(z3.And(x == T, y == T), T, U)))

def k3_or(x, y):
    """K3 Strong Kleene disjunction: ur
    Key property: T dominates (T ∨ U = T)"""
    return z3.If(x == T, T,
           z3.If(y == T, T,
           z3.If(z3.And(x == F, y == F), F, U)))

def k3_guard(g, a):
    """K3 guard operator: kra
    True guard passes through; everything else → undefined"""
    return z3.If(g == T, a, U)

# ═══════════════════════════════════════════════════════════════════
# 3. PROOF HARNESS
# ═══════════════════════════════════════════════════════════════════

results = []
total_proofs = 0
total_passed = 0

def prove(name, description, claim, nip_ref=""):
    """
    Prove a universal property by checking that its negation is UNSAT.

    If Z3 returns UNSAT: the property is PROVEN (no counterexample exists).
    If Z3 returns SAT: the property is REFUTED (counterexample found).
    """
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

    record = {
        "id": name,
        "description": description,
        "nip_ref": nip_ref,
        "status": status,
        "counterexample": model,
    }
    results.append(record)

    icon = "✓" if status == "PROVEN" else "✗" if status == "REFUTED" else "?"
    print(f"  {icon} {name}: {description} — {status}")
    if model:
        print(f"    COUNTEREXAMPLE: {model}")

    return status == "PROVEN"


# ═══════════════════════════════════════════════════════════════════
# 4. THE PROOFS
# ═══════════════════════════════════════════════════════════════════

print("=" * 70)
print("NOE PROTOCOL — FORMAL K3 PROOFS (Z3 SMT SOLVER)")
print("=" * 70)
print()

# -- Symbolic variables (universally quantified over K3) --
p = z3.Const('p', K3)
q = z3.Const('q', K3)
r = z3.Const('r', K3)
a = z3.Const('a', K3)

# ── Section A: Negation (nai) ────────────────────────────────────
print("── A. NEGATION (nai) ──────────────────────────────────────")

prove("A1", "nai T = F",
      k3_not(T) == F,
      "NIP-005 §3.1")

prove("A2", "nai F = T",
      k3_not(F) == T,
      "NIP-005 §3.1")

prove("A3", "nai U = U (uncertainty preserved)",
      k3_not(U) == U,
      "NIP-005 §3.1")

prove("A4", "Double negation: nai(nai(p)) = p (involution)",
      z3.ForAll([p], k3_not(k3_not(p)) == p),
      "NIP-005 §3.1")

print()

# ── Section B: Conjunction (an) — Strong Kleene ──────────────────
print("── B. CONJUNCTION (an) — Strong Kleene ────────────────────")

prove("B1", "T an T = T",
      k3_and(T, T) == T,
      "NIP-009 §2")

prove("B2", "T an F = F",
      k3_and(T, F) == F,
      "NIP-009 §2")

prove("B3", "F an T = F",
      k3_and(F, T) == F,
      "NIP-009 §2")

prove("B4", "F an F = F",
      k3_and(F, F) == F,
      "NIP-009 §2")

prove("B5", "T an U = U",
      k3_and(T, U) == U,
      "NIP-009 §2")

prove("B6", "U an T = U",
      k3_and(U, T) == U,
      "NIP-009 §2")

prove("B7", "F an U = F (False dominates — STRONG Kleene)",
      k3_and(F, U) == F,
      "NIP-009 §2")

prove("B8", "U an F = F (False dominates — STRONG Kleene)",
      k3_and(U, F) == F,
      "NIP-009 §2")

prove("B9", "U an U = U",
      k3_and(U, U) == U,
      "NIP-009 §2")

prove("B10", "an is commutative: p an q = q an p",
      z3.ForAll([p, q], k3_and(p, q) == k3_and(q, p)),
      "NIP-009 §2")

prove("B11", "an is associative: (p an q) an r = p an (q an r)",
      z3.ForAll([p, q, r], k3_and(k3_and(p, q), r) == k3_and(p, k3_and(q, r))),
      "NIP-009 §2")

prove("B12", "T is identity for an: T an p = p",
      z3.ForAll([p], k3_and(T, p) == p),
      "NIP-009 §2")

prove("B13", "F is annihilator for an: F an p = F",
      z3.ForAll([p], k3_and(F, p) == F),
      "NIP-009 §2")

print()

# ── Section C: Disjunction (ur) — Strong Kleene ─────────────────
print("── C. DISJUNCTION (ur) — Strong Kleene ────────────────────")

prove("C1", "T ur T = T",
      k3_or(T, T) == T,
      "NIP-009 §2")

prove("C2", "T ur F = T",
      k3_or(T, F) == T,
      "NIP-009 §2")

prove("C3", "F ur T = T",
      k3_or(F, T) == T,
      "NIP-009 §2")

prove("C4", "F ur F = F",
      k3_or(F, F) == F,
      "NIP-009 §2")

prove("C5", "T ur U = T (True dominates — STRONG Kleene)",
      k3_or(T, U) == T,
      "NIP-009 §2")

prove("C6", "U ur T = T (True dominates — STRONG Kleene)",
      k3_or(U, T) == T,
      "NIP-009 §2")

prove("C7", "F ur U = U",
      k3_or(F, U) == U,
      "NIP-009 §2")

prove("C8", "U ur F = U",
      k3_or(U, F) == U,
      "NIP-009 §2")

prove("C9", "U ur U = U",
      k3_or(U, U) == U,
      "NIP-009 §2")

prove("C10", "ur is commutative: p ur q = q ur p",
      z3.ForAll([p, q], k3_or(p, q) == k3_or(q, p)),
      "NIP-009 §2")

prove("C11", "ur is associative: (p ur q) ur r = p ur (q ur r)",
      z3.ForAll([p, q, r], k3_or(k3_or(p, q), r) == k3_or(p, k3_or(q, r))),
      "NIP-009 §2")

prove("C12", "F is identity for ur: F ur p = p",
      z3.ForAll([p], k3_or(F, p) == p),
      "NIP-009 §2")

prove("C13", "T is annihilator for ur: T ur p = T",
      z3.ForAll([p], k3_or(T, p) == T),
      "NIP-009 §2")

print()

# ── Section D: De Morgan's Laws ──────────────────────────────────
print("── D. DE MORGAN'S LAWS ────────────────────────────────────")

prove("D1", "De Morgan 1: nai(p an q) = (nai p) ur (nai q)",
      z3.ForAll([p, q], k3_not(k3_and(p, q)) == k3_or(k3_not(p), k3_not(q))),
      "NIP-009 §2, NIP-011")

prove("D2", "De Morgan 2: nai(p ur q) = (nai p) an (nai q)",
      z3.ForAll([p, q], k3_not(k3_or(p, q)) == k3_and(k3_not(p), k3_not(q))),
      "NIP-009 §2, NIP-011")

print()

# ── Section E: Distributivity ────────────────────────────────────
print("── E. DISTRIBUTIVITY ──────────────────────────────────────")

prove("E1", "an distributes over ur: p an (q ur r) = (p an q) ur (p an r)",
      z3.ForAll([p, q, r], k3_and(p, k3_or(q, r)) == k3_or(k3_and(p, q), k3_and(p, r))),
      "NIP-009 §2")

prove("E2", "ur distributes over an: p ur (q an r) = (p ur q) an (p ur r)",
      z3.ForAll([p, q, r], k3_or(p, k3_and(q, r)) == k3_and(k3_or(p, q), k3_or(p, r))),
      "NIP-009 §2")

print()

# ── Section F: Guard (kra) — Safety Properties ──────────────────
print("── F. GUARD (kra) — SAFETY PROPERTIES ─────────────────────")

prove("F1", "True guard passes through: T kra a = a",
      z3.ForAll([a], k3_guard(T, a) == a),
      "NIP-005 §4")

prove("F2", "False guard blocks: F kra a = U",
      z3.ForAll([a], k3_guard(F, a) == U),
      "NIP-005 §4")

prove("F3", "Undefined guard blocks: U kra a = U",
      z3.ForAll([a], k3_guard(U, a) == U),
      "NIP-005 §4")

print()

# ── Section G: THE SAFETY INVARIANT ──────────────────────────────
print("── G. THE SAFETY INVARIANT ────────────────────────────────")
print("   (The foundational property of Noe)")
print()

# The safety invariant: if the guard is not provably True,
# the guarded expression evaluates to Undefined.
# This means: undefined chains NEVER produce actions.

prove("G1", "Safety Invariant: ¬(g = T) → (g kra a) = U",
      z3.ForAll([p, a], z3.Implies(p != T, k3_guard(p, a) == U)),
      "NIP-005 §4, AGENTS.md Invariant #1")

# Stronger form: an action can only occur if the guard is True
prove("G2", "Action requires proof: (g kra a) ≠ U → g = T",
      z3.ForAll([p, a], z3.Implies(k3_guard(p, a) != U, p == T)),
      "NIP-005 §4")

# The guard never produces False (it's either pass-through or undefined)
prove("G3", "Guard is binary: kra result is either 'a' (if T) or U",
      z3.ForAll([p, a], z3.Or(k3_guard(p, a) == a, k3_guard(p, a) == U)),
      "NIP-005 §4")

print()

# ── Section H: Strong vs Weak Kleene Distinction ────────────────
print("── H. STRONG vs WEAK KLEENE ───────────────────────────────")
print("   (Proving Noe uses Strong Kleene, NOT Weak Kleene)")
print()

# In Weak Kleene (Bochvar): F ∧ U = U and T ∨ U = U
# In Strong Kleene: F ∧ U = F and T ∨ U = T
# Noe uses Strong Kleene.

prove("H1", "F an U = F (Strong Kleene, NOT Weak Kleene where F∧U=U)",
      k3_and(F, U) == F,
      "NIP-009 §2")

prove("H2", "T ur U = T (Strong Kleene, NOT Weak Kleene where T∨U=U)",
      k3_or(T, U) == T,
      "NIP-009 §2")

# Prove these are NOT Weak Kleene results
prove("H3", "Noe refutes Weak Kleene: F an U ≠ U",
      k3_and(F, U) != U,
      "NIP-009 §2")

prove("H4", "Noe refutes Weak Kleene: T ur U ≠ U",
      k3_or(T, U) != U,
      "NIP-009 §2")

print()

# ── Section I: Absorption Laws ───────────────────────────────────
print("── I. ABSORPTION LAWS ─────────────────────────────────────")

prove("I1", "p an (p ur q) = p",
      z3.ForAll([p, q], k3_and(p, k3_or(p, q)) == p),
      "K3 lattice property")

prove("I2", "p ur (p an q) = p",
      z3.ForAll([p, q], k3_or(p, k3_and(p, q)) == p),
      "K3 lattice property")

print()

# ── Section J: Idempotence ───────────────────────────────────────
print("── J. IDEMPOTENCE ─────────────────────────────────────────")

prove("J1", "p an p = p",
      z3.ForAll([p], k3_and(p, p) == p),
      "K3 lattice property")

prove("J2", "p ur p = p",
      z3.ForAll([p], k3_or(p, p) == p),
      "K3 lattice property")

print()

# ── Section K: Complement Laws ───────────────────────────────────
print("── K. COMPLEMENT BEHAVIOUR IN K3 ──────────────────────────")
print("   (These DIFFER from classical logic!)")
print()

# In classical logic: p ∧ ¬p = F and p ∨ ¬p = T
# In K3: U ∧ ¬U = U and U ∨ ¬U = U (excluded middle FAILS)

prove("K1", "T an nai(T) = F (complement for definite values)",
      k3_and(T, k3_not(T)) == F,
      "K3")

prove("K2", "F an nai(F) = F (complement for definite values)",
      k3_and(F, k3_not(F)) == F,
      "K3")

prove("K3_special", "U an nai(U) = U (NOT F — excluded middle fails for undefined)",
      k3_and(U, k3_not(U)) == U,
      "K3 — critical distinction from classical logic")

prove("K4", "Excluded middle fails: ¬∀p. p ur nai(p) = T",
      z3.Not(z3.ForAll([p], k3_or(p, k3_not(p)) == T)),
      "K3 — U ∨ ¬U = U ≠ T")

prove("K5", "Non-contradiction fails: ¬∀p. p an nai(p) = F",
      z3.Not(z3.ForAll([p], k3_and(p, k3_not(p)) == F)),
      "K3 — U ∧ ¬U = U ≠ F")

print()

# ═══════════════════════════════════════════════════════════════════
# 5. SUMMARY
# ═══════════════════════════════════════════════════════════════════

print("=" * 70)
print(f"RESULTS: {total_passed}/{total_proofs} properties PROVEN")
print("=" * 70)

if total_passed == total_proofs:
    print()
    print("ALL PROPERTIES VERIFIED.")
    print("Z3 has confirmed that no counterexample exists for any property.")
    print("These are complete, machine-checked proofs over the full K3 domain.")
else:
    print()
    failed = [r for r in results if r["status"] != "PROVEN"]
    print(f"FAILURES ({len(failed)}):")
    for f in failed:
        print(f"  - {f['id']}: {f['description']}")
        if f['counterexample']:
            print(f"    Counterexample: {f['counterexample']}")

# Save structured results
output = {
    "prover": "Z3 4.12.2",
    "logic": "QF_DT + QF_UF (Quantifier-Free Datatypes + Uninterpreted Functions)",
    "protocol": "Noe Protocol",
    "nips": ["NIP-005", "NIP-009", "NIP-011"],
    "timestamp": datetime.utcnow().isoformat() + "Z",
    "total_proofs": total_proofs,
    "total_proven": total_passed,
    "all_proven": total_passed == total_proofs,
    "results": results,
}

with open("/sessions/kind-serene-davinci/noe_k3_proof_results.json", "w") as f:
    json.dump(output, f, indent=2)

print()
print(f"Proof results saved to noe_k3_proof_results.json")
