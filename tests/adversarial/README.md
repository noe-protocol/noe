# Adversarial and Red Team Tests

This directory contains aggressive stress tests and red-team scenarios used to probe the system’s safety and determinism under hostile, malformed, or boundary-case inputs.

## Overview

These tests intentionally try to break core invariants using:

- malformed inputs
- semantically unusual but valid edge cases
- API misuse
- context/state inconsistencies
- known exploit patterns and regression cases

The goal is to verify that the system fails safely and deterministically:
- block execution when conditions are invalid or undefined
- return explicit errors where required
- never fail open
- never silently coerce unsafe input into execution

## Test Files

- **`test_anti_axiom_security.py`**  
  Verifies the system does **not** depend on unsafe assumptions (for example, treating all inputs as valid or well-typed).

- **`test_adversarial_correctness.py`**  
  Probes the boundary between unusual-but-valid inputs and truly invalid inputs, ensuring deterministic classification and behavior.

- **`test_context_misuse.py`**  
  Checks that the Context Manager handles API misuse safely (incorrect types, missing arguments, invalid shapes, stale/malformed context updates).

- **`red_team_audit.py`**  
  Catch-all suite for known exploit attempts, regression tests for previously fixed vulnerabilities, and release-blocking safety checks.

## Note to Reviewers

Failures in this directory may occur during active development and are useful signals.

Before release, this suite must be green.

A passing suite here indicates the system is rejecting unsafe inputs predictably and preserving core invariants, rather than failing silently, failing open, or crashing unpredictably.

## Scope

These tests are focused on adversarial correctness and fail-safe behavior. They are not a substitute for:
- performance benchmarking
- broad fuzzing coverage
- formal verification
- end-to-end integration tests
