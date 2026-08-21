#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${BOOK_FORGE_REPO_URL:-https://github.com/Ymx1ZQ/book-forge.git}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_HOME="${BOOK_FORGE_CONFIG_HOME:-$HOME/.config/opencode}"
DEST="$CONFIG_HOME/skills/book-forge"
FORCE=false
CHECK=false
CLEANUP_DIR=""

cleanup() {
    if [ -n "$CLEANUP_DIR" ] && [ -d "$CLEANUP_DIR" ]; then
        rm -rf "$CLEANUP_DIR"
    fi
}
trap cleanup EXIT

usage() {
    cat <<'EOF'
Usage: ./install.sh [--force] [--check]

Install book-forge into the OpenCode skills directory.

Options:
  --force  Replace an existing installation without prompting.
  --check  Compare the installed payload with this source checkout.
  --help   Show this message.

Environment:
  BOOK_FORGE_CONFIG_HOME  Override the OpenCode config root.
  BOOK_FORGE_REPO_URL     Override the repository used by remote installs.
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --force) FORCE=true ;;
        --check) CHECK=true ;;
        --help|-h) usage; exit 0 ;;
        *) echo "Error: unknown option '$1'" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

if [ -f "$SCRIPT_DIR/SKILL.md" ]; then
    SRC_ROOT="$SCRIPT_DIR"
else
    command -v git >/dev/null 2>&1 || {
        echo "Error: git is required for a remote installation." >&2
        exit 1
    }
    CLEANUP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/book-forge-install-XXXXXX")"
    git clone --depth 1 --quiet "$REPO_URL" "$CLEANUP_DIR/book-forge"
    SRC_ROOT="$CLEANUP_DIR/book-forge"
fi

for required in SKILL.md agents/openai.yaml; do
    if [ ! -f "$SRC_ROOT/$required" ]; then
        echo "Error: runtime payload is missing $required." >&2
        exit 1
    fi
done

PAYLOAD=(SKILL.md agents references scripts assets)

check_payload() {
    if [ ! -d "$DEST" ]; then
        echo "DRIFT: book-forge is not installed at $DEST"
        return 1
    fi
    local entry output status=0
    for entry in "${PAYLOAD[@]}"; do
        if [ ! -e "$SRC_ROOT/$entry" ]; then
            continue
        fi
        if [ ! -e "$DEST/$entry" ]; then
            echo "DRIFT: installed payload is missing $entry"
            status=1
            continue
        fi
        output="$(diff -r --exclude=__pycache__ --exclude='*.pyc' "$SRC_ROOT/$entry" "$DEST/$entry" 2>&1)" || true
        if [ -n "$output" ]; then
            echo "DRIFT: installed $entry differs from source"
            echo "$output" | head -10
            status=1
        fi
    done
    if [ "$status" -eq 0 ]; then
        echo "OK: installed book-forge matches $SRC_ROOT"
    fi
    return "$status"
}

if [ "$CHECK" = true ]; then
    check_payload
    exit $?
fi

if [ -d "$DEST" ] && [ "$FORCE" != true ]; then
    printf 'book-forge already exists at %s. Replace it? [y/N] ' "$DEST"
    read -r reply
    case "$reply" in y|Y|yes|YES) ;; *) echo "Installation cancelled."; exit 0 ;; esac
fi

mkdir -p "$(dirname "$DEST")"
STAGING="$(mktemp -d "$(dirname "$DEST")/.book-forge-install-XXXXXX")"
for entry in "${PAYLOAD[@]}"; do
    if [ -e "$SRC_ROOT/$entry" ]; then
        cp -R "$SRC_ROOT/$entry" "$STAGING/$entry"
    fi
done

if [ -d "$DEST" ]; then
    rm -rf "$DEST"
fi
mv "$STAGING" "$DEST"
echo "Installed book-forge -> $DEST"
