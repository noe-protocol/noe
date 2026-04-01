#!/usr/bin/env python3
"""
Noe Implementation Conformance Bridge

Exhaustively tests the Python reference implementation against
the formally verified K3 specification model. Since K3 has exactly
3 values, every operator can be tested over the COMPLETE input space.

Two test passes are run:
  Pass 1 (partial mode): Tests the K3 evaluation core directly.
         Missing literals become semantic undefined, operators evaluate.
         This tests whether the K3 operators themselves match the model.

  Pass 2 (strict mode):  Tests the full production pipeline.
         Missing literals trigger ERR_LITERAL_MISSING before evaluation.
         This tests the NIP-009 validation contract on top of K3.

If Pass 1 is fully conformant, the K3 evaluation layer matches the
formal model. Pass 2 documents the intentional strict-mode contract
where the validator rejects chains referencing missing literals.

Usage:
  cd noe-gate/
  python3 formal/conformance_bridge.py
"""

import sys
import os
import json
from datetime import datetime

# Add the repo root to path so we can import noe
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from noe.noe_parser import NoeEvaluator, run_noe_logic

# ═══════════════════════════════════════════════════════════════════
# 1. THE FORMAL MODEL (what Z3 proved)
# ═══════════════════════════════════════════════════════════════════

# K3 values
T, F, U = True, False, "undefined"

# Formal K3 operators (identical to the Z3 definitions)
def model_not(x):
    if x == U: return U
    return not x

def model_and(x, y):
    if x is False or y is False: return False
    if x == U or y == U: return U
    return True

def model_or(x, y):
    if x is True or y is True: return True
    if x == U or y == U: return U
    return False

def model_guard(g, a):
    if g is True: return a
    return U

K3_VALUES = [T, F, U]
K3_LABELS = {True: "T", False: "F", "undefined": "U"}

# ═══════════════════════════════════════════════════════════════════
# 2. IMPLEMENTATION BRIDGE
# ═══════════════════════════════════════════════════════════════════

def make_context(literals=None):
    """Build a minimal NIP-009 compliant context for the evaluator."""
    return {
        "literals": literals or {},
        "entities": {},
        "spatial": {},
        "temporal": {"now": 1000, "max_skew_ms": 200},
        "modal": {"knowledge": {}, "belief": {}, "certainty": {}},
        "axioms": {"value_system": {"accepted": [], "rejected": []}},
        "rel": {},
        "demonstratives": {},
        "delivery": {"status": {}},
        "audit": {"log": []}
    }

def eval_chain(chain_text, context, mode="partial"):
    """Run a chain through the actual evaluator and return the K3 result."""
    try:
        result = run_noe_logic(chain_text, context, mode=mode)
        domain = result.get("domain", "")
        value = result.get("value", None)

        if domain == "truth":
            return value  # True or False
        elif domain == "undefined":
            return "undefined"
        elif domain == "error":
            return "error:" + result.get("code", "unknown")
        elif domain == "action":
            return "action"
        else:
            return f"unexpected:{domain}"
    except Exception as e:
        return f"exception:{e}"

# ═══════════════════════════════════════════════════════════════════
# 3. TEST INFRASTRUCTURE
# ═══════════════════════════════════════════════════════════════════

class TestSuite:
    def __init__(self, name):
        self.name = name
        self.results = []
        self.total = 0
        self.passed = 0
        self.failed = 0

    def test(self, name, impl_result, model_result):
        self.total += 1
        impl_norm = self._normalize(impl_result)
        model_norm = self._normalize(model_result)
        match = impl_norm == model_norm

        if match:
            self.passed += 1
        else:
            self.failed += 1

        record = {
            "name": name,
            "model": K3_LABELS.get(model_result, str(model_result)),
            "impl": str(impl_result),
            "impl_normalized": K3_LABELS.get(impl_norm, str(impl_norm)),
            "match": match,
        }
        self.results.append(record)

        if not match:
            print(f"  ✗ {name}: model={K3_LABELS.get(model_result, model_result)}, "
                  f"impl={impl_result}")
        return match

    def _normalize(self, v):
        if v is True: return True
        if v is False: return False
        if v == "undefined": return "undefined"
        if isinstance(v, str) and v.startswith("error:"):
            return "undefined"  # errors map to undefined for comparison
        if v == "action": return True
        return v


def run_test_battery(mode, suite):
    """Run all K3 conformance tests in the given mode."""

    def lits_for(vals):
        """Build literals dict. For undefined values, omit the key."""
        lits = {}
        for key, val in vals.items():
            if val != U:
                lits[key] = val
        return lits

    # ── A. Negation (nai) — 3 tests ─────────────────────────────
    print(f"── A. NEGATION (nai) — 3 tests ──────────────────────────")

    for v in K3_VALUES:
        label = K3_LABELS[v]
        expected = model_not(v)
        ctx = make_context(lits_for({"@x": v}))
        impl = eval_chain("nai @x", ctx, mode=mode)
        suite.test(f"nai {label}", impl, expected)

    recent = suite.results[-3:]
    print(f"  {sum(1 for r in recent if r['match'])}/3")
    print()

    # ── B. Conjunction (an) — 9 tests ────────────────────────────
    print(f"── B. CONJUNCTION (an) — 9 tests ────────────────────────")

    for a in K3_VALUES:
        for b in K3_VALUES:
            la, lb = K3_LABELS[a], K3_LABELS[b]
            expected = model_and(a, b)
            ctx = make_context(lits_for({"@a": a, "@b": b}))
            impl = eval_chain("@a an @b", ctx, mode=mode)
            suite.test(f"{la} an {lb}", impl, expected)

    recent = suite.results[-9:]
    print(f"  {sum(1 for r in recent if r['match'])}/9")
    print()

    # ── C. Disjunction (ur) — 9 tests ───────────────────────────
    print(f"── C. DISJUNCTION (ur) — 9 tests ───────────────────────")

    for a in K3_VALUES:
        for b in K3_VALUES:
            la, lb = K3_LABELS[a], K3_LABELS[b]
            expected = model_or(a, b)
            ctx = make_context(lits_for({"@a": a, "@b": b}))
            impl = eval_chain("@a ur @b", ctx, mode=mode)
            suite.test(f"{la} ur {lb}", impl, expected)

    recent = suite.results[-9:]
    print(f"  {sum(1 for r in recent if r['match'])}/9")
    print()

    # ── D. Guard (kra) — 9 tests ────────────────────────────────
    print(f"── D. GUARD (kra) — 9 tests ─────────────────────────────")

    for g in K3_VALUES:
        for a in K3_VALUES:
            lg, la = K3_LABELS[g], K3_LABELS[a]
            expected = model_guard(g, a)
            ctx = make_context(lits_for({"@g": g, "@a": a}))
            impl = eval_chain("@g kra @a", ctx, mode=mode)
            suite.test(f"{lg} kra {la}", impl, expected)

    recent = suite.results[-9:]
    print(f"  {sum(1 for r in recent if r['match'])}/9")
    print()

    # ── E. Double Negation — 3 tests ────────────────────────────
    print(f"── E. DOUBLE NEGATION — nai(nai(p)) = p ──────────────────")

    for v in K3_VALUES:
        label = K3_LABELS[v]
        expected = v  # nai(nai(p)) = p (involution)
        ctx = make_context(lits_for({"@x": v}))
        impl = eval_chain("nai nai @x", ctx, mode=mode)
        suite.test(f"nai nai {label}", impl, expected)

    recent = suite.results[-3:]
    print(f"  {sum(1 for r in recent if r['match'])}/3")
    print()

    # ── F. De Morgan's Laws — 36 tests ──────────────────────────
    print(f"── F. DE MORGAN'S LAWS — 36 tests ────────────────────────")

    for a in K3_VALUES:
        for b in K3_VALUES:
            la, lb = K3_LABELS[a], K3_LABELS[b]
            ctx = make_context(lits_for({"@a": a, "@b": b}))

            # DM1: nai(a an b) = (nai a) ur (nai b)
            expected = model_not(model_and(a, b))
            impl_lhs = eval_chain("nai sek @a an @b sek", ctx, mode=mode)
            impl_rhs = eval_chain("nai @a ur nai @b", ctx, mode=mode)
            suite.test(f"DM1 {la},{lb} LHS", impl_lhs, expected)
            suite.test(f"DM1 {la},{lb} RHS", impl_rhs, expected)

    for a in K3_VALUES:
        for b in K3_VALUES:
            la, lb = K3_LABELS[a], K3_LABELS[b]
            ctx = make_context(lits_for({"@a": a, "@b": b}))

            # DM2: nai(a ur b) = (nai a) an (nai b)
            expected = model_not(model_or(a, b))
            impl_lhs = eval_chain("nai sek @a ur @b sek", ctx, mode=mode)
            impl_rhs = eval_chain("nai @a an nai @b", ctx, mode=mode)
            suite.test(f"DM2 {la},{lb} LHS", impl_lhs, expected)
            suite.test(f"DM2 {la},{lb} RHS", impl_rhs, expected)

    recent = suite.results[-36:]
    print(f"  {sum(1 for r in recent if r['match'])}/36")
    print()

    # ── G. Safety Invariant — 6 tests ───────────────────────────
    print(f"── G. SAFETY INVARIANT — g ≠ T → (g kra a) = U ──────────")

    for g in [F, U]:
        for a in K3_VALUES:
            lg, la = K3_LABELS[g], K3_LABELS[a]
            ctx = make_context(lits_for({"@g": g, "@a": a}))
            impl = eval_chain("@g kra @a", ctx, mode=mode)
            suite.test(f"Safety: {lg} kra {la} = U", impl, U)

    recent = suite.results[-6:]
    print(f"  {sum(1 for r in recent if r['match'])}/6")
    print()

    # ── H. Fail-Closed — 5 tests ────────────────────────────────
    print(f"── H. FAIL-CLOSED — no U-only expression produces T ──────")

    fail_closed_chains = [
        ("nai @x", "nai U"),
        ("@x an @y", "U an U"),
        ("@x ur @y", "U ur U"),
        ("@x kra @y", "U kra U"),
        ("nai sek @x an @y sek", "nai(U an U)"),
    ]

    for chain, desc in fail_closed_chains:
        ctx = make_context({})  # empty context = all undefined
        impl = eval_chain(chain, ctx, mode=mode)
        suite.test(f"FailClosed: {desc} ≠ T", impl, U)

    recent = suite.results[-5:]
    print(f"  {sum(1 for r in recent if r['match'])}/5")
    print()


# ═══════════════════════════════════════════════════════════════════
# 4. RUN BOTH PASSES
# ═══════════════════════════════════════════════════════════════════

print("=" * 70)
print("NOE IMPLEMENTATION CONFORMANCE BRIDGE")
print("Model (Z3-verified) vs Python Reference Implementation")
print("=" * 70)
print()

# ── Pass 1: Partial mode (K3 core) ──────────────────────────────
print("━" * 70)
print("PASS 1: PARTIAL MODE — K3 evaluation core")
print("  Missing literals → semantic undefined → operators evaluate")
print("━" * 70)
print()

partial_suite = TestSuite("partial")
run_test_battery("partial", partial_suite)

# ── Pass 2: Strict mode (production pipeline) ───────────────────
print("━" * 70)
print("PASS 2: STRICT MODE — NIP-009 production pipeline")
print("  Missing literals → ERR_LITERAL_MISSING → evaluation blocked")
print("━" * 70)
print()

strict_suite = TestSuite("strict")
run_test_battery("strict", strict_suite)

# ═══════════════════════════════════════════════════════════════════
# 5. ANALYSIS AND SUMMARY
# ═══════════════════════════════════════════════════════════════════

print("=" * 70)
print("SUMMARY")
print("=" * 70)
print()

print(f"  Pass 1 (partial): {partial_suite.passed}/{partial_suite.total} "
      f"({partial_suite.failed} failures)")
print(f"  Pass 2 (strict):  {strict_suite.passed}/{strict_suite.total} "
      f"({strict_suite.failed} failures)")
print()

# Analyze strict-mode divergences
if strict_suite.failed > 0:
    # Categorize: which failures are due to missing-literal rejection
    # vs genuine K3 divergence?
    strict_only_failures = []
    genuine_divergences = []

    for sr in strict_suite.results:
        if not sr["match"]:
            # Find the corresponding partial-mode result
            pr = next((p for p in partial_suite.results if p["name"] == sr["name"]), None)
            if pr and pr["match"]:
                strict_only_failures.append(sr)
            else:
                genuine_divergences.append(sr)

    if strict_only_failures:
        print(f"  Strict-only failures (validation layer, not K3 core): {len(strict_only_failures)}")
        print(f"  These are cases where K3 short-circuits (e.g., F∧U=F, T∨U=T)")
        print(f"  but strict mode rejects the chain because a literal is missing.")
        print(f"  This is a deliberate design choice: strict mode requires all")
        print(f"  referenced literals to be present in the context object.")
        print()
        for r in strict_only_failures:
            print(f"    ✗ {r['name']}: model={r['model']}, impl={r['impl']}")
        print()

    if genuine_divergences:
        print(f"  GENUINE K3 DIVERGENCES: {len(genuine_divergences)}")
        for r in genuine_divergences:
            print(f"    ✗ {r['name']}: model={r['model']}, impl={r['impl']}")
        print()

if partial_suite.failed == 0:
    print("╔════════════════════════════════════════════════════════════════════╗")
    print("║  K3 CORE CONFORMANCE: Implementation matches formal model.       ║")
    print("║                                                                   ║")
    print("║  The Python reference implementation produces identical results   ║")
    print("║  to the Z3-verified specification model for every input in the   ║")
    print("║  complete K3 domain (80 tests, 3^n exhaustive).                  ║")
    print("║                                                                   ║")
    print("║  The specification-implementation gap for the K3 evaluation      ║")
    print("║  layer is closed.                                                 ║")
    if strict_suite.failed > 0:
        print("║                                                                   ║")
        print("║  NOTE: Strict mode adds a validation layer that rejects chains    ║")
        print("║  referencing missing literals before K3 evaluation. This is a     ║")
        print("║  deliberate safety contract (NIP-009), not a K3 divergence.       ║")
    print("╚════════════════════════════════════════════════════════════════════╝")
elif partial_suite.failed > 0:
    print(f"⚠ K3 CORE DIVERGENCES FOUND ({partial_suite.failed}):")
    for r in partial_suite.results:
        if not r["match"]:
            print(f"  ✗ {r['name']}: model={r['model']}, impl={r['impl']}")

# ═══════════════════════════════════════════════════════════════════
# 6. SAVE RESULTS
# ═══════════════════════════════════════════════════════════════════

output = {
    "type": "conformance_bridge",
    "description": "Exhaustive comparison of Python implementation against Z3-verified K3 model",
    "timestamp": datetime.utcnow().isoformat() + "Z",
    "passes": {
        "partial": {
            "mode": "partial",
            "description": "K3 evaluation core — missing literals become semantic undefined",
            "total": partial_suite.total,
            "passed": partial_suite.passed,
            "failed": partial_suite.failed,
            "conformant": partial_suite.failed == 0,
            "results": partial_suite.results,
        },
        "strict": {
            "mode": "strict",
            "description": "NIP-009 production pipeline — missing literals rejected pre-evaluation",
            "total": strict_suite.total,
            "passed": strict_suite.passed,
            "failed": strict_suite.failed,
            "conformant": strict_suite.failed == 0,
            "results": strict_suite.results,
        }
    },
    "k3_core_conformant": partial_suite.failed == 0,
    "strict_mode_conformant": strict_suite.failed == 0,
    "coverage": "complete K3 domain (3^n for n-ary operators, 80 tests per pass)",
    "analysis": {
        "k3_operators_correct": partial_suite.failed == 0,
        "strict_divergence_count": strict_suite.failed,
        "strict_divergence_cause": "NIP-009 validation rejects chains referencing missing literals before K3 evaluation — deliberate safety contract" if strict_suite.failed > 0 and partial_suite.failed == 0 else None,
    }
}

outpath = os.path.join(os.path.dirname(__file__), "conformance_bridge_results.json")
with open(outpath, "w") as f:
    json.dump(output, f, indent=2)

print(f"\nResults saved to formal/conformance_bridge_results.json")
