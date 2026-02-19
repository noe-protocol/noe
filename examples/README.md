# Noe Canonical Examples

This directory contains fully worked, realistic examples demonstrating Noe semantics aligned with the core specifications.

**Reference Standards**:
* **NIP-005**: Chain Grammar and basic evaluation.
* **NIP-009**: Context Specification (projection and layering).
* **NIP-010**: Provenance and Audit semantics (covers `men`).
* **NIP-015**: Strict Mode and Error Semantics (covers fail-stop logic).

## Examples

### 1. [Stop if Human Present](01_stop_if_human_present.md)
**Demonstrates**: Epistemic-gated action with `shi` (knowledge) operator  
**Key Concepts**:
- **3-valued Semantics**: Undefined/error states propagate; strict-mode gates (`khi`) refuse execution on non-positive knowledge.
- **Safety-first design**: Only act on positive knowledge (`shi`).
- **NIP-015 Enforcement**: Non-execution invariant when data is missing or ambiguous (see [Auditor Demo](../auditor_demo/README.md)).

**Use Case**: Safety-critical human detection in robotics.

<br />

### 2. [Sensor-Drift Audit Request](02_sensor_drift_audit.md)
**Demonstrates**: Delivery + audit operators working together  
**Key Concepts**:
- **Delivery (`vus`)**: Event routing to external subsystems (draft; see `noe/noe_parser.py`).
- **Audit (`men`)**: Provenance logging and state-snapshot commitment (NIP-010).
- **Strict-mode guard rule**: Actions emit only when the guard is `true`; `false`, `undefined`, or `error` all yield non-execution.
- **Pure Evaluation**: The interpreter is a pure function of `(chain, C_safe)`. Context updates are handled out-of-band by adapters.

**Use Case**: Sensor validation and audit trail in safety-critical systems.

<br />

## Execution Model
The Noe interpreter is **pure** and **stateless**. It does not mutate context during evaluation. 
1. **Evaluation**: Returns a list of proposed actions (e.g., `mek`, `vus`, `men`).
2. **Execution**: System-level adapters consume these actions to effect change or update state.
3. **Re-Projection**: Any state changes are reflected in the next context tick, which is then re-projected to `C_safe` before the next evaluation.

<br />

## Structure & Layout
These are **static worked examples** (no automated runner). Each example follows a standard format:
- `Intent`: Semantic goal.
- `Noe Chain`: The Noe expression.
- `Context (Before)`: The initial state of `C_total` (for traceability; replay uses the `C_safe` projection).
- `Evaluation`: Step-by-step trace of the logic.
- `Result`: Final interpreter output.
- `Context (After)`: Conceptual state of the system *after* adapters process the output.

## Conformance Testing
These examples serve as templates for NIP-011 conformance vectors. To integrate into `tests/nip011/`:
1. Extract the `chain` and `context`.
2. Wrap in a standard vector format (see `nip011_manifest.json`).
3. Targeted files: `nip011_epistemic.json` for Example 1, `nip011_audit.json` for Example 2.

## Integration
For ROS2/PX4/Circular integration:
- **Actions** (`mek`, `vus`, `men`) → routed to appropriate hardware/log adapters.
- **State Updates** → applied out-of-band; never inside the Noe evaluation loop.
