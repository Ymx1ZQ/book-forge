#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${BOOK_FORGE_REPO_URL:-https://github.com/Ymx1ZQ/book-forge.git}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_HOME="${BOOK_FORGE_CONFIG_HOME:-$HOME/.config/opencode}"
DEST="$CONFIG_HOME/skills/book-forge"
GLOBAL_AGENT="$CONFIG_HOME/agents/book-forge-orchestrator.md"
GLOBAL_COMMAND="$CONFIG_HOME/commands/book-forge.md"
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

SOURCE_COMMIT="$(git -C "$SRC_ROOT" rev-parse HEAD 2>/dev/null || true)"
if ! [[ "$SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]]; then
    SOURCE_COMMIT="0000000000000000000000000000000000000000"
fi

# Every role runs through OpenCode; installing without it produces a skill that
# fails at the first dispatch with an error about something else.
if command -v opencode >/dev/null 2>&1; then
    OPENCODE_BIN="$(command -v opencode)"
elif [ -x "$HOME/.opencode/bin/opencode" ]; then
    OPENCODE_BIN="$HOME/.opencode/bin/opencode"
else
    echo "book-forge requires OpenCode on PATH; none found" >&2
    exit 1
fi
OPENCODE_VERSION="$("$OPENCODE_BIN" --version 2>/dev/null | head -1)"
# sort -V -C succeeds when its input is already ascending, so the minimum goes first.
if ! printf '1.18.18\n%s\n' "$OPENCODE_VERSION" | sort -V -C; then
    echo "book-forge requires OpenCode 1.18.18 or newer; found ${OPENCODE_VERSION:-unknown}" >&2
    exit 1
fi

for required in SKILL.md agents/openai.yaml assets/opencode/book-forge-orchestrator.md assets/opencode/book-forge-command.md; do
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
        if ! cmp -s "$SRC_ROOT/assets/opencode/book-forge-orchestrator.md" "$GLOBAL_AGENT"; then
            echo "DRIFT: global book-forge orchestrator differs from source"
            status=1
        fi
        if ! cmp -s "$SRC_ROOT/assets/opencode/book-forge-command.md" "$GLOBAL_COMMAND"; then
            echo "DRIFT: global /book-forge command differs from source"
            status=1
        fi
    fi
    if [ "$status" -eq 0 ]; then
        echo "OK: installed book-forge and global OpenCode entrypoints match $SRC_ROOT"
    fi
    return "$status"
}

if [ "$CHECK" = true ]; then
    check_payload
    exit $?
fi

if { [ -d "$DEST" ] || [ -e "$GLOBAL_AGENT" ] || [ -e "$GLOBAL_COMMAND" ]; } && [ "$FORCE" != true ]; then
    printf 'book-forge components already exist under %s. Replace them? [y/N] ' "$CONFIG_HOME"
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
find "$STAGING" -type f -name '*.pyc' -delete
find "$STAGING" -type d -name __pycache__ -prune -exec rm -rf -- {} +

if [ -d "$DEST" ]; then
    rm -rf "$DEST"
fi
mv "$STAGING" "$DEST"
printf '{\n  "schema": 1,\n  "source_commit": "%s"\n}\n' "$SOURCE_COMMIT" >"$DEST/INSTALL-MANIFEST.json"
mkdir -p "$(dirname "$GLOBAL_AGENT")" "$(dirname "$GLOBAL_COMMAND")"
install -m 0644 "$SRC_ROOT/assets/opencode/book-forge-orchestrator.md" "$GLOBAL_AGENT"
install -m 0644 "$SRC_ROOT/assets/opencode/book-forge-command.md" "$GLOBAL_COMMAND"
echo "Installed book-forge -> $DEST"
echo "Installed OpenCode command -> $GLOBAL_COMMAND"
