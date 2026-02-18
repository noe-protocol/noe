# Noe Auditor Demo: Deterministic Execution Certificates

**Reference Standards:**

| NIP | Scope |
|-----|-------|
| NIP-005 | Chain Grammar: syntax and evaluation rules for Noe expressions |
| NIP-009 | Context Specification: layered context model (`C_root`, `C_domain`, `C_local` -> `C_safe`) |
| NIP-010 | Provenance Certificates: schema and replay rules for execution evidence |
| NIP-015 | Strict Mode: deterministic evaluation constraints and error semantics |

**Status / Commit:** This README describes the behavior of the reference evaluator as of commit `d0bc1a9`. If behavior differs in your local checkout, treat the code as authoritative.

This demo demonstrates how Noe provides **hash-committed execution certificates** to resolve the liability bottleneck in autonomous systems. Noe implements a deterministic provenance format for autonomous decisions, providing an evidence trail intended to support admissibility in safety-critical domains.

<br />

## Why This Demo Exists

As autonomous systems enter regulated spaces, safety-relevant decisions must move from "black box" logs to **audit-ready evidence**. Regulators and insurers require that every critical action:

* **Is Reproducible:** The logic can be re-evaluated bit-identically by a third party.
* **Is Grounded:** The specific world-state used for authorization is captured.
* **Is Traceable:** Every decision is hash-committed to a specific system state (and can be anchored to an external append-only log or chain).

<br />

## Folder Layout

Demos 1-4, plus one variant script:

```
examples/auditor_demo/
+-- README.md                              <-- You are here
+-- run_demo.sh                            <-- Runs all scenarios end-to-end
+-- verify_shipment.py                     <-- Demo 1: Happy path, stale fail-stop, tamper detection
+-- verify_shipment_uncertain.py           <-- Demo 2: Epistemic gap (confidence trap)
+-- verify_shipment_stale.py               <-- Demo 2 variant: staleness-only scenario
+-- verify_hallucination.py                <-- Demo 3: Cross-modal hallucination firewall
+-- verify_multi_agent.py                  <-- Demo 4: Mutual safety arbitration
+-- shipment_certificate_strict.json       <-- Output: happy-path certificate
+-- shipment_certificate_REFUSED.json      <-- Output: fail-stop certificate
+-- shipment_certificate_epistemic.json    <-- Output: epistemic-gap certificate
+-- hallucination_certificate_*.json       <-- Output: hallucination scenario certificates
+-- cert_green.json / cert_yellow.json / cert_red.json  <-- Output: multi-agent certificates
+-- ...
```

<br />

## What It Demonstrates

### 1. Deterministic Decision Replay

Given the same chain and `C_safe`, the outcome is identical across runs under the pinned reference runtime. Proven via bit-identical hashes in the emitted certificates.

> **Portability caveat:** Bit-identical replay is only claimed for runtimes that match the reference canonicalization exactly (see NIP-011 conformance vectors). We do not claim cross-runtime or cross-library equivalence without passing those vectors.

<br />

### Determinism Preconditions

Bit-identical replay is not a free property. The following constraints make it true in the reference evaluator:

* **No wall-clock calls during evaluation:** Staleness checks use `C_safe.temporal.now_us` (frozen at context assembly time), never `time.time()` during chain evaluation. The evaluator is a pure function of `(chain, C_safe)`.
* **No floats in hashed paths:** All numeric values in context are integers (e.g., `int64` microsecond timestamps, millicelsius, millimeters). `NaN`/`Inf` are rejected by `canonical_json(allow_nan=False)` (guaranteed by shared `noe.canonical` module).
* **Stable hashing:** SHA-256 over canonical JSON bytes. No use of Python's built-in `hash()` (which is randomized per-process via `PYTHONHASHSEED`).
* **Deterministic map ordering:** All context dicts are serialized with `sort_keys=True` before hashing.
* **Pinned runtime:** The reference evaluator targets CPython 3.10+, and all hashed artifacts use `noe.canonical.canonical_json()` (sort keys, no `NaN`/`Inf`).
* **Chain canonicalization:** The chain string is normalized via `canonicalize_chain()` (defined in `noe/canonical.py`): Unicode NFKC normalization, whitespace collapsed to single spaces, leading/trailing whitespace stripped. Certificates canonicalize the chain before hashing (via `noe.provenance`). Replay should evaluate the canonicalized chain (or use an evaluator that canonicalizes internally).

<br />

### Canonicalization: Unified Implementation

The reference auditor demo and provenance layer use a **single source of truth** for JSON canonicalization: `noe.canonical.canonical_json()`.

| Parameter | Value | Reason |
|-----------|-------|--------|
| `ensure_ascii` | `True` | Maximum compatibility; forces Unicode to escape sequences (e.g. `\uXXXX`). |
| `allow_nan` | `False` | Determinism; rejects `NaN` / `Infinity` which are invalid in standard JSON. |
| Returns | `str` | Standardized string format before encoding to bytes for hashing. |

This ensures that context hashes are bit-identical for certificates emitted by the auditor demo and any component that uses `noe.canonical.canonical_json()`.

<br />

### 2. Epistemic Grounding (NIP-009)

Shows the **Safety Kernel** filtering a raw context through the projection function `pi_safe` (implemented as `project_safe_context()`).

**Grounded propositions** are those retained in `C_safe` after projection applies staleness pruning and threshold gating. In the reference implementation, the grounded set lives in `C_safe.modal.knowledge`. This is the field that `shi` looks up at evaluation time.

#### `shi` Lookup Logic (Reference Implementation)

The `shi` operator (implemented in `noe/noe_parser.py`, `_apply_unary_op()`) works as follows:

1. Extract the literal key from the operand (e.g., `@temperature_ok`).
2. Retrieve `C.modal` from the effective context. If `C.modal` is missing or not a dict, return `"undefined"`.
3. Get `knowledge` map from `C.modal` (defaults to `{}`).
4. Look up the key in `C.modal.knowledge` (tries both `key` and `@key` forms).

| Condition | Result in strict mode | Result in non-strict mode |
|-----------|----------------------|--------------------------|
| `C.modal` is missing or not a dict | `"undefined"` | `"undefined"` |
| Key not found in `C.modal.knowledge` | Error object: `{"domain": "error", "code": "ERR_EPISTEMIC_MISMATCH", ...}` | `"undefined"` |
| Key found in `C.modal.knowledge` | Returns the stored value (e.g., `true`) | Returns the stored value |

**Strict mode behavior:** In strict mode, a missing key in `C.modal.knowledge` returns an `ERR_EPISTEMIC_MISMATCH` error object (not plain `"undefined"`). When this error object flows into an action guard (`khi`), it triggers non-execution (the fail-stop invariant).

The same pattern applies to `vek` (checks `C.modal.belief`, falling back to `C.modal.knowledge`) and `sha` (checks `C.modal.certainty` against a threshold, then looks up truth value in `C.modal.knowledge` or `C.modal.belief`).

The projection performs:

* Pruning **stale** sensor data (Temporal Safety): any literal with `timestamp_us` older than `max_staleness_us` is removed from `C_safe.literals` and `C_safe.modal.knowledge`.
* Handling **probabilistic** fields (Confidence Thresholds): confidence/probability fields are stripped; membership in `C_safe.modal.knowledge` is binary after projection.
* Enforcing the **Non-Execution Invariant**: evaluation uses 3-valued logic (`True` / `False` / `Undefined`/`Error`). In strict mode, any `Undefined` or `ERR_EPISTEMIC_MISMATCH` on a safety-relevant gate yields non-execution and a refusal certificate. A **safety-relevant gate** is any predicate upstream of an action emission (`mek`) under NIP-015 strict mode, equivalently, any `shi` / `vek` / `sha` call whose result flows into a `khi` (conditional) that guards a `sek...sek` (action block).

<br />

### 3. Provenance Integrity (NIP-010)

Generation of **Execution Certificates**: SHA-256 commitments over the logic, context, and outcome. The format is designed for high-integrity anchoring to a blockchain or immutable ledger.

<br />

## Threat Model and Security Guarantees

**What is Proven:** The integrity of the decision logic, the replayability of the specific `C_safe` snapshot, and bit-identical outcomes under the CPython 3.10+ reference evaluator with the canonicalization described above.

**What is NOT Proven:**

* *Perception Truth:* The truth of upstream sensor data. If a sensor lies, Noe hash-commits the lie, crystallizing it for forensic analysis, not validating it.
* *Proposer Identity:* Unless digital signatures are applied externally (see Anchoring section).
* *System-level Liveness:* Recovery, fault tolerance, and availability guarantees are out of scope.
* *Remote Execution Integrity:* This demo assumes the validator is the local root of trust. Production deployments should pair certificates with code-signing / build attestation and issuer signatures.

**Root-of-Trust Assumptions:**

* Host OS integrity is assumed (no kernel-level compromise).
* Context assembly pipeline integrity is assumed (sensor drivers, timestamps, transport).
* The evaluator binary has not been tampered with (code signing / reproducible builds are a future extension).

<br />

## Running the Demos

### Quick Start

```bash
chmod +x run_demo.sh
./run_demo.sh
```

### Demo 1: The Happy Path (Provenance and Auditability)

`verify_shipment.py` runs three scenarios in sequence: happy path, stale fail-stop, and tamper detection.

Shows a successful decision with valid, fresh data.

```bash
cd examples/auditor_demo
export PYTHONPATH=../..
python3 verify_shipment.py
```

**Expected output:**

```
======================================================================
NOE AUDITOR DEMO: Shipment Verification (Strict)
======================================================================

SCENARIO 1: Happy Path (All Fresh Sensors)
   Result: list[action] -> ACTION EXECUTED
   Written to: shipment_certificate_strict.json

SCENARIO 2: Stale Context (Fail-Stop Demonstration)
   Result: REFUSED (undefined)
   NO ACTION EMITTED - Fail-Stop Succeeded

REPLAY VERIFICATION (Happy Path)
Replay successful: Bit-identical context and outcome verified.

TAMPER DETECTION TEST (The Liability Firewall)
   SUCCESS: Tampering Detected!

DEMO COMPLETE: Integrity Verified
======================================================================
```

**Verification (replay from certificate):**

```bash
# The script runs replay automatically. To replay manually:
python3 -c "
from verify_shipment import replay_from_certificate
from pathlib import Path
ok, msg = replay_from_certificate(Path('shipment_certificate_strict.json'))
print(f'REPLAY_MATCH={ok}')
print(msg)
"
```

* **Outcome:** `shipment_certificate_strict.json`
* **Replay:** `REPLAY_MATCH=True` -- hashes match bit-for-bit.

<br />

### Demo 2: The Epistemic Gap (Confidence Trap)

Shows Noe blocking an action where a sensor is fresh but **noisy/uncertain** (Confidence: 0.85).

* **Noe Logic:** `shi` (grounded-true under `C_safe.modal.knowledge`) fails because the confidence score does not meet the strict-mode threshold.
* **Threshold source:** The `0.90` gate is defined in the domain safety policy within `C_safe`. It is therefore covered by the certificate's `context_hashes.safe`, ensuring the threshold itself is replay-stable. NIP-009 defines *where* thresholds live in the context structure and the projection mechanics; the *specific values* are domain policy embedded in `C_safe`.
* **Result:** `0.85 < 0.90` -> proposition excluded from `C_safe.modal.knowledge` by `project_safe_context()` -> `shi` returns `ERR_EPISTEMIC_MISMATCH` -> **BLOCKS**.

<br />

### Demo 3: The Hallucination Firewall (Cross-Modal Safety)

Shows Noe blocking a dangerous maneuver when a Vision Model (VLM) hallucinates a door, but Lidar confirms a solid wall.

* **Logic:** `shi @visual_door_detect an shi @lidar_depth_open` (`an` = logical AND)
* **Result:** `True an False` -> **Safe Halt**.

<br />

### Demo 4: Mutual Safety Arbitration

Two robots must agree on human safety to enable motion. Noe validates each proposed action deterministically; the consensus layer runs above Noe as a liveness/policy layer.

```bash
python3 verify_multi_agent.py
```

<br />

## Why Noe Matters for LLM Governance

Large Language Models are probabilistic; you cannot cryptographically "replay" an LLM's internal weights across different versions or hardware.

Noe provides the **Safety Floor**: a deterministic, symbolic validation layer that sits *below* the LLM.

1. **LLM (Proposer):** Suggests an action.
2. **Noe (Kernel):** Evaluates the suggestion against `C_safe.modal.knowledge`.
3. **Result:** Hallucinations are trapped and converted into deterministic **Non-Execution** events.

<br />

## How to Read a Noe Execution Certificate (NIP-010)

A Noe certificate is a frozen evidence object. The JSON schema shown below is derived from the current demo output (`shipment_certificate_strict.json`). If the reference evaluator or demo scripts change field names, this section must be updated in the same PR.

**Replay anchor:** Deterministic replay requires only `chain` + `context_snapshot.safe`. The `root`, `domain`, and `local` layers are included for traceability and independent hash verification, but are not inputs to the replay function. `C_safe` MUST include all policy thresholds and gate definitions required for evaluation; replay MUST NOT consult external configuration. Replay MUST use the evaluator pinned in `evaluation` (or an implementation proven equivalent via NIP-011 conformance vectors). Strict mode additionally enforces ≤ 1 emitted action per evaluation (NIP-015).

### Action Hashing: Single Source of Truth

Action hashing is centralized in **`noe/provenance.py:compute_action_hash()`**.

This function guarantees:
1.  **Normalization:** Filters volatile fields (`status`, `provenance`, timestamps, etc.) and sorts keys.
2.  **Canonical Serialization:** Uses `noe.canonical.canonical_json()` (`ensure_ascii=True`, `allow_nan=False`).
3.  **Stability:** Returns a consistent SHA-256 hash regardless of where it is called (parser, runtime, or auditor tools).

The outdated divergent implementations in `noe_parser.py` and demo scripts have been removed and replaced with imports from `noe.provenance`.

### Certificate Schema (Current Demo Output)

The following schema is from `shipment_certificate_strict.json` (Demo 1). Other demos produce slightly different certificate structures (e.g., `verify_multi_agent.py` adds a `signatures` field and `scenario` field).

```json
{
  "noe_version": "v1.0-rc1",
  "spec_version": "NIP-010-draft",
  "chain": "shi @temperature_ok an shi @location_ok ...",
  "created_at": "2026-02-18T06:14:49Z",
  "context_hashes": {
    "root": "<sha256>",
    "domain": "<sha256>",
    "local": "<sha256>",
    "safe": "<sha256>"
  },
  "context_snapshot": {
    "root": { "...": "full C_root" },
    "domain": { "...": "full C_domain" },
    "local": { "...": "full C_local" },
    "safe": { "...": "full C_safe (THE replay anchor)" }
  },
  "outcome": {
    "domain": "list",
    "value": [ { "type": "action", "verb": "mek", "...": "..." } ],
    "action_hash": "<sha256>",
    "meta": {
      "safe_context_hash": "<sha256>",
      "mode": "strict"
    }
  },
  "evaluation": {
    "mode": "strict",
    "runtime": "python-reference",
    "nip": ["NIP-005", "NIP-009", "NIP-010", "NIP-014"]
  }
}
```

### Field Reference

| Field | Source | Notes |
|-------|--------|-------|
| `chain` | `SHIPMENT_CHAIN` constant in each demo | Stored as-is. Canonicalized via `canonicalize_chain()` (NFKC) before hashing in `noe/provenance.py`. |
| `created_at` | `time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())` | Wall-clock UTC (ISO 8601 with `Z` suffix). **Not part of the replay determinism invariant.** |
| `context_hashes.safe` | `SHA-256(canonical_json(C_safe))` | Computed using the shared `noe.canonical.canonical_json()` (`ensure_ascii=True`, `allow_nan=False`). |
| `context_snapshot.safe` | The actual `C_safe` dict | Full projected context. Replay loads this and re-evaluates `chain` against it. |
| `outcome.domain` | Evaluation result | `"list"` for standard action outcomes (even single actions), `"undefined"` for non-execution, `"error"` for errors. |
| `outcome.action_hash` | `noe.provenance.compute_action_hash()` | **Unified.** In strict mode, the top-level `outcome.action_hash` is computed from the single emitted action: `compute_action_hash(outcome.value[0])`. Lenient/multi-agent certificates define their hashing rule in the emitting script (e.g., `verify_multi_agent.py`). |
| `outcome.meta.safe_context_hash` | `SHA-256(canonical_json(C_safe))` | Explicitly injected in all demos to bind the result to the safe context. |
| `evaluation.mode` | Hardcoded | `"strict"` in Demos 1-3 (safety kernel); `"lenient"` in Demo 4 (multi-agent arbitration layer, above the safety kernel). |

### Non-Execution Paths

When evaluation yields `domain: "undefined"` or `domain: "error"`, the `build_provenance_record()` function in `noe/provenance.py` sets `action_hash = None`.

### The Auditor's Checklist

To verify a Noe decision, an auditor performs the following steps:

1. **Recompute context hashes:** Hash `context_snapshot.safe` using `noe.canonical.canonical_json()`. Verify it matches `context_hashes.safe`.
2. **Deterministic replay:** Load `chain` and `context_snapshot.safe` into the reference evaluator (`noe_parser.run_noe_logic()`) under the mode specified in `evaluation.mode`.
3. **Validate outcome:** Confirm the replayed `outcome.domain` and `outcome.value` match the certificate.
4. **Verify action hash (if applicable):** In strict mode, verify `outcome.domain == "list"` and `len(outcome.value) == 1`, then compute `action_hash = noe.provenance.compute_action_hash(outcome.value[0])` and compare to `outcome.action_hash`.
5. **Verify non-execution (if applicable):** If `outcome.domain` is `"undefined"`, confirm no `action_hash` fields are present.

<br />

## Optional: Anchoring and Signatures

Hash commitments prove *integrity* (tamper evidence). To prove *provenance* (who issued when), the certificate can be externally anchored:

| Method | What It Adds | How |
|--------|-------------|-----|
| **Deploy-key signature** | Proves issuer identity | Sign the certificate body (or a hash of it) with an Ed25519/ECDSA deploy key. |
| **Append-only log** | Proves temporal ordering | Write a certificate hash + `created_at` to a Merkle-based transparency log (e.g., Sigstore Rekor, Trillian). |
| **Blockchain anchor** | Proves global ordering + immutability | Commit a certificate hash to an on-chain transaction (e.g., Ethereum calldata, Bitcoin OP_RETURN). |

**What anchoring does NOT add:** It does not change the replay or determinism guarantees. Those are properties of the evaluator and `C_safe`. Anchoring adds *non-repudiation* and *temporal proof* on top of the existing integrity guarantees.

This demo does not implement signing or anchoring. It produces the hash-committed certificate that these mechanisms would consume.

<br />


<br />

## Planned / Future Extensions

The following are not implemented in the current reference evaluator or demo output:

| Feature | Purpose | Status |
|---------|---------|--------|
| `hash_domain` field | Protocol version tag (e.g., `"noe-cert:v1"`) to prevent cross-protocol hash collisions | Planned |
| `certificate_hash` field | Top-level SHA-256 commitment over the certificate body for external anchoring | Planned |
| `evaluator_version` field | Git commit or semver of the evaluator binary (e.g., `noe-python-ref@v1.0.0`) | Planned |
| `registry_hash` in certificate | Already computed by `provenance.py:compute_registry_hash()` but not yet included in demo certificates | Planned |


<br />

## Insurance and Liability Relevance

**Why certificates change disputes.**

In autonomous incidents, liability often turns on **standard of care** and **reconstructability**, not perfect perception truth. A Noe Execution Certificate provides a frozen, hash-committed record of:

1. The **policy/logic** evaluated (the chain).
2. The **grounded context snapshot** used for authorization (`C_safe` + hashes).
3. The **deterministic outcome** (action or non-execution).

This enables:

* **Claim triage:** Was a safety gate violated, or did the system correctly halt on `undefined`?
* **Subrogation:** If a specific sensor feed provided the state that triggered the decision, the evidence trail supports shifting liability to the responsible component vendor.
* **Dispute resolution:** Third parties can replay the decision deterministically to confirm the action was or was not permitted under the captured context.

**Non-goal:** The certificate does not prove sensor truth. It proves what the system could justify at decision time under strict evaluation rules.

<br />

## Engineering Constraints:

* **"The Latency Tax":** Noe is a **Supervisor**, not a Reflex. You use Noe to decide *if* the robot enters the room (1Hz), not to balance the motors (1kHz).
* **"Garbage-In, Hash-Committed-Garbage-Out":** Noe does not solve sensor truth; it solves **Standard of Care**. By hash-committing the lie, Noe **crystallizes the state**. You can prove exactly which sensor lied, shifting liability from the System Integrator to the Component Vendor.
