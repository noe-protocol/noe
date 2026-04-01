# Formal Verification

Machine-checked proofs of Noe's evaluation semantics, provenance integrity, temporal safety, and end-to-end safety invariant.

## Summary

Four proof suites provide full pipeline coverage across K3 evaluation, temporal filtering, provenance integrity, and authorization. 117 properties total, zero violations, verified using the Z3 SMT solver (v4.12.2). Isabelle/HOL theory files included for independent verification.

| Suite | File | Properties | What it proves |
|-------|------|-----------|----------------|
| K3 semantics | `noe_k3_proofs.py` | 53 | Complete truth tables, algebraic laws (commutativity, associativity, De Morgan, distributivity, absorption), Strong Kleene characterisation, excluded middle failure, lattice structure |
| Provenance | `noe_provenance_proofs.py` | 18 | Null hash on undefined, determinism, tamper detection (given collision resistance), chain break propagation, guard-provenance integration, completeness |
| Temporal safety | `noe_temporal_proofs.py` | 23 | Staleness rejection, clock skew bounds, boundary precision, monotonicity, multi-agent negotiation (commutativity, associativity, idempotence), negotiated safety, full pipeline |
| Safety kernel | `noe_safety_kernel_proofs.py` | 23 | Guard composition, nested guards = conjunction, fail-closed closure, end-to-end pipeline, audit theorem, negotiated multi-agent safety |

The structurally significant results are the algebraic laws (De Morgan, distributivity), the fail-closed closure property (no expression over only-undefined inputs can produce True), and the end-to-end safety kernel theorems. The truth table entries provide exhaustive ground truth but are individually trivial.

## The master theorem

**SK2 (Audit Theorem):** If a provenance record has a non-null hash, then the evidence was temporally fresh AND the guard evaluated to True.

The definitions are precise:

- **"Authorized"** = the evaluation produced a non-null provenance hash (an observable, auditable artifact — not just internal state)
- **"Uncertain"** = K3U (the third truth value in Strong Kleene three-valued logic, meaning insufficient information)
- **"Temporally fresh"** = evidence age is within `[−max_skew, tau_stale]` milliseconds

The proof chain: temporal freshness → K3 evaluation → guard truth → provenance emission. Each link is formally verified. SK2 proves the composition holds end-to-end.

This theorem underpins the runtime invariant that undefined evaluation results cannot produce action execution (`mek` never fires when the guard is not provably True).

## Soundness and completeness

The K3 proofs are both sound and complete: the domain has exactly three values, and Z3 performs exhaustive case analysis over all possible inputs. No counterexample can exist and none is missed.

The temporal and provenance proofs are sound (Z3 UNSAT = the property holds universally over the model) but are complete only relative to the model. The model uses integer arithmetic for time and an uninterpreted function for hashing. Properties proven here hold for any system that conforms to the model — but the model does not capture all real-world failure modes (see Limitations).

## Reproduce

```bash
pip install z3-solver==4.12.2
python3 noe_k3_proofs.py
python3 noe_provenance_proofs.py
python3 noe_temporal_proofs.py
python3 noe_safety_kernel_proofs.py
```

Each script prints results to stdout and writes structured JSON to a `*_proof_results.json` file.

## Isabelle/HOL

Four Isabelle theory files are provided for verification in a higher-assurance proof assistant. They must be checked in dependency order:

1. `Noe_K3.thy` — standalone
2. `Noe_Provenance.thy` — imports Noe_K3
3. `Noe_Temporal.thy` — imports Noe_K3
4. `Noe_Safety_Kernel.thy` — imports all three

To check interactively: open in Isabelle/jEdit (requires [Isabelle 2024+](https://isabelle.in.tum.de)).

To batch check:
```bash
isabelle build -D . -o document=false
```

A `ROOT` session file is required for batch builds:
```
session Noe_Proofs = HOL +
  theories
    Noe_K3
    Noe_Provenance
    Noe_Temporal
    Noe_Safety_Kernel
```

## Scope and limitations

**What is verified:** the mathematical model of Noe's evaluation pipeline — the K3 operators, guard semantics, provenance hash structure, and temporal freshness predicate as abstract functions with formally specified behavior.

**What is not verified:** the Python and Rust implementations are not proven to conform to this model. The proofs verify the specification, not the code. This is specification-level verification (comparable to TLA+ for distributed systems), not implementation-level verification (comparable to seL4 or CompCert). Implementation correctness currently relies on the NIP-011 conformance suite (93 locked vectors, SHA-256 manifest) and cross-runtime parity testing.

**Assumptions:**

- **Collision resistance.** Provenance proofs assume SHA-256 collision resistance (modeled as hash function injectivity). This is standard cryptographic practice.
- **Clock integrity.** Temporal proofs model time as integers and assume the system clock is trustworthy. The temporal safety guarantee depends on clock integrity — if an attacker can manipulate the clock, the staleness and skew bounds do not hold. In practice, clock integrity is often the weakest link in real-time systems, and deployments should treat NTP/PTP integrity as a security requirement.
- **K3 completeness.** K3 proofs are exhaustive over the finite three-valued domain — no assumptions required.

## Files

```
noe_k3_proofs.py                  Z3 proof script — K3 semantics
noe_k3_proof_results.json         Structured results
noe_provenance_proofs.py          Z3 proof script — provenance
noe_provenance_proof_results.json Structured results
noe_temporal_proofs.py            Z3 proof script — temporal safety
noe_temporal_proof_results.json   Structured results
noe_safety_kernel_proofs.py       Z3 proof script — end-to-end safety
noe_safety_kernel_proof_results.json Structured results
Noe_K3.thy                        Isabelle/HOL — K3 semantics
Noe_Provenance.thy                Isabelle/HOL — provenance
Noe_Temporal.thy                  Isabelle/HOL — temporal safety
Noe_Safety_Kernel.thy             Isabelle/HOL — end-to-end safety
```
