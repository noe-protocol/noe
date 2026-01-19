# Adversarial & Red Team Tests

This directory contains aggressive stress tests and "red team" scenarios designed to probe the system's resilience.

## Overview
These tests intentionally attempt to break system invariants using malformed inputs, edge cases, and security exploits.

- **`test_anti_axiom_security.py`**: Verifies that the system does NOT rely on unsafe axioms (e.g., assuming "all inputs are valid").
- **`test_adversarial_correctness.py`**: Probes the boundary between "valid but weird" and "invalid" inputs.
- **`test_context_misuse.py`**: Checks that the Context Manager correctly handles API misuse (e.g., incorrect types, missing args).
- **`red_team_audit.py`**: A catch-all suite for known exploits and regression tests for fixed vulnerabilities.

## Note to Reviewers
Failures here are expected during development but must be green for release. These tests ensure the system fails *safely* (by blocking execution) rather than failing *silently* or crashing unpredictably.
