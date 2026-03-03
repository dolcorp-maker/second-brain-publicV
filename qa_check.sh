#!/usr/bin/env bash
# qa_check.sh — Syntax-check all project Python files before deploying
# Usage:  ./qa_check.sh
# Returns 0 if all pass, 1 if any fail.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="${PROJECT_DIR}/venv/bin/python3"

# Fall back to system python3 if venv not present
if [ ! -x "$PYTHON" ]; then
    PYTHON="$(command -v python3)"
fi

echo "=== QA Syntax Check ==="
echo "    Python : $PYTHON"
echo "    Project: $PROJECT_DIR"
echo ""

FAIL=0
PASS=0

while IFS= read -r -d '' f; do
    rel="${f#${PROJECT_DIR}/}"
    if "$PYTHON" -m py_compile "$f" 2>&1; then
        echo "  OK   $rel"
        PASS=$((PASS + 1))
    else
        echo "  FAIL $rel"
        FAIL=$((FAIL + 1))
    fi
done < <(find "$PROJECT_DIR" -name "*.py" \
    -not -path "*/venv/*" \
    -not -path "*/__pycache__/*" \
    -not -path "*/.git/*" \
    -print0)

echo ""
echo "Results: ${PASS} passed, ${FAIL} failed"

if [ $FAIL -eq 0 ]; then
    echo "All files OK — safe to restart services."
else
    echo "Syntax errors found — DO NOT restart until fixed."
fi

exit $FAIL
