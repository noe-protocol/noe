# AGENTS.md — noe-gate

> This file is for AI coding assistants (Claude Code, Copilot, Cursor, etc.).
> It describes the invariants, constraints, and hazards you must respect when
> working in this repository. Violating these constraints can silently break
> protocol conformance, provenance determinism, or evaluation correctness.

---

## What this repository is

noe-gate is the reference runtime for the Noe protocol — a deterministic
symbolic protocol for representing bounded meaning across agents. It contains
a Python reference implementation, a Rust core implementation, a formal
verification suite, and the NIP-011 conformance test pack.

The Python runtime is the **normative reference**. The Rust implementation
must match it exactly. If they disagree, the Python runtime is authoritative
unless a verified bug exists in the Python (as happened with the K3 Weak/Strong
Kleene fix — see below).

---

## Refusal rule

**If a requested change would violate any invariant in this document, break
conformance vectors, break Python/Rust parity, or lack a required NIP
reference, you must refuse to perform the change.** Do not comply and hedge.
Do not partially apply the change. Do not "try to help." Refuse, explain
which constraint would be violated, and ask the human how to proceed.

This applies equally to direct requests and to changes that seem like
improvements — performance optimizations, cleanup refactors, and
"simplifying logic" are the most common vectors for silently breaking
determinism, evaluation semantics, or hash parity. Do not optimize, refactor,
or simplify code in this repository without explicit instruction and a clear
understanding of which invariants are at risk.

---

## Critical invariants — do not violate

### 1. registry.json is the single source of truth

`noe/registry.json` defines every glyph in the protocol: its `id`, `phonetic`
form, `tier`, `domain`, `type_sig`, `semantic` meaning, and `visual_placeholder`.

**Rules:**
- Never add, remove, rename, or reorder entries without a NIP.
- Never change `phonetic` values. These are the parse tokens the grammar matches.
- The `semantic` field is a display-only English gloss. It is NOT the definition.
  The definition is the evaluation behavior in `noe_parser.py` and `eval.rs`.
- One glyph, one meaning. There are no synonyms. `conflicts_with` fields exist
  to enforce this.

### 2. Evaluation semantics are K3 Strong Kleene

The evaluation engine uses three-valued logic: True, False, Undefined.

**The binary operators are:**
- `an` — conjunction (AND). Defined at `noe_parser.py` line ~597 and `eval.rs` `BinOp::An`.
- `ur` — disjunction (OR). Defined at `noe_parser.py` line ~610 and `eval.rs` `BinOp::Ur`.

**Strong Kleene truth tables (not Weak Kleene):**
- `False an Undefined = False` (False dominates in conjunction)
- `True ur Undefined = True` (True dominates in disjunction)
- `Undefined an True = Undefined`
- `Undefined ur False = Undefined`

**Do NOT use `kel` or `dom` as conjunction/disjunction operators.** These are
not the binary connectives. The grammar operators are `an` and `ur`. This was
the source of a formally verified bug — see the fix history below.

**Other operators you will encounter:**
- `nai` / `nex` — negation (K3: nai Undefined = Undefined)
- `shi` — epistemic knowledge gate (checks `context.modal.knowledge`)
- `sek...sek` — strict scoping (like parentheses, but returns a structural list)
- `kra` — guarded execution (True → pass through, else → Undefined)
- `khi` — conditional guard (lower precedence than disjunction)
- `mek` / `men` — action execution / action completion

### 3. Undefined is not False

Undefined means "insufficient information to evaluate." It is a distinct third
value, not a falsy sentinel. Key consequences:

- Missing literals resolve to Undefined, never False.
- Undefined chains never produce actions (E10 property).
- `nai Undefined = Undefined` (not True).
- Fail-closed: if evaluation cannot determine truth, the result is Undefined
  and the action is NOT executed. This is a safety property.

### 4. Provenance hashes are deterministic

`noe/provenance.py` builds SHA-256 provenance records using `canonical_json`
serialization. The hash depends on every field in a specific canonical order.

**Rules:**
- Never change the field order in `build_provenance_record()`.
- Never change `canonical_json()` in `noe/canonical.py` — it defines the
  byte-level serialization that hashes must agree on across implementations.
- `result_domain in ("error", "undefined")` → `provenance_hash = None`.
  This is property P6 (BlockedNullHash). Do not remove this guard.
- `SEMANTICS_VERSION = "NIP-005-v1.0"` in `provenance.py` — do not change
  without a NIP. This tags every provenance record for replay compatibility.

### 5. Temporal constants are load-bearing

These constants enforce temporal safety (NIP-009 §4.9):

| Constant | Value | Location | Meaning |
|----------|-------|----------|---------|
| `MAX_CLOCK_SKEW_MS` | 200 | `context_projection.py:37` | Max future timestamp tolerance |
| `tau_stale_ms` | 1000 | `context_projection.py:76` | Max evidence age before rejection |
| `tau_window_ms` | 100 | `context_projection.py` | Projection window |
| `theta_thresh` | 0.8 | `context_projection.py` | Confidence threshold |

These are formally verified (T1-T10 properties). Changing any value changes the
acceptance window and can break temporal safety guarantees.

### 6. NIP-011 conformance vectors are locked

`tests/nip011/conformance_pack_v1.0.0.json` contains 80 locked test vectors
with a SHA-256 manifest. These vectors are the ground truth for whether an
implementation is conformant.

**Rules:**
- Never modify locked vectors.
- Never skip or ignore failing conformance tests.
- If your change breaks a conformance vector, your change is wrong.

---

## Python / Rust parity

Both implementations must produce identical outputs for identical inputs.
The Rust implementation at `rust/noe_core/` has 93/93 conformance assertions
passing. Python is the normative reference, but the Rust K3 logic was already
correct when the Python had the Weak Kleene bug — so "normative" means
"specification-defining," not "infallible."

**Key parity surfaces:**
- `noe_parser.py` `_apply_binary_op()` ↔ `eval.rs` `eval_binop()`
- `noe_parser.py` `_to_trit()` ↔ `eval.rs` `to_trit()` / pattern matching
- `provenance.py` `build_provenance_record()` ↔ `hash.rs`
- `canonical.py` `canonical_json()` ↔ `hash.rs` canonical serialization
- `noe_validator.py` ↔ `validator.rs`

**Rules:**
- Do not change evaluation behavior in Python without updating Rust to match,
  or explicitly documenting the gap in `CONFORMANCE_GAPS.md` with a reason
  and promotion path.
- Do not leave parity "for later." A split-brain runtime — where Python and
  Rust produce different outputs for the same input — is worse than a bug.
  Either update both implementations in the same change, or document the
  divergence before the change is considered complete.
- If you cannot update Rust (e.g., unfamiliar with the codebase), refuse the
  Python change and explain that it would break parity.

---

## Grammar precedence (highest to lowest)

```
1. primary         — literal (@x), glyph, sek...sek scope
2. unary_op        — nai, shi, vek, vus, vel, nau, ret, tri, ...
3. action_event    — mek X, men X
4. conjunction_op  — an, kos, til, nel, tel, xel, en, kra, ...
5. disjunction     — ur
6. guard           — khi
```

This means `nai @p an @q` parses as `(nai @p) an @q`, NOT `nai (@p an @q)`.
To negate a conjunction, you must scope it: `nai sek @p an @q sek`.

The `sek...sek` scope returns a structural list (Python: `[value]`). The
`_to_trit()` function unwraps singleton lists, so `nai sek ... sek` works
correctly. Be aware of this if you touch `_to_trit` or `visit_sek_scope`.

---

## Float values in normative inputs

Noe contexts carry float values (confidence scores, timestamps, spatial
coordinates). These flow through hashing and comparison. Rules:

- Never introduce floating-point arithmetic into hash inputs. Use the
  canonical JSON serialization which has deterministic float representation.
- Confidence values are in [0.0, 1.0]. Values outside this range are invalid.
- Timestamps are milliseconds since epoch (integer or float). The temporal
  safety layer uses integer comparison with `MAX_CLOCK_SKEW_MS`.

---

## Formal verification suite

`formal/` contains four exhaustive verifiers:

| File | NIP | Properties | What it checks |
|------|-----|------------|----------------|
| `verify_nip019.py` | NIP-019 | S2-S8, L1-L2 | Multi-agent negotiation protocol |
| `verify_provenance.py` | NIP-010 | P1-P8 | Hash chains, tamper evidence |
| `verify_evaluation.py` | NIP-005/009 | E1-E10 | K3 truth tables, De Morgan, fail-closed |
| `verify_temporal.py` | NIP-009 §4.9 | T1-T10 | Stale/future rejection, boundary precision |

Plus `NIP019.tla` (TLA+ specification) and `NIP019.cfg`.

**After any change to evaluation, provenance, temporal, or agent negotiation
logic, you must run the relevant verifier before the change is considered
complete.** Zero violations is required — not recommended, required. A change
that introduces any violation is not finished. Do not commit, do not move on,
do not mark the task as done until the verifier passes clean.

```bash
python formal/verify_evaluation.py   # after touching noe_parser.py
python formal/verify_provenance.py   # after touching provenance.py or canonical.py
python formal/verify_temporal.py     # after touching context_projection.py
python formal/verify_nip019.py       # after touching agent.py or agent_auth.py
```

---

## Fix history — known hazards

### K3 Weak Kleene → Strong Kleene (2026-03)

`_apply_binary_op` in `noe_parser.py` had a blanket early-return for undefined
operands (lines ~1955-1958) that fired BEFORE the K3-specific `an`/`ur` logic.
This made `False an Undefined = Undefined` (Weak Kleene / Bochvar) instead of
the correct `False an Undefined = False` (Strong Kleene).

**Fix:** Added `if op not in ("an", "ur"):` guard around the blanket undefined
propagation. The `an`/`ur` handlers already had correct K3 logic — they just
weren't being reached.

**Related fix:** `_to_trit` didn't unwrap singleton lists from `sek...sek`
scoping. Added singleton-list unwrapping so `nai sek P an Q sek` evaluates
correctly.

The Rust implementation (`k3_and`/`k3_or` in `eval.rs`) was already correct.
This bug was Python-only.

---

## Test suite structure

```
tests/
├── nip011/                  NIP-011 conformance (locked, DO NOT MODIFY)
├── adversarial/             Red-team security tests
├── test_nip019_agent.py     Multi-agent protocol (Phase 3)
├── test_nip019_phase4.py    Network, clock, byzantine, scale (Phase 4)
├── test_nip019_phase5.py    PKI auth + chaos network (Phase 5)
├── test_safety_*.py         Safety kernel invariants
├── test_hashing_*.py        Hash determinism
├── test_canonical_*.py      Canonical serialization
└── fuzz_noe.py              Fuzzing harness
```

Run the full suite (excluding known broken imports) with:
```bash
python -m pytest tests/ -q \
  --ignore=tests/adversarial/test_anti_axiom_security.py \
  --ignore=tests/btcpp_converter/ \
  --ignore=tests/persistence/
```

---

## Pre-edit checklist

Before completing any change to this repository, verify all of the following:

1. **Conformance:** Does this change break any NIP-011 conformance vector?
   Run `python -m pytest tests/nip011/ -q` and confirm all vectors pass.
2. **Parity:** Does this change affect evaluation, hashing, or validation?
   If yes, verify Python and Rust still produce identical outputs, or document
   the gap in `CONFORMANCE_GAPS.md`.
3. **Determinism:** Does this change affect `canonical_json()`,
   `build_provenance_record()`, or any hash computation? If yes, verify
   hash outputs are unchanged for existing inputs.
4. **Temporal safety:** Does this change affect `context_projection.py` or
   any temporal constant? If yes, run `python formal/verify_temporal.py`
   and confirm zero violations.
5. **Evaluation correctness:** Does this change affect `noe_parser.py` or
   any evaluation logic? If yes, run `python formal/verify_evaluation.py`
   and confirm zero violations.
6. **Safety invariant:** Does this change introduce any path where Undefined
   evaluation could result in action execution? If yes, reject the change.

This checklist is not optional. It runs on every edit. If any check fails,
the change is not complete.

---

## What NOT to do

- **Do not rename operators.** `an` is conjunction, `ur` is disjunction. These
  are not abbreviations to be expanded. They are the canonical phonetic tokens.
- **Do not "improve" English glosses in registry.json.** The glosses are
  display-only and must not be treated as definitions.
- **Do not add default values for missing context fields.** Missing = Undefined.
  Fabricating a default violates fail-closed semantics.
- **Do not refactor `canonical_json()`.** The byte-level output is a protocol
  invariant. Even whitespace changes break hash parity.
- **Do not change test vector expected values.** If your code doesn't match the
  vector, your code is wrong.
- **Do not use `kel` or `dom` as binary operators.** These are glyph phonetics
  in the registry but they are NOT the grammar's conjunction/disjunction.
