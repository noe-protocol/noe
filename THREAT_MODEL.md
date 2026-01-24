# Threat Model & Security Limits

> **Version**: 1.0  
> **Applicability**: Noe Runtime v1.0

This document defines the security model, trust boundaries, and specific guarantees provided by the Noe runtime. It is intended for security auditors, system architects, and integrators.

<br />

## 1. Adversary Model & Trust Boundaries

### 1.1. Trust Boundaries
Noe operates as a **Policy Decision Point (PDP)** within a larger robotic or agentic system.

*   **Trusted Components (TCB)**:
    *   **The Noe Binary/Runtime**: Assumed to be executed as intended on the host CPU.
    *   **The Registry (Policy Store)**: Assumed to be tamper-evident or immutable (e.g., signed Git repo, hash-pinned).
    *   **The Context Manager Thread**: Assumed to have exclusive write access to the context object during a tick properly synchronized by the integrator.
    *   **The Host Clock**: Assumed to provide monotonic time for staleness checks.

*   **Untrusted / Adversarial inputs**:
    *   **Action Chains (The Proposer)**: The LLM or planner generating action chains is considered **completely untrusted**. It may originate from a compromised model, a hallucinating agent, or a malicious external actor.
    *   **Context Data (The Sensors)**: While the *schema* is enforced, the *veracity* of the data is out of scope (Garbage In, Garbage Out). However, the *timeliness* (staleness) is enforced.

### 1.2. Adversary Goals
An adversary (e.g., a prompt-injected LLM) aims to:
1.  **Force Unsafe Execution**: Cause the robot to execute an action that violates safety preconditions (e.g., `mek move` when `human_dist < 1.0`).
2.  **Bypass Auditing**: Execute an action without generating a traceable provenance record.
3.  **Denial of Service**: Supply malformed chains or context to crash the validator loop.

<br />

## 2. Assets & Failure Consequences

### 2.1. Assets to Protect
1.  **Safety Invariants**: Rules defined in the Registry (e.g., "Must allow `mek` ONLY IF `context.safe`").
2.  **Audit Trail**: The cryptographic binding between Context + Chain + Decision = ActionHash.
3.  **Determinism**: The guarantee that `f(Context, Chain)` always produces the same `Verdict`.

### 2.2. Failure Consequences
*   **False Positive (Unsafe Allow)**: Catastrophic physical risk (collision, data leak). **Critical Severity**.
*   **False Negative (Safe Block)**: Operational inefficiency (robot stops unnecessarily). **Medium Severity**.
*   **Validator Crash**: Availability loss. **High Severity**.

<br />

## 3. Security Guarantees

Noe explicitly provides the following guarantees when run in **Strict Mode**:

### 3.1. Partiality is Fatal (The "undefined" Trap)
If *any* required information is missing, stale, or malformed, the system **MUST** transition to a `non-execution` state.
*   **Missing Shard**: If `spatial.thresholds` is missing for a spatial operator, result is `undefined` (Block).
*   **Stale Context**: If `now - timestamp > max_skew_ms`, result is `ERR_STALE_CONTEXT` (Block).
*   **Schema Violation**: If context root is not a Map, result is `ERR_BAD_CONTEXT` (Block).

### 3.2. Epistemic Consistency
*   **Claim vs Evidence**: An operator like `shi @p` (I know P) evaluates to True  **IF and ONLY IF** `P` exists in `context.modal.knowledge`.
*   **No Hallucinated Knowledge**: The proposer cannot invent knowledge (e.g. by passing a literal `@p` that isn't in the context). It will trigger `ERR_INVALID_LITERAL` or `ERR_EPISTEMIC_MISMATCH`.

### 3.3. Provenance Binding
*   Every decision produces a SHA-256 `action_hash` covering the canonicalized AST and the `context_hash`.
*   It is computationally infeasible to produce the same `action_hash` with different context data or logic.

<br />

## 4. Out of Scope & Residual Risks

Noe guards the **logic**, not the **physics**.

### 4.1. Sensor Compromise (Spoofing)
*   **Risk**: An attacker compromises the Lidar driver to report `human_dist = 100.0` when it is actually `0.5`.
*   **Noe Behavior**: Noe sees `100.0`, follows the policy, and allows the move.
*   **Mitigation**: Sensor fusion, signed sensor data (upstream of Noe). Use `context.audit` fields to require multi-sensor consensus.

### 4.2. Host OS Compromise
*   **Risk**: Attacker calculates the correct `action_hash` but uses `ptrace` or physical memory access to flip the boolean decision bit in RAM before it reaches the actuators.
*   **Noe Behavior**: Noe cannot defend against kernel-level compromise.
*   **Mitigation**: Secure Boot, TEE (Trusted Execution Environment).

### 4.3. Physical Actuation Bugs
*   **Risk**: Noe returns "BLOCK", but the downstream Python script ignores the return value and calls `motor.move()` anyway.
*   **Noe Behavior**: Noe is a library, not a hypervisor. It returns a verdict; it does not physically disconnect power.
*   **Mitigation**: Integrator discipline; hard-wired E-stops linked to the "Heartbeat" of the Noe Validator.

<br />

## 5. Secure Operations Guide

### 5.1. Secure Defaults
*   Always use `mode="strict"` in production.
*   Set `NOE_DEBUG=0` to prevent log leakage of sensitive context data.
*   Use `ContextManager(transient=True)` for high-frequency loops to minimize GC pressure/attack surface.

### 5.2. Handling Undefined
Integrators **MUST** treat `undefined` or `error` domains as **STOP**.
*   **Correct**: `if decision['domain'] == 'action': execute()`
*   **Incorrect**: `if decision['value'] != 'False': execute()` (This fails open on errors).

### 5.3. Registry Pinning
*   Do not load rules from completely dynamic sources.
*   Pin the Registry Git commit hash in your deploy pipeline.
