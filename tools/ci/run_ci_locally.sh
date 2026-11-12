#!/bin/bash
# Run the GitHub Actions workflow (.github/workflows/build.yaml) locally, in a
# throwaway clean checkout of a commit, before pushing it.
#
# A clean checkout is the point: CI clones only tracked files, so a file the
# main checkout happens to have (a generated sheet, an untracked helper) is
# exactly what breaks CI and never breaks here.
#
# usage: tools/ci/run_ci_locally.sh [REV]
#   REV   commit to test (default HEAD; uncommitted edits are NOT tested)
#   env KEEP=1 leaves the checkout in place (path printed) for debugging
#
# toki1-decomp comes from tools/repo_paths.py (the sibling checkout or
# TOKI_DECOMP_DIR), as in CI; the host's own Python is used (CI: 3.11):
# $PYTHON, ./.venv, or python3 (it needs requirements.txt: Pillow, numpy).
set -u
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
REV=${1:-HEAD}
SHA=$(git -C "$ROOT" rev-parse --verify "$REV^{commit}") || exit 2
# the Python: $PYTHON (make ci passes its PYTHON), else ./.venv, else python3
PY=${PYTHON:-python3}
[ -z "${PYTHON:-}" ] && [ -x "$ROOT/.venv/bin/python" ] && PY="$ROOT/.venv/bin/python"
DECOMP=$("$PY" "$ROOT/tools/repo_paths.py" | sed -n 's/^DECOMP=//p')
[ -n "$DECOMP" ] || { echo "toki1-decomp not found (sibling checkout or TOKI_DECOMP_DIR)"; exit 2; }
export TOKI_DECOMP_DIR="$DECOMP"
DIR=$(mktemp -d "${TMPDIR:-/tmp}/toki1-english-ci.XXXXXX")
cleanup() { [ "${KEEP:-0}" = 1 ] && { echo "kept: $DIR"; return; }
            git -C "$ROOT" worktree remove --force "$DIR" 2>/dev/null; rm -rf "$DIR"; }
trap cleanup EXIT
git -C "$ROOT" worktree add -q --detach "$DIR" "$SHA" || exit 2
cd "$DIR" || exit 2
echo "== CI on $(git log -1 --oneline) in $DIR (toki1-decomp: $DECOMP)"
FAIL=""
step() { local name=$1; shift; echo "-- $name"; if ! bash -c "$*"; then echo "FAIL: $name"; FAIL="$FAIL $name"; fi; }

step "byte-compile Python" "$PY -m compileall -q -x '/(\\.venv|build|__pycache__|\\.git)/' tools"
step "shell syntax" "find tools -name '*.sh' -print0 | xargs -0 -r -n1 bash -n"
step "tracked JSON parses" "$PY tools/ci/check_json.py"
step "sheet lint (no disc)" "make lint PYTHON=$PY"
step "disc-free unit tests and the symbol sync check" "make test-disc-free PYTHON=$PY"

if [ -n "$FAIL" ]; then echo "== CI would FAIL:$FAIL"; exit 1; fi
echo "== CI would pass"
