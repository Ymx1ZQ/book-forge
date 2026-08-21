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
import time
from pathlib import Path


MODEL = "openrouter/deepseek/deepseek-v4-flash-0731"
SCHEMA_VERSION = 1
ROLE_SPECS = {
    "book-forge-orchestrator": ("primary", "high", 30),
    "designer": ("all", "high", 10),
    "writer": ("all", "low", 8),
    "cold-reader": ("all", "low", 5),
    "technical-editor": ("all", "mid", 7),
    "reviser": ("all", "mid", 8),
    "canon-auditor": ("all", "high", 8),
    "translator": ("all", "low", 7),
    "judge": ("all", "high", 6),
    "book-forge-smoke": ("primary", "low", 3),
}


class BookForgeError(RuntimeError):
    pass


class ContextOverflowError(BookForgeError):
    def __init__(self, estimated: int, budget: int, contributors: list[dict[str, object]]):
        self.estimated = estimated
        self.budget = budget
        self.contributors = contributors
        summary = ", ".join(f"{row['name']}={row['estimated_tokens']}" for row in contributors[:5])
        super().__init__(f"Context estimate {estimated} exceeds budget {budget}; contributors: {summary}")


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


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


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


def _seed_control_plane(stage: Path) -> None:
    plan = {"schema": SCHEMA_VERSION, "generation": 0, "tasks": [], "attempts": []}
    plan_bytes = _json_bytes(plan)
    plan_hash = _sha256_bytes(plan_bytes)
    _write_bytes_atomic(stage / ".book-forge" / "plan.json", plan_bytes)
    _write_bytes_atomic(stage / ".book-forge" / "plan.shadow.json", plan_bytes)
    _write_json(
        stage / ".book-forge" / "control.json",
        {
            "schema": SCHEMA_VERSION,
            "fencing_counter": 0,
            "plan_hash": plan_hash,
            "active_run": None,
            "desired_generation": 0,
        },
    )
    for name, value in {
        "state.json": {"schema": SCHEMA_VERSION, "source_locked": False},
        "artifact-deps.json": {"schema": SCHEMA_VERSION, "artifacts": {}, "edges": []},
        "currentness.json": {"schema": SCHEMA_VERSION, "artifacts": {}},
        "index.json": {"schema": SCHEMA_VERSION, "blocks": {}},
        "revdeps.json": {"schema": SCHEMA_VERSION, "dependencies": {}},
        "appearances.json": {"schema": SCHEMA_VERSION, "entities": {}},
        "provider.json": {"schema": SCHEMA_VERSION, "eligible_at": None},
    }.items():
        _write_json(stage / ".book-forge" / name, value)


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
    _seed_control_plane(stage)
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


def _control(root: Path) -> dict[str, object]:
    return _read_json(root / ".book-forge" / "control.json")


def _load_plan(root: Path) -> dict[str, object]:
    path = root / ".book-forge" / "plan.json"
    plan_bytes = path.read_bytes()
    expected = _control(root).get("plan_hash")
    if _sha256_bytes(plan_bytes) != expected:
        raise BookForgeError("Canonical plan hash mismatch; use status --repair-view only after inspecting the change")
    try:
        plan = json.loads(plan_bytes)
    except json.JSONDecodeError as exc:
        raise BookForgeError(f"Invalid canonical plan: {exc}") from exc
    if not isinstance(plan, dict) or not isinstance(plan.get("tasks"), list) or not isinstance(plan.get("attempts"), list):
        raise BookForgeError("Canonical plan has an invalid shape")
    return plan


def _save_plan(root: Path, plan: dict[str, object], *, control: dict[str, object] | None = None) -> None:
    plan["generation"] = int(plan.get("generation", 0)) + 1
    value = _json_bytes(plan)
    _write_bytes_atomic(root / ".book-forge" / "plan.json", value)
    _write_bytes_atomic(root / ".book-forge" / "plan.shadow.json", value)
    state = control or _control(root)
    state["plan_hash"] = _sha256_bytes(value)
    _write_json(root / ".book-forge" / "control.json", state)


def add_task(
    project: Path | str,
    task_id: str,
    role: str,
    *,
    deps: list[str] | None = None,
    priority: int = 100,
    book_order: int = 0,
    chapter_order: int = 0,
    inputs: list[str] | None = None,
    outputs: list[str] | None = None,
) -> dict[str, object]:
    root = _project_root(project)
    plan = _load_plan(root)
    if role not in ROLE_SPECS or role in {"book-forge-orchestrator", "book-forge-smoke"}:
        raise BookForgeError(f"Invalid worker role: {role}")
    if any(task["id"] == task_id for task in plan["tasks"]):
        raise BookForgeError(f"Duplicate task: {task_id}")
    dependencies = deps or []
    known = {str(task["id"]) for task in plan["tasks"]}
    if not set(dependencies) <= known:
        raise BookForgeError("Task depends on an unknown or not-yet-declared task")
    task = {
        "id": task_id,
        "role": role,
        "deps": list(dependencies),
        "priority": priority,
        "book_order": book_order,
        "chapter_order": chapter_order,
        "inputs": list(inputs or []),
        "outputs": list(outputs or []),
        "state": "pending",
    }
    plan["tasks"].append(task)
    _save_plan(root, plan)
    render_plan(root)
    return task


def _task_depth(task_id: str, tasks: dict[str, dict[str, object]], cache: dict[str, int]) -> int:
    if task_id not in cache:
        deps = tasks[task_id].get("deps", [])
        cache[task_id] = 0 if not deps else 1 + max(_task_depth(str(dep), tasks, cache) for dep in deps)
    return cache[task_id]


def ready_frontier(project: Path | str) -> list[dict[str, object]]:
    root = _project_root(project)
    active = _control(root).get("active_run")
    if active:
        run_path = root / ".book-forge" / "runs" / str(active) / "run.json"
        if run_path.exists() and _read_json(run_path).get("state") != "running":
            return []
    plan = _load_plan(root)
    tasks = {str(task["id"]): task for task in plan["tasks"]}
    succeeded = {task_id for task_id, task in tasks.items() if task["state"] == "succeeded"}
    ready = [task for task in tasks.values() if task["state"] == "pending" and set(task["deps"]) <= succeeded]
    depths: dict[str, int] = {}
    return sorted(
        ready,
        key=lambda task: (
            int(task["priority"]),
            _task_depth(str(task["id"]), tasks, depths),
            int(task["book_order"]),
            int(task["chapter_order"]),
            str(task["id"]),
        ),
    )


def claim_task(
    project: Path | str,
    task_id: str,
    *,
    request_hash: str,
    now: float | None = None,
    lease_seconds: float = 300,
) -> dict[str, object]:
    root = _project_root(project)
    current_time = time.time() if now is None else now
    if not provider_ready(root, now=current_time):
        raise BookForgeError("Provider is rate-limited; dispatch is not yet eligible")
    run = start_run(root, now=current_time)
    if run["state"] != "running":
        raise BookForgeError(f"Run does not accept dispatch while {run['state']}")
    if not re.fullmatch(r"[0-9a-f]{64}", request_hash):
        raise BookForgeError("request_hash must be a lowercase SHA-256")
    plan = _load_plan(root)
    active_attempts = [row for row in plan["attempts"] if row["state"] in {"running", "promotion_pending"}]
    if len(active_attempts) >= 2:
        raise BookForgeError("Maximum subagent concurrency is two")
    ready_ids = {str(task["id"]) for task in ready_frontier(root)}
    if task_id not in ready_ids:
        raise BookForgeError(f"Task is not ready: {task_id}")
    control = _control(root)
    control["fencing_counter"] = int(control["fencing_counter"]) + 1
    fence = int(control["fencing_counter"])
    attempt_id = _next_id([str(row["id"]) for row in plan["attempts"]], "ATT-")
    task = next(row for row in plan["tasks"] if row["id"] == task_id)
    task["state"] = "running"
    task["attempt"] = attempt_id
    attempt = {
        "id": attempt_id,
        "task": task_id,
        "role": task["role"],
        "fence": fence,
        "request_hash": request_hash,
        "state": "running",
        "provider_accepted": False,
        "heartbeat_at": current_time,
        "lease_expires_at": current_time + lease_seconds,
    }
    plan["attempts"].append(attempt)
    capsule = {"schema": 1, "task": task, "attempt": attempt_id, "fence": fence, "request_hash": request_hash}
    attempt_dir = root / ".book-forge" / "runs" / "RUN-0001" / "attempts" / attempt_id
    _write_json(attempt_dir / "capsule.json", capsule)
    _write_json(attempt_dir / "intent.json", {"schema": 1, "accepted": False, **attempt})
    _save_plan(root, plan, control=control)
    render_plan(root)
    return {"attempt": attempt_id, "fence": fence, "capsule": str(attempt_dir / "capsule.json")}


def _attempt(plan: dict[str, object], attempt_id: str) -> dict[str, object]:
    for row in plan["attempts"]:
        if row["id"] == attempt_id:
            return row
    raise BookForgeError(f"Unknown attempt: {attempt_id}")


def _assert_fence(attempt: dict[str, object], fence: int) -> None:
    if int(attempt["fence"]) != fence:
        raise BookForgeError("Stale fencing token")


def record_execution(project: Path | str, attempt_id: str, fence: int, *, output_hash: str) -> dict[str, object]:
    root = _project_root(project)
    plan = _load_plan(root)
    attempt = _attempt(plan, attempt_id)
    _assert_fence(attempt, fence)
    if attempt["state"] != "running":
        raise BookForgeError("Attempt is not awaiting execution evidence")
    if not re.fullmatch(r"[0-9a-f]{64}", output_hash):
        raise BookForgeError("output_hash must be a lowercase SHA-256")
    receipt = {"schema": 1, "attempt": attempt_id, "task": attempt["task"], "fence": fence, "output_hash": output_hash, "outcome": "observed"}
    receipt_path = root / ".book-forge" / "runs" / "RUN-0001" / "attempts" / attempt_id / "execution-receipt.json"
    if receipt_path.exists():
        raise BookForgeError("Execution receipt is immutable")
    _write_json(receipt_path, receipt)
    attempt["state"] = "promotion_pending"
    task = next(row for row in plan["tasks"] if row["id"] == attempt["task"])
    task["state"] = "promotion_pending"
    task["execution_receipt"] = str(receipt_path.relative_to(root))
    _save_plan(root, plan)
    render_plan(root)
    _settle_run(root)
    return receipt


def _safe_relative_target(root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts or candidate.parts[0] == ".book-forge":
        raise BookForgeError(f"Unsafe promotion target: {relative}")
    current = root
    for part in candidate.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise BookForgeError(f"Symlink escape in promotion target: {relative}")
    target = root / candidate
    try:
        target.resolve(strict=False).relative_to(root.resolve())
    except ValueError as exc:
        raise BookForgeError(f"Promotion target escapes project: {relative}") from exc
    if target.is_symlink():
        raise BookForgeError(f"Promotion target is a symlink: {relative}")
    return target


def _file_hash(path: Path) -> str | None:
    return _sha256_bytes(path.read_bytes()) if path.is_file() else None


def stage_outputs(project: Path | str, attempt_id: str, outputs: dict[str, str | bytes]) -> dict[str, object]:
    root = _project_root(project)
    plan = _load_plan(root)
    attempt = _attempt(plan, attempt_id)
    if attempt["state"] != "running":
        raise BookForgeError("Outputs can be staged only for a running attempt")
    task = next(row for row in plan["tasks"] if row["id"] == attempt["task"])
    declared = set(task.get("outputs", []))
    if set(outputs) != declared:
        raise BookForgeError("Staged outputs must exactly match the task's declared outputs")
    attempt_dir = root / ".book-forge" / "runs" / "RUN-0001" / "attempts" / attempt_id
    rows = []
    for relative in sorted(outputs):
        target = _safe_relative_target(root, relative)
        value = outputs[relative].encode() if isinstance(outputs[relative], str) else outputs[relative]
        staged = attempt_dir / "staged" / relative
        _write_bytes_atomic(staged, value)
        rows.append(
            {
                "path": relative,
                "base_hash": _file_hash(target),
                "target_hash": _sha256_bytes(value),
                "staged": str(staged.relative_to(root)),
            }
        )
    manifest = {"schema": 1, "attempt": attempt_id, "task": attempt["task"], "files": rows}
    _write_json(attempt_dir / "output-manifest.json", manifest)
    return manifest


def _scoped_git_commit(root: Path, paths: list[str], transaction_id: str) -> tuple[str | None, bool]:
    if not paths or not _inside_git_repo(root):
        return None, False
    add = subprocess.run(["git", "-C", str(root), "add", "--", *paths], capture_output=True, text=True, check=False)
    if add.returncode != 0:
        return None, True
    changed = subprocess.run(["git", "-C", str(root), "diff", "--cached", "--quiet", "--", *paths], check=False)
    if changed.returncode == 0:
        head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
        return (head.stdout.strip() or None), False
    commit = subprocess.run(
        ["git", "-C", str(root), "commit", "-m", f"book-forge: promote {transaction_id}", "--", *paths],
        capture_output=True,
        text=True,
        check=False,
    )
    if commit.returncode != 0:
        return None, True
    head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
    return head.stdout.strip(), False


def _complete_promoted_attempt(root: Path, attempt_id: str, receipt_path: Path) -> None:
    plan = _load_plan(root)
    attempt = _attempt(plan, attempt_id)
    if attempt["state"] == "succeeded":
        return
    attempt["state"] = "succeeded"
    task = next(row for row in plan["tasks"] if row["id"] == attempt["task"])
    task["state"] = "succeeded"
    task["promotion_receipt"] = str(receipt_path.relative_to(root))
    _save_plan(root, plan)
    render_plan(root)
    _settle_run(root)


def _recover_transaction(root: Path, transaction: Path, *, fault_hook=None) -> dict[str, object]:
    journal_path = transaction / "journal.json"
    journal = _read_json(journal_path)
    if journal.get("state") == "completed":
        return journal
    for row in journal["files"]:
        target = _safe_relative_target(root, str(row["path"]))
        current = _file_hash(target)
        if current == row["target_hash"]:
            if row["path"] not in journal["installed"]:
                journal["installed"].append(row["path"])
                _write_json(journal_path, journal)
            continue
        if current != row["base_hash"]:
            journal["state"] = "blocked_conflict"
            journal["conflict"] = row["path"]
            _write_json(journal_path, journal)
            raise BookForgeError(f"Promotion conflict at {row['path']}; staged output was preserved")
        staged = root / row["staged"]
        if _file_hash(staged) != row["target_hash"]:
            raise BookForgeError(f"Staged output hash mismatch at {row['path']}")
        _write_bytes_atomic(target, staged.read_bytes())
        journal["installed"].append(row["path"])
        journal["state"] = "installing"
        _write_json(journal_path, journal)
        if fault_hook:
            fault_hook(f"after_install:{row['path']}")

    if not journal.get("commit_recorded"):
        commit, sync_pending = _scoped_git_commit(root, [str(row["path"]) for row in journal["files"]], str(journal["id"]))
        journal["commit"] = commit
        journal["sync_pending"] = sync_pending
        journal["commit_recorded"] = True
        journal["state"] = "committed" if not sync_pending else "sync_pending"
        _write_json(journal_path, journal)
        if fault_hook:
            fault_hook("after_commit")

    receipt_path = root / journal["receipt"]
    if not receipt_path.exists():
        receipt = {
            "schema": 1,
            "attempt": journal["attempt"],
            "task": journal["task"],
            "fence": journal["fence"],
            "transaction": journal["id"],
            "promoted": True,
            "commit": journal.get("commit"),
            "sync_pending": journal.get("sync_pending", False),
            "files": [{"path": row["path"], "hash": row["target_hash"]} for row in journal["files"]],
        }
        _write_json(receipt_path, receipt)
        journal["state"] = "receipted"
        _write_json(journal_path, journal)
        if fault_hook:
            fault_hook("after_receipt")
    _complete_promoted_attempt(root, str(journal["attempt"]), receipt_path)
    journal["state"] = "completed"
    _write_json(journal_path, journal)
    return journal


def recover_transactions(project: Path | str) -> list[dict[str, object]]:
    root = _project_root(project)
    transactions = root / ".book-forge" / "transactions"
    results = []
    if transactions.exists():
        for path in sorted(transactions.glob("TXN-*")):
            results.append(_recover_transaction(root, path))
    return results


def promote_task(project: Path | str, attempt_id: str, fence: int, *, fault_hook=None) -> dict[str, object]:
    root = _project_root(project)
    plan = _load_plan(root)
    attempt = _attempt(plan, attempt_id)
    _assert_fence(attempt, fence)
    if attempt["state"] != "promotion_pending":
        raise BookForgeError("Attempt is not ready for promotion")
    receipt_path = root / ".book-forge" / "runs" / "RUN-0001" / "attempts" / attempt_id / "promotion-receipt.json"
    if receipt_path.exists():
        raise BookForgeError("Promotion receipt is immutable")
    attempt_dir = receipt_path.parent
    manifest_path = attempt_dir / "output-manifest.json"
    manifest = _read_json(manifest_path) if manifest_path.exists() else {"files": []}
    transaction_root = root / ".book-forge" / "transactions"
    transaction_root.mkdir(parents=True, exist_ok=True)
    transaction_id = _next_id([path.name for path in transaction_root.glob("TXN-*")], "TXN-")
    transaction = transaction_root / transaction_id
    transaction.mkdir()
    journal = {
        "schema": 1,
        "id": transaction_id,
        "attempt": attempt_id,
        "task": attempt["task"],
        "fence": fence,
        "files": manifest["files"],
        "installed": [],
        "receipt": str(receipt_path.relative_to(root)),
        "commit_recorded": False,
        "sync_pending": False,
        "state": "prepared",
    }
    _write_json(transaction / "journal.json", journal)
    if fault_hook:
        fault_hook("after_prepare")
    completed = _recover_transaction(root, transaction, fault_hook=fault_hook)
    return _read_json(root / completed["receipt"])


def status_project(project: Path | str) -> dict[str, object]:
    root = _project_root(project)
    plan = _load_plan(root)
    counts: dict[str, int] = {}
    for task in plan["tasks"]:
        counts[str(task["state"])] = counts.get(str(task["state"]), 0) + 1
    transaction_states: dict[str, int] = {}
    transactions = root / ".book-forge" / "transactions"
    if transactions.exists():
        for path in transactions.glob("TXN-*/journal.json"):
            state = str(_read_json(path)["state"])
            transaction_states[state] = transaction_states.get(state, 0) + 1
    control = _control(root)
    run = None
    if control.get("active_run"):
        run = _read_json(root / ".book-forge" / "runs" / str(control["active_run"]) / "run.json")
    return {"tasks": counts, "transactions": transaction_states, "plan_hash": control["plan_hash"], "run": run}


def _run_path(root: Path, run_id: str) -> Path:
    return root / ".book-forge" / "runs" / run_id / "run.json"


def start_run(project: Path | str, *, now: float | None = None) -> dict[str, object]:
    root = _project_root(project)
    control = _control(root)
    if control.get("active_run"):
        run = _read_json(_run_path(root, str(control["active_run"])))
        if run["state"] not in {"completed", "cancelled"}:
            return run
    runs_root = root / ".book-forge" / "runs"
    run_id = _next_id([path.name for path in runs_root.glob("RUN-*")], "RUN-")
    current_time = time.time() if now is None else now
    run = {
        "schema": 1,
        "id": run_id,
        "state": "running",
        "desired_state": "running",
        "desired_generation": int(control.get("desired_generation", 0)) + 1,
        "started_at": current_time,
    }
    _write_json(_run_path(root, run_id), run)
    control["active_run"] = run_id
    control["desired_generation"] = run["desired_generation"]
    _write_json(root / ".book-forge" / "control.json", control)
    return run


def _settle_run(project: Path | str) -> dict[str, object] | None:
    root = _project_root(project)
    control = _control(root)
    if not control.get("active_run"):
        return None
    path = _run_path(root, str(control["active_run"]))
    run = _read_json(path)
    plan = _load_plan(root)
    task_states = {str(task["state"]) for task in plan["tasks"]}
    if run.get("desired_state") == "paused":
        if "outcome_unknown" in task_states:
            run["state"] = "blocked"
        elif task_states & {"running", "validating", "promotion_pending"}:
            run["state"] = "pausing"
        else:
            run["state"] = "paused"
    elif plan["tasks"] and task_states <= {"succeeded", "cancelled"}:
        run["state"] = "completed"
    _write_json(path, run)
    return run


def mark_provider_accepted(
    project: Path | str, attempt_id: str, session_id: str, *, now: float | None = None
) -> dict[str, object]:
    root = _project_root(project)
    plan = _load_plan(root)
    attempt = _attempt(plan, attempt_id)
    if attempt["state"] != "running":
        raise BookForgeError("Only a running attempt can be marked accepted")
    attempt["provider_accepted"] = True
    attempt["session_id"] = session_id
    attempt["accepted_at"] = time.time() if now is None else now
    _save_plan(root, plan)
    intent = root / ".book-forge" / "runs" / "RUN-0001" / "attempts" / attempt_id / "intent.json"
    value = _read_json(intent)
    value["accepted"] = True
    value["session_id"] = session_id
    _write_json(intent, value)
    return attempt


def pause_run(project: Path | str, *, emergency: bool = False) -> dict[str, object]:
    root = _project_root(project)
    control = _control(root)
    if not control.get("active_run"):
        raise BookForgeError("No active run")
    run_path = _run_path(root, str(control["active_run"]))
    run = _read_json(run_path)
    if run["state"] not in {"running", "pausing"}:
        raise BookForgeError(f"Run cannot pause while {run['state']}")
    run["desired_state"] = "paused"
    run["desired_generation"] = int(run["desired_generation"]) + 1
    run["state"] = "pausing"
    run["emergency"] = emergency
    _write_json(run_path, run)
    control["desired_generation"] = run["desired_generation"]
    _write_json(root / ".book-forge" / "control.json", control)
    if emergency:
        plan = _load_plan(root)
        for attempt in plan["attempts"]:
            if attempt["state"] != "running":
                continue
            task = next(row for row in plan["tasks"] if row["id"] == attempt["task"])
            if attempt.get("provider_accepted"):
                attempt["state"] = "outcome_unknown"
                task["state"] = "outcome_unknown"
            else:
                attempt["state"] = "orphaned"
                task["state"] = "pending"
        _save_plan(root, plan)
        render_plan(root)
    return _settle_run(root)


def _block_descendants(plan: dict[str, object], task_id: str) -> None:
    blocked = {task_id}
    changed = True
    while changed:
        changed = False
        for task in plan["tasks"]:
            if task["id"] in blocked or set(task["deps"]) & blocked:
                if task["id"] not in blocked:
                    blocked.add(str(task["id"]))
                    changed = True
                task["state"] = "blocked"


def resume_run(project: Path | str, *, resolutions: dict[str, str] | None = None) -> dict[str, object]:
    root = _project_root(project)
    control = _control(root)
    if not control.get("active_run"):
        raise BookForgeError("No active run")
    run_path = _run_path(root, str(control["active_run"]))
    run = _read_json(run_path)
    if run["state"] not in {"paused", "blocked"}:
        raise BookForgeError(f"Run cannot resume while {run['state']}")
    plan = _load_plan(root)
    unknown_tasks = {str(task["id"]): task for task in plan["tasks"] if task["state"] == "outcome_unknown"}
    choices = resolutions or {}
    if set(unknown_tasks) != set(choices):
        raise BookForgeError("Every outcome_unknown task requires an explicit retry or abandon resolution")
    for task_id, task in unknown_tasks.items():
        choice = choices[task_id]
        if choice not in {"retry", "abandon"}:
            raise BookForgeError(f"Invalid unknown resolution for {task_id}: {choice}")
        attempt = _attempt(plan, str(task["attempt"]))
        if choice == "retry":
            attempt["state"] = "orphaned"
            attempt["resolution"] = "retry"
            task["state"] = "pending"
            task.pop("attempt", None)
        else:
            attempt["resolution"] = "abandon"
            _block_descendants(plan, task_id)
    _save_plan(root, plan)
    render_plan(root)
    run["state"] = "running"
    run["desired_state"] = "running"
    run["desired_generation"] = int(run["desired_generation"]) + 1
    _write_json(run_path, run)
    control = _control(root)
    control["desired_generation"] = run["desired_generation"]
    _write_json(root / ".book-forge" / "control.json", control)
    return run


def set_rate_limit(project: Path | str, *, retry_after: float, now: float | None = None) -> dict[str, object]:
    if retry_after < 0:
        raise BookForgeError("Retry-After cannot be negative")
    root = _project_root(project)
    current_time = time.time() if now is None else now
    data = _read_json(root / ".book-forge" / "provider.json")
    data.update({"retry_after": retry_after, "chosen_backoff": retry_after, "wait_started_at": current_time, "eligible_at": current_time + retry_after})
    _write_json(root / ".book-forge" / "provider.json", data)
    return data


def provider_ready(project: Path | str, *, now: float | None = None) -> bool:
    root = _project_root(project)
    current_time = time.time() if now is None else now
    eligible = _read_json(root / ".book-forge" / "provider.json").get("eligible_at")
    return eligible is None or current_time >= float(eligible)


def recover_run(project: Path | str, *, now: float | None = None) -> dict[str, object]:
    root = _project_root(project)
    recover_transactions(root)
    current_time = time.time() if now is None else now
    plan = _load_plan(root)
    orphaned = []
    unknown = []
    for attempt in plan["attempts"]:
        if attempt["state"] == "running" and current_time > float(attempt.get("lease_expires_at", current_time + 1)):
            task = next(row for row in plan["tasks"] if row["id"] == attempt["task"])
            if attempt.get("provider_accepted"):
                attempt["state"] = "outcome_unknown"
                task["state"] = "outcome_unknown"
                unknown.append(str(attempt["id"]))
            else:
                attempt["state"] = "orphaned"
                task["state"] = "pending"
                task.pop("attempt", None)
                orphaned.append(str(attempt["id"]))
    _save_plan(root, plan)
    render_plan(root)
    if unknown:
        control = _control(root)
        if control.get("active_run"):
            run_path = _run_path(root, str(control["active_run"]))
            run = _read_json(run_path)
            run["state"] = "blocked"
            _write_json(run_path, run)
    return {"orphaned": orphaned, "outcome_unknown": unknown}


def record_late_result(project: Path | str, attempt_id: str, output_hash: str) -> dict[str, object]:
    root = _project_root(project)
    plan = _load_plan(root)
    attempt = _attempt(plan, attempt_id)
    if not attempt.get("provider_accepted") or attempt["state"] not in {"outcome_unknown", "orphaned"}:
        raise BookForgeError("Late result is not associated with an ambiguous accepted attempt")
    attempt["state"] = "orphaned"
    attempt["late_output_hash"] = output_hash
    path = root / ".book-forge" / "runs" / "RUN-0001" / "attempts" / attempt_id / "orphaned-result.json"
    _write_json(path, {"schema": 1, "attempt": attempt_id, "output_hash": output_hash, "state": "orphaned"})
    _save_plan(root, plan)
    return attempt


def cleanup_attempt(project: Path | str, attempt_id: str) -> None:
    root = _project_root(project)
    plan = _load_plan(root)
    attempt = _attempt(plan, attempt_id)
    if attempt["state"] in {"running", "validating", "promotion_pending", "outcome_unknown", "orphaned"}:
        raise BookForgeError(f"Refusing cleanup for {attempt['state']} attempt")
    path = root / ".book-forge" / "runs" / "RUN-0001" / "attempts" / attempt_id / "staged"
    if path.exists():
        shutil.rmtree(path)


BLOCK_MARKER = re.compile(r"<!--\s*bf:block\s+([a-z0-9][a-z0-9-]*)\s*-->")
IMPORT_MARKER = re.compile(r"<!--\s*bf:import\s+([A-Z][A-Z0-9-]*#[a-z0-9][a-z0-9-]*)\s*-->")


def _markdown_metadata(text_value: str) -> dict[str, str]:
    if not text_value.startswith("---\n") or "\n---\n" not in text_value[4:]:
        return {}
    header = text_value[4:].split("\n---\n", 1)[0]
    metadata = {}
    for line in header.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            metadata[key.strip()] = value.strip()
    return metadata


def _artifact_registry(root: Path) -> dict[str, object]:
    return _read_json(root / ".book-forge" / "artifact-deps.json")


def rebuild_indexes(project: Path | str) -> dict[str, object]:
    root = _project_root(project)
    blocks: dict[str, dict[str, object]] = {}
    import_edges: dict[str, list[str]] = {}
    authored_roots = [root / "universe", root / "books"]
    for authored_root in authored_roots:
        if not authored_root.exists():
            continue
        for path in sorted(authored_root.rglob("*.md")):
            if "translations" in path.parts or "manuscript" in path.parts:
                continue
            text_value = path.read_text(encoding="utf-8")
            metadata = _markdown_metadata(text_value)
            owner = metadata.get("id")
            markers = list(BLOCK_MARKER.finditer(text_value))
            if markers and not owner:
                raise BookForgeError(f"Addressable blocks require frontmatter id: {path.relative_to(root)}")
            for index, marker in enumerate(markers):
                block_id = f"{owner}#{marker.group(1)}"
                end = markers[index + 1].start() if index + 1 < len(markers) else len(text_value)
                content = text_value[marker.end():end].strip().encode()
                if block_id in blocks:
                    raise BookForgeError(f"Duplicate addressable block: {block_id}")
                imports = IMPORT_MARKER.findall(text_value[marker.end():end])
                blocks[block_id] = {
                    "path": str(path.relative_to(root)),
                    "hash": _sha256_bytes(content),
                    "continuity": metadata.get("continuity"),
                    "imports": imports,
                }
                import_edges[block_id] = imports
    relations = _read_json(root / "universe" / "relations.yaml")
    for relation in relations.get("relations", []):
        for imported in relation.get("imports", []):
            if imported.get("block") not in blocks:
                raise BookForgeError(f"Dangling relation import: {imported.get('block')}")
    for owner, dependencies in import_edges.items():
        for dependency in dependencies:
            if dependency not in blocks:
                raise BookForgeError(f"Dangling block import: {owner} -> {dependency}")

    def visit(node: str, visiting: set[str], visited: set[str]) -> None:
        if node in visiting:
            raise BookForgeError(f"Block import cycle at {node}")
        if node in visited:
            return
        visiting.add(node)
        for dependency in import_edges.get(node, []):
            visit(dependency, visiting, visited)
        visiting.remove(node)
        visited.add(node)

    visited: set[str] = set()
    for block_id in blocks:
        visit(block_id, set(), visited)
    index = {"schema": 1, "blocks": blocks}
    _write_json(root / ".book-forge" / "index.json", index)
    _write_derived_dependency_views(root)
    return index


def _write_derived_dependency_views(root: Path) -> None:
    registry = _artifact_registry(root)
    revdeps: dict[str, list[str]] = {}
    appearances: dict[str, list[str]] = {}
    timeline: dict[str, list[str]] = {}
    for artifact_id, artifact in registry.get("artifacts", {}).items():
        for dependency in artifact.get("dependencies", []):
            revdeps.setdefault(str(dependency), []).append(str(artifact_id))
        for entity in artifact.get("entities", []):
            appearances.setdefault(str(entity), []).append(str(artifact_id))
        for event in artifact.get("events", []):
            timeline.setdefault(str(event), []).append(str(artifact_id))
    _write_json(root / ".book-forge" / "revdeps.json", {"schema": 1, "dependencies": {key: sorted(set(value)) for key, value in sorted(revdeps.items())}})
    _write_json(root / ".book-forge" / "appearances.json", {"schema": 1, "entities": {key: sorted(set(value)) for key, value in sorted(appearances.items())}, "events": {key: sorted(set(value)) for key, value in sorted(timeline.items())}})


def _dependency_hash(root: Path, dependency: str, registry: dict[str, object], index: dict[str, object]) -> str:
    if "#" in dependency:
        block = index["blocks"].get(dependency)
        if not block:
            raise BookForgeError(f"Dangling block dependency: {dependency}")
        return str(block["hash"])
    artifact = registry["artifacts"].get(dependency)
    if not artifact:
        raise BookForgeError(f"Dangling artifact dependency: {dependency}")
    return str(artifact["hash"])


def register_artifact(
    project: Path | str,
    artifact_id: str,
    kind: str,
    *,
    path: Path | str,
    dependencies: list[str] | None = None,
    entities: list[str] | None = None,
    events: list[str] | None = None,
    authored: bool = False,
) -> dict[str, object]:
    root = _project_root(project)
    target = Path(path).resolve() if Path(path).is_absolute() else (root / path).resolve()
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise BookForgeError("Artifact path escapes the project") from exc
    if not target.is_file():
        raise BookForgeError(f"Artifact path does not exist: {relative}")
    registry = _artifact_registry(root)
    if artifact_id in registry["artifacts"]:
        raise BookForgeError(f"Duplicate artifact: {artifact_id}")
    index = rebuild_indexes(root)
    dependency_list = list(dependencies or [])
    dependency_hashes = {dependency: _dependency_hash(root, dependency, registry, index) for dependency in dependency_list}
    row = {
        "kind": kind,
        "path": str(relative),
        "hash": _file_hash(target),
        "authored": authored,
        "dependencies": dependency_list,
        "dependency_hashes": dependency_hashes,
        "entities": list(entities or []),
        "events": list(events or []),
    }
    registry["artifacts"][artifact_id] = row
    registry["edges"] = sorted(
        [{"from": dependency, "to": target_id} for target_id, artifact in registry["artifacts"].items() for dependency in artifact.get("dependencies", [])],
        key=lambda edge: (edge["from"], edge["to"]),
    )
    _write_json(root / ".book-forge" / "artifact-deps.json", registry)
    _write_derived_dependency_views(root)
    return row


def reconcile_artifacts(project: Path | str) -> list[str]:
    root = _project_root(project)
    index = rebuild_indexes(root)
    registry = _artifact_registry(root)
    direct_stale: set[str] = set()
    for artifact_id, artifact in registry["artifacts"].items():
        target = root / artifact["path"]
        current_hash = _file_hash(target)
        if current_hash != artifact["hash"]:
            if not artifact.get("authored"):
                raise BookForgeError(f"Derived artifact was edited directly: {artifact_id}")
            artifact["hash"] = current_hash
        for dependency in artifact.get("dependencies", []):
            current_dependency = _dependency_hash(root, dependency, registry, index)
            if current_dependency != artifact["dependency_hashes"].get(dependency):
                direct_stale.add(str(artifact_id))
    revdeps = _read_json(root / ".book-forge" / "revdeps.json")["dependencies"]
    stale = set(direct_stale)
    frontier = list(direct_stale)
    while frontier:
        dependency = frontier.pop()
        for consumer in revdeps.get(dependency, []):
            if consumer not in stale:
                stale.add(consumer)
                frontier.append(consumer)
    _write_json(root / ".book-forge" / "artifact-deps.json", registry)
    _write_json(
        root / ".book-forge" / "currentness.json",
        {"schema": 1, "artifacts": {artifact_id: {"current": artifact_id not in stale, "causes": sorted(direct_stale) if artifact_id in stale else []} for artifact_id in sorted(registry["artifacts"])}},
    )
    return sorted(stale)


ROLE_BUDGETS = {
    "designer": (16000, 5000),
    "writer": (12000, 6000),
    "cold-reader": (8000, 2500),
    "technical-editor": (10000, 3000),
    "reviser": (14000, 6000),
    "canon-auditor": (16000, 3500),
    "translator": (14000, 6000),
    "judge": (10000, 2000),
}


def _estimate_deepseek_tokens(value: bytes, *, include_overhead: bool = False) -> int:
    # Conservative byte-based estimator pinned for the DeepSeek V4 Flash application
    # envelope. Provider telemetry calibrates the separately visible OpenCode overhead.
    estimate = (len(value) + 2) // 3
    estimate = (estimate * 115 + 99) // 100
    return estimate + (768 if include_overhead else 0)


def _block_content(root: Path, block_id: str, index: dict[str, object]) -> str:
    block = index["blocks"][block_id]
    text_value = (root / block["path"]).read_text(encoding="utf-8")
    local_name = block_id.split("#", 1)[1]
    markers = list(BLOCK_MARKER.finditer(text_value))
    for position, marker in enumerate(markers):
        if marker.group(1) == local_name:
            end = markers[position + 1].start() if position + 1 < len(markers) else len(text_value)
            return text_value[marker.end():end].strip()
    raise BookForgeError(f"Indexed block cannot be materialized: {block_id}")


def _close_imports(index: dict[str, object], requested: list[str]) -> list[str]:
    closed: set[str] = set()
    frontier = list(requested)
    while frontier:
        block_id = frontier.pop()
        if block_id in closed:
            continue
        if block_id not in index["blocks"]:
            raise BookForgeError(f"Unknown context import: {block_id}")
        closed.add(block_id)
        frontier.extend(index["blocks"][block_id].get("imports", []))
    return sorted(closed)


def build_envelope(
    project: Path | str,
    *,
    role: str,
    task_capsule: dict[str, object],
    imports: list[str],
    state: dict[str, object],
    tools: list[dict[str, object]],
    max_output_tokens: int,
    input_budget: int | None = None,
) -> dict[str, object]:
    root = _project_root(project)
    if role not in ROLE_BUDGETS:
        raise BookForgeError(f"Role has no envelope budget: {role}")
    default_input, output_budget = ROLE_BUDGETS[role]
    budget = default_input if input_budget is None else input_budget
    if max_output_tokens <= 0 or max_output_tokens > output_budget:
        raise BookForgeError(f"Output allowance {max_output_tokens} exceeds {role} budget {output_budget}")
    prompt_path = Path(__file__).resolve().parents[1] / "assets" / "prompts" / f"{role}.md"
    if not prompt_path.is_file():
        raise BookForgeError(f"Missing pinned role prompt: {prompt_path.name}")
    role_prompt = prompt_path.read_text(encoding="utf-8").strip()
    clean_task = dict(task_capsule)
    if role in {"cold-reader", "technical-editor", "canon-auditor", "judge"}:
        clean_task.pop("author_history", None)
    index = rebuild_indexes(root)
    context = []
    if role != "cold-reader":
        for block_id in _close_imports(index, imports):
            context.append({"id": block_id, "hash": index["blocks"][block_id]["hash"], "content": _block_content(root, block_id, index)})
    payload = {
        "schema": 1,
        "model": MODEL,
        "role": role,
        "role_prompt": role_prompt,
        "task": clean_task,
        "context": context,
        "state": state,
        "tools": tools,
        "max_output_tokens": max_output_tokens,
    }
    envelope_bytes = (json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode()
    estimate = _estimate_deepseek_tokens(envelope_bytes, include_overhead=True)
    sections: list[tuple[str, object]] = [
        ("role_prompt", role_prompt),
        ("task", clean_task),
        ("state", state),
        ("tools", tools),
    ]
    sections.extend((f"context:{row['id']}", row) for row in context)
    contributors = sorted(
        [
            {
                "name": name,
                "estimated_tokens": _estimate_deepseek_tokens(
                    json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
                ),
            }
            for name, value in sections
        ],
        key=lambda row: (-int(row["estimated_tokens"]), str(row["name"])),
    )
    if estimate > budget:
        raise ContextOverflowError(estimate, budget, contributors)
    return {
        "payload": payload,
        "bytes": envelope_bytes,
        "hash": _sha256_bytes(envelope_bytes),
        "estimated_input_tokens": estimate,
        "max_output_tokens": max_output_tokens,
        "estimated_total_tokens": estimate + max_output_tokens,
        "input_budget": budget,
        "output_budget": output_budget,
        "estimator": "deepseek-v4-flash-conservative-v1",
        "opencode_overhead_allowance_tokens": 768,
        "contributors": contributors,
    }


def render_plan(project: Path | str) -> str:
    root = _project_root(project)
    plan = _load_plan(root)
    plan_hash = str(_control(root)["plan_hash"])
    lines = ["# Universe Work Plan", "", f"<!-- book-forge-plan-hash: {plan_hash} -->", ""]
    for task in sorted(plan["tasks"], key=lambda row: str(row["id"])):
        marker = "x" if task["state"] == "succeeded" else " "
        lines.append(f"- [{marker}] {task['id']} · {task['role']} · {task['state']}")
    value = "\n".join(lines) + "\n"
    _write_bytes_atomic(root / "DEVPLAN.md", value.encode())
    return value


def repair_plan_view(project: Path | str, *, restore_canonical: bool = False) -> str:
    root = _project_root(project)
    if restore_canonical:
        shadow = root / ".book-forge" / "plan.shadow.json"
        value = shadow.read_bytes()
        control = _control(root)
        if _sha256_bytes(value) != control.get("plan_hash"):
            raise BookForgeError("Canonical shadow also differs; manual recovery is required")
        _write_bytes_atomic(root / ".book-forge" / "plan.json", value)
    return render_plan(root)


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
    pause = commands.add_parser("pause")
    pause.add_argument("--run")
    pause.add_argument("--emergency", action="store_true")
    resume = commands.add_parser("resume")
    resume.add_argument("--run")
    resume.add_argument("--resolve-unknown", action="append", default=[])
    status = commands.add_parser("status")
    status.add_argument("--book")
    status.add_argument("--run")
    status.add_argument("--locale")
    status.add_argument("--repair-view", action="store_true")
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
        elif args.command == "pause":
            print(json.dumps(pause_run(args.project, emergency=args.emergency), sort_keys=True))
        elif args.command == "resume":
            resolutions = {}
            for value in args.resolve_unknown:
                if ":" not in value:
                    raise BookForgeError("--resolve-unknown must be TASK:retry or TASK:abandon")
                task, resolution = value.rsplit(":", 1)
                resolutions[task] = resolution
            print(json.dumps(resume_run(args.project, resolutions=resolutions), sort_keys=True))
        elif args.command == "status":
            if args.repair_view:
                repair_plan_view(args.project)
            print(json.dumps(status_project(args.project), sort_keys=True))
        return 0
    except (BookForgeError, OSError, subprocess.SubprocessError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
