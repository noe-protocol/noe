#!/bin/bash
# Quick determinism demo runner
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$DIR")"

cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT"
export NOE_DEBUG=0

echo "======================================================================="
echo "  NOE v1.0 DETERMINISM PROOF"
echo "======================================================================="
echo

python3 examples/determinism_proof.py

exit $?
