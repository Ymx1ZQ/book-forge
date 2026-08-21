#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/book-forge-install-test-XXXXXX")"
trap 'rm -rf "$TMP_ROOT"' EXIT

export BOOK_FORGE_CONFIG_HOME="$TMP_ROOT/opencode"
DEST="$BOOK_FORGE_CONFIG_HOME/skills/book-forge"

"$ROOT/install.sh" --force

test -f "$DEST/SKILL.md"
test -f "$DEST/agents/openai.yaml"
test ! -e "$DEST/DEVPLAN.md"
test ! -e "$DEST/tests"
test ! -e "$DEST/install.sh"

"$ROOT/install.sh" --check
printf '\n# drift\n' >> "$DEST/SKILL.md"

if "$ROOT/install.sh" --check >"$TMP_ROOT/check.out" 2>&1; then
    echo "expected --check to fail after installed payload drift" >&2
    exit 1
fi
grep -q "DRIFT" "$TMP_ROOT/check.out"

"$ROOT/install.sh" --force
"$ROOT/install.sh" --check

echo "install tests passed"
