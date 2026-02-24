#!/usr/bin/env bash
# Noe Release Gate Verification Script
# This is the release gate - all tests here must pass for any release
# Current: v1.0
set -euo pipefail

echo "🔍 Noe Release Gate Verification"
echo "================================"
echo ""

# Run core v1.0 verification tests
echo "Running core verification tests..."
python3 -m pytest -q \
  tests/test_v1_0_verification.py \
  tests/adversarial/test_anti_axiom_security.py \
  tests/test_safety_kernel_invariants.py \
  tests/test_spatial_operators.py \
  tests/test_strict_actions.py \
  tests/test_runtime_blockers.py

echo ""
echo "Running NIP-011 conformance..."
cd tests/nip011 && python3 run_conformance.py | tail -5
cd ../..

echo ""
echo "✅ Release Gate Verification Complete"
