#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


MODEL = "openrouter/deepseek/deepseek-v4-flash-0731"
SCHEMA_VERSION = 1
ROLE_SPECS = {
    "book-forge-orchestrator": ("primary", "high", 30),
    "designer": ("subagent", "high", 10),
    "writer": ("subagent", "low", 8),
    "cold-reader": ("subagent", "low", 5),
    "technical-editor": ("subagent", "mid", 7),
    "reviser": ("subagent", "mid", 8),
    "canon-auditor": ("subagent", "high", 8),
    "translator": ("subagent", "low", 7),
    "judge": ("subagent", "high", 6),
    "book-forge-smoke": ("primary", "low", 3),
}


class BookForgeError(RuntimeError):
    pass


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_bytes_atomic(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BookForgeError(f"Invalid project file {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BookForgeError(f"Expected an object in {path}")
    return value


def _project_root(project: Path | str) -> Path:
    root = Path(project).expanduser().resolve()
    if not (root / "book-forge.yaml").is_file():
        raise BookForgeError(f"Not a Book Forge universe: {root}")
    return root


def _next_id(existing: list[str], prefix: str) -> str:
    used = {int(value.removeprefix(prefix)) for value in existing if value.startswith(prefix) and value.removeprefix(prefix).isdigit()}
    number = 1
    while number in used:
        number += 1
    return f"{prefix}{number:04d}"


def _block_record(block: str) -> dict[str, str]:
    if not re.fullmatch(r"[A-Z][A-Z0-9-]*#[a-z0-9][a-z0-9-]*", block):
        raise BookForgeError(f"Invalid addressable block: {block}")
    return {"block": block, "hash": hashlib.sha256(block.encode()).hexdigest()}


def _opencode_config() -> dict[str, object]:
    return {
        "$schema": "https://opencode.ai/config.json",
        "model": MODEL,
        "small_model": MODEL,
        "default_agent": "book-forge-orchestrator",
        "provider": {
            "openrouter": {
                "whitelist": ["deepseek/deepseek-v4-flash-0731"],
                "models": {
                    "deepseek/deepseek-v4-flash-0731": {
                        "options": {
                            "reasoningEffort": "medium",
                            "provider": {
                                "order": ["deepseek", "baidu"],
                                "only": ["deepseek", "baidu"],
                                "allow_fallbacks": False,
                            },
                        },
                        "variants": {
                            "low": {"reasoningEffort": "low"},
                            "mid": {"reasoningEffort": "medium"},
                            "high": {"reasoningEffort": "high"},
                            "xhigh": {"reasoningEffort": "xhigh"},
                        },
                    }
                },
            }
        },
    }


def _write_agents(stage: Path) -> None:
    agents = stage / ".opencode" / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    for name, (mode, variant, steps) in ROLE_SPECS.items():
        if name == "book-forge-orchestrator":
            permissions = (
                'permission:\n  "*": deny\n  skill:\n    "*": deny\n    book-forge: allow\n'
                '  read:\n    "*": allow\n  bash:\n    "python3 *book_forge.py*": allow\n'
            )
            instruction = (
                "Load the book-forge skill before acting. Route the request through its deterministic "
                "control plane. Never edit canonical universe files directly."
            )
        elif name == "book-forge-smoke":
            permissions = 'permission:\n  "*": deny\n  skill:\n    "*": deny\n    book-forge: allow\n'
            instruction = "Load the book-forge skill when requested, then return exactly the requested readiness token."
        else:
            permissions = 'permission:\n  "*": deny\n'
            instruction = (
                f"You are the Book Forge {name} role. Return only the task's requested output contract. "
                "You have no tools and must not assume context outside the supplied envelope."
            )
        body = (
            "---\n"
            f"description: Book Forge {name} role.\n"
            f"mode: {mode}\nmodel: {MODEL}\nvariant: {variant}\nsteps: {steps}\n"
            f"{permissions}---\n\n{instruction}\n"
        )
        (agents / f"{name}.md").write_text(body, encoding="utf-8")
    commands = stage / ".opencode" / "commands"
    commands.mkdir(parents=True, exist_ok=True)
    (commands / "book-forge.md").write_text(
        "---\ndescription: Run a Book Forge universe workflow.\nagent: book-forge-orchestrator\n---\n\n"
        "Load the `book-forge` skill, then execute this request exactly: $ARGUMENTS\n",
        encoding="utf-8",
    )


def _canonical_language(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", value):
        raise BookForgeError(f"Invalid source language tag: {value}")
    parts = value.split("-")
    return "-".join([parts[0].lower(), *parts[1:]])


def _inside_git_repo(parent: Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(parent), "rev-parse", "--show-toplevel"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def _validate_existing(project: Path, title: str, source_language: str) -> dict[str, object]:
    config_path = project / "book-forge.yaml"
    if not config_path.is_file():
        raise BookForgeError(f"Refusing to initialize non-empty directory: {project}")
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BookForgeError(f"Existing project configuration is invalid: {exc}") from exc
    expected = {
        "schema": SCHEMA_VERSION,
        "title": title,
        "source_language": source_language,
        "universe": "UNI-0001",
        "model": MODEL,
    }
    for key, value in expected.items():
        if config.get(key) != value:
            raise BookForgeError(f"Existing project differs at {key}")
    return {"created": False, "project": str(project)}


def _build_project(stage: Path, title: str, source_language: str, initialize_git: bool) -> None:
    config = {
        "schema": SCHEMA_VERSION,
        "title": title,
        "universe": "UNI-0001",
        "default_continuity": "CNT-0001",
        "source_language": source_language,
        "model": MODEL,
        "context": {"writer_max_input_tokens": 12000, "hard_fail_on_overflow": True},
    }
    _write_json(stage / "book-forge.yaml", config)
    _write_json(stage / "opencode.json", _opencode_config())
    _write_agents(stage)
    _write_json(
        stage / "universe" / "universe.yaml",
        {
            "schema": SCHEMA_VERSION,
            "id": "UNI-0001",
            "title": title,
            "kernel": "UNI-0001#kernel",
            "default_continuity": "CNT-0001",
        },
    )
    _write_json(
        stage / "universe" / "continuities.yaml",
        {"schema": SCHEMA_VERSION, "continuities": [{"id": "CNT-0001", "kind": "primary", "name": "Prime"}]},
    )
    _write_json(stage / "universe" / "collections.yaml", {"schema": SCHEMA_VERSION, "collections": []})
    _write_json(stage / "universe" / "relations.yaml", {"schema": SCHEMA_VERSION, "relations": []})
    _write_json(stage / "universe" / "timeline" / "eras.yaml", {"schema": SCHEMA_VERSION, "eras": []})
    _write_json(stage / "universe" / "timeline" / "events.yaml", {"schema": SCHEMA_VERSION, "events": []})
    (stage / "universe" / "kernel.md").write_text(
        "---\nid: UNI-0001\nkind: universe-kernel\n---\n\n"
        "## Kernel\n<!-- bf:block kernel -->\n\nDefine only invariants inherited by every continuity.\n",
        encoding="utf-8",
    )
    for directory in (
        stage / "universe" / "canon" / "topics",
        stage / "universe" / "canon" / "characters",
        stage / "universe" / "canon" / "places",
        stage / "universe" / "canon" / "factions",
        stage / "books",
        stage / "dist",
        stage / ".book-forge" / "runs",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    _write_json(
        stage / ".book-forge" / "project.json",
        {"schema": SCHEMA_VERSION, "universe": "UNI-0001", "source_language": source_language},
    )
    (stage / "DEVPLAN.md").write_text(
        "# Universe Work Plan\n\nGenerated by book-forge. No tasks are scheduled yet.\n",
        encoding="utf-8",
    )
    (stage / "DEVPLAN-COMPLETED.md").write_text("# Completed Universe Tasks\n", encoding="utf-8")
    if initialize_git:
        subprocess.run(
            ["git", "init", "-b", "main", str(stage)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )


def init_project(
    project: Path | str,
    title: str,
    source_language: str = "en",
    *,
    fault_hook=None,
) -> dict[str, object]:
    target = Path(project).expanduser().resolve()
    language = _canonical_language(source_language)
    if target.exists() and any(target.iterdir()):
        return _validate_existing(target, title, language)

    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{target.name}-book-forge-", dir=target.parent))
    target_was_empty = target.exists()
    try:
        _build_project(stage, title, language, initialize_git=not _inside_git_repo(target.parent))
        if fault_hook is not None:
            fault_hook("before_promote")
        if target_was_empty:
            target.rmdir()
        os.replace(stage, target)
        return {"created": True, "project": str(target)}
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def list_books(project: Path | str) -> list[dict[str, object]]:
    root = _project_root(project)
    books: list[dict[str, object]] = []
    for path in sorted((root / "books").glob("*/book.yaml")):
        book = _read_json(path)
        if path.parent.name != book.get("id"):
            raise BookForgeError(f"Book path and stable ID differ: {path}")
        books.append(book)
    return sorted(books, key=lambda item: str(item["id"]))


def _continuities(root: Path) -> dict[str, object]:
    return _read_json(root / "universe" / "continuities.yaml")


def add_continuity(
    project: Path | str,
    name: str,
    *,
    kind: str = "alternate",
    fork_from: str | None = None,
    imports: list[str] | None = None,
) -> dict[str, object]:
    root = _project_root(project)
    data = _continuities(root)
    rows = data.setdefault("continuities", [])
    if not isinstance(rows, list):
        raise BookForgeError("Invalid continuities registry")
    if kind not in {"primary", "alternate"}:
        raise BookForgeError(f"Invalid continuity kind: {kind}")
    if kind == "alternate" and not fork_from:
        raise BookForgeError("Alternate continuity requires fork_from")
    ids = [str(row["id"]) for row in rows if isinstance(row, dict)]
    if fork_from and fork_from not in ids:
        raise BookForgeError(f"Unknown fork continuity: {fork_from}")
    row: dict[str, object] = {
        "id": _next_id(ids, "CNT-"),
        "kind": kind,
        "name": name,
        "imports": [_block_record(value) for value in (imports or [])],
    }
    if fork_from:
        row["fork_from"] = fork_from
    rows.append(row)
    _write_json(root / "universe" / "continuities.yaml", data)
    return row


def add_book(project: Path | str, title: str, *, continuity: str = "CNT-0001") -> dict[str, object]:
    root = _project_root(project)
    continuity_ids = {str(row["id"]) for row in _continuities(root)["continuities"]}
    if continuity not in continuity_ids:
        raise BookForgeError(f"Unknown continuity: {continuity}")
    books = list_books(root)
    book_id = _next_id([str(book["id"]) for book in books], "BOOK-")
    book = {"schema": SCHEMA_VERSION, "id": book_id, "title": title, "continuity": continuity, "order": len(books) + 1}
    directory = root / "books" / book_id
    if directory.exists():
        raise BookForgeError(f"Book path collision: {directory}")
    directory.mkdir(parents=True)
    _write_json(directory / "book.yaml", book)
    _write_json(directory / "outline.yaml", {"schema": SCHEMA_VERSION, "chapters": []})
    _write_json(directory / "state.yaml", {"schema": SCHEMA_VERSION, "closed_chapters": []})
    _write_json(directory / "continuity.yaml", {"schema": SCHEMA_VERSION, "imports": [], "obligations": []})
    (directory / "design.md").write_text(f"# {title}\n\n<!-- bf:block premise -->\n", encoding="utf-8")
    (directory / "reader-state.md").write_text("# Reader State\n", encoding="utf-8")
    (directory / "manuscript" / "chapters").mkdir(parents=True)
    return book


def collection_add(project: Path | str, name: str, books: list[str]) -> dict[str, object]:
    root = _project_root(project)
    known = {str(book["id"]) for book in list_books(root)}
    if len(set(books)) != len(books) or not set(books) <= known:
        raise BookForgeError("Collection contains duplicate or unknown books")
    data = _read_json(root / "universe" / "collections.yaml")
    rows = data.setdefault("collections", [])
    ids = [str(row["id"]) for row in rows]
    row = {"id": _next_id(ids, "COL-"), "name": name, "books": list(books)}
    rows.append(row)
    _write_json(root / "universe" / "collections.yaml", data)
    return row


def collection_order(project: Path | str, collection_id: str, books: list[str]) -> dict[str, object]:
    root = _project_root(project)
    data = _read_json(root / "universe" / "collections.yaml")
    for row in data["collections"]:
        if row["id"] == collection_id:
            if set(row["books"]) != set(books) or len(books) != len(set(books)):
                raise BookForgeError("Order must contain every collection book exactly once")
            row["books"] = list(books)
            _write_json(root / "universe" / "collections.yaml", data)
            return row
    raise BookForgeError(f"Unknown collection: {collection_id}")


def collection_remove(project: Path | str, collection_id: str) -> None:
    root = _project_root(project)
    data = _read_json(root / "universe" / "collections.yaml")
    before = len(data["collections"])
    data["collections"] = [row for row in data["collections"] if row["id"] != collection_id]
    if len(data["collections"]) == before:
        raise BookForgeError(f"Unknown collection: {collection_id}")
    _write_json(root / "universe" / "collections.yaml", data)


def _ancestry_edges(relations: list[dict[str, object]]) -> dict[str, set[str]]:
    edges: dict[str, set[str]] = {}
    for row in relations:
        endpoints = row.get("endpoints", [])
        if row.get("type") == "sequel_of":
            edges.setdefault(str(endpoints[0]), set()).add(str(endpoints[1]))
        elif row.get("type") == "prequel_of":
            edges.setdefault(str(endpoints[1]), set()).add(str(endpoints[0]))
    return edges


def _reachable(edges: dict[str, set[str]], start: str, target: str) -> bool:
    frontier = [start]
    seen: set[str] = set()
    while frontier:
        node = frontier.pop()
        if node == target:
            return True
        if node not in seen:
            seen.add(node)
            frontier.extend(edges.get(node, set()))
    return False


def add_relation(
    project: Path | str,
    relation_type: str,
    endpoints: list[str],
    *,
    imports: list[str] | None = None,
    obligations: list[str] | None = None,
) -> dict[str, object]:
    root = _project_root(project)
    allowed = {"sequel_of", "prequel_of", "adaptation_of", "alternate_of", "parallel_to", "crossover"}
    if relation_type not in allowed:
        raise BookForgeError(f"Unknown relation type: {relation_type}")
    expected_arity = 2 if relation_type != "crossover" else None
    if (expected_arity and len(endpoints) != expected_arity) or (relation_type == "crossover" and len(endpoints) < 2):
        raise BookForgeError(f"Invalid arity for {relation_type}")
    if len(set(endpoints)) != len(endpoints):
        raise BookForgeError("Relation endpoints must be distinct")
    books = {str(book["id"]): book for book in list_books(root)}
    if not set(endpoints) <= books.keys():
        raise BookForgeError("Unknown relation endpoint")
    continuities = {str(books[value]["continuity"]) for value in endpoints}
    local_types = {"sequel_of", "prequel_of", "parallel_to", "crossover"}
    if relation_type in local_types and len(continuities) != 1:
        raise BookForgeError(f"{relation_type} must remain inside one continuity")
    if relation_type in {"adaptation_of", "alternate_of"} and len(continuities) > 1 and not imports:
        raise BookForgeError("Cross-continuity relations require explicit block imports")
    normalized = sorted(endpoints) if relation_type in {"parallel_to", "crossover"} else list(endpoints)
    data = _read_json(root / "universe" / "relations.yaml")
    rows = data.setdefault("relations", [])
    if any(row["type"] == relation_type and row["endpoints"] == normalized for row in rows):
        raise BookForgeError("Duplicate relation")
    if relation_type in {"sequel_of", "prequel_of"}:
        child, parent = normalized if relation_type == "sequel_of" else [normalized[1], normalized[0]]
        edges = _ancestry_edges(rows)
        if _reachable(edges, parent, child):
            raise BookForgeError("Ancestry relation would create a cycle")
    relation_ids = [str(row["id"]) for row in rows]
    obligation_ids = [str(item["id"]) for row in rows for item in row.get("obligations", [])]
    obligation_rows = []
    for text_value in obligations or []:
        obligation_id = _next_id(obligation_ids, "OBL-")
        obligation_ids.append(obligation_id)
        obligation_rows.append({"id": obligation_id, "text": text_value, "hash": hashlib.sha256(text_value.encode()).hexdigest()})
    row = {
        "id": _next_id(relation_ids, "REL-"),
        "type": relation_type,
        "endpoints": normalized,
        "imports": [_block_record(value) for value in (imports or [])],
        "obligations": obligation_rows,
    }
    rows.append(row)
    _write_json(root / "universe" / "relations.yaml", data)
    return row


MIGRATABLE_FILES = (
    "book-forge.yaml",
    "universe/universe.yaml",
    "universe/continuities.yaml",
    "universe/collections.yaml",
    "universe/relations.yaml",
)


def _validate_machine_state(root: Path, config: dict[str, object]) -> None:
    state = _read_json(root / ".book-forge" / "project.json")
    for key in ("universe", "source_language"):
        if state.get(key) != config.get(key):
            raise BookForgeError(f"Machine state differs from authored configuration at {key}; restore it or use status --repair-view")


def migrate_project(project: Path | str, mode: str, *, fault_hook=None) -> dict[str, object]:
    root = _project_root(project)
    if mode not in {"check", "dry-run", "apply", "rollback"}:
        raise BookForgeError(f"Unknown migration mode: {mode}")
    migrations_root = root / ".book-forge" / "migrations"
    if mode == "rollback":
        candidates = []
        if migrations_root.exists():
            for path in sorted(migrations_root.glob("MIG-*"), reverse=True):
                journal = _read_json(path / "journal.json")
                if journal.get("status") == "completed":
                    candidates.append((path, journal))
        if not candidates:
            raise BookForgeError("No completed migration is available to roll back")
        migration, journal = candidates[0]
        for relative in journal["files"]:
            backup = migration / "backup" / relative
            _write_bytes_atomic(root / relative, backup.read_bytes())
        journal["status"] = "rolled_back"
        _write_json(migration / "journal.json", journal)
        return {"rolled_back": True, "migration": migration.name, "to": journal["from"]}

    config = _read_json(root / "book-forge.yaml")
    schema = config.get("schema")
    if not isinstance(schema, int) or schema < 0 or schema > SCHEMA_VERSION:
        raise BookForgeError(f"Unsupported schema version: {schema}")
    _validate_machine_state(root, config)
    if schema == SCHEMA_VERSION:
        return {"compatible": True, "from": schema, "to": schema, "changes": []}
    if schema != 0:
        raise BookForgeError(f"No ordered migration from schema {schema}")
    changes: dict[str, bytes] = {}
    for relative in MIGRATABLE_FILES:
        path = root / relative
        data = _read_json(path)
        if data.get("schema") != 0:
            raise BookForgeError(f"Mixed schema versions at {relative}")
        data["schema"] = 1
        changes[relative] = (json.dumps(data, indent=2, sort_keys=True) + "\n").encode()
    report = {"compatible": True, "from": 0, "to": 1, "changes": list(changes)}
    if mode in {"check", "dry-run"}:
        return report

    migrations_root.mkdir(parents=True, exist_ok=True)
    migration_id = _next_id([path.name for path in migrations_root.glob("MIG-*")], "MIG-")
    migration = migrations_root / migration_id
    migration.mkdir()
    journal: dict[str, object] = {"schema": 1, "from": 0, "to": 1, "files": list(changes), "status": "preparing"}
    _write_json(migration / "journal.json", journal)
    for relative in changes:
        backup = migration / "backup" / relative
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes((root / relative).read_bytes())
    installed: list[str] = []
    try:
        for relative, value in changes.items():
            _write_bytes_atomic(root / relative, value)
            installed.append(relative)
            if len(installed) == 1 and fault_hook:
                fault_hook("after_first_install")
        journal["status"] = "completed"
        journal["installed"] = installed
        _write_json(migration / "journal.json", journal)
    except BaseException:
        for relative in changes:
            _write_bytes_atomic(root / relative, (migration / "backup" / relative).read_bytes())
        journal["status"] = "restored_after_failure"
        _write_json(migration / "journal.json", journal)
        raise
    return {**report, "migration": migration_id}


def _opencode_binary() -> str:
    binary = shutil.which("opencode")
    if binary:
        return binary
    fallback = Path.home() / ".opencode" / "bin" / "opencode"
    if fallback.is_file():
        return str(fallback)
    raise BookForgeError("OpenCode is not installed")


def verify_runtime(project: Path | str) -> dict[str, object]:
    root = _project_root(project)
    binary = _opencode_binary()
    version = subprocess.run([binary, "--version"], capture_output=True, text=True, check=True).stdout.strip()
    numbers = re.findall(r"\d+", version)
    if tuple(map(int, numbers[:3])) < (1, 18, 18):
        raise BookForgeError(f"OpenCode 1.18.18 or newer is required; found {version}")
    models = subprocess.run([binary, "models", "openrouter"], capture_output=True, text=True, check=True).stdout
    if MODEL not in models:
        raise BookForgeError(f"Pinned model is unavailable: {MODEL}")
    help_result = subprocess.run([binary, "run", "--help"], capture_output=True, text=True, check=True)
    help_text = help_result.stdout + help_result.stderr
    for required in ("--format", "--session", "--variant"):
        if required not in help_text:
            raise BookForgeError(f"OpenCode lacks required run capability: {required}")
    debug = subprocess.run(
        [binary, "--pure", "debug", "config"], cwd=root, capture_output=True, text=True, check=True
    ).stdout
    resolved = json.loads(debug)
    if resolved.get("model") != MODEL:
        raise BookForgeError("Resolved OpenCode model differs from the project pin")
    return {
        "version": version,
        "model": MODEL,
        "variants": ["low", "mid", "high", "xhigh"],
        "json_events": "--format" in help_text,
        "session_resume": "--session" in help_text,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="book-forge")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--title")
    init.add_argument("--source-language", default="en")
    continuity = commands.add_parser("continuity")
    continuity_commands = continuity.add_subparsers(dest="continuity_command", required=True)
    continuity_add = continuity_commands.add_parser("add")
    continuity_add.add_argument("name")
    continuity_add.add_argument("--kind", choices=("primary", "alternate"), default="alternate")
    continuity_add.add_argument("--fork-from")
    continuity_add.add_argument("--import", dest="imports", action="append", default=[])
    add_book_command = commands.add_parser("add-book")
    add_book_command.add_argument("title")
    add_book_command.add_argument("--continuity", default="CNT-0001")
    relate = commands.add_parser("relate")
    relate.add_argument("books", nargs="+")
    relate.add_argument("--type", required=True)
    relate.add_argument("--import", dest="imports", action="append", default=[])
    relate.add_argument("--obligation", action="append", default=[])
    collection = commands.add_parser("collection")
    collection_commands = collection.add_subparsers(dest="collection_command", required=True)
    collection_add_command = collection_commands.add_parser("add")
    collection_add_command.add_argument("name")
    collection_add_command.add_argument("books", nargs="+")
    collection_order_command = collection_commands.add_parser("order")
    collection_order_command.add_argument("collection")
    collection_order_command.add_argument("books", nargs="+")
    collection_remove_command = collection_commands.add_parser("remove")
    collection_remove_command.add_argument("collection")
    migrate = commands.add_parser("migrate")
    migrate.add_argument("mode", choices=("check", "dry-run", "apply", "rollback"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init":
            title = args.title or args.project.name.replace("-", " ").title()
            print(json.dumps(init_project(args.project, title, args.source_language), sort_keys=True))
        elif args.command == "continuity" and args.continuity_command == "add":
            print(json.dumps(add_continuity(args.project, args.name, kind=args.kind, fork_from=args.fork_from, imports=args.imports), sort_keys=True))
        elif args.command == "add-book":
            print(json.dumps(add_book(args.project, args.title, continuity=args.continuity), sort_keys=True))
        elif args.command == "relate":
            print(json.dumps(add_relation(args.project, args.type, args.books, imports=args.imports, obligations=args.obligation), sort_keys=True))
        elif args.command == "collection" and args.collection_command == "add":
            print(json.dumps(collection_add(args.project, args.name, args.books), sort_keys=True))
        elif args.command == "collection" and args.collection_command == "order":
            print(json.dumps(collection_order(args.project, args.collection, args.books), sort_keys=True))
        elif args.command == "collection" and args.collection_command == "remove":
            collection_remove(args.project, args.collection)
            print(json.dumps({"removed": args.collection}, sort_keys=True))
        elif args.command == "migrate":
            print(json.dumps(migrate_project(args.project, args.mode), sort_keys=True))
        return 0
    except (BookForgeError, OSError, subprocess.SubprocessError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
