#!/bin/bash
set -e

echo "========================================================"
echo "   NOE v1.0-rc1: CORE VERIFICATION & DEMO SUITE       "
echo "========================================================"
echo ""

# 0. Check Env
echo "[0] Checking Environment..."
python3 -m pip install -r requirements.txt -q
echo "    Dependencies: OK"
echo ""

# 1. Robot Guard (The "Physics" Proof)
echo "[1] Running Robot Guard (Logic + Hysteresis Verification)..."
export PYTHONPATH=$PYTHONPATH:.

# TRY BOTH LOCATIONS: Root or examples/ folder
if [ -f "examples/robot_guard_demo.py" ]; then
    python3 examples/robot_guard_demo.py
elif [ -f "robot_guard_demo.py" ]; then
    python3 robot_guard_demo.py
else
    echo "❌ ERROR: Could not find robot_guard_demo.py in current dir or examples/"
    exit 1
fi
echo ""

# 2. Benchmarks (The "Speed" Proof)
echo "[2] Running Performance Benchmarks (P99 Latency)..."

if [ -f "benchmarks/noe_benchmark_testing.py" ]; then
    python3 benchmarks/noe_benchmark_testing.py
elif [ -f "noe_benchmark_testing.py" ]; then
    python3 noe_benchmark_testing.py
else
    echo "❌ ERROR: Could not find noe_benchmark_testing.py"
    exit 1
fi
echo ""

# 3. Release Gate Verification (The "Correctness" Proof)
echo "[3] Running Release Gate Verification..."
./scripts/verify_release_gate.sh
echo ""

# 4. Generate Canonical Artifact (For Gianluca)
echo "[4] Generating v1.0 Canonical Artifact..."
python3 generate_demo_artifact.py
echo ""

# Optional: Extended test suite (experimental/legacy features)
if [ "${NOE_RUN_EXTENDED:-0}" = "1" ]; then
    echo "[5] Running Extended Test Suite (experimental features)..."
    python3 -m pytest -q -m "experimental or legacy" tests/ || echo "⚠️  Some extended tests failed (non-blocking for v1.0)"
    echo ""
fi

echo "========================================================"
echo "   ✅ DEMO COMPLETE. v1.0 VERIFICATION PASSED."
echo "   See 'demo_artifact.json' for canonical provenance."
echo "========================================================"
echo ""
echo "💡 Tip: Run 'NOE_RUN_EXTENDED=1 ./run_demo.sh' to include experimental tests"
