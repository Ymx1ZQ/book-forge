#!/usr/bin/env python3
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import html
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
import uuid
# M2: brief gate import — robust for both package and direct-file execution
def _load_brief_gate():
    try:
        import importlib.util
        from pathlib import Path as _P
        bf_path = _P(__file__).parent / "brief.py"
        if bf_path.is_file():
            spec = importlib.util.spec_from_file_location("_bf_brief", bf_path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod.should_gate, mod.BRIEF_QUESTIONS
    except Exception:
        pass
    return (lambda *a, **kw: False), []
_should_brief_gate, BRIEF_QUESTIONS = _load_brief_gate()
# M4: tiered validation
try:
    import importlib.util as _ilu
    import pathlib as _pl
    _vp = _pl.Path(__file__).parent / "validate.py"
    if _vp.is_file():
        _spec = _ilu.spec_from_file_location("_bf_validate", _vp)
        _mod = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        _validate_tiered_cast = _mod.validate_tiered_cast
        _validate_places = _mod.validate_places_tiered
        _validate_graph = _mod.validate_graph_connectivity
        _split_characters = _mod.split_characters_tiered
    else:
        raise ImportError
except Exception:
    def _validate_tiered_cast(*a, **kw): return []
    def _validate_places(*a, **kw): return []
    def _validate_graph(*a, **kw): return []
    def _split_characters(*a, **kw): return ([],[])

# M3: verbose step logging [1/7]..[7/7] with →/✓/✗ and length → retry
def _log_step(n: int, total: int, msg: str, status: str = "→") -> None:
    import sys
    print(f"[{n}/{total}] {msg} {status}", file=sys.stderr)

def _log_summary(artifacts: list[str]) -> None:
    import sys
    print(f"Summary: artifacts {', '.join(sorted(artifacts))}", file=sys.stderr)

import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path


MODEL = "openrouter/deepseek/deepseek-v4-flash-0731"
SCHEMA_VERSION = 1
MODEL_ID = MODEL.split("/", 1)[1]
VARIANT_EFFORTS = {"low": "low", "high": "high", "max": "max"}
DEFAULT_EFFORT = "high"
ROLE_SPECS = {
    "book-forge-orchestrator": ("primary", "max", 30),
    "designer": ("all", "high", 10),
    "writer": ("all", "low", 8),
    "cold-reader": ("all", "low", 5),
    "technical-editor": ("all", "high", 7),
    "reviser": ("all", "high", 8),
    "canon-auditor": ("all", "max", 8),
    "translator": ("all", "low", 7),
    "judge": ("all", "max", 6),
    "book-forge-smoke": ("primary", "low", 3),
}

# Chorus ensemble — default-on, opt-out via chorus.enabled or --no-chorus.
# Mirrors the user's global opencode.json catalog so every generated project
# exposes the same 7 models without hand-editing provider config.
CHORUS_SYNTHESIZER = "openrouter/deepseek/deepseek-v4-pro-0813"
CHORUS_DEFAULT_MODELS: list[str] = [
    "openrouter/deepseek/deepseek-v4-flash-0731",
    "openrouter/deepseek/deepseek-v4-pro-0813",
    "openrouter/z-ai/glm-5.3",
    "openrouter/qwen/qwen3.8-max",
    "openrouter/moonshotai/kimi-k3",
    "openrouter/x-ai/grok-4.6",
    "openrouter/google/gemini-3.7-flash",
    "openrouter/openai/gpt-5.6-luna",
]
# Per-model provider pin and reasoning ladder — taken from the global config.
# Each entry mirrors provider.openrouter.models[<id>] in ~/.config/opencode/opencode.json.
CHORUS_MODEL_CONFIGS: dict[str, dict[str, object]] = {
    "openrouter/deepseek/deepseek-v4-flash-0731": {
        "provider": {"order": ["deepseek", "baidu"], "only": ["deepseek", "baidu"], "allow_fallbacks": False},
        "default_effort": "high",
        "variants": {"low": "low", "high": "high", "max": "max"},
    },
    "openrouter/deepseek/deepseek-v4-pro-0813": {
        "provider": {"order": ["deepseek", "baidu"], "only": ["deepseek", "baidu"], "allow_fallbacks": False},
        "default_effort": "high",
        "variants": {"low": "low", "high": "high", "max": "max"},
    },
    "openrouter/z-ai/glm-5.3": {
        "provider": {"order": ["z-ai"], "only": ["z-ai"], "allow_fallbacks": False},
        "default_effort": "max",
        "variants": {"high": "high", "max": "max"},
    },
    "openrouter/qwen/qwen3.8-max": {
        "provider": {"order": ["alibaba"], "only": ["alibaba"], "allow_fallbacks": False},
        "default_effort": "xhigh",
        "variants": {"medium": "medium", "high": "high", "xhigh": "xhigh"},
    },
    "openrouter/moonshotai/kimi-k3": {
        "provider": {"order": ["moonshotai"], "only": ["moonshotai"], "allow_fallbacks": False},
        "default_effort": "max",
        "variants": {"high": "high", "max": "max"},
    },
    "openrouter/x-ai/grok-4.6": {
        "provider": {"order": ["xai"], "only": ["xai"], "allow_fallbacks": False},
        "default_effort": "high",
        "variants": {"low": "low", "medium": "medium", "high": "high", "xhigh": "xhigh"},
    },
    "openrouter/google/gemini-3.7-flash": {
        "provider": {"order": ["google-vertex", "google-ai-studio"], "only": ["google-vertex", "google-ai-studio"], "allow_fallbacks": False},
        "default_effort": "high",
        "variants": {"low": "low", "medium": "medium", "high": "high"},
    },
    "openrouter/openai/gpt-5.6-luna": {
        "provider": {"order": ["openai"], "only": ["openai"], "allow_fallbacks": False},
        "default_effort": "high",
        "variants": {"low": "low", "medium": "medium", "high": "high", "max": "max"},
    },
}


def _chorus_slug(model: str) -> str:
    """Stable slug for advisor agent file: openrouter/x-ai/grok-4.6 -> grok-4-6."""
    slug = model.split("/", 1)[1].replace("/", "-").replace(".", "-")
    # x-ai/grok-4.6 -> x-ai-grok-4-6 -> grok-4-6 for brevity
    if slug.startswith("x-ai-"):
        slug = slug[len("x-ai-"):]
    if slug.startswith("z-ai-"):
        slug = slug[len("z-ai-"):]
    return slug


def _chorus_advisor_name(model: str) -> str:
    return f"advisor-{_chorus_slug(model)}"


CHORUS_ADVISOR_SPECS: dict[str, tuple[str, str, int]] = {
    _chorus_advisor_name(m): ("all", str(CHORUS_MODEL_CONFIGS[m]["default_effort"]), 6)  # type: ignore[arg-type]
    for m in CHORUS_DEFAULT_MODELS
}
# Dedicated synthesizer agent (pro/max) for chorus synthesis.
CHORUS_SYNTHESIZER_AGENT = "chorus-synthesizer"
# Reverse map advisor agent name -> model id, for resolved-pin verification.
CHORUS_ADVISOR_MODELS: dict[str, str] = {_chorus_advisor_name(m): m for m in CHORUS_DEFAULT_MODELS}


def _expected_pin(role: str) -> tuple[str, str]:
    """Expected (model_id, variant) of the resolved agent for a role, mirroring _write_agents."""
    if role in ROLE_SPECS:
        return MODEL_ID, ROLE_SPECS[role][1]
    if role == CHORUS_SYNTHESIZER_AGENT:
        cfg = CHORUS_MODEL_CONFIGS.get(CHORUS_SYNTHESIZER, {})
        variant = str(cfg.get("default_effort", "max")) if isinstance(cfg, dict) else "max"
        return CHORUS_SYNTHESIZER.split("/", 1)[1], variant
    model = CHORUS_ADVISOR_MODELS.get(role)
    if model is None:
        raise BookForgeError(f"Role cannot run headlessly: {role}")
    return model.split("/", 1)[1], CHORUS_ADVISOR_SPECS[role][1]


class BookForgeError(RuntimeError):
    pass


class ContextOverflowError(BookForgeError):
    def __init__(self, estimated: int, budget: int, contributors: list[dict[str, object]]):
        self.estimated = estimated
        self.budget = budget
        self.contributors = contributors
        summary = ", ".join(f"{row['name']}={row['estimated_tokens']}" for row in contributors[:5])
        super().__init__(f"Context estimate {estimated} exceeds budget {budget} (estimated_input {estimated} > budget {budget}); contributors: {summary}")


class ProviderOutcomeUnknown(BookForgeError):
    def __init__(self, session_id: str | None, message: str):
        self.session_id = session_id
        super().__init__(message)


def _write_json(path: Path, value: object) -> None:
    _write_bytes_atomic(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())


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


def _project_root_from(attempt_dir: Path) -> Path:
    """Resolve the project root from an attempt dir, walking up to the nearest
    ancestor containing a `.book-forge` directory. Works for the run-attempt
    layout (root/.book-forge/runs/RUN-x/attempts/ATT-x) and for chorus tmp dirs
    created under the project root. Fail closed when no ancestor qualifies."""
    candidate = attempt_dir
    while True:
        if (candidate / ".book-forge").is_dir():
            return candidate
        if candidate.parent == candidate:
            raise BookForgeError(f"Cannot locate project root above {attempt_dir}")
        candidate = candidate.parent


def _project_root(project: Path | str) -> Path:
    root = Path(project).expanduser().resolve()
    if not (root / "book-forge.yaml").is_file():
        raise BookForgeError(f"Not a Book Forge universe: {root}")
    state_path = root / ".book-forge" / "state.json"
    if state_path.is_file():
        machine_state = _read_json(state_path)
        if machine_state.get("source_locked"):
            configured = _canonical_locale(str(_read_json(root / "book-forge.yaml").get("source_language", "")))
            locked = _canonical_locale(str(machine_state.get("source_language", "")))
            if configured != locked:
                raise BookForgeError(
                    f"Source language is locked to {locked} after chapter closure; restore book-forge.yaml"
                )
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


def _opencode_config(chorus_models: list[str] | None = None) -> dict[str, object]:
    """Build opencode.json with primary model + chorus catalog."""
    models = chorus_models if chorus_models is not None else CHORUS_DEFAULT_MODELS
    # Ensure primary MODEL is included even if caller filters.
    if MODEL not in models:
        models = [MODEL] + [m for m in models if m != MODEL]
    models_dict: dict[str, object] = {}
    for mid in models:
        cfg = CHORUS_MODEL_CONFIGS.get(mid)
        if cfg is None:
            # Fallback for unknown model — use primary ladder.
            cfg = {
                "provider": {"order": ["deepseek", "baidu"], "only": ["deepseek", "baidu"], "allow_fallbacks": False},
                "default_effort": DEFAULT_EFFORT,
                "variants": VARIANT_EFFORTS,
            }
        model_id = mid.split("/", 1)[1]
        variants = cfg["variants"]  # type: ignore[index]
        models_dict[model_id] = {
            "options": {
                "reasoningEffort": cfg["default_effort"],  # type: ignore[index]
                "provider": cfg["provider"],  # type: ignore[index]
            },
            "variants": {name: {"reasoningEffort": effort} for name, effort in variants.items()},  # type: ignore[union-attr]
        }
    return {
        "$schema": "https://opencode.ai/config.json",
        "model": MODEL,
        "small_model": MODEL,
        "provider": {
            "openrouter": {
                "models": models_dict,
            }
        },
    }


def _chorus_models_from_config(config: dict[str, object]) -> list[str]:
    """Read chorus.models from book-forge.yaml, fallback to defaults."""
    chorus = config.get("chorus")
    if isinstance(chorus, dict):
        models = chorus.get("models")
        if isinstance(models, list) and all(isinstance(m, str) for m in models):
            # Validate each entry looks like openrouter/...
            filtered = [m for m in models if "/" in m and m.startswith("openrouter/")]
            if filtered:
                return filtered
    return list(CHORUS_DEFAULT_MODELS)


def _chorus_enabled(config: dict[str, object]) -> bool:
    chorus = config.get("chorus")
    if isinstance(chorus, dict) and "enabled" in chorus:
        return bool(chorus["enabled"])
    return True


def _write_agents(stage: Path, chorus_models: list[str] | None = None) -> None:
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
        _write_bytes_atomic(agents / f"{name}.md", body.encode("utf-8"))
    # Chorus advisors — one per model in the catalog, plus synthesizer.
    models = chorus_models if chorus_models is not None else CHORUS_DEFAULT_MODELS
    if MODEL not in models:
        models = [MODEL] + [m for m in models if m != MODEL]
    for mid in models:
        name = _chorus_advisor_name(mid)
        cfg = CHORUS_MODEL_CONFIGS.get(mid, {})
        variant = str(cfg.get("default_effort", DEFAULT_EFFORT)) if isinstance(cfg, dict) else DEFAULT_EFFORT
        # Keep steps bounded like other editorial roles.
        body = (
            "---\n"
            f"description: Book Forge {name} chorus advisor.\n"
            f"mode: all\nmodel: {mid}\nvariant: {variant}\nsteps: 6\n"
            'permission:\n  "*": deny\n'
            "---\n\n"
            f"You are the Book Forge chorus advisor {name} ({mid}). "
            "Return only the requested chorus findings contract. "
            "You have no tools and must not assume context outside the supplied envelope.\n"
        )
        _write_bytes_atomic(agents / f"{name}.md", body.encode("utf-8"))
    # Synthesizer
    synth_cfg = CHORUS_MODEL_CONFIGS.get(CHORUS_SYNTHESIZER, {})
    synth_variant = str(synth_cfg.get("default_effort", "max")) if isinstance(synth_cfg, dict) else "max"
    _write_bytes_atomic(
        agents / f"{CHORUS_SYNTHESIZER_AGENT}.md",
        (
            "---\n"
            f"description: Book Forge {CHORUS_SYNTHESIZER_AGENT} role.\n"
            f"mode: all\nmodel: {CHORUS_SYNTHESIZER}\nvariant: {synth_variant}\nsteps: 8\n"
            'permission:\n  "*": deny\n'
            "---\n\n"
            "You are the Book Forge chorus synthesizer. Deduplicate and rank chorus findings. "
            "Return only the requested synthesis contract. "
            "You have no tools and must not assume context outside the supplied envelope.\n"
        ).encode("utf-8"),
    )
    allowed = set(ROLE_SPECS) | {_chorus_advisor_name(m) for m in models} | {CHORUS_SYNTHESIZER_AGENT}
    for stale in agents.glob("*.md"):
        if stale.stem not in allowed:
            stale.unlink()
    commands = stage / ".opencode" / "commands"
    commands.mkdir(parents=True, exist_ok=True)
    _write_bytes_atomic(
        commands / "book-forge.md",
        (
            "---\ndescription: Run a Book Forge universe workflow.\nagent: book-forge-orchestrator\n---\n\n"
            "Load the `book-forge` skill, then execute this request exactly: $ARGUMENTS\n"
        ).encode("utf-8"),
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


def _canonical_locale(value: str) -> str:
    if "/" in value or "\\" in value or ".." in value:
        raise BookForgeError(f"Unsafe language tag: {value}")
    if not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", value):
        raise BookForgeError(f"Invalid BCP 47 language tag: {value}")
    parts = value.split("-")
    language = parts[0].lower()
    if language in {"iw", "in", "ji", "sh"}:
        raise BookForgeError(f"Legacy language alias is not accepted: {language}")
    canonical = [language]
    for index, part in enumerate(parts[1:], start=1):
        if index == 1 and len(part) == 4 and part.isalpha():
            canonical.append(part.title())
        elif (len(part) == 2 and part.isalpha()) or (len(part) == 3 and part.isdigit()):
            canonical.append(part.upper())
        else:
            canonical.append(part.lower())
    return "-".join(canonical)


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
        "context": {"writer_max_input_tokens": 12000, "design_max_input_tokens": 16000, "hard_fail_on_overflow": True},
        "audit": {"input_budget": 32000},
        "chorus": {"enabled": True, "models": list(CHORUS_DEFAULT_MODELS), "synthesizer": CHORUS_SYNTHESIZER},
    }
    _write_json(stage / "book-forge.yaml", config)
    _write_json(stage / "opencode.json", _opencode_config(list(CHORUS_DEFAULT_MODELS)))
    _write_agents(stage, list(CHORUS_DEFAULT_MODELS))
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


def sync_runtime(project: Path | str) -> dict[str, object]:
    """Regenerate an existing universe's OpenCode configuration from the pins.

    `init` only validates an already-created project, so a change to the pinned
    model, variant ladder, or role matrix would otherwise reach existing
    universes only by hand. This rewrites the generated runtime surface —
    `opencode.json`, `.opencode/agents/`, `.opencode/commands/` — and touches
    neither `book-forge.yaml` nor any control-plane or canonical state.
    """
    root = _project_root(project)
    config = _read_json(root / "book-forge.yaml")
    chorus_models = _chorus_models_from_config(config)
    _write_json(root / "opencode.json", _opencode_config(chorus_models))
    _write_agents(root, chorus_models)
    return {
        "synced": True,
        "project": str(root),
        "model": MODEL,
        "default_effort": DEFAULT_EFFORT,
        "variants": VARIANT_EFFORTS,
        "roles": {name: spec[1] for name, spec in ROLE_SPECS.items()},
        "chorus_models": chorus_models,
        "chorus_synthesizer": config.get("chorus", {}).get("synthesizer", CHORUS_SYNTHESIZER) if isinstance(config.get("chorus"), dict) else CHORUS_SYNTHESIZER,
    }


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
    (directory / "design.md").write_text(
        f"---\nid: {book_id}\ncontinuity: {continuity}\n---\n\n# {title}\n\n<!-- bf:block premise -->\n",
        encoding="utf-8",
    )
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
    config = _read_json(root / "book-forge.yaml")
    chorus_models = _chorus_models_from_config(config)
    return {
        "version": version,
        "model": MODEL,
        "variants": list(VARIANT_EFFORTS),
        "json_events": "--format" in help_text,
        "session_resume": "--session" in help_text,
        "chorus_models": chorus_models,
        "chorus_enabled": _chorus_enabled(config),
        "chorus_synthesizer": config.get("chorus", {}).get("synthesizer", CHORUS_SYNTHESIZER) if isinstance(config.get("chorus"), dict) else CHORUS_SYNTHESIZER,
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
        "run": run["id"],
        "provider_accepted": False,
        "heartbeat_at": current_time,
        "lease_expires_at": current_time + lease_seconds,
    }
    plan["attempts"].append(attempt)
    capsule = {"schema": 1, "task": task, "attempt": attempt_id, "fence": fence, "request_hash": request_hash}
    attempt_dir = root / ".book-forge" / "runs" / str(run["id"]) / "attempts" / attempt_id
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


def _attempt_dir(root: Path, attempt: dict[str, object]) -> Path:
    return root / ".book-forge" / "runs" / str(attempt.get("run", "RUN-0001")) / "attempts" / str(attempt["id"])


def record_execution(
    project: Path | str,
    attempt_id: str,
    fence: int,
    *,
    output_hash: str,
    telemetry: dict[str, object] | None = None,
) -> dict[str, object]:
    root = _project_root(project)
    plan = _load_plan(root)
    attempt = _attempt(plan, attempt_id)
    _assert_fence(attempt, fence)
    if attempt["state"] != "running":
        raise BookForgeError("Attempt is not awaiting execution evidence")
    if not re.fullmatch(r"[0-9a-f]{64}", output_hash):
        raise BookForgeError("output_hash must be a lowercase SHA-256")
    receipt = {"schema": 1, "attempt": attempt_id, "task": attempt["task"], "fence": fence, "output_hash": output_hash, "outcome": "observed"}
    if telemetry:
        role = str(attempt["role"])
        expected_variant = ROLE_SPECS[role][1]
        observed_model = str(telemetry.get("model"))
        if telemetry.get("provider") != "openrouter" or observed_model not in {MODEL, MODEL.split("/", 1)[1]}:
            raise BookForgeError("Provider receipt does not match the pinned OpenRouter DeepSeek model")
        if telemetry.get("variant") != expected_variant:
            raise BookForgeError(f"Provider variant {telemetry.get('variant')} does not match {role} pin {expected_variant}")
        receipt.update(telemetry)
    receipt_path = _attempt_dir(root, attempt) / "execution-receipt.json"
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
    attempt_dir = _attempt_dir(root, attempt)
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
    receipt_path = _attempt_dir(root, attempt) / "promotion-receipt.json"
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


def _telemetry_bucket() -> dict[str, object]:
    return {
        "calls": 0,
        "estimated_input_tokens": 0,
        "provider_input_tokens": 0,
        "output_tokens": 0,
        "cost": 0.0,
        "latency_ms": 0,
    }


def _add_telemetry(bucket: dict[str, object], receipt: dict[str, object]) -> None:
    tokens = receipt.get("tokens") if isinstance(receipt.get("tokens"), dict) else {}
    bucket["calls"] = int(bucket["calls"]) + 1
    bucket["estimated_input_tokens"] = int(bucket["estimated_input_tokens"]) + int(receipt.get("estimated_input_tokens", 0) or 0)
    bucket["provider_input_tokens"] = int(bucket["provider_input_tokens"]) + int(tokens.get("input", 0) or 0)
    bucket["output_tokens"] = int(bucket["output_tokens"]) + int(tokens.get("output", 0) or 0)
    bucket["cost"] = float(bucket["cost"]) + float(receipt.get("cost", 0) or 0)
    bucket["latency_ms"] = int(bucket["latency_ms"]) + int(receipt.get("latency_ms", 0) or 0)


def _task_coordinates(task_id: str) -> dict[str, str | None]:
    book = re.search(r"BOOK-\d+", task_id)
    chapter = re.search(r"CH-\d+", task_id)
    locale = None
    if task_id.startswith("TRANSLATE-") and chapter:
        suffix = task_id.split(chapter.group(0), 1)[1].lstrip("-")
        locale = suffix or None
    return {
        "book": book.group(0) if book else None,
        "chapter": chapter.group(0) if chapter else None,
        "locale": locale,
    }


def telemetry_report(project: Path | str, *, strict: bool = False) -> dict[str, object]:
    root = _project_root(project)
    plan = _load_plan(root)
    tasks = {str(task["id"]): task for task in plan["tasks"]}
    attempts = {str(attempt["id"]): attempt for attempt in plan["attempts"]}
    receipts = []
    for path in sorted((root / ".book-forge" / "runs").glob("RUN-*/attempts/*/execution-receipt.json")):
        value = _read_json(path)
        value["_run"] = path.parts[-4]
        value["_path"] = str(path.relative_to(root))
        attempt = attempts.get(str(value.get("attempt")), {})
        value["_role"] = str(attempt.get("role") or tasks.get(str(value.get("task")), {}).get("role", "unknown"))
        receipts.append(value)

    by_role: dict[str, dict[str, object]] = {}
    by_book: dict[str, dict[str, object]] = {}
    by_locale: dict[str, dict[str, object]] = {}
    by_run: dict[str, dict[str, object]] = {}
    usage = _telemetry_bucket()
    violations = []
    calls_by_chapter: dict[tuple[str, str], int] = {}
    calls_by_translation: dict[str, int] = {}
    calls_by_design: dict[str, int] = {}
    calls_by_audit: dict[str, int] = {}
    for receipt in receipts:
        role = str(receipt["_role"])
        task_id = str(receipt.get("task", ""))
        coordinates = _task_coordinates(task_id)
        _add_telemetry(usage, receipt)
        for mapping, key in (
            (by_role, role),
            (by_book, coordinates["book"]),
            (by_locale, coordinates["locale"]),
            (by_run, str(receipt["_run"])),
        ):
            if key:
                bucket = mapping.setdefault(str(key), _telemetry_bucket())
                _add_telemetry(bucket, receipt)
        expected = ROLE_SPECS.get(role)
        if receipt.get("provider") != "openrouter" or str(receipt.get("model")) not in {MODEL, MODEL.split("/", 1)[1]}:
            violations.append({"code": "model_pin", "task": task_id, "detail": "provider or model differs from the OpenRouter pin"})
        if expected and receipt.get("variant") != expected[1]:
            violations.append({"code": "variant_pin", "task": task_id, "detail": f"expected {expected[1]}, found {receipt.get('variant')}"})
        estimated = int(receipt.get("estimated_input_tokens", 0) or 0)
        provider_input = int((receipt.get("tokens") or {}).get("input", 0) or 0)
        chunk_telemetry = receipt.get("chunk_telemetry") or []
        if chunk_telemetry:
            # Chunked design: the aggregate receipt spans several per-chunk
            # calls, so budget and overhead are validated per chunk instead.
            for chunk in chunk_telemetry:
                chunk_estimated = int(chunk.get("estimated_input_tokens", 0) or 0)
                chunk_input = int((chunk.get("tokens") or {}).get("input", 0) or 0)
                if expected and chunk_estimated > _envelope_input_budget(root, role):
                    violations.append({"code": "envelope_budget", "task": task_id, "detail": f"{chunk_estimated} > {_envelope_input_budget(root, role)}"})
                if chunk_estimated and chunk_input > int(chunk_estimated * 1.25) + 256:
                    violations.append({"code": "provider_overhead", "task": task_id, "detail": f"provider {chunk_input}, estimated {chunk_estimated}"})
        else:
            if expected and estimated > _envelope_input_budget(root, role):
                violations.append({"code": "envelope_budget", "task": task_id, "detail": f"{estimated} > {_envelope_input_budget(root, role)}"})
            if estimated and provider_input > int(estimated * 1.25) + 256:
                violations.append({"code": "provider_overhead", "task": task_id, "detail": f"provider {provider_input}, estimated {estimated}"})
        if task_id.startswith("TRANSLATE-"):
            calls_by_translation[task_id] = calls_by_translation.get(task_id, 0) + 1
        elif task_id.startswith("DESIGN-"):
            scope = coordinates["book"] or "universe"
            calls_by_design[str(scope)] = calls_by_design.get(str(scope), 0) + 1
        elif task_id.startswith("AUDIT-"):
            calls_by_audit[task_id] = calls_by_audit.get(task_id, 0) + 1
        elif coordinates["book"] and coordinates["chapter"]:
            key = (str(coordinates["book"]), str(coordinates["chapter"]))
            calls_by_chapter[key] = calls_by_chapter.get(key, 0) + 1

    accepted_attempts = [attempt for attempt in plan["attempts"] if attempt.get("provider_accepted")]
    accepted_by_task: dict[str, int] = {}
    for attempt in accepted_attempts:
        task_id = str(attempt["task"])
        accepted_by_task[task_id] = accepted_by_task.get(task_id, 0) + 1
    receipt_attempts = {str(receipt.get("attempt")) for receipt in receipts}
    unattributed = [str(attempt["id"]) for attempt in accepted_attempts if str(attempt["id"]) not in receipt_attempts and attempt.get("state") not in {"outcome_unknown", "orphaned"}]
    for attempt_id in unattributed:
        violations.append({"code": "accepted_call_unattributed", "attempt": attempt_id, "detail": "accepted call lacks a receipt or explicit ambiguous state"})

    for (book_id, chapter_id), count in sorted(calls_by_chapter.items()):
        contract_path = root / "books" / book_id / "chapters" / f"{chapter_id}.json"
        pivotal = contract_path.is_file() and bool(_read_json(contract_path).get("pivotal"))
        limit = 7 if pivotal else 5
        if count > limit:
            violations.append({"code": "chapter_call_budget", "task": f"{book_id}/{chapter_id}", "detail": f"{count} > {limit}"})
    for task_id, count in sorted(calls_by_translation.items()):
        if count > 2:
            violations.append({"code": "translation_call_budget", "task": task_id, "detail": f"{count} > 2"})
    for scope, count in sorted(calls_by_design.items()):
        if count > 3:
            violations.append({"code": "design_call_budget", "task": scope, "detail": f"{count} > 3"})
    for task_id, count in sorted(calls_by_audit.items()):
        if count > 2:
            violations.append({"code": "audit_call_budget", "task": task_id, "detail": f"{count} > 2"})

    active = [attempt for attempt in plan["attempts"] if attempt.get("state") in {"running", "promotion_pending"}]
    if len(active) > 2:
        violations.append({"code": "concurrency", "detail": f"{len(active)} active attempts > 2"})
    currentness_path = root / ".book-forge" / "currentness.json"
    currentness = _read_json(currentness_path) if currentness_path.is_file() else {"artifacts": {}}
    stale = {key: value for key, value in currentness.get("artifacts", {}).items() if not value.get("current", True)}
    override_path = root / ".book-forge" / "budget-overrides.json"
    overrides = _read_json(override_path) if override_path.is_file() else {}
    if len(stale) > 20 and not overrides.get("invalidation_fanout"):
        violations.append({"code": "invalidation_fanout", "detail": f"{len(stale)} stale artifacts > 20 without override"})

    registry = _artifact_registry(root)
    missing_edges = []
    for artifact_id, artifact in registry.get("artifacts", {}).items():
        if not (root / str(artifact["path"])).is_file():
            missing_edges.append(f"missing path: {artifact_id}")
        for dependency in artifact.get("dependencies", []):
            if "#" not in dependency and dependency not in registry["artifacts"]:
                missing_edges.append(f"missing dependency: {artifact_id} -> {dependency}")
    if missing_edges:
        violations.append({"code": "artifact_dag", "detail": "; ".join(missing_edges)})

    provider = _read_json(root / ".book-forge" / "provider.json")
    retry_count = sum(max(0, count - 1) for count in accepted_by_task.values())
    ambiguous = [str(attempt["id"]) for attempt in plan["attempts"] if attempt.get("state") == "outcome_unknown"]
    resolved_attempts = {
        str(attempt["id"]): str(attempt["resolution"])
        for attempt in plan["attempts"]
        if attempt.get("resolution") is not None
    }
    stale_causes: dict[str, list[str]] = {key: list(value.get("causes", [])) for key, value in stale.items()}
    for state_path in sorted((root / "books").glob("*/translations/*/state.yaml")):
        state = _read_json(state_path)
        for chapter, causes in state.get("stale_causes", {}).items():
            stale_causes[f"{state_path.parent.relative_to(root)}:{chapter}"] = list(causes)
    report = {
        "valid": not violations,
        "calls": {"accepted": len(accepted_attempts), "with_receipts": len(receipts), "unattributed": unattributed},
        "usage": {key: value for key, value in usage.items() if key != "calls"},
        "by_role": dict(sorted(by_role.items())),
        "by_book": dict(sorted(by_book.items())),
        "by_locale": dict(sorted(by_locale.items())),
        "by_run": dict(sorted(by_run.items())),
        "retries": retry_count,
        "ambiguous_calls": ambiguous,
        "resolutions": resolved_attempts,
        "wait": {key: provider.get(key) for key in ("retry_after", "chosen_backoff", "wait_started_at", "eligible_at") if provider.get(key) is not None},
        "stale_causes": stale_causes,
        "artifact_dag": {"registered": len(registry.get("artifacts", {})), "missing": missing_edges},
        "violations": violations,
    }
    if strict and violations:
        raise BookForgeError("Telemetry budget validation failed: " + ", ".join(sorted({str(row["code"]) for row in violations})))
    return report


def _wrapped_lines(path: Path) -> list[dict[str, object]]:
    """Lines that look like soft-wrapped prose: end mid-sentence and the
    following line continues the same sentence. Authoritative for generated
    markdown artifacts (design, canon, drafts, reader-state)."""
    try:
        text_value = path.read_text(encoding="utf-8")
    except OSError:
        return []
    lines = text_value.split("\n")
    wrapped = []
    for position, line in enumerate(lines[:-1]):
        content = line.rstrip()
        if not content or len(content) < 40:
            continue
        if content.startswith(("#", "-", ">", "|", "<!--", "{", "[", "---", "```")):
            continue
        if not re.search(r"[a-zà-ù]$", content):
            continue
        following = lines[position + 1].strip()
        if not following or following.startswith(("#", "-", ">", "|", "<!--", "{", "[", "---", "```")):
            continue
        if re.search(r"^[a-zà-ù]", following):
            wrapped.append({"line": position + 1, "text": content[:90]})
    return wrapped


def _status_wrapped_lines(root: Path) -> dict[str, list[dict[str, object]]]:
    candidates = [root / "universe" / "worldbuilding.md", root / "universe" / "style.md"]
    for block in (root / "universe" / "canon").glob("**/*.md"):
        candidates.append(block)
    for book_dir in (root / "books").glob("BOOK-*"):
        for pattern in ("design.md", "reader-state.md", "work/*/draft.md", "manuscript/chapters/*.md"):
            candidates.extend(book_dir.glob(pattern))
    return {
        str(path.relative_to(root)): wrapped
        for path in sorted(candidates)
        if (wrapped := _wrapped_lines(path))
    }


def status_project(
    project: Path | str,
    *,
    book_id: str | None = None,
    run_id: str | None = None,
    locale: str | None = None,
) -> dict[str, object]:
    root = _project_root(project)
    plan = _load_plan(root)
    if book_id and book_id not in {str(book["id"]) for book in list_books(root)}:
        raise BookForgeError(f"Unknown book: {book_id}")
    selected_tasks = plan["tasks"]
    if book_id:
        path_marker = f"books/{book_id}/"
        selected_tasks = [
            task
            for task in selected_tasks
            if book_id in str(task["id"])
            or any(path_marker in str(value) for value in [*task.get("inputs", []), *task.get("outputs", [])])
        ]
    counts: dict[str, int] = {}
    for task in selected_tasks:
        counts[str(task["state"])] = counts.get(str(task["state"]), 0) + 1
    transaction_states: dict[str, int] = {}
    transactions = root / ".book-forge" / "transactions"
    if transactions.exists():
        for path in transactions.glob("TXN-*/journal.json"):
            state = str(_read_json(path)["state"])
            transaction_states[state] = transaction_states.get(state, 0) + 1
    control = _control(root)
    selected_run_id = run_id or control.get("active_run")
    run = None
    if selected_run_id:
        run_path = root / ".book-forge" / "runs" / str(selected_run_id) / "run.json"
        if not run_path.is_file():
            raise BookForgeError(f"Unknown run: {selected_run_id}")
        run = _read_json(run_path)
    telemetry = telemetry_report(root)
    scope: dict[str, object] = {}
    if book_id:
        scope["book"] = book_id
        scope["book_telemetry"] = telemetry["by_book"].get(book_id, _telemetry_bucket())
    if run_id:
        scope["run"] = run_id
        scope["run_telemetry"] = telemetry["by_run"].get(run_id, _telemetry_bucket())
    if locale:
        canonical = _canonical_locale(locale)
        locale_rows = []
        candidate_books = [book_id] if book_id else [str(book["id"]) for book in list_books(root)]
        for candidate in candidate_books:
            state_path = root / "books" / str(candidate) / "translations" / canonical / "state.yaml"
            if state_path.is_file():
                locale_rows.append({"book": candidate, "state": _read_json(state_path)})
        if not locale_rows:
            raise BookForgeError(f"No translation workspace for locale {canonical} in the selected scope")
        scope["locale"] = canonical
        scope["locales"] = locale_rows
        scope["locale_telemetry"] = telemetry["by_locale"].get(canonical, _telemetry_bucket())
    result = {
        "tasks": counts,
        "transactions": transaction_states,
        "plan_hash": control["plan_hash"],
        "run": run,
        "telemetry": telemetry,
    }
    wrapped = _status_wrapped_lines(root)
    if wrapped:
        result["wrapped_lines"] = wrapped
    if scope:
        result["scope"] = scope
    return result


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
    intent = _attempt_dir(root, attempt) / "intent.json"
    value = _read_json(intent)
    value["accepted"] = True
    value["session_id"] = session_id
    _write_json(intent, value)
    return attempt


def pause_run(project: Path | str, *, run_id: str | None = None, emergency: bool = False) -> dict[str, object]:
    root = _project_root(project)
    control = _control(root)
    if not control.get("active_run"):
        raise BookForgeError("No active run")
    if run_id and run_id != control["active_run"]:
        raise BookForgeError(f"Requested run {run_id} is not the active run {control['active_run']}")
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


def _last_validation_failure(plan: dict[str, object], task_id: str) -> dict[str, object] | None:
    rows = [row for row in plan["attempts"] if row.get("task") == task_id]
    if not rows:
        return None
    # Most recent first: an active validation failure, or an orphaned retry
    # that still carries the recorded failure (the capsule reuses it as
    # repair context once the task is pending again).
    for row in reversed(rows):
        if row.get("state") == "validation_failed":
            return row
        if row.get("state") == "orphaned" and row.get("resolution") == "retry" and row.get("failure"):
            return row
    return None


def resume_run(
    project: Path | str,
    *,
    run_id: str | None = None,
    resolutions: dict[str, str] | None = None,
    blocked_resolutions: dict[str, str] | None = None,
) -> dict[str, object]:
    root = _project_root(project)
    control = _control(root)
    if not control.get("active_run"):
        raise BookForgeError("No active run")
    if run_id and run_id != control["active_run"]:
        raise BookForgeError(f"Requested run {run_id} is not the active run {control['active_run']}")
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
    retryable_blocked: dict[str, dict[str, object]] = {}
    for task in plan["tasks"]:
        if task["state"] != "blocked":
            continue
        failure = _last_validation_failure(plan, str(task["id"]))
        if failure is not None:
            retryable_blocked[str(task["id"])] = failure
            continue
        # A failed_length task is blocked but retryable: its last attempt is
        # marked failed_length, so surface that attempt for the explicit retry.
        attempts = [row for row in plan["attempts"] if row.get("task") == task["id"]]
        for attempt in reversed(attempts):
            if attempt["state"] == "failed_length":
                retryable_blocked[str(task["id"])] = attempt
                break
    blocked_choices = blocked_resolutions or {}
    if set(retryable_blocked) != set(blocked_choices):
        raise BookForgeError("Every validation-blocked task requires an explicit retry resolution")
    for task_id, attempt in retryable_blocked.items():
        choice = blocked_choices[task_id]
        if choice != "retry":
            raise BookForgeError(f"Invalid blocked resolution for {task_id}: {choice} (only retry is supported)")
        attempt["state"] = "orphaned"
        attempt["resolution"] = "retry"
        task = next(row for row in plan["tasks"] if row["id"] == task_id)
        task["state"] = "pending"
        task.pop("attempt", None)
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
    path = _attempt_dir(root, attempt) / "orphaned-result.json"
    _write_json(path, {"schema": 1, "attempt": attempt_id, "output_hash": output_hash, "state": "orphaned"})
    _save_plan(root, plan)
    return attempt


def cleanup_attempt(project: Path | str, attempt_id: str) -> None:
    root = _project_root(project)
    plan = _load_plan(root)
    attempt = _attempt(plan, attempt_id)
    if attempt["state"] in {"running", "validating", "promotion_pending", "outcome_unknown", "orphaned"}:
        raise BookForgeError(f"Refusing cleanup for {attempt['state']} attempt")
    path = _attempt_dir(root, attempt) / "staged"
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
    "designer": (16000, 12288),
    "writer": (12000, 6000),
    "cold-reader": (8000, 2500),
    "technical-editor": (10000, 3000),
    "reviser": (14000, 6000),
    "canon-auditor": (32000, 3500),
    "translator": (14000, 6000),
    "judge": (10000, 2000),
}
# Chorus advisors reuse designer/auditor budgets (advisory, same context).
for _adv in list(CHORUS_ADVISOR_SPECS):
    ROLE_BUDGETS[_adv] = (16000, 3000)
ROLE_BUDGETS[CHORUS_SYNTHESIZER_AGENT] = (16000, 4000)


def _envelope_input_budget(root: Path, role: str) -> int:
    """Per-role envelope input budget; project override wins over ROLE_BUDGETS.

    `book-forge.yaml` may raise the design envelope ceiling under
    `context.design_max_input_tokens` (applies to the designer and to chorus
    advisors, which share the same context contract) and the audit envelope
    ceiling under `audit.input_budget` (applies to the canon-auditor). Defaults
    to the fixed role budget. Fail closed on a malformed override value."""
    default_input, _ = ROLE_BUDGETS[role]
    config_path = root / "book-forge.yaml"
    if config_path.is_file():
        config = _read_json(config_path)
        ctx = config.get("context")
        if isinstance(ctx, dict) and (role == "designer" or role.startswith("advisor-")):
            knob = ctx.get("design_max_input_tokens")
            if knob is not None:
                try:
                    return int(knob)
                except (TypeError, ValueError):
                    raise BookForgeError(f"context.design_max_input_tokens must be an integer, got {knob!r}")
        audit_cfg = config.get("audit")
        if isinstance(audit_cfg, dict) and role == "canon-auditor":
            knob = audit_cfg.get("input_budget")
            if knob is not None:
                try:
                    return int(knob)
                except (TypeError, ValueError):
                    raise BookForgeError(f"audit.input_budget must be an integer, got {knob!r}")
    return default_input


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
    if input_budget is None:
        budget = _envelope_input_budget(root, role)
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


def schedule_universe_design(
    project: Path | str, *, guided_answers: dict[str, object] | None = None
) -> list[dict[str, object]]:
    root = _project_root(project)
    brief_path = root / "universe" / "design-brief.json"
    if not brief_path.exists():
        _write_json(
            brief_path,
            {
                "schema": 1,
                "mode": "guided" if guided_answers else "autonomous",
                "answers": guided_answers or {},
                "scope": ["kernel", "chronology", "places", "factions", "characters", "themes", "style"],
            },
        )
    plan = _load_plan(root)
    existing = {str(task["id"]): task for task in plan["tasks"]}
    if "DESIGN-UNI-0001" not in existing:
        add_task(root, "DESIGN-UNI-0001", "designer", priority=10, inputs=["universe/design-brief.json"])
    plan = _load_plan(root)
    existing = {str(task["id"]): task for task in plan["tasks"]}
    if "AUDIT-UNI-0001" not in existing:
        add_task(root, "AUDIT-UNI-0001", "canon-auditor", deps=["DESIGN-UNI-0001"], priority=20)
    plan = _load_plan(root)
    return [next(task for task in plan["tasks"] if task["id"] == task_id) for task_id in ("DESIGN-UNI-0001", "AUDIT-UNI-0001")]


def _validate_id_rows(rows: object, prefix: str, name: str) -> list[dict[str, object]]:
    if not isinstance(rows, list):
        raise BookForgeError(f"Universe proposal field {name} must be a list")
    seen: set[str] = set()
    result = []
    for row in rows:
        if not isinstance(row, dict) or not re.fullmatch(fr"{prefix}-\d{{4}}", str(row.get("id", ""))):
            raise BookForgeError(f"Invalid stable ID in {name}")
        if row["id"] in seen:
            raise BookForgeError(f"Duplicate stable ID in {name}: {row['id']}")
        seen.add(str(row["id"]))
        result.append(row)
    return result


def validate_universe_design(project: Path | str, proposal: dict[str, object]) -> list[dict[str, object]]:
    root = _project_root(project)
    findings: list[dict[str, object]] = []
    laws = _validate_id_rows(proposal.get("kernel"), "LAW", "kernel")
    eras = _validate_id_rows(proposal.get("eras"), "ERA", "eras")
    events = _validate_id_rows(proposal.get("events"), "EVT", "events")
    _validate_id_rows(proposal.get("places"), "PLC", "places")
    _validate_id_rows(proposal.get("factions"), "FAC", "factions")
    _validate_id_rows(proposal.get("characters"), "CHR", "characters")
    if not laws:
        findings.append({"code": "kernel.empty", "severity": "blocking"})
    era_ids = {str(row["id"]) for row in eras}
    event_slots: set[tuple[str, int]] = set()
    for event in events:
        era = str(event.get("era", ""))
        if era not in era_ids:
            findings.append({"code": "event.unknown-era", "severity": "blocking", "event": event["id"], "era": era})
        slot = (era, int(event.get("order", 0)))
        if slot in event_slots:
            findings.append({"code": "event.order-conflict", "severity": "blocking", "event": event["id"]})
        event_slots.add(slot)
    continuity_ids = {str(row["id"]) for row in _continuities(root)["continuities"]}
    material = proposal.get("continuity_material", {})
    if not isinstance(material, dict) or not set(material) <= continuity_ids:
        findings.append({"code": "continuity.unknown", "severity": "blocking"})
    for category in ("kernel", "places", "factions", "characters"):
        for row in proposal.get(category, []):
            if not _row_summary(row):
                findings.append({"code": "canon-row.content-missing", "severity": "blocking", "row": row.get("id"), "category": category})
    if not isinstance(proposal.get("style"), dict) or not proposal.get("themes"):
        findings.append({"code": "creative-contract.incomplete", "severity": "blocking"})
    # M4: anti-laziness tiered checks (only when proposal has tiered structure or for 80k validation)
    try:
        findings.extend(_validate_tiered_cast(proposal, target_words=80000))
        findings.extend(_validate_places(proposal))
        findings.extend(_validate_graph(proposal))
    except Exception as exc:
        findings.append({"code": "tier.validation-error", "severity": "blocking", "detail": str(exc)})
    return findings


def _row_summary(row: dict[str, object]) -> str:
    explicit = row.get("summary")
    if isinstance(explicit, str) and explicit.strip():
        return explicit
    parts = [row.get(key) for key in ("fact", "description", "invariant", "statement", "law")]
    return " ".join(part.strip() for part in parts if isinstance(part, str) and part.strip())


def _normalize_universe_proposal(proposal: dict[str, object]) -> dict[str, object]:
    for category in ("kernel", "eras", "events", "places", "factions", "characters"):
        value = proposal.get(category)
        if not isinstance(value, dict):
            continue
        rows = []
        for key, row in value.items():
            if isinstance(row, dict):
                merged = dict(row)
                merged["id"] = str(key)
                if "name" not in merged and isinstance(merged.get("label"), str):
                    merged["name"] = merged["label"]
                rows.append(merged)
            elif isinstance(row, str):
                rows.append({"id": str(key), "summary": row})
            else:
                rows.append({"id": str(key)})
        proposal[category] = rows
    return proposal


CANON_DETAIL_BLOCKS = ("voice", "appearance", "past", "sensory", "want", "need", "flaw", "wound", "arc", "secret")

# M1: chunking guard — 41KB truncation fix: each design chunk must stay <15KB
DESIGN_CHUNK_MAX_BYTES = 15 * 1024
DESIGN_CHUNKS_UNIVERSE = ("kernel", "eras", "events", "places", "factions", "characters")
# Per-chunk output budget (8192-12288)
DESIGN_CHUNK_MAX_TOKENS = 8192


def chunk_bytes(obj: object) -> int:
    """Byte length of JSON-serialized chunk (deterministic)."""
    import json
    return len(json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode())


def assert_chunk_size(chunk: object, *, label: str = "chunk") -> None:
    size = chunk_bytes(chunk)
    if size > DESIGN_CHUNK_MAX_BYTES:
        raise BookForgeError(f"{label} exceeds {DESIGN_CHUNK_MAX_BYTES} bytes: {size}")


def split_proposal_into_chunks(proposal: dict[str, object]) -> list[dict[str, object]]:
    """Split universe proposal into per-category chunks each <15KB."""
    chunks: list[dict[str, object]] = []
    for key in DESIGN_CHUNKS_UNIVERSE:
        if key not in proposal:
            continue
        # M4: split characters into 2 sub-chunks (L1+L2 and L3+L4) to stay <15KB
        if key == "characters":
            try:
                c1, c2 = _split_characters(proposal[key])
                for idx, sub in enumerate([c1, c2], 1):
                    if not sub:
                        continue
                    chunk = {key: sub, "_subchunk": idx}
                    # strip _subchunk before size check? keep for trace but not counted
                    check_chunk = {key: sub}
                    assert_chunk_size(check_chunk, label=f"{key}-part{idx}")
                    chunks.append(chunk)
                continue
            except Exception:
                pass
        chunk = {key: proposal[key]}
        assert_chunk_size(chunk, label=key)
        chunks.append(chunk)
    # themes/style/continuity_material go with last chunk or own
    tail = {k: proposal[k] for k in ("themes", "style", "continuity_material", "book_local", "unresolved_questions") if k in proposal}
    if tail:
        assert_chunk_size(tail, label="tail")
        chunks.append(tail)
    return chunks


def _is_length_finish(result: dict[str, object]) -> bool:
    return str(result.get("finish", "")).lower() == "length"


def _run_with_length_retry(root, task_id: str, role: str, envelope: dict[str, object], runner, *, max_retries: int = 2):
    """Run role with retry on finish_reason==length. On exhaustion mark failed_length."""
    last_result = None
    last_claim = None
    for attempt in range(max_retries + 1):
        claim, result = _run_design_role(root, task_id, role, envelope, runner)
        last_claim, last_result = claim, result
        if not _is_length_finish(result):
            return claim, result
        if attempt < max_retries:
            # length → retry: orphan prior attempt so next claim can proceed
            plan = _load_plan(root)
            att = _attempt(plan, str(claim["attempt"]))
            att["state"] = "failed_length"
            att["failure"] = f"finish_reason==length attempt {attempt+1}"
            # keep attempt as failed_length but free task for retry
            task = next(row for row in plan["tasks"] if row["id"] == task_id)
            task["state"] = "pending"
            task.pop("attempt", None)
            _save_plan(root, plan)
            render_plan(root)
            print(f"[{role}] length truncation on attempt {attempt+1}/{max_retries+1} -> retry", file=__import__("sys").stderr)
            continue
        # exhausted: mark failed_length not outcome_unknown
        plan = _load_plan(root)
        att = _attempt(plan, str(claim["attempt"]))
        att["state"] = "failed_length"
        att["failure"] = "finish_reason==length after retries"
        task = next(row for row in plan["tasks"] if row["id"] == task_id)
        task["state"] = "blocked"
        task.pop("attempt", None)
        _save_plan(root, plan)
        render_plan(root)
        control = _control(root)
        if control.get("active_run"):
            run_path = _run_path(root, str(control["active_run"]))
            run = _read_json(run_path)
            run["state"] = "blocked"
            _write_json(run_path, run)
        raise BookForgeError(f"Design {task_id} failed_length after {max_retries+1} attempts")
    return last_claim, last_result  # type: ignore[return-value]


# M1 per-chunk design calls: the helper invokes the designer once per category
# (each call well inside the per-response output budget), then merges.
UNIVERSE_DESIGN_CHUNKS: list[dict[str, object]] = [
    {"category": "kernel"},
    {"category": "eras"},
    {"category": "events"},
    {"category": "places"},
    {"category": "factions"},
    {"category": "characters", "part": "L1+L2"},
    {"category": "characters", "part": "L3+L4"},
    {"category": "tail", "keys": ["themes", "style", "continuity_material", "book_local", "unresolved_questions"]},
]


def _chunk_slug(chunk: dict[str, object]) -> str:
    part = str(chunk.get("part", ""))
    return f"{chunk['category']}{'-' + part.lower() if part else ''}"


def _dedupe_rows(rows: list[object]) -> list[object]:
    """Stable-id dedupe, last occurrence wins; non-id rows pass through in order."""
    out: list[object] = []
    index: dict[str, int] = {}
    for row in rows:
        if isinstance(row, dict) and row.get("id"):
            key = str(row["id"])
            if key in index:
                out[index[key]] = row
            else:
                index[key] = len(out)
                out.append(row)
        else:
            out.append(row)
    return out


def _merge_design_chunks(merged: dict[str, object], parsed: dict[str, object]) -> dict[str, object]:
    """Merge one parsed chunk into the proposal. List keys concatenate with
    stable-id dedupe (last wins); dict keys shallow-update; scalars last wins.
    A "tail" object ({themes, style, continuity_material, ...}) is unwrapped
    to the top level."""
    for key, value in parsed.items():
        if key == "tail" and isinstance(value, dict):
            for inner_key, inner_value in value.items():
                merged = _merge_design_chunks(merged, {inner_key: inner_value})
            continue
        if isinstance(value, list):
            if isinstance(merged.get(key), list):
                merged[key] = _dedupe_rows(merged[key] + value)
            else:
                merged[key] = value
        elif isinstance(value, dict):
            if isinstance(merged.get(key), dict):
                merged[key] = {**merged[key], **value}
            else:
                merged[key] = value
        else:
            merged[key] = value
    return merged


def _block_task_failed_length(root: Path, task_id: str, claim: dict[str, object]) -> None:
    plan = _load_plan(root)
    att = _attempt(plan, str(claim["attempt"]))
    att["state"] = "failed_length"
    att["failure"] = "finish_reason==length after retries"
    task = next(row for row in plan["tasks"] if row["id"] == task_id)
    task["state"] = "blocked"
    task.pop("attempt", None)
    _save_plan(root, plan)
    render_plan(root)
    control = _control(root)
    if control.get("active_run"):
        run_path = _run_path(root, str(control["active_run"]))
        run = _read_json(run_path)
        run["state"] = "blocked"
        _write_json(run_path, run)


def _run_design_chunked(
    root: Path,
    task_id: str,
    base_capsule: dict[str, object],
    imports: list[str],
    runner,
    *,
    chunks: list[dict[str, object]] | None = None,
    max_output_tokens: int = 8192,
) -> tuple[dict[str, object], dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    """Run the designer once per category chunk (M1), then merge the responses.

    One DAG claim covers the whole chunked run; per-chunk length truncation is
    retried locally up to 2 times, and exhaustion blocks the task as
    failed_length (never outcome_unknown). Returns (claim, merged_proposal,
    results, chunk_telemetry) where chunk_telemetry holds one per-call record
    {estimated_input_tokens, tokens} for budget validation.
    """
    chunk_specs = chunks if chunks is not None else UNIVERSE_DESIGN_CHUNKS
    request_hash = _sha256_bytes(
        _json_bytes({"task": task_id, "chunks": [_chunk_slug(c) for c in chunk_specs]})
    )
    claim = claim_task(root, task_id, request_hash=request_hash)
    attempt_dir = Path(claim["capsule"]).parent
    merged: dict[str, object] = {}
    results: list[dict[str, object]] = []
    chunk_telemetry: list[dict[str, object]] = []
    for chunk in chunk_specs:
        capsule = dict(base_capsule)
        capsule["chunk"] = chunk
        envelope = build_envelope(
            root,
            role="designer",
            task_capsule=capsule,
            imports=imports,
            state={},
            tools=[],
            max_output_tokens=max_output_tokens,
        )
        _write_bytes_atomic(attempt_dir / f"envelope-{_chunk_slug(chunk)}.json", envelope["bytes"])
        result = None
        for attempt in range(3):
            result = runner("designer", envelope, attempt_dir)
            results.append(result)
            mark_provider_accepted(root, str(claim["attempt"]), str(result["session_id"]))
            if result["finish"] != "length":
                break
            _write_bytes_atomic(
                attempt_dir / f"raw-{_chunk_slug(chunk)}-attempt{attempt + 1}.txt",
                str(result.get("text", "")).encode(),
            )
        if result is None or _is_length_finish(result):
            _block_task_failed_length(root, task_id, claim)
            raise BookForgeError(f"Design {task_id} failed_length on chunk {_chunk_slug(chunk)}")
        _write_bytes_atomic(attempt_dir / f"raw-{_chunk_slug(chunk)}.txt", str(result.get("text", "")).encode())
        chunk_telemetry.append(
            {
                "chunk": _chunk_slug(chunk),
                "estimated_input_tokens": envelope["estimated_input_tokens"],
                "tokens": result.get("tokens") or {},
            }
        )
        try:
            parsed = _parse_chunked_contract(str(result.get("text", "")))
        except BookForgeError as exc:
            _set_attempt_failure(root, str(claim["attempt"]), block=True, reason=str(exc))
            raise
        merged = _merge_design_chunks(merged, parsed)
    return claim, merged, results, chunk_telemetry


def _synthetic_chunk_result(results: list[dict[str, object]], merged: dict[str, object]) -> dict[str, object]:
    """Aggregate per-chunk results into one result record for completion telemetry."""
    tokens = {"input": 0, "output": 0}
    cost = 0.0
    latency = 0
    session_id = None
    for row in results:
        row_tokens = row.get("tokens") or {}
        for key in ("input", "output"):
            if isinstance(row_tokens.get(key), (int, float)):
                tokens[key] = int(tokens[key]) + int(row_tokens[key])
        cost += float(row.get("cost") or 0)
        latency += int(row.get("latency_ms") or 0)
        session_id = row.get("session_id") or session_id
    return {
        "text": json.dumps(merged, ensure_ascii=False, sort_keys=True),
        "provider": "openrouter",
        "model": "deepseek/deepseek-v4-flash-0731",
        "variant": "high",
        "session_id": session_id,
        "tokens": tokens,
        "cost": cost,
        "latency_ms": latency,
        "finish": "stop",
    }


def _canon_markdown(row: dict[str, object], *, continuity: str | None = None) -> str:
    metadata = f"---\nid: {row['id']}\n"
    if continuity:
        metadata += f"continuity: {continuity}\n"
    metadata += "---\n\n"
    name = row.get("name", row["id"])
    body = f"# {name}\n\n<!-- bf:block summary -->\n{_row_summary(row)}\n"
    for block in CANON_DETAIL_BLOCKS:
        value = row.get(block)
        if isinstance(value, str) and value.strip():
            body += f"\n<!-- bf:block {block} -->\n{value.strip()}\n"
    return metadata + body


def _set_task_outputs(root: Path, task_id: str, outputs: list[str]) -> None:
    plan = _load_plan(root)
    task = next((row for row in plan["tasks"] if row["id"] == task_id), None)
    if not task or task["state"] != "pending":
        raise BookForgeError(f"Design task cannot accept outputs while {task['state'] if task else 'missing'}")
    task["outputs"] = sorted(outputs)
    _save_plan(root, plan)
    render_plan(root)


def _execute_materialized_task(root: Path, task_id: str, outputs: dict[str, str | bytes]) -> None:
    _set_task_outputs(root, task_id, list(outputs))
    request_hash = _sha256_bytes(_json_bytes({"task": task_id, "outputs": sorted(outputs)}))
    claim = claim_task(root, task_id, request_hash=request_hash)
    manifest = stage_outputs(root, claim["attempt"], outputs)
    output_hash = _sha256_bytes(_json_bytes(manifest))
    record_execution(root, claim["attempt"], claim["fence"], output_hash=output_hash)
    promote_task(root, claim["attempt"], claim["fence"])


def _complete_model_task(
    root: Path,
    task_id: str,
    claim: dict[str, object],
    outputs: dict[str, str | bytes],
    result: dict[str, object],
    envelope: dict[str, object],
) -> dict[str, object]:
    plan = _load_plan(root)
    task = next((row for row in plan["tasks"] if row["id"] == task_id), None)
    if not task or task.get("state") != "running" or task.get("attempt") != claim["attempt"]:
        raise BookForgeError(f"Model task is not owned by its active claim: {task_id}")
    task["outputs"] = sorted(outputs)
    _save_plan(root, plan)
    render_plan(root)
    manifest = stage_outputs(root, str(claim["attempt"]), outputs)
    receipt = record_execution(
        root,
        str(claim["attempt"]),
        int(claim["fence"]),
        output_hash=_sha256_bytes(_json_bytes(manifest)),
        telemetry=_provider_telemetry(result, envelope),
    )
    promote_task(root, str(claim["attempt"]), int(claim["fence"]))
    return receipt


def _universe_design_outputs(proposal: dict[str, object]) -> dict[str, str | bytes]:
    outputs: dict[str, str | bytes] = {
        "universe/design.json": _json_bytes({"schema": 1, **proposal}),
        "universe/timeline/eras.yaml": _json_bytes({"schema": 1, "eras": proposal["eras"]}),
        "universe/timeline/events.yaml": _json_bytes({"schema": 1, "events": proposal["events"]}),
        "universe/style.md": (
            "---\nid: STYLE-0001\n---\n\n# Style\n\n<!-- bf:block prose -->\n"
            + json.dumps(proposal["style"], ensure_ascii=False, sort_keys=True)
            + "\n"
        ),
    }
    law_imports = "\n".join(f"<!-- bf:import {row['id']}#summary -->" for row in proposal["kernel"])
    outputs["universe/kernel.md"] = (
        "---\nid: UNI-0001\nkind: universe-kernel\n---\n\n## Kernel\n<!-- bf:block kernel -->\n"
        f"{law_imports}\nThe following invariants are inherited by every continuity.\n"
    )
    for category, directory in (("kernel", "topics"), ("places", "places"), ("factions", "factions"), ("characters", "characters")):
        for row in proposal[category]:
            continuity = None if category == "kernel" else "CNT-0001"
            outputs[f"universe/canon/{directory}/{row['id']}.md"] = _canon_markdown(row, continuity=continuity)
    return outputs


def apply_universe_design(project: Path | str, proposal: dict[str, object]) -> dict[str, object]:
    root = _project_root(project)
    findings = validate_universe_design(root, proposal)
    blocking = [finding for finding in findings if finding["severity"] == "blocking"]
    if blocking:
        raise BookForgeError(f"Universe design has blocking findings: {json.dumps(blocking, sort_keys=True)}")
    schedule_universe_design(root)
    outputs = _universe_design_outputs(proposal)
    _execute_materialized_task(root, "DESIGN-UNI-0001", outputs)
    audit = {"schema": 1, "state": "design_clean", "blocking": [], "checked": ["world-rules", "chronology", "identity", "scope", "imports"]}
    _execute_materialized_task(root, "AUDIT-UNI-0001", {"universe/design-audit.json": _json_bytes(audit)})
    rebuild_indexes(root)
    return audit


def schedule_book_design(project: Path | str, book_id: str) -> list[dict[str, object]]:
    root = _project_root(project)
    books = {str(book["id"]): book for book in list_books(root)}
    if book_id not in books:
        raise BookForgeError(f"Unknown book: {book_id}")
    design_id = f"DESIGN-{book_id}"
    audit_id = f"AUDIT-{book_id}"
    plan = _load_plan(root)
    existing = {str(task["id"]) for task in plan["tasks"]}
    if design_id not in existing:
        add_task(
            root,
            design_id,
            "designer",
            priority=30,
            book_order=int(books[book_id].get("order", 0)),
            inputs=[f"books/{book_id}/book.yaml", "universe/relations.yaml"],
        )
    plan = _load_plan(root)
    existing = {str(task["id"]) for task in plan["tasks"]}
    if audit_id not in existing:
        add_task(root, audit_id, "canon-auditor", deps=[design_id], priority=40, book_order=int(books[book_id].get("order", 0)))
    plan = _load_plan(root)
    return [next(task for task in plan["tasks"] if task["id"] == task_id) for task_id in (design_id, audit_id)]


def _write_book_brief(project: Path | str, book_id: str, brief: str) -> dict[str, object]:
    root = _project_root(project)
    books = {str(book["id"]): book for book in list_books(root)}
    if book_id not in books:
        raise BookForgeError(f"Unknown book: {book_id}")
    value = json.loads(brief)
    if not isinstance(value, dict):
        raise BookForgeError("book brief must be a JSON object")
    allowed = {"schema", "premise", "characters", "plot", "tone", "length_notes"}
    if not allowed & set(value):
        raise BookForgeError(f"book brief must contain at least one of: {sorted(allowed)}")
    value.setdefault("schema", 1)
    path = root / "books" / book_id / "book-brief.json"
    _write_json(path, value)
    return value


def _book_brief(root: Path, book_id: str) -> dict[str, object]:
    path = root / "books" / book_id / "book-brief.json"
    if not path.is_file():
        raise BookForgeError(
            f"No author brief for {book_id}: create books/{book_id}/book-brief.json "
            "(or pass --brief '<json>') with premise, characters, plot, tone, "
            "length_notes. design book will not invent a story."
        )
    return _read_json(path)


def _book_canon_context(root: Path, book_id: str, index: dict[str, object]) -> list[dict[str, object]]:
    blocks = index.get("blocks", {})
    wanted = ["UNI-0001#kernel"]
    for block_id in blocks:
        owner = block_id.split("#", 1)[0]
        if owner.startswith(("LAW-", "PLC-", "FAC-", "CHR-", "STYLE-")) and block_id.endswith("#summary"):
            wanted.append(block_id)
    wanted = sorted(set(wanted))
    closed = _close_imports(index, wanted)
    worldbuilding = root / "universe" / "worldbuilding.md"
    context = []
    for block_id in closed:
        context.append({"id": block_id, "hash": index["blocks"][block_id]["hash"], "content": _block_content(root, block_id, index)})
    if worldbuilding.is_file():
        context.append({"id": "worldbuilding.md", "hash": _file_hash(worldbuilding), "content": worldbuilding.read_text(encoding="utf-8")})
    return context


def _book_obligations(root: Path, book_id: str) -> tuple[dict[str, dict[str, object]], list[str]]:
    relations = _read_json(root / "universe" / "relations.yaml").get("relations", [])
    obligations = {}
    imports = []
    for relation in relations:
        if book_id not in relation.get("endpoints", []):
            continue
        for obligation in relation.get("obligations", []):
            obligations[str(obligation["id"])] = obligation
        imports.extend(str(item["block"]) for item in relation.get("imports", []))
    return obligations, sorted(set(imports))


def validate_book_design(project: Path | str, book_id: str, proposal: dict[str, object]) -> list[dict[str, object]]:
    root = _project_root(project)
    if book_id not in {str(book["id"]) for book in list_books(root)}:
        raise BookForgeError(f"Unknown book: {book_id}")
    findings: list[dict[str, object]] = []
    chapters = proposal.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        return [{"code": "chapters.empty", "severity": "blocking"}]
    ids = [str(chapter.get("id", "")) for chapter in chapters]
    if len(set(ids)) != len(ids) or any(not re.fullmatch(r"CH-\d{4}", value) for value in ids):
        findings.append({"code": "chapter.id", "severity": "blocking"})
    orders = [chapter.get("order") for chapter in chapters]
    if orders != list(range(1, len(chapters) + 1)):
        findings.append({"code": "chapter.order", "severity": "blocking"})
    for chapter in chapters:
        if not chapter.get("pov") or not chapter.get("beats"):
            findings.append({"code": "chapter.contract-incomplete", "severity": "blocking", "chapter": chapter.get("id")})
        if not isinstance(chapter.get("target_words"), int) or not 500 <= int(chapter.get("target_words", 0)) <= 10000:
            findings.append({"code": "chapter.target-words", "severity": "blocking", "chapter": chapter.get("id")})
    required, _ = _book_obligations(root, book_id)
    assigned: dict[str, list[str]] = {obligation_id: [] for obligation_id in required}
    for chapter in chapters:
        for obligation_id in chapter.get("obligations", []):
            if obligation_id not in required:
                findings.append({"code": "obligation.unknown", "severity": "blocking", "obligation": obligation_id})
            else:
                assigned[obligation_id].append(str(chapter.get("id")))
    for obligation_id, targets in assigned.items():
        if len(targets) != 1:
            findings.append({"code": "obligation.target-count", "severity": "blocking", "obligation": obligation_id, "targets": targets})
    if not proposal.get("premise") or len(proposal.get("arc", [])) < 3 or not proposal.get("entry_state") or not proposal.get("exit_boundary"):
        findings.append({"code": "book.arc-incomplete", "severity": "blocking"})
    return findings


def _book_design_outputs(root: Path, book_id: str, proposal: dict[str, object]) -> dict[str, str | bytes]:
    obligations, relation_imports = _book_obligations(root, book_id)
    chapters = sorted(proposal["chapters"], key=lambda row: int(row["order"]))
    outputs: dict[str, str | bytes] = {
        f"books/{book_id}/design.md": (
            f"---\nid: {book_id}\ncontinuity: {next(book['continuity'] for book in list_books(root) if book['id'] == book_id)}\n---\n\n"
            f"# Premise\n\n<!-- bf:block premise -->\n{proposal['premise']}\n\n"
            f"## Arc\n\n{json.dumps(proposal['arc'], ensure_ascii=False)}\n"
        ),
        f"books/{book_id}/outline.yaml": _json_bytes({"schema": 1, "chapters": chapters}),
        f"books/{book_id}/continuity.yaml": _json_bytes(
            {
                "schema": 1,
                "imports": relation_imports,
                "obligations": [
                    {**obligation, "target": next(chapter["id"] for chapter in chapters if obligation_id in chapter.get("obligations", []))}
                    for obligation_id, obligation in sorted(obligations.items())
                ],
            }
        ),
        f"books/{book_id}/reader-state.md": (
            "# Reader State\n\n"
            f"Entry: {json.dumps(proposal['entry_state'], ensure_ascii=False, sort_keys=True)}\n\n"
            f"Intended exit: {json.dumps(proposal['exit_boundary'], ensure_ascii=False, sort_keys=True)}\n"
        ),
    }
    for chapter in chapters:
        contract = {
            "schema": 1,
            "book": book_id,
            **chapter,
            "imports": sorted(set(chapter.get("imports", []) + relation_imports)),
        }
        outputs[f"books/{book_id}/chapters/{chapter['id']}.json"] = _json_bytes(contract)
    return outputs


def apply_book_design(project: Path | str, book_id: str, proposal: dict[str, object]) -> dict[str, object]:
    root = _project_root(project)
    findings = validate_book_design(root, book_id, proposal)
    blocking = [finding for finding in findings if finding["severity"] == "blocking"]
    if blocking:
        raise BookForgeError(f"Book design has blocking findings: {json.dumps(blocking, sort_keys=True)}")
    schedule_book_design(root, book_id)
    outputs = _book_design_outputs(root, book_id, proposal)
    _execute_materialized_task(root, f"DESIGN-{book_id}", outputs)
    audit = {
        "schema": 1,
        "book": book_id,
        "state": "design_clean",
        "blocking": [],
        "checked": ["pacing", "causality", "agency", "relations", "packetization"],
    }
    _execute_materialized_task(root, f"AUDIT-{book_id}", {f"books/{book_id}/design-audit.json": _json_bytes(audit)})
    return audit


def _run_design_role(
    root: Path,
    task_id: str,
    role: str,
    envelope: dict[str, object],
    runner,
) -> tuple[dict[str, object], dict[str, object]]:
    claim = claim_task(root, task_id, request_hash=str(envelope["hash"]))
    attempt_dir = Path(claim["capsule"]).parent
    _write_bytes_atomic(attempt_dir / "envelope.json", envelope["bytes"])
    try:
        result = runner(role, envelope, attempt_dir)
    except ProviderOutcomeUnknown as exc:
        if exc.session_id:
            mark_provider_accepted(root, str(claim["attempt"]), exc.session_id)
        plan = _load_plan(root)
        attempt = _attempt(plan, str(claim["attempt"]))
        attempt["state"] = "outcome_unknown"
        task = next(row for row in plan["tasks"] if row["id"] == task_id)
        task["state"] = "outcome_unknown"
        _save_plan(root, plan)
        raise
    except BookForgeError as exc:
        _set_attempt_failure(root, str(claim["attempt"]), block=True, reason=str(exc))
        raise
    mark_provider_accepted(root, str(claim["attempt"]), str(result["session_id"]))
    _write_bytes_atomic(attempt_dir / "raw-output.txt", str(result["text"]).encode())
    return claim, result


_EVIDENCE_ROW_RE = re.compile(r"\b(LAW|PLC|FAC|CHR|CH)-\d{4}\b")
_ERA_EVENT_RE = re.compile(r"\b(ERA|EVT)-\d{4}\b")
_CANON_DIRECTORIES = {"LAW": "topics", "PLC": "places", "FAC": "factions", "CHR": "characters"}


def _design_artifact_path(root: Path, scope: dict[str, object]) -> Path:
    if scope.get("scope") == "book" and scope.get("book"):
        return root / "books" / str(scope["book"]) / "design.md"
    return root / "universe" / "design.json"


def _book_proposal_from_artifacts(root: Path, book_id: str) -> dict[str, object]:
    book_root = root / "books" / book_id
    design_text = (book_root / "design.md").read_text(encoding="utf-8")
    arc_match = re.search(r"## Arc\s*\n+\s*(\[.*\])", design_text, re.DOTALL)
    if not arc_match:
        raise BookForgeError(f"Promoted book design lacks an Arc section: books/{book_id}/design.md")
    outline = _read_json(book_root / "outline.yaml")
    reader = (book_root / "reader-state.md").read_text(encoding="utf-8")
    entry_match = re.search(r"^Entry: (\{.*\})$", reader, re.MULTILINE)
    exit_match = re.search(r"^Intended exit: (\{.*\})$", reader, re.MULTILINE)
    premise_match = re.search(r"<!--\s*bf:block\s+premise\s*-->([\s\S]*?)(?=\n##\s|<!--)", design_text)
    return {
        "premise": premise_match.group(1).strip() if premise_match else "",
        "entry_state": json.loads(entry_match.group(1)) if entry_match else {},
        "arc": json.loads(arc_match.group(1)),
        "exit_boundary": json.loads(exit_match.group(1)) if exit_match else {},
        "chapters": outline.get("chapters", []),
    }


def _normalize_evidence_location(location: str) -> str:
    """Strip prose annotations from auditor-cited evidence locations.

    The canon-auditor often appends free prose after a stable location:
    `design_scope.premise — Silent Mind description`, or wraps the location
    in a parenthetical: `BEAT-0003 (design_scope.proposal.chapters[0].beats[2],
    unhashed in envelope)`. Normalize to the bare location before matching so
    binding fails closed only on genuinely unresolvable locations.
    """
    value = str(location).strip()
    parenthetical = re.search(r"\(([^()]*(?:design_scope|proposal|chapters|entry_state|exit_boundary|#)[^()]*)\)", value)
    if parenthetical:
        value = parenthetical.group(1).strip()
    value = re.split(r"\s*[—–]\s*", value, maxsplit=1)[0].strip()
    value = re.sub(r"\s*\([^()]*\)\s*$", "", value).strip()
    return value


def _resolve_evidence_target(root: Path, book_id: str | None, design_artifact: Path, location: str) -> Path | None:
    location = _normalize_evidence_location(location)
    book_scoped = re.match(r"^BOOK-\d{4}#(.+)$", location)
    if book_scoped:
        if not book_id or location.split("#", 1)[0] != book_id:
            return None
        suffix = book_scoped.group(1)
        chapter = re.match(r"^proposal/chapters/(CH-\d{4})(?:/|$)", suffix)
        if chapter:
            path = root / "books" / book_id / "chapters" / f"{chapter.group(1)}.json"
            if path.is_file():
                return path
        if re.fullmatch(r"CH-\d{4}", suffix):
            path = root / "books" / book_id / "chapters" / f"{suffix}.json"
            if path.is_file():
                return path
        if suffix.startswith("proposal"):
            return design_artifact if design_artifact.is_file() else None
        if re.match(r"(entry_state|exit_boundary)", suffix):
            path = root / "books" / book_id / "reader-state.md"
            return path if path.is_file() else None
        return None
    for match in _EVIDENCE_ROW_RE.finditer(location):
        prefix, row_id = match.group(1), match.group(0)
        if prefix == "CH":
            if book_id:
                path = root / "books" / book_id / "chapters" / f"{row_id}.json"
                if path.is_file():
                    return path
            continue
        path = root / "universe" / "canon" / _CANON_DIRECTORIES[prefix] / f"{row_id}.md"
        if path.is_file():
            return path
    for match in _ERA_EVENT_RE.finditer(location):
        prefix = match.group(1)
        path = root / "universe" / "timeline" / ("eras.yaml" if prefix == "ERA" else "events.yaml")
        if path.is_file():
            return path
    if location.startswith("proposal"):
        return design_artifact if design_artifact.is_file() else None
    envelope_scope = re.search(r"design_scope\.(.+)", location)
    if envelope_scope:
        if not book_id:
            return None
        suffix = envelope_scope.group(1)
        chapter = re.search(r"(?:^|\.)chapters(?:\[|\.)(CH-\d{4})\b", suffix)
        if chapter:
            path = root / "books" / book_id / "chapters" / f"{chapter.group(1)}.json"
            if path.is_file():
                return path
            return None
        if re.match(r"(entry_state|exit_boundary)", suffix):
            path = root / "books" / book_id / "reader-state.md"
            return path if path.is_file() else None
        if re.match(r"(premise|arc|proposal)", suffix):
            return design_artifact if design_artifact.is_file() else None
        return None
    block_match = re.fullmatch(r"[A-Z][A-Z0-9]*-\d{4}#[a-z0-9][a-z0-9-]*", location)
    if block_match:
        index = rebuild_indexes(root)
        block = index["blocks"].get(location)
        if block:
            return root / str(block["path"])
        return None
    candidate = root / location
    if candidate.is_file():
        return candidate
    return None


def _bind_audit_evidence(root: Path, scope: dict[str, object], value: dict[str, object]) -> dict[str, object]:
    findings = value.get("findings")
    if not isinstance(findings, list):
        return value
    book_id = str(scope.get("book")) if scope.get("scope") == "book" and scope.get("book") else None
    design_artifact = _design_artifact_path(root, scope)
    bound: list[dict[str, object]] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        evidence = finding.get("evidence")
        if not isinstance(evidence, list):
            continue
        fixed = []
        for item in evidence:
            if not isinstance(item, dict):
                continue
            location = str(item.get("location", ""))
            target = _resolve_evidence_target(root, book_id, design_artifact, location)
            if target is None:
                raise BookForgeError(f"Audit evidence location is not a stable artifact: {location}")
            fixed.append({**item, "location": location, "hash": _file_hash(target)})
        finding["evidence"] = fixed
        bound.append(finding)
    return {"findings": bound}


def _design_audit_record(
    root: Path,
    task_id: str,
    scope: dict[str, object],
    imports: list[str],
    runner,
    output_path: str,
) -> dict[str, object]:
    envelope = build_envelope(
        root,
        role="canon-auditor",
        task_capsule={"design_scope": scope, "required_output": {"findings": []}},
        imports=imports,
        state={},
        tools=[],
        max_output_tokens=3000,
    )
    claim, result = _run_design_role(root, task_id, "canon-auditor", envelope, runner)
    try:
        value = _parse_contract_json(str(result["text"]))
        findings = _validate_audit_output(_bind_audit_evidence(root, scope, value))
    except BookForgeError as exc:
        _set_attempt_failure(root, str(claim["attempt"]), block=True, reason=str(exc))
        raise
    record = {
        "schema": 1,
        "state": "blocked" if any(row["severity"] == "blocking" for row in findings) else "design_clean",
        "findings": findings,
    }
    _complete_model_task(root, task_id, claim, {output_path: _json_bytes(record)}, result, envelope)
    if record["state"] == "blocked":
        raise BookForgeError(f"Independent design audit found blocking issues: {json.dumps(findings, sort_keys=True)}")
    return record


def _parse_chorus_models_arg(value: str | None, default: list[str]) -> list[str]:
    if not value:
        return list(default)
    parts = [p.strip() for p in value.split(",") if p.strip()]
    filtered = [m for m in parts if m.startswith("openrouter/") and "/" in m]
    if not filtered:
        raise BookForgeError("--chorus-models must be comma-separated openrouter/... IDs")
    return filtered


def _chorus_scope_id(scope: dict[str, object]) -> str:
    if scope.get("scope") == "book" and scope.get("book"):
        return f"book-{scope['book']}"
    return "universe"


def _validate_chorus_output(value: dict[str, object]) -> dict[str, object]:
    findings = value.get("findings")
    suggestions = value.get("suggestions")
    if not isinstance(findings, list):
        raise BookForgeError("Chorus output missing findings list")
    if suggestions is not None and not isinstance(suggestions, list):
        raise BookForgeError("Chorus output suggestions must be a list")
    for row in findings:
        if not isinstance(row, dict):
            raise BookForgeError("Chorus finding must be an object")
        for key in ("id", "severity", "issue"):
            if key not in row:
                raise BookForgeError(f"Chorus finding missing {key}")
        if row.get("severity") not in {"blocking", "warning", "note"}:
            raise BookForgeError("Chorus finding has invalid severity")
        evidence = row.get("evidence")
        if evidence is not None and not isinstance(evidence, list):
            raise BookForgeError("Chorus evidence must be a list")
    return {"findings": findings, "suggestions": list(suggestions or [])}


def run_chorus(
    project: Path | str,
    scope: dict[str, object],
    envelope: dict[str, object],
    chorus_models: list[str],
    *,
    provider=None,
) -> dict[str, object]:
    """Run chorus advisors (advisory-only, never writes canon)."""
    root = _project_root(project)
    runner = provider or run_opencode_role
    scope_id = _chorus_scope_id(scope)
    timestamp = str(int(time.time()))
    # Concurrency 2, advisory-only: record but never block design DAG.
    confirmed = ", ".join(chorus_models)
    print(f"Chorus enabled — advisors: {confirmed}", file=sys.stderr)

    # Build per-advisor envelopes (same context, different role).
    results: dict[str, dict[str, object]] = {}
    # Dispatch in waves of 2 (bounded concurrency).
    def dispatch_one(model: str) -> tuple[str, dict[str, object]]:
        advisor = _chorus_advisor_name(model)
        # Build a chorus-specific envelope (same imports/state but advisor role).
        adv_envelope = build_envelope(
            root,
            role=advisor,  # type: ignore[arg-type] — advisor is not in ROLE_SPECS but has its own agent
            task_capsule={"chorus_scope": scope, "task": envelope.get("task_capsule")},
            imports=list(envelope.get("imports", [])),  # type: ignore[arg-type]
            state=dict(envelope.get("state", {})),  # type: ignore[arg-type]
            tools=[],
            max_output_tokens=3000,
        )
        # Allow advisor roles that are not in ROLE_SPECS — use raw opencode dispatch.
        # We bypass claim_task/DAG and call runner directly (advisory, at-most-once not required).
        # Use a temp dir for advisory output.
        import tempfile as _tmp
        chorus_tmp_root = root / ".book-forge" / "chorus" / ".tmp"
        chorus_tmp_root.mkdir(parents=True, exist_ok=True)
        tmp = Path(_tmp.mkdtemp(prefix=f".chorus-{_chorus_slug(model)}-", dir=chorus_tmp_root))
        try:
            result = runner(advisor, adv_envelope, tmp)
            raw = _parse_contract_json(str(result["text"]))
            validated = _validate_chorus_output(raw)
            # Bind hashes for evidence (advisory, fail-closed per item, skip invalid instead of blocking).
            bound_findings = []
            for f in validated["findings"]:
                evidence = f.get("evidence") or []
                fixed_ev = []
                for item in evidence:
                    loc = str(item.get("location", ""))
                    # Reuse audit evidence binder logic but advisory: skip unresolved instead of raising global.
                    try:
                        target = _resolve_evidence_target(root, str(scope.get("book")) if scope.get("book") else None, _design_artifact_path(root, scope), loc)
                        if target is None:
                            fixed_ev.append({**item, "location": loc, "hash": item.get("hash", "unvalidated")})
                        else:
                            fixed_ev.append({**item, "location": loc, "hash": _file_hash(target)})
                    except Exception:
                        fixed_ev.append({**item, "location": loc, "hash": item.get("hash", "unvalidated")})
                bound_findings.append({**f, "evidence": fixed_ev})
            return advisor, {"findings": bound_findings, "suggestions": validated["suggestions"], "raw": raw, "envelope_hash": adv_envelope["hash"]}
        except Exception as exc:
            # Advisory-only: a malformed single advisor must not kill the run.
            return advisor, {"findings": [], "suggestions": [], "error": str(exc), "envelope_hash": adv_envelope["hash"]}
        finally:
            import shutil as _sh
            if tmp.exists():
                _sh.rmtree(tmp)

    # Use ThreadPoolExecutor with max 2 for bounded concurrency.
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(dispatch_one, m): m for m in chorus_models}
        for fut in futures:
            advisor, data = fut.result()
            results[advisor] = data

    # Persist advisory outputs.
    chorus_dir = root / ".book-forge" / "chorus" / scope_id / timestamp
    chorus_dir.mkdir(parents=True, exist_ok=True)
    for advisor, data in results.items():
        _write_json(chorus_dir / f"{advisor}.json", data)
    # Human report
    report_lines = [f"# Chorus Report — {scope_id} — {timestamp}", "", f"Advisors: {confirmed}", ""]
    total_findings = sum(len(v["findings"]) for v in results.values())
    report_lines.append(f"Total findings: {total_findings}")
    report_lines.append("")
    for advisor, data in sorted(results.items()):
        if data.get("error"):
            report_lines.append(f"## {advisor} — FAILED (non-blocking)")
            report_lines.append(f"  error: {data['error']}")
            report_lines.append("")
            continue
        report_lines.append(f"## {advisor} — {len(data['findings'])} findings")
        for f in data["findings"]:
            report_lines.append(f"- **{f['id']}** ({f['severity']}): {f['issue']}")
            if f.get("suggestion"):
                report_lines.append(f"  suggestion: {f['suggestion']}")
        report_lines.append("")
    _write_bytes_atomic(chorus_dir / "chorus-report.md", "\n".join(report_lines).encode("utf-8"))
    # Also write to project root for discoverability (latest).
    _write_bytes_atomic(root / ".book-forge" / f"chorus-{scope_id}-latest.md", "\n".join(report_lines).encode("utf-8"))
    return {"scope": scope_id, "timestamp": timestamp, "advisors": sorted(results), "total_findings": total_findings, "dir": str(chorus_dir)}


def chorus_status(project: Path | str, book_id: str | None = None) -> dict[str, object]:
    root = _project_root(project)
    scopes = [f"book-{book_id}"] if book_id else ["universe", *[f"book-{b['id']}" for b in list_books(root)]]
    # Include universe always if book filter not exclusive.
    if book_id and "universe" not in scopes:
        scopes = [f"book-{book_id}"]
    elif not book_id:
        scopes = ["universe"] + [f"book-{b['id']}" for b in list_books(root)]
    result: dict[str, object] = {"scopes": []}
    for sid in scopes:
        cdir = root / ".book-forge" / "chorus" / sid
        runs = sorted([p.name for p in cdir.glob("*") if p.is_dir()]) if cdir.is_dir() else []
        latest = runs[-1] if runs else None
        synth = root / ".book-forge" / "chorus" / sid / (latest + "/chorus-synthesis.json") if latest else None
        has_synthesis = bool(synth and synth.is_file())
        result["scopes"].append({"scope": sid, "runs": runs, "latest": latest, "has_synthesis": has_synthesis, "stale": False})
    return result


def chorus_synthesize(project: Path | str, book_id: str | None = None, chorus_models: list[str] | None = None, *, provider=None) -> dict[str, object]:
    root = _project_root(project)
    scope_id = f"book-{book_id}" if book_id else "universe"
    cdir = root / ".book-forge" / "chorus" / scope_id
    if not cdir.is_dir():
        raise BookForgeError(f"No chorus runs for {scope_id}; run design or chorus first")
    latest = sorted([p.name for p in cdir.glob("*") if p.is_dir()])[-1]
    run_dir = cdir / latest
    # Collect all advisor outputs
    advisor_files = list(run_dir.glob("advisor-*.json"))
    if not advisor_files:
        raise BookForgeError(f"No advisor outputs in {run_dir}")
    all_findings: list[dict[str, object]] = []
    for af in advisor_files:
        data = _read_json(af)
        all_findings.extend(data.get("findings", []))  # type: ignore[arg-type]
    # Deduplicate by issue text (casefold) and rank severity blocking>warning>note
    seen: dict[str, dict[str, object]] = {}
    for f in all_findings:
        key = str(f.get("issue", "")).casefold().strip()
        if key not in seen:
            seen[key] = f
    rank = {"blocking": 0, "warning": 1, "note": 2}
    deduped = sorted(seen.values(), key=lambda r: (rank.get(str(r.get("severity")), 9), str(r.get("id"))))
    # Call synthesizer to rank/propose patches if provider available, else just dedup.
    synthesis = {"schema": 1, "scope": scope_id, "run": latest, "findings": deduped, "patches": []}
    if provider or True:
        runner = provider or run_opencode_role
        try:
            synth_envelope = build_envelope(
                root,
                role=CHORUS_SYNTHESIZER_AGENT,  # type: ignore[arg-type]
                task_capsule={"chorus_scope": {"scope": scope_id}, "findings": deduped},
                imports=[],
                state={},
                tools=[],
                max_output_tokens=4000,
            )
            import tempfile as _tmp
            chorus_tmp_root = root / ".book-forge" / "chorus" / ".tmp"
            chorus_tmp_root.mkdir(parents=True, exist_ok=True)
            tmp = Path(_tmp.mkdtemp(prefix=".chorus-synth-", dir=chorus_tmp_root))
            try:
                result = runner(CHORUS_SYNTHESIZER_AGENT, synth_envelope, tmp)
                raw = _parse_contract_json(str(result["text"]))
                # Expect {"patches":[{"finding":"F-...","patch":"...","location":"..."}]}
                if isinstance(raw.get("patches"), list):
                    synthesis["patches"] = raw["patches"]
                if isinstance(raw.get("ranked_findings"), list) and raw["ranked_findings"]:
                    synthesis["findings"] = raw["ranked_findings"]
            finally:
                import shutil as _sh
                if tmp.exists():
                    _sh.rmtree(tmp)
        except Exception:
            pass
    _write_json(run_dir / "chorus-synthesis.json", synthesis)
    return synthesis



def _latest_chorus_report(project: Path | str, scope_id: str) -> dict[str, object] | None:
    root = _project_root(project)
    cdir = root / ".book-forge" / "chorus" / scope_id
    if not cdir.is_dir():
        return None
    runs = sorted([p.name for p in cdir.glob("*") if p.is_dir()])
    if not runs:
        return None
    latest = runs[-1]
    report_path = cdir / latest / "chorus-synthesis.json"
    if report_path.is_file():
        return _read_json(report_path)
    # Fallback to raw advisor findings
    run_dir = cdir / latest
    findings = []
    for af in run_dir.glob("advisor-*.json"):
        data = _read_json(af)
        findings.extend(data.get("findings", []))
    return {"findings": findings, "patches": []} if findings else None

def _reset_universe_design_tasks(root: Path) -> None:
    """Receipted reset of the universe design cycle for an explicit refresh.

    Orphans every prior attempt (resolution: refresh) and returns both tasks
    to pending. Fail closed when any book exists: post-book canon changes
    flow through artifact currentness and repair, never wholesale redesign.
    """
    if list_books(root):
        raise BookForgeError("Universe redesign is refused once books exist; canon changes must flow through audit and repair")
    plan = _load_plan(root)
    for task_id in ("DESIGN-UNI-0001", "AUDIT-UNI-0001"):
        task = next((row for row in plan["tasks"] if row["id"] == task_id), None)
        if task is None or task["state"] == "pending":
            continue
        attempt_id = task.get("attempt")
        if attempt_id:
            attempt = _attempt(plan, str(attempt_id))
            if attempt["state"] not in {"orphaned"}:
                attempt["state"] = "orphaned"
                attempt["resolution"] = "refresh"
        for attempt in plan["attempts"]:
            if attempt["task"] == task_id and attempt["state"] in {"running", "succeeded", "validation_failed", "outcome_unknown", "blocked"}:
                attempt["state"] = "orphaned"
                attempt["resolution"] = "refresh"
        task["state"] = "pending"
        task.pop("attempt", None)
        task["outputs"] = []
    _save_plan(root, plan)
    render_plan(root)


def _sweep_orphaned_canon(root: Path, proposal: dict[str, object]) -> list[str]:
    """Remove canon files whose IDs the refreshed proposal no longer declares."""
    live_ids = {str(row["id"]) for category in ("kernel", "places", "factions", "characters") for row in proposal.get(category, [])}
    swept: list[str] = []
    for directory in ("topics", "places", "factions", "characters"):
        folder = root / "universe" / "canon" / directory
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.md")):
            if path.stem not in live_ids:
                path.unlink()
                swept.append(str(path.relative_to(root)))
    return swept


def execute_universe_design(project: Path | str, *, provider=None, chorus_models: str | None = None, no_chorus: bool = False, with_chorus_context: bool = False, refresh: bool = False, skip_brief: bool = False) -> dict[str, object]:
    root = _project_root(project)
    runner = provider or run_opencode_role
    tasks = schedule_universe_design(root)
    if refresh:
        _reset_universe_design_tasks(root)
    elif all(task["state"] == "succeeded" for task in tasks):
        return {**_read_json(root / "universe" / "design-audit.json"), "calls": 0}
    plan = _load_plan(root)
    design_task = next(task for task in plan["tasks"] if task["id"] == "DESIGN-UNI-0001")
    if design_task["state"] == "succeeded":
        proposal = _read_json(root / "universe" / "design.json")
        audit = _design_audit_record(
            root,
            "AUDIT-UNI-0001",
            {"scope": "universe", "proposal": proposal},
            ["UNI-0001#kernel"],
            runner,
            "universe/design-audit.json",
        )
        return {**audit, "calls": 1}
    # 00-BRIEF gate default ON (M2)
    if _should_brief_gate(root, "universe", skip_flag=skip_brief):
        raise BookForgeError(f"brief.missing: 00-BRIEF gate blocks design universe — answer 7 questions in universe/design-brief.json or pass --skip-brief / usa default")
    brief = _read_json(root / "universe" / "design-brief.json")
    config = _read_json(root / "book-forge.yaml")
    _chorus_default = _chorus_models_from_config(config)
    _chorus_effective = _parse_chorus_models_arg(chorus_models, _chorus_default) if chorus_models else _chorus_default
    last_failure = _last_validation_failure(plan, "DESIGN-UNI-0001")
    repair_context = {"repair": {"validation_error": str(last_failure.get("failure"))}} if last_failure else {}
    should_chorus = (not no_chorus) and _chorus_enabled(config)
    base_capsule = {
        "scope": "universe",
        "brief": brief,
        "continuities": _continuities(root)["continuities"],
        **repair_context,
        **({"chorus_report": _latest_chorus_report(root, "universe")} if with_chorus_context and _latest_chorus_report(root, "universe") else {}),
        "required_output": {
                "kernel": "LAW-#### rows: {id, name, summary}",
                "eras": "ERA-#### rows: {id, name, summary}",
                "events": "EVT-#### rows: {id, name, summary, era, order}",
                "places": "PLC-#### rows: {id, name, summary, sensory, tier} — tiered: L1 3-5, L2 5-8, L3 6-12, total >= 14 places",
                "factions": "FAC-#### rows: {id, name, summary}",
                "characters": "CHR-#### rows: {id, name, tier, summary, voice, appearance, past, want, need, flaw, wound, arc, secret} — tiered cast (M4): L1 1-3 protagonists 250-350 words each with want/need/flaw/wound/arc/voice/secret, L2 4-7 secondaries 150-200 words, L3 6-12 recurring 60-90 words, L4 10-20 walk-ons one line (<20 words), total named characters >= 22; emit characters in at most two sub-chunks (L1+L2, then L3+L4) if needed to stay <15KB each",
                "themes": ["theme"],
                "style": {"tense": "past", "person": "third-limited"},
                "continuity_material": {"CNT-0001": ["stable IDs"]},
                "book_local": {},
                "unresolved_questions": [],
            },
    }
    envelope = build_envelope(
        root,
        role="designer",
        task_capsule=base_capsule,
        imports=["UNI-0001#kernel"],
        state={},
        tools=[],
        max_output_tokens=8192,
    )
    _log_step(1, 7, "brief gate", "→")
    _log_step(1, 7, "brief gate", "✓")
    _log_step(2, 7, "chorus", "→")
    if should_chorus:
        try:
            run_chorus(root, {"scope": "universe", "proposal": brief}, envelope, _chorus_effective, provider=runner)
            _log_step(2, 7, "chorus", "✓")
        except Exception as exc:
            print(f"Chorus advisory failed (non-blocking): {exc}", file=sys.stderr)
            _log_step(2, 7, "chorus", "✗")
    else:
        _log_step(2, 7, "chorus", "✓ (skipped)")
    _log_step(3, 7, "designer envelope", "✓")
    _log_step(4, 7, "designer call", "→")
    claim, merged, results, chunk_telemetry = _run_design_chunked(
        root, "DESIGN-UNI-0001", base_capsule, ["UNI-0001#kernel"], runner
    )
    result = _synthetic_chunk_result(results, merged)
    result["chunk_telemetry"] = chunk_telemetry
    _log_step(4, 7, "designer call", "✓")
    _log_step(5, 7, "validate", "→")
    try:
        proposal = _normalize_universe_proposal(merged)
        findings = validate_universe_design(root, proposal)
        if any(row["severity"] == "blocking" for row in findings):
            _log_step(5, 7, "validate", "✗")
            raise BookForgeError(f"Universe design has blocking findings: {json.dumps(findings, sort_keys=True)}")
        _log_step(5, 7, "validate", "✓")
    except BookForgeError as exc:
        _set_attempt_failure(root, str(claim["attempt"]), block=True, reason=str(exc))
        raise
    _log_step(6, 7, "promote", "→")
    _complete_model_task(root, "DESIGN-UNI-0001", claim, _universe_design_outputs(proposal), result, envelope)
    _sweep_orphaned_canon(root, proposal)
    rebuild_indexes(root)
    _log_step(6, 7, "promote", "✓")
    _log_step(7, 7, "audit", "→")
    audit = _design_audit_record(
        root,
        "AUDIT-UNI-0001",
        {"scope": "universe", "proposal": proposal},
        ["UNI-0001#kernel"],
        runner,
        "universe/design-audit.json",
    )
    _log_step(7, 7, "audit", "✓")
    # M3 summary
    arts = list(_universe_design_outputs(proposal).keys()) + ["universe/design-audit.json"]
    _log_summary(arts)
    return {**audit, "calls": len(results) + 1}


def execute_book_design(project: Path | str, book_id: str, *, provider=None, chorus_models: str | None = None, no_chorus: bool = False, with_chorus_context: bool = False, skip_brief: bool = False) -> dict[str, object]:
    root = _project_root(project)
    runner = provider or run_opencode_role
    tasks = schedule_book_design(root, book_id)
    if all(task["state"] == "succeeded" for task in tasks):
        return {**_read_json(root / "books" / book_id / "design-audit.json"), "calls": 0}
    plan = _load_plan(root)
    design_task = next(task for task in plan["tasks"] if task["id"] == f"DESIGN-{book_id}")
    if design_task["state"] == "succeeded":
        obligations, relation_imports = _book_obligations(root, book_id)
        imports = sorted(set(["UNI-0001#kernel", *relation_imports]))
        proposal = _book_proposal_from_artifacts(root, book_id)
        audit = _design_audit_record(
            root,
            f"AUDIT-{book_id}",
            {"scope": "book", "book": book_id, "proposal": proposal},
            imports,
            runner,
            f"books/{book_id}/design-audit.json",
        )
        return {**audit, "calls": 1}
    if _should_brief_gate(root, "book", book_id=book_id, skip_flag=skip_brief):
        raise BookForgeError(f"brief.missing: 00-BRIEF gate blocks design book {book_id} — answer 7 questions in books/{book_id}/book-brief.json or pass --skip-brief / usa default")
    book = next(row for row in list_books(root) if row["id"] == book_id)
    brief = _book_brief(root, book_id)
    obligations, relation_imports = _book_obligations(root, book_id)
    index = rebuild_indexes(root)
    context = _book_canon_context(root, book_id, index)
    worldbuilding = next((row["content"] for row in context if row["id"] == "worldbuilding.md"), None)
    imports = sorted({row["id"] for row in context if row["id"] != "worldbuilding.md"})
    chapter_imports = sorted(set(["UNI-0001#kernel", *relation_imports]))
    config = _read_json(root / "book-forge.yaml")
    _chorus_default = _chorus_models_from_config(config)
    _chorus_effective = _parse_chorus_models_arg(chorus_models, _chorus_default) if chorus_models else _chorus_default
    should_chorus = (not no_chorus) and _chorus_enabled(config)
    last_failure = _last_validation_failure(plan, f"DESIGN-{book_id}")
    repair_context = {"repair": {"validation_error": str(last_failure.get("failure"))}} if last_failure else {}
    envelope = build_envelope(
        root,
        role="designer",
        task_capsule={
            "scope": "book",
            "book": book,
            "brief": brief,
            "worldbuilding": worldbuilding,
            **repair_context,
            **({"chorus_report": _latest_chorus_report(root, f"book-{book_id}")} if with_chorus_context and _latest_chorus_report(root, f"book-{book_id}") else {}),
            "relations": [row for row in _read_json(root / "universe" / "relations.yaml").get("relations", []) if book_id in row.get("endpoints", [])],
            "obligations": list(obligations.values()),
            "required_output": {
                "premise": "string",
                "entry_state": {},
                "arc": ["at least three causal turns"],
                "exit_boundary": {},
                "chapters": [
                    {
                        "id": "CH-0001",
                        "order": 1,
                        "pov": "stable character ID",
                        "beats": ["causal beat"],
                        "plants": [],
                        "reveals": [],
                        "target_words": 2000,
                        "imports": chapter_imports,
                        "obligations": [],
                        "pivotal": None,
                    }
                ],
            },
        },
        imports=imports,
        state={},
        tools=[],
        max_output_tokens=8192,
    )
    task_id = f"DESIGN-{book_id}"
    _log_step(1, 7, "brief gate", "✓")
    _log_step(2, 7, "chorus", "→")
    if should_chorus:
        try:
            run_chorus(root, {"scope": "book", "book": book_id, "brief": brief}, envelope, _chorus_effective, provider=runner)
            _log_step(2, 7, "chorus", "✓")
        except Exception as exc:
            print(f"Chorus advisory failed (non-blocking): {exc}", file=sys.stderr)
            _log_step(2, 7, "chorus", "✗")
    else:
        _log_step(2, 7, "chorus", "✓ (skipped)")
    _log_step(3, 7, "designer envelope", "✓")
    _log_step(4, 7, "designer call", "→")
    claim, result = _run_with_length_retry(root, task_id, "designer", envelope, runner)
    if _is_length_finish(result):
        _log_step(4, 7, "designer call", "✗ length → retry")
    else:
        _log_step(4, 7, "designer call", "✓")
    _log_step(5, 7, "validate", "→")
    try:
        proposal = _parse_chunked_contract(str(result["text"]))
        findings = validate_book_design(root, book_id, proposal)
        if any(row["severity"] == "blocking" for row in findings):
            _log_step(5, 7, "validate", "✗")
            raise BookForgeError(f"Book design has blocking findings: {json.dumps(findings, sort_keys=True)}")
        _log_step(5, 7, "validate", "✓")
    except BookForgeError as exc:
        _set_attempt_failure(root, str(claim["attempt"]), block=True, reason=str(exc))
        raise
    _log_step(6, 7, "promote", "→")
    _complete_model_task(root, task_id, claim, _book_design_outputs(root, book_id, proposal), result, envelope)
    _log_step(6, 7, "promote", "✓")
    _log_step(7, 7, "audit", "→")
    audit = _design_audit_record(
        root,
        f"AUDIT-{book_id}",
        {"scope": "book", "book": book_id, "proposal": proposal},
        imports,
        runner,
        f"books/{book_id}/design-audit.json",
    )
    _log_step(7, 7, "audit", "✓")
    arts = list(_book_design_outputs(root, book_id, proposal).keys()) + [f"books/{book_id}/design-audit.json"]
    _log_summary(arts)
    return {**audit, "calls": 2}


def _parse_contract_json(text_value: str) -> dict[str, object]:
    stripped = text_value.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            stripped = "\n".join(lines[1:-1])
            if stripped.lstrip().startswith("json\n"):
                stripped = stripped.lstrip()[5:]
    start = stripped.find("{")
    if start < 0:
        raise BookForgeError("Model output contains no JSON object")
    try:
        value, _ = json.JSONDecoder().raw_decode(stripped[start:])
    except json.JSONDecodeError as exc:
        raise BookForgeError(f"Model output is not contract JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise BookForgeError("Model output contract must be an object")
    return value


def _parse_chunked_contract(text_value: str) -> dict[str, object]:
    """Parse a designer response that may contain multiple top-level JSON
    objects — one per category (M1 per-chunk generation) — and merge them
    into a single proposal.

    Each top-level object is treated as a chunk and must stay below
    DESIGN_CHUNK_MAX_BYTES (M1). List keys are concatenated in order (e.g.
    characters emitted in two sub-chunks L1+L2 / L3+L4), dict keys are
    shallow-updated, and scalar keys take the last non-conflicting value.
    A single monolithic object is also accepted but is still size-checked.
    """
    stripped = text_value.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            stripped = "\n".join(lines[1:-1])
            if stripped.lstrip().startswith("json\n"):
                stripped = stripped.lstrip()[5:]
    start = stripped.find("{")
    if start < 0:
        raise BookForgeError("Model output contains no JSON object")
    decoder = json.JSONDecoder()
    merged: dict[str, object] = {}
    pos = start
    found = 0
    length = len(stripped)
    while pos < length:
        pos = stripped.find("{", pos)
        if pos < 0:
            break
        try:
            value, end = decoder.raw_decode(stripped, pos)
        except json.JSONDecodeError:
            # Not a JSON object here (e.g. prose brace); keep scanning.
            pos += 1
            continue
        if not isinstance(value, dict):
            raise BookForgeError("Model output contract must be an object")
        found += 1
        chunk_size = len(json.dumps(value, ensure_ascii=False))
        if chunk_size > DESIGN_CHUNK_MAX_BYTES:
            raise BookForgeError(f"Design chunk exceeds {DESIGN_CHUNK_MAX_BYTES} bytes: {chunk_size}")
        # Accept both direct category keys and the labeled form
        # {"_contract": "kernel", "rows": [...]}.
        contract = value.get("_contract")
        if isinstance(contract, str) and "rows" in value and contract not in value:
            value = {contract: value["rows"]}
        for key, chunk_value in value.items():
            if key in merged and isinstance(merged[key], list) and isinstance(chunk_value, list):
                merged[key] = merged[key] + chunk_value
            else:
                merged[key] = chunk_value
        pos = end
    if found == 0:
        raise BookForgeError("Model output contains no JSON object")
    return merged


def validate_writer_output(contract: dict[str, object], text_value: str) -> dict[str, object]:
    value = _parse_contract_json(text_value)
    prose = value.get("prose_markdown")
    if not isinstance(prose, str) or not prose.strip():
        raise BookForgeError("Writer output has no prose_markdown")
    if not isinstance(value.get("beat_map"), list) or len(value["beat_map"]) < len(contract.get("beats", [])):
        raise BookForgeError("Writer output has an incomplete beat map")
    if not isinstance(value.get("consequences"), list):
        raise BookForgeError("Writer output has no consequence disclosure")
    if re.search(r"\b(?:TODO|TBD)\b|\[(?:INSERT|PLACEHOLDER)[^]]*\]", prose, re.IGNORECASE):
        raise BookForgeError("Writer output contains a placeholder")
    words = len(re.findall(r"\b[\w’'-]+\b", prose, re.UNICODE))
    target = int(contract["target_words"])
    lower = max(1, int(target * 0.70))
    upper = int(target * 1.40)
    if not lower <= words <= upper:
        raise BookForgeError(f"Writer output word count {words} is outside {lower}..{upper}")
    value["word_count"] = words
    return value


def run_opencode_role(role: str, envelope: dict[str, object], attempt_dir: Path) -> dict[str, object]:
    # Chorus advisors are allowed despite not being in ROLE_SPECS.
    if role not in ROLE_SPECS and role not in CHORUS_ADVISOR_SPECS and role != CHORUS_SYNTHESIZER_AGENT:
        raise BookForgeError(f"Role cannot run headlessly: {role}")
    if role in ROLE_SPECS and ROLE_SPECS[role][0] not in {"all", "primary"}:
        raise BookForgeError(f"Role cannot run headlessly: {role}")
    root = _project_root_from(attempt_dir)
    binary = _opencode_binary()
    resolved_result = subprocess.run(
        [binary, "--pure", "debug", "agent", role],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    resolved = json.loads(resolved_result.stdout)
    resolved_model = resolved.get("model", {})
    expected_model_id, expected_variant = _expected_pin(role)
    if (
        resolved.get("name") != role
        or resolved_model.get("providerID") != "openrouter"
        or resolved_model.get("modelID") != expected_model_id
        or resolved.get("variant") != expected_variant
    ):
        raise BookForgeError(f"Resolved OpenCode agent pin differs for {role}")
    environment = dict(os.environ)
    environment.pop("OPENROUTER_API_KEY", None)
    started = time.monotonic()
    result = subprocess.run(
        [
            binary,
            "run",
            "--pure",
            "--dir",
            str(root),
            "--agent",
            role,
            "--format",
            "json",
            "--title",
            f"book-forge-{attempt_dir.name.lower()}",
            envelope["bytes"].decode("utf-8"),
        ],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )
    _write_bytes_atomic(attempt_dir / "provider-events.jsonl", result.stdout.encode())
    events = []
    for line in result.stdout.splitlines():
        if line.startswith("{"):
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    session_ids = [str(event["sessionID"]) for event in events if event.get("sessionID")]
    session_id = session_ids[0] if session_ids else None
    if result.returncode != 0 or not session_id:
        if session_id:
            raise ProviderOutcomeUnknown(session_id, f"OpenCode ended without a complete result: {result.stderr.strip()}")
        raise BookForgeError(f"OpenCode failed before provider acceptance: {result.stderr.strip()}")
    finishes = [event["part"] for event in events if event.get("type") == "step_finish" and isinstance(event.get("part"), dict)]
    # M1: handle length truncation explicitly — do not map to outcome_unknown; surface finish for retry
    completed = [part for part in finishes if part.get("reason") in ("stop", "length")]
    if not completed:
        raise ProviderOutcomeUnknown(session_id, "Accepted call has no terminal stop event")
    raw_finish = completed[-1]
    if raw_finish.get("reason") == "length":
        # still extract text/tokens but mark as length for caller retry
        pass
    export = subprocess.run([binary, "export", session_id], capture_output=True, text=True, check=False)
    receipt = None
    try:
        if export.returncode == 0:
            receipt = json.loads(export.stdout)
    except json.JSONDecodeError:
        receipt = None
    texts = [event["part"]["text"] for event in events if event.get("type") == "text" and isinstance(event.get("part", {}).get("text"), str)]
    if not texts:
        if raw_finish.get("reason") == "length":
            # M1: zero-output length truncation — surface finish="length" so the
            # caller retries; do not map to outcome_unknown. length != unknown.
            return {
                "text": "",
                "provider": "openrouter",
                "model": expected_model_id,
                "variant": resolved["variant"],
                "session_id": session_id,
                "tokens": raw_finish.get("tokens", {}),
                "cost": raw_finish.get("cost", 0),
                "latency_ms": int((time.monotonic() - started) * 1000),
                "finish": "length",
            }
        raise ProviderOutcomeUnknown(session_id, "Accepted call produced no observable text")
    if receipt is not None:
        info = receipt["info"]
        if info.get("agent") != role:
            raise BookForgeError(f"OpenCode fell back from {role} to {info.get('agent')}")
        tokens = info.get("tokens", raw_finish.get("tokens", {}))
        cost = info.get("cost", raw_finish.get("cost", 0))
    else:
        tokens = raw_finish.get("tokens", {})
        cost = raw_finish.get("cost", 0)
    return {
        "text": texts[-1],
        "provider": "openrouter",
        "model": expected_model_id,
        "variant": resolved["variant"],
        "session_id": session_id,
        "tokens": tokens,
        "cost": cost,
        "latency_ms": int((time.monotonic() - started) * 1000),
        "finish": raw_finish["reason"],
        "session_export": "complete" if receipt is not None else "truncated-fallback-to-events",
    }


def _set_attempt_failure(root: Path, attempt_id: str, *, block: bool, reason: str) -> None:
    plan = _load_plan(root)
    attempt = _attempt(plan, attempt_id)
    attempt["state"] = "validation_failed"
    attempt["failure"] = reason
    task = next(row for row in plan["tasks"] if row["id"] == attempt["task"])
    task["state"] = "blocked" if block else "pending"
    task.pop("attempt", None)
    _save_plan(root, plan)
    render_plan(root)
    if block:
        control = _control(root)
        if control.get("active_run"):
            run_path = _run_path(root, str(control["active_run"]))
            run = _read_json(run_path)
            run["state"] = "blocked"
            _write_json(run_path, run)


def _ensure_draft_task(root: Path, book_id: str, chapter_id: str) -> dict[str, object]:
    task_id = f"DRAFT-{book_id}-{chapter_id}"
    plan = _load_plan(root)
    existing = next((task for task in plan["tasks"] if task["id"] == task_id), None)
    if existing:
        return existing
    book = next((item for item in list_books(root) if item["id"] == book_id), None)
    if not book:
        raise BookForgeError(f"Unknown book: {book_id}")
    return add_task(
        root,
        task_id,
        "writer",
        priority=50,
        book_order=int(book.get("order", 0)),
        chapter_order=int(chapter_id.split("-")[-1]),
        inputs=[f"books/{book_id}/chapters/{chapter_id}.json"],
        outputs=[
            f"books/{book_id}/work/{chapter_id}/draft.md",
            f"books/{book_id}/work/{chapter_id}/beat-map.json",
            f"books/{book_id}/work/{chapter_id}/consequences.json",
        ],
    )


def draft_chapter(
    project: Path | str,
    book_id: str,
    chapter_id: str,
    *,
    provider=None,
) -> dict[str, object]:
    root = _project_root(project)
    contract_path = root / "books" / book_id / "chapters" / f"{chapter_id}.json"
    contract = _read_json(contract_path)
    if contract.get("book") != book_id or contract.get("id") != chapter_id:
        raise BookForgeError("Chapter contract identity mismatch")
    if contract.get("pivotal"):
        raise BookForgeError("Pivotal chapters must use the judge workflow")
    _ensure_draft_task(root, book_id, chapter_id)
    runner = provider or run_opencode_role
    last_error = ""
    for call_number in (1, 2):
        capsule = dict(contract)
        if last_error:
            capsule["repair"] = {"attempt": call_number, "validation_error": last_error}
        state_path = root / "books" / book_id / "state.yaml"
        state = _read_json(state_path)
        envelope = build_envelope(
            root,
            role="writer",
            task_capsule=capsule,
            imports=list(contract.get("imports", [])),
            state={"book_state": state, "previous_chapter_tail": state.get("previous_chapter_tail", "")},
            tools=[],
            max_output_tokens=min(6000, max(1000, int(contract["target_words"]) * 2)),
        )
        claim = claim_task(root, f"DRAFT-{book_id}-{chapter_id}", request_hash=str(envelope["hash"]))
        attempt_dir = Path(claim["capsule"]).parent
        _write_bytes_atomic(attempt_dir / "envelope.json", envelope["bytes"])
        try:
            result = runner("writer", envelope, attempt_dir)
            mark_provider_accepted(root, claim["attempt"], str(result["session_id"]))
            parsed = validate_writer_output(contract, str(result["text"]))
        except ProviderOutcomeUnknown as exc:
            if exc.session_id:
                mark_provider_accepted(root, claim["attempt"], exc.session_id)
            plan = _load_plan(root)
            attempt = _attempt(plan, claim["attempt"])
            attempt["state"] = "outcome_unknown"
            task = next(row for row in plan["tasks"] if row["id"] == attempt["task"])
            task["state"] = "outcome_unknown"
            _save_plan(root, plan)
            raise
        except BookForgeError as exc:
            last_error = str(exc)
            _set_attempt_failure(root, claim["attempt"], block=call_number == 2, reason=last_error)
            if call_number == 2:
                raise BookForgeError(f"Chapter draft blocked after one repair: {last_error}") from exc
            continue
        outputs = {
            f"books/{book_id}/work/{chapter_id}/draft.md": str(parsed["prose_markdown"]).rstrip() + "\n",
            f"books/{book_id}/work/{chapter_id}/beat-map.json": _json_bytes({"schema": 1, "chapter": chapter_id, "beats": parsed["beat_map"]}),
            f"books/{book_id}/work/{chapter_id}/consequences.json": _json_bytes({"schema": 1, "chapter": chapter_id, "consequences": parsed["consequences"]}),
        }
        manifest = stage_outputs(root, claim["attempt"], outputs)
        telemetry = {key: result[key] for key in ("provider", "model", "variant", "session_id", "tokens", "cost", "latency_ms", "finish")}
        telemetry.update({"envelope_hash": envelope["hash"], "estimated_input_tokens": envelope["estimated_input_tokens"], "call_number": call_number})
        receipt = record_execution(
            root,
            claim["attempt"],
            claim["fence"],
            output_hash=_sha256_bytes(_json_bytes(manifest)),
            telemetry=telemetry,
        )
        promote_task(root, claim["attempt"], claim["fence"])
        return {"state": "drafted", "book": book_id, "chapter": chapter_id, "calls": call_number, "receipt": receipt}
    raise BookForgeError("Unreachable draft workflow state")


def run_next(
    project: Path | str,
    *,
    book_id: str | None = None,
    task_id: str | None = None,
    provider=None,
) -> dict[str, object]:
    root = _project_root(project)
    if task_id:
        match = re.fullmatch(r"DRAFT-(BOOK-\d{4})-(CH-\d{4})", task_id)
        if not match:
            raise BookForgeError(f"Task route is not executable by run yet: {task_id}")
        return draft_chapter(root, match.group(1), match.group(2), provider=provider)
    books = list_books(root)
    if book_id:
        books = [book for book in books if book["id"] == book_id]
        if not books:
            raise BookForgeError(f"Unknown book: {book_id}")
    for book in sorted(books, key=lambda row: (int(row.get("order", 0)), str(row["id"]))):
        for contract_path in sorted((root / "books" / str(book["id"]) / "chapters").glob("CH-*.json")):
            contract = _read_json(contract_path)
            draft_path = root / "books" / str(book["id"]) / "work" / str(contract["id"]) / "draft.md"
            final_path = root / "books" / str(book["id"]) / "manuscript" / "chapters" / f"{contract['id']}.md"
            if final_path.exists():
                continue
            if contract.get("pivotal"):
                return produce_pivotal_chapter(root, str(book["id"]), str(contract["id"]), provider=provider)
            if draft_path.exists() and not contract.get("pivotal"):
                return review_and_close_chapter(root, str(book["id"]), str(contract["id"]), provider=provider)
            if not draft_path.exists() and not contract.get("pivotal"):
                return draft_chapter(root, str(book["id"]), str(contract["id"]), provider=provider)
    raise BookForgeError("No ordinary chapter draft is ready; design a book or use the pivotal workflow")


def _ensure_review_tasks(root: Path, book_id: str, chapter_id: str) -> dict[str, dict[str, object]]:
    draft_id = f"DRAFT-{book_id}-{chapter_id}"
    plan = _load_plan(root)
    if not any(task["id"] == draft_id and task["state"] == "succeeded" for task in plan["tasks"]):
        raise BookForgeError("Chapter must have a promoted draft before review")
    specs = [
        (
            f"REVIEW-COLD-{book_id}-{chapter_id}",
            "cold-reader",
            [draft_id],
            [f"books/{book_id}/reviews/{chapter_id}/cold-reader.json"],
        ),
        (
            f"REVIEW-TECH-{book_id}-{chapter_id}",
            "technical-editor",
            [draft_id],
            [f"books/{book_id}/reviews/{chapter_id}/technical-editor.json"],
        ),
    ]
    existing = {str(task["id"]) for task in plan["tasks"]}
    for task_id, role, deps, outputs in specs:
        if task_id not in existing:
            add_task(root, task_id, role, deps=deps, priority=60, outputs=outputs)
    reviser_id = f"REVISE-{book_id}-{chapter_id}"
    plan = _load_plan(root)
    if not any(task["id"] == reviser_id for task in plan["tasks"]):
        add_task(
            root,
            reviser_id,
            "reviser",
            deps=[specs[0][0], specs[1][0]],
            priority=70,
            outputs=[
                f"books/{book_id}/manuscript/chapters/{chapter_id}.md",
                f"books/{book_id}/state.yaml",
                f"books/{book_id}/reader-state.md",
                f"books/{book_id}/reviews/{chapter_id}/dispositions.json",
                f"books/{book_id}/reviews/{chapter_id}/previous-synthetic.md",
                f"books/{book_id}/coldread-state/{chapter_id}.md",
            ],
        )
    plan = _load_plan(root)
    ids = [spec[0] for spec in specs] + [reviser_id]
    return {task_id: next(task for task in plan["tasks"] if task["id"] == task_id) for task_id in ids}


def _provider_telemetry(result: dict[str, object], envelope: dict[str, object], call_number: int = 1) -> dict[str, object]:
    telemetry = {key: result[key] for key in ("provider", "model", "variant", "session_id", "tokens", "cost", "latency_ms", "finish")}
    telemetry.update({"envelope_hash": envelope["hash"], "estimated_input_tokens": envelope["estimated_input_tokens"], "call_number": call_number})
    if "chunk_telemetry" in result:
        telemetry["chunk_telemetry"] = result["chunk_telemetry"]
    return telemetry


def _validate_findings(value: dict[str, object], *, technical: bool) -> list[dict[str, object]]:
    findings = value.get("findings")
    if not isinstance(findings, list):
        raise BookForgeError("Review output has no findings list")
    seen = set()
    for finding in findings:
        required = {"id", "dimension", "severity", "evidence", "issue", "fix_required"}
        if not isinstance(finding, dict) or not required <= finding.keys():
            raise BookForgeError("Review finding is missing required evidence fields")
        if finding["id"] in seen or finding["severity"] not in {"blocking", "warning", "note"}:
            raise BookForgeError("Review finding has duplicate ID or invalid severity")
        if technical and "objective" not in finding:
            raise BookForgeError("Technical finding must declare objective status")
        seen.add(finding["id"])
    return findings


def _materialize_review_result(
    root: Path,
    task_id: str,
    claim: dict[str, object],
    envelope: dict[str, object],
    result: dict[str, object],
    value: dict[str, object],
) -> dict[str, object]:
    plan = _load_plan(root)
    task = next(row for row in plan["tasks"] if row["id"] == task_id)
    output = str(task["outputs"][0])
    manifest = stage_outputs(root, claim["attempt"], {output: _json_bytes({"schema": 1, **value})})
    receipt = record_execution(
        root,
        claim["attempt"],
        claim["fence"],
        output_hash=_sha256_bytes(_json_bytes(manifest)),
        telemetry=_provider_telemetry(result, envelope),
    )
    promote_task(root, claim["attempt"], claim["fence"])
    return receipt


def _call_parallel_reviews(
    root: Path,
    book_id: str,
    chapter_id: str,
    contract: dict[str, object],
    draft: str,
    writer_consequences: dict[str, object],
    runner,
) -> tuple[dict[str, object], dict[str, object], list[dict[str, object]]]:
    materialized = {}
    for role, task_id, output in (
        ("cold-reader", f"REVIEW-COLD-{book_id}-{chapter_id}", f"books/{book_id}/reviews/{chapter_id}/cold-reader.json"),
        ("technical-editor", f"REVIEW-TECH-{book_id}-{chapter_id}", f"books/{book_id}/reviews/{chapter_id}/technical-editor.json"),
    ):
        review_path = root / output
        plan = _load_plan(root)
        task = next((row for row in plan["tasks"] if row["id"] == task_id), None)
        if review_path.is_file() and task and task["state"] == "succeeded":
            materialized[role] = _read_json(review_path)
    if len(materialized) == 2:
        return materialized["cold-reader"], materialized["technical-editor"], []
    jobs = []
    # Build synthetic previous-chapters summary for cold-reader — persisted artifact, not reconstructed
    previous_synthetic = ""
    try:
        # Prefer persisted coldread-state chain (authoritative, versioned)
        coldread_state_dir = root / f"books/{book_id}/coldread-state"
        if coldread_state_dir.is_dir():
            for prev in sorted(coldread_state_dir.glob("*.md")):
                # Only include chapters before current (lexicographic order = chapter order for CH-####)
                if prev.stem < chapter_id:
                    previous_synthetic += f"\n\n{prev.read_text(encoding='utf-8').strip()[:600]}"
            previous_synthetic = previous_synthetic.strip()[-3000:]
        if not previous_synthetic:
            reader_state_path = root / f"books/{book_id}/reader-state.md"
            if reader_state_path.is_file():
                previous_synthetic = reader_state_path.read_text(encoding="utf-8").strip()[-2000:]
    except Exception:
        previous_synthetic = ""
    for role, task_id in (
        ("cold-reader", f"REVIEW-COLD-{book_id}-{chapter_id}"),
        ("technical-editor", f"REVIEW-TECH-{book_id}-{chapter_id}"),
    ):
        capsule = {"book": book_id, "chapter": chapter_id, "contract": contract, "prose": draft}
        if role == "cold-reader":
            capsule["previous_synthetic"] = previous_synthetic
            capsule["has_full_canon"] = False
        if role == "technical-editor":
            capsule["writer_consequences"] = writer_consequences.get("consequences", [])
        envelope = build_envelope(
            root,
            role=role,
            task_capsule=capsule,
            imports=list(contract.get("imports", [])),
            state={},
            tools=[],
            max_output_tokens=2500 if role == "cold-reader" else 3000,
        )
        claim = claim_task(root, task_id, request_hash=str(envelope["hash"]))
        attempt_dir = Path(claim["capsule"]).parent
        _write_bytes_atomic(attempt_dir / "envelope.json", envelope["bytes"])
        jobs.append((role, task_id, envelope, claim, attempt_dir))
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {executor.submit(runner, role, envelope, attempt_dir): (role, task_id, envelope, claim) for role, task_id, envelope, claim, attempt_dir in jobs}
        results = []
        for future, metadata in futures.items():
            results.append((*metadata, future.result()))
    parsed: dict[str, dict[str, object]] = {}
    receipts = []
    for role, task_id, envelope, claim, result in results:
        mark_provider_accepted(root, claim["attempt"], str(result["session_id"]))
        value = _parse_contract_json(str(result["text"]))
        _validate_findings(value, technical=role == "technical-editor")
        if role == "technical-editor" and not isinstance(value.get("consequences"), list):
            raise BookForgeError("Technical review has no independent consequence extraction")
        parsed[role] = value
        receipts.append(_materialize_review_result(root, task_id, claim, envelope, result, value))
    return parsed["cold-reader"], parsed["technical-editor"], receipts


def _validate_revision(
    contract: dict[str, object],
    value: dict[str, object],
    findings: list[dict[str, object]],
    technical_consequences: list[dict[str, object]],
) -> dict[str, object]:
    validated = validate_writer_output(contract, json.dumps(value))
    dispositions = value.get("dispositions")
    if not isinstance(dispositions, list):
        raise BookForgeError("Revision has no finding dispositions")
    by_finding = {str(row.get("finding")): row for row in dispositions if isinstance(row, dict)}
    if set(by_finding) != {str(finding["id"]) for finding in findings}:
        raise BookForgeError("Revision must disposition every finding exactly once")
    for finding in findings:
        disposition = by_finding[str(finding["id"])]
        required = {"action", "evidence", "loss", "supersedes"}
        if not required <= disposition.keys():
            raise BookForgeError(f"Incomplete disposition for {finding['id']}")
        if finding.get("objective") and finding["severity"] == "blocking" and disposition["action"] != "repaired":
            raise BookForgeError(f"Objective blocker {finding['id']} cannot be dismissed")
    revised_rows = value.get("consequences", [])
    if not isinstance(revised_rows, list) or not all(isinstance(row, dict) for row in revised_rows):
        raise BookForgeError("Revision consequences must be a list of objects with fact/scope/entities")
    revised_facts = {str(row.get("fact")) for row in revised_rows}
    required_facts = {str(row.get("fact")) for row in technical_consequences}
    if not required_facts <= revised_facts:
        raise BookForgeError("Revision omitted an independently extracted shared consequence")
    if not isinstance(value.get("reader_state"), str) or not value["reader_state"].strip():
        raise BookForgeError("Revision has no compact reader state")
    return validated


def review_and_close_chapter(
    project: Path | str,
    book_id: str,
    chapter_id: str,
    *,
    provider=None,
) -> dict[str, object]:
    root = _project_root(project)
    runner = provider or run_opencode_role
    contract = _read_json(root / "books" / book_id / "chapters" / f"{chapter_id}.json")
    draft_path = root / "books" / book_id / "work" / chapter_id / "draft.md"
    if not draft_path.is_file():
        raise BookForgeError("No promoted draft is available for review")
    draft = draft_path.read_text(encoding="utf-8")
    writer_consequences = _read_json(root / "books" / book_id / "work" / chapter_id / "consequences.json")
    _ensure_review_tasks(root, book_id, chapter_id)
    cold, technical, receipts = _call_parallel_reviews(root, book_id, chapter_id, contract, draft, writer_consequences, runner)
    technical_findings = []
    for position, finding in enumerate(technical["findings"], start=1):
        renamed = dict(finding)
        renamed["id"] = f"T-{position:04d}"
        renamed["review"] = "technical"
        technical_findings.append(renamed)
    findings = list(cold["findings"]) + technical_findings
    reviser_id = f"REVISE-{book_id}-{chapter_id}"
    envelope = build_envelope(
        root,
        role="reviser",
        task_capsule={"book": book_id, "chapter": chapter_id, "contract": contract, "draft": draft, "findings": findings, "technical_consequences": technical["consequences"]},
        imports=list(contract.get("imports", [])),
        state=_read_json(root / "books" / book_id / "state.yaml"),
        tools=[],
        max_output_tokens=min(6000, max(1000, int(contract["target_words"]) * 2)),
    )
    claim = claim_task(root, reviser_id, request_hash=str(envelope["hash"]))
    attempt_dir = Path(claim["capsule"]).parent
    _write_bytes_atomic(attempt_dir / "envelope.json", envelope["bytes"])
    result = runner("reviser", envelope, attempt_dir)
    mark_provider_accepted(root, claim["attempt"], str(result["session_id"]))
    value = _parse_contract_json(str(result["text"]))
    try:
        validated = _validate_revision(contract, value, findings, list(technical["consequences"]))
    except BookForgeError as exc:
        _set_attempt_failure(root, claim["attempt"], block=True, reason=str(exc))
        raise
    state_path = root / "books" / book_id / "state.yaml"
    state = _read_json(state_path)
    if chapter_id in state.get("closed_chapters", []):
        raise BookForgeError("Chapter is already closed")
    state.setdefault("closed_chapters", []).append(chapter_id)
    state.setdefault("consequences", []).extend(value["consequences"])
    state["previous_chapter_tail"] = str(validated["prose_markdown"])[-2000:]
    stored_dispositions = []
    for disposition in value["dispositions"]:
        row = dict(disposition)
        review = next((finding.get("review") for finding in findings if str(finding["id"]) == str(row.get("finding"))), None)
        if review == "technical":
            row["finding"] = f"F-{int(str(row.get('finding')).removeprefix('T-')):04d}"
        stored_dispositions.append(row)
    # Persistent synthetic for next cold-reader (fresh reader = only this + previous synthetic)
    synthetic_content = f"# Synthetic Previous — {chapter_id}\n\n{value['reader_state'].strip()}\n"
    # Keep last 2 chapters' synthetic chain - append to a cumulative file
    outputs = {
        f"books/{book_id}/manuscript/chapters/{chapter_id}.md": str(validated["prose_markdown"]).rstrip() + "\n",
        f"books/{book_id}/state.yaml": _json_bytes(state),
        f"books/{book_id}/reader-state.md": f"# Reader State\n\n{value['reader_state'].strip()}\n",
        f"books/{book_id}/reviews/{chapter_id}/dispositions.json": _json_bytes({"schema": 1, "chapter": chapter_id, "dispositions": stored_dispositions}),
        f"books/{book_id}/reviews/{chapter_id}/previous-synthetic.md": synthetic_content,
        f"books/{book_id}/coldread-state/{chapter_id}.md": synthetic_content,
    }
    manifest = stage_outputs(root, claim["attempt"], outputs)
    revision_receipt = record_execution(
        root,
        claim["attempt"],
        claim["fence"],
        output_hash=_sha256_bytes(_json_bytes(manifest)),
        telemetry=_provider_telemetry(result, envelope),
    )
    receipts.append(revision_receipt)
    objective_blockers = [finding for finding in findings if finding.get("objective") and finding["severity"] == "blocking"]
    calls = 3
    if objective_blockers:
        verify_id = f"VERIFY-{book_id}-{chapter_id}"
        plan = _load_plan(root)
        if not any(task["id"] == verify_id for task in plan["tasks"]):
            add_task(
                root,
                verify_id,
                "technical-editor",
                deps=[f"REVIEW-COLD-{book_id}-{chapter_id}", f"REVIEW-TECH-{book_id}-{chapter_id}"],
                priority=75,
                outputs=[f"books/{book_id}/reviews/{chapter_id}/verification.json"],
            )
        verification_envelope = build_envelope(
            root,
            role="technical-editor",
            task_capsule={"mode": "changed-span-verification", "blockers": objective_blockers, "revised_prose": validated["prose_markdown"], "dispositions": value["dispositions"]},
            imports=list(contract.get("imports", [])),
            state={},
            tools=[],
            max_output_tokens=1500,
        )
        verify_claim = claim_task(root, verify_id, request_hash=str(verification_envelope["hash"]))
        verify_dir = Path(verify_claim["capsule"]).parent
        verification_result = runner("technical-editor", verification_envelope, verify_dir)
        mark_provider_accepted(root, verify_claim["attempt"], str(verification_result["session_id"]))
        verification = _parse_contract_json(str(verification_result["text"]))
        if verification.get("verified") is not True or verification.get("findings"):
            _set_attempt_failure(root, verify_claim["attempt"], block=True, reason="Independent semantic verification failed")
            raise BookForgeError("Independent semantic verification failed; chapter remains unpromoted")
        receipts.append(_materialize_review_result(root, verify_id, verify_claim, verification_envelope, verification_result, verification))
        calls += 1
    promote_task(root, claim["attempt"], claim["fence"])
    machine_state = _read_json(root / ".book-forge" / "state.json")
    machine_state["source_locked"] = True
    machine_state["source_language"] = _read_json(root / "book-forge.yaml")["source_language"]
    _write_json(root / ".book-forge" / "state.json", machine_state)
    artifact_id = f"SOURCE-{book_id}-{chapter_id}"
    registry = _artifact_registry(root)
    if artifact_id not in registry["artifacts"]:
        register_artifact(
            root,
            artifact_id,
            "source-chapter",
            path=root / "books" / book_id / "manuscript" / "chapters" / f"{chapter_id}.md",
            dependencies=list(contract.get("imports", [])),
            entities=[str(contract.get("pov"))],
        )
    return {"state": "closed", "book": book_id, "chapter": chapter_id, "calls": calls, "receipts": receipts}


def produce_pivotal_chapter(
    project: Path | str,
    book_id: str,
    chapter_id: str,
    *,
    provider=None,
) -> dict[str, object]:
    root = _project_root(project)
    runner = provider or run_opencode_role
    contract = _read_json(root / "books" / book_id / "chapters" / f"{chapter_id}.json")
    if contract.get("pivotal") not in {"opener", "midpoint", "climax", "finale", "user-selected"}:
        raise BookForgeError("Chapter is not explicitly pivotal")
    task_specs = []
    for label, brief in (
        ("A", "Favor intimate restraint, subtext, and a precise interior turn."),
        ("B", "Favor external pressure, irreversible action, and dramatic contrast."),
    ):
        task_id = f"PIVOT-{label}-{book_id}-{chapter_id}"
        output_prefix = f"books/{book_id}/work/{chapter_id}/variants/{label}"
        plan = _load_plan(root)
        if not any(task["id"] == task_id for task in plan["tasks"]):
            add_task(
                root,
                task_id,
                "writer",
                priority=45,
                outputs=[f"{output_prefix}/draft.md", f"{output_prefix}/beat-map.json", f"{output_prefix}/consequences.json"],
            )
        capsule = {**contract, "variant_brief": brief, "anonymous": True}
        envelope = build_envelope(
            root,
            role="writer",
            task_capsule=capsule,
            imports=list(contract.get("imports", [])),
            state={"book_state": _read_json(root / "books" / book_id / "state.yaml")},
            tools=[],
            max_output_tokens=min(6000, max(1000, int(contract["target_words"]) * 2)),
        )
        claim = claim_task(root, task_id, request_hash=str(envelope["hash"]))
        task_specs.append((label, task_id, output_prefix, envelope, claim, Path(claim["capsule"]).parent))
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(runner, "writer", envelope, attempt_dir): (label, task_id, output_prefix, envelope, claim)
            for label, task_id, output_prefix, envelope, claim, attempt_dir in task_specs
        }
        variant_results = []
        for future, metadata in futures.items():
            variant_results.append((*metadata, future.result()))
    candidates = {}
    source_labels = {}
    for label, task_id, output_prefix, envelope, claim, result in variant_results:
        mark_provider_accepted(root, claim["attempt"], str(result["session_id"]))
        value = validate_writer_output(contract, str(result["text"]))
        anonymous = f"candidate-{_sha256_bytes(str(value['prose_markdown']).encode())[:10]}"
        if anonymous in candidates:
            anonymous += f"-{label.lower()}"
        candidates[anonymous] = value
        source_labels[anonymous] = label
        outputs = {
            f"{output_prefix}/draft.md": str(value["prose_markdown"]).rstrip() + "\n",
            f"{output_prefix}/beat-map.json": _json_bytes({"schema": 1, "beats": value["beat_map"]}),
            f"{output_prefix}/consequences.json": _json_bytes({"schema": 1, "consequences": value["consequences"]}),
        }
        manifest = stage_outputs(root, claim["attempt"], outputs)
        record_execution(
            root,
            claim["attempt"],
            claim["fence"],
            output_hash=_sha256_bytes(_json_bytes(manifest)),
            telemetry=_provider_telemetry(result, envelope),
        )
        promote_task(root, claim["attempt"], claim["fence"])
    judge_id = f"JUDGE-{book_id}-{chapter_id}"
    judgement_path = f"books/{book_id}/reviews/{chapter_id}/judgement.json"
    plan = _load_plan(root)
    if not any(task["id"] == judge_id for task in plan["tasks"]):
        add_task(
            root,
            judge_id,
            "judge",
            deps=[f"PIVOT-A-{book_id}-{chapter_id}", f"PIVOT-B-{book_id}-{chapter_id}"],
            priority=50,
            outputs=[judgement_path],
        )
    judge_envelope = build_envelope(
        root,
        role="judge",
        task_capsule={
            "contract": contract,
            "candidates": {label: {"prose_markdown": value["prose_markdown"], "beat_map": value["beat_map"]} for label, value in sorted(candidates.items())},
        },
        imports=list(contract.get("imports", [])),
        state={},
        tools=[],
        max_output_tokens=2000,
    )
    judge_claim = claim_task(root, judge_id, request_hash=str(judge_envelope["hash"]))
    judge_result = runner("judge", judge_envelope, Path(judge_claim["capsule"]).parent)
    mark_provider_accepted(root, judge_claim["attempt"], str(judge_result["session_id"]))
    decision = _parse_contract_json(str(judge_result["text"]))
    ranking = decision.get("ranking")
    if not isinstance(ranking, list) or len(ranking) != 2 or set(ranking) != set(candidates):
        raise BookForgeError("Blind judge did not rank every anonymous candidate exactly once")
    if not isinstance(decision.get("evidence"), list):
        raise BookForgeError("Blind judge supplied no rank evidence")
    winner_label = str(ranking[0])
    winner = candidates[winner_label]
    decision_record = {
        "schema": 1,
        "chapter": chapter_id,
        "anonymous_candidates": sorted(candidates),
        "ranking": ranking,
        "evidence": decision["evidence"],
        "winner": winner_label,
        "anchors": [],
    }
    manifest = stage_outputs(root, judge_claim["attempt"], {judgement_path: _json_bytes(decision_record)})
    record_execution(
        root,
        judge_claim["attempt"],
        judge_claim["fence"],
        output_hash=_sha256_bytes(_json_bytes(manifest)),
        telemetry=_provider_telemetry(judge_result, judge_envelope),
    )
    promote_task(root, judge_claim["attempt"], judge_claim["fence"])
    draft_id = f"DRAFT-{book_id}-{chapter_id}"
    regular_outputs = [
        f"books/{book_id}/work/{chapter_id}/draft.md",
        f"books/{book_id}/work/{chapter_id}/beat-map.json",
        f"books/{book_id}/work/{chapter_id}/consequences.json",
    ]
    plan = _load_plan(root)
    if not any(task["id"] == draft_id for task in plan["tasks"]):
        add_task(root, draft_id, "writer", deps=[judge_id], priority=55, outputs=regular_outputs)
    _execute_materialized_task(
        root,
        draft_id,
        {
            regular_outputs[0]: str(winner["prose_markdown"]).rstrip() + "\n",
            regular_outputs[1]: _json_bytes({"schema": 1, "chapter": chapter_id, "beats": winner["beat_map"]}),
            regular_outputs[2]: _json_bytes({"schema": 1, "chapter": chapter_id, "consequences": winner["consequences"]}),
        },
    )
    closure = review_and_close_chapter(root, book_id, chapter_id, provider=runner)
    return {"state": closure["state"], "book": book_id, "chapter": chapter_id, "calls": 3 + int(closure["calls"]), "winner": winner_label}


def add_translation(project: Path | str, book_id: str, locale: str) -> dict[str, object]:
    root = _project_root(project)
    book = next((item for item in list_books(root) if item["id"] == book_id), None)
    if not book:
        raise BookForgeError(f"Unknown book: {book_id}")
    canonical = _canonical_locale(locale)
    source = _canonical_locale(str(_read_json(root / "book-forge.yaml")["source_language"]))
    if canonical == source:
        raise BookForgeError("Translation locale duplicates the authoritative source language")
    translations = root / "books" / book_id / "translations"
    target = translations / canonical
    config_path = target / "locale.yaml"
    if target.exists():
        if not config_path.is_file():
            raise BookForgeError(f"Translation path collision: {target}")
        config = _read_json(config_path)
        if config.get("locale") != canonical or config.get("book") != book_id:
            raise BookForgeError(f"Translation workspace identity collision: {target}")
        return {**config, "created": False}
    locale_id = f"LOC-{hashlib.sha256(f'{book_id}:{canonical}'.encode()).hexdigest()[:8].upper()}"
    translations.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{canonical}-", dir=translations))
    try:
        config = {
            "schema": 1,
            "id": locale_id,
            "book": book_id,
            "source_language": source,
            "locale": canonical,
            "status": "empty",
        }
        _write_json(stage / "locale.yaml", config)
        _write_json(
            stage / "metadata.yaml",
            {"schema": 1, "locale": canonical, "title": book["title"], "subtitle": "", "contributors": []},
        )
        _write_json(
            stage / "state.yaml",
            {"schema": 1, "locale": canonical, "completed_chapters": [], "current": True, "boundary_hashes": {}},
        )
        (stage / "style.md").write_text(
            f"---\nid: {locale_id}-STYLE\n---\n\n# Locale Style\n\n<!-- bf:block style -->\n"
            "Define register, dialogue punctuation, narrative tense, and voice-preservation decisions here.\n",
            encoding="utf-8",
        )
        (stage / "glossary.md").write_text(
            f"---\nid: {locale_id}-GLOSS\n---\n\n# Locale Glossary\n\n<!-- bf:block terms -->\n"
            "Record names, honorifics, register, character dialogue voices, and do-not-translate terms here.\n",
            encoding="utf-8",
        )
        (stage / "chapters").mkdir()
        os.replace(stage, target)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return {**config, "created": True}


def _translation_validation(source: str, value: dict[str, object]) -> list[str]:
    translated = value.get("translated_markdown")
    problems = []
    if not isinstance(translated, str) or not translated.strip():
        return ["missing translated_markdown"]
    if not isinstance(value.get("glossary_updates"), list):
        problems.append("missing glossary_updates")
    if not isinstance(value.get("boundary"), str) or not value["boundary"].strip():
        problems.append("missing translated boundary")
    source_numbers = re.findall(r"(?<!\w)\d+(?:[.,]\d+)?", source)
    translated_numbers = re.findall(r"(?<!\w)\d+(?:[.,]\d+)?", translated)
    if source_numbers != translated_numbers:
        problems.append("numbers differ from source")
    source_headings = len(re.findall(r"(?m)^#{1,6}\s", source))
    translated_headings = len(re.findall(r"(?m)^#{1,6}\s", translated))
    if source_headings != translated_headings or source.count("\n***\n") != translated.count("\n***\n"):
        problems.append("scene or heading structure differs")
    source_words = re.findall(r"\b[\w’'-]+\b", source, re.UNICODE)
    translated_words = re.findall(r"\b[\w’'-]+\b", translated, re.UNICODE)
    ratio = len(translated_words) / max(1, len(source_words))
    if not 0.45 <= ratio <= 2.2:
        problems.append("probable omission or expansion")
    if len(source_words) >= 10:
        sequences = [" ".join(source_words[index:index + 10]).lower() for index in range(len(source_words) - 9)]
        normalized_translation = " ".join(translated_words).lower()
        if any(sequence in normalized_translation for sequence in sequences):
            problems.append("probable source-language leakage")
    return problems


def _append_glossary(glossary: str, updates: list[dict[str, object]]) -> str:
    existing = set()
    for line in glossary.splitlines():
        if line.startswith("- **") and "** → " in line:
            existing.add(line.split("**", 2)[1].casefold())
    lines = [glossary.rstrip()]
    for row in updates:
        if not isinstance(row, dict) or not {"source", "translation", "note"} <= row.keys():
            raise BookForgeError("Glossary update is missing source, translation, or note")
        source = str(row["source"])
        if source.casefold() not in existing:
            lines.append(f"- **{source}** → {row['translation']} — {row['note']}")
            existing.add(source.casefold())
    return "\n".join(lines).rstrip() + "\n"


def _ensure_locale_artifacts(root: Path, book_id: str, locale: str) -> None:
    registry = _artifact_registry(root)
    locale_root = root / "books" / book_id / "translations" / locale
    specs = [
        (f"LOCALE-STYLE-{book_id}-{locale}", "locale-style", locale_root / "style.md"),
        (f"LOCALE-GLOSSARY-{book_id}-{locale}", "locale-glossary", locale_root / "glossary.md"),
        (f"LOCALE-METADATA-{book_id}-{locale}", "locale-metadata", locale_root / "metadata.yaml"),
    ]
    for artifact_id, kind, path in specs:
        if artifact_id not in registry["artifacts"]:
            register_artifact(root, artifact_id, kind, path=path, authored=True)
            registry = _artifact_registry(root)


def _translate_one(
    root: Path,
    book_id: str,
    locale: str,
    chapter_id: str,
    *,
    provider=None,
) -> dict[str, object]:
    runner = provider or run_opencode_role
    locale_root = root / "books" / book_id / "translations" / locale
    source_path = root / "books" / book_id / "manuscript" / "chapters" / f"{chapter_id}.md"
    contract = _read_json(root / "books" / book_id / "chapters" / f"{chapter_id}.json")
    source = source_path.read_text(encoding="utf-8")
    state_path = locale_root / "state.yaml"
    state = _read_json(state_path)
    previous = state.get("boundary", "")
    previous_id = None
    if state.get("completed_chapters"):
        previous_id = f"TRANSLATION-{book_id}-{state['completed_chapters'][-1]}-{locale}"
    task_id = f"TRANSLATE-{book_id}-{chapter_id}-{locale}"
    plan = _load_plan(root)
    if not any(task["id"] == task_id for task in plan["tasks"]):
        deps = [previous_id.replace("TRANSLATION-", "TRANSLATE-", 1)] if previous_id else []
        add_task(
            root,
            task_id,
            "translator",
            deps=deps,
            priority=80,
            chapter_order=int(contract["order"]),
            outputs=[
                f"books/{book_id}/translations/{locale}/chapters/{chapter_id}.md",
                f"books/{book_id}/translations/{locale}/state.yaml",
                f"books/{book_id}/translations/{locale}/glossary.md",
            ],
        )
    last_error = ""
    calls = 0
    must_review = bool(contract.get("pivotal"))
    for attempt_number in (1, 2):
        capsule = {
            "book": book_id,
            "chapter": chapter_id,
            "source_language": _read_json(root / "book-forge.yaml")["source_language"],
            "target_locale": locale,
            "source_markdown": source,
            "contract": contract,
            "locale_style": (locale_root / "style.md").read_text(encoding="utf-8"),
            "glossary": (locale_root / "glossary.md").read_text(encoding="utf-8"),
            "metadata": _read_json(locale_root / "metadata.yaml"),
        }
        if last_error or (must_review and attempt_number == 2):
            capsule["repair"] = {"reason": last_error or "pivotal translation independent self-review", "previous_output": previous_output}
        envelope = build_envelope(
            root,
            role="translator",
            task_capsule=capsule,
            imports=list(contract.get("imports", [])),
            state={"previous_boundary": previous},
            tools=[],
            max_output_tokens=min(6000, max(1000, int(contract.get("target_words", 2000)) * 2)),
        )
        claim = claim_task(root, task_id, request_hash=str(envelope["hash"]))
        attempt_dir = Path(claim["capsule"]).parent
        result = runner("translator", envelope, attempt_dir)
        calls += 1
        mark_provider_accepted(root, claim["attempt"], str(result["session_id"]))
        _write_bytes_atomic(attempt_dir / "raw-output.txt", str(result["text"]).encode())
        try:
            value = _parse_contract_json(str(result["text"]))
            problems = _translation_validation(source, value)
            if problems:
                raise BookForgeError("; ".join(problems))
        except BookForgeError as exc:
            last_error = str(exc)
            _set_attempt_failure(root, claim["attempt"], block=attempt_number == 2, reason=last_error)
            if attempt_number == 2:
                raise BookForgeError(f"Translation blocked after one repair: {last_error}") from exc
            previous_output = str(result["text"])
            continue
        if must_review and attempt_number == 1:
            previous_output = value
            _set_attempt_failure(root, claim["attempt"], block=False, reason="pivotal-review-requested")
            continue
        glossary = _append_glossary((locale_root / "glossary.md").read_text(encoding="utf-8"), list(value["glossary_updates"]))
        completed = list(state.get("completed_chapters", []))
        if chapter_id not in completed:
            completed.append(chapter_id)
        all_source = [path.stem for path in sorted((root / "books" / book_id / "manuscript" / "chapters").glob("CH-*.md"))]
        state.update(
            {
                "completed_chapters": completed,
                "boundary": value["boundary"],
                "boundary_hashes": {**state.get("boundary_hashes", {}), chapter_id: _sha256_bytes(str(value["boundary"]).encode())},
                "status": "current" if completed == all_source else "in_progress",
                "current": True,
            }
        )
        input_hashes = state.setdefault("input_hashes", {"source": {}, "canon": {}, "global": {}})
        input_hashes.setdefault("source", {})[chapter_id] = _file_hash(source_path)
        index = rebuild_indexes(root)
        input_hashes.setdefault("canon", {})[chapter_id] = {
            block_id: index["blocks"][block_id]["hash"] for block_id in contract.get("imports", [])
        }
        input_hashes["global"] = {
            "style": _file_hash(locale_root / "style.md"),
            "glossary": _sha256_bytes(glossary.encode()),
            "metadata": _file_hash(locale_root / "metadata.yaml"),
        }
        outputs = {
            f"books/{book_id}/translations/{locale}/chapters/{chapter_id}.md": str(value["translated_markdown"]).rstrip() + "\n",
            f"books/{book_id}/translations/{locale}/state.yaml": _json_bytes(state),
            f"books/{book_id}/translations/{locale}/glossary.md": glossary,
        }
        manifest = stage_outputs(root, claim["attempt"], outputs)
        receipt = record_execution(
            root,
            claim["attempt"],
            claim["fence"],
            output_hash=_sha256_bytes(_json_bytes(manifest)),
            telemetry=_provider_telemetry(result, envelope, attempt_number),
        )
        promote_task(root, claim["attempt"], claim["fence"])
        reconcile_artifacts(root)
        artifact_id = f"TRANSLATION-{book_id}-{chapter_id}-{locale}"
        registry = _artifact_registry(root)
        if f"SOURCE-{book_id}-{chapter_id}" not in registry["artifacts"]:
            register_artifact(root, f"SOURCE-{book_id}-{chapter_id}", "source-chapter", path=source_path)
        dependencies = [
            f"SOURCE-{book_id}-{chapter_id}",
            f"LOCALE-STYLE-{book_id}-{locale}",
            f"LOCALE-GLOSSARY-{book_id}-{locale}",
            f"LOCALE-METADATA-{book_id}-{locale}",
        ]
        if previous_id:
            dependencies.append(previous_id)
        registry = _artifact_registry(root)
        if artifact_id not in registry["artifacts"]:
            register_artifact(root, artifact_id, "translation-chapter", path=locale_root / "chapters" / f"{chapter_id}.md", dependencies=dependencies)
        return {"chapter": chapter_id, "locale": locale, "calls": calls, "receipt": receipt}
    raise BookForgeError("Unreachable translation state")


def translate_next(
    project: Path | str,
    book_id: str,
    locale: str,
    *,
    provider=None,
    run_all: bool = False,
) -> dict[str, object]:
    root = _project_root(project)
    canonical = _canonical_locale(locale)
    locale_root = root / "books" / book_id / "translations" / canonical
    if not (locale_root / "locale.yaml").is_file():
        raise BookForgeError("Translation workspace does not exist; run translate add explicitly")
    _ensure_locale_artifacts(root, book_id, canonical)
    results = []
    while True:
        source_chapters = sorted((root / "books" / book_id / "manuscript" / "chapters").glob("CH-*.md"))
        next_source = next((path for path in source_chapters if not (locale_root / "chapters" / path.name).is_file()), None)
        if not next_source:
            break
        results.append(_translate_one(root, book_id, canonical, next_source.stem, provider=provider))
        if not run_all:
            break
    if not results:
        return {"state": "current", "book": book_id, "locale": canonical, "calls": 0, "chapters": []}
    return {
        "state": _read_json(locale_root / "state.yaml")["status"],
        "book": book_id,
        "locale": canonical,
        "calls": sum(int(result["calls"]) for result in results),
        "chapters": [result["chapter"] for result in results],
    }


def translation_impact(project: Path | str, book_id: str, locale: str) -> dict[str, object]:
    root = _project_root(project)
    canonical = _canonical_locale(locale)
    locale_root = root / "books" / book_id / "translations" / canonical
    state_path = locale_root / "state.yaml"
    state = _read_json(state_path)
    chapters = list(state.get("completed_chapters", []))
    stored = state.get("input_hashes", {})
    causes: dict[str, list[str]] = {chapter: [] for chapter in chapters}
    current_global = {
        "style": _file_hash(locale_root / "style.md"),
        "glossary": _file_hash(locale_root / "glossary.md"),
        "metadata": _file_hash(locale_root / "metadata.yaml"),
    }
    global_changes = [name for name, value in current_global.items() if stored.get("global", {}).get(name) != value]
    stale: set[str] = set()
    if global_changes:
        for chapter in chapters:
            stale.add(chapter)
            causes[chapter].extend(f"locale {name} hash changed" for name in global_changes)
    index = rebuild_indexes(root)
    for chapter in chapters:
        source = root / "books" / book_id / "manuscript" / "chapters" / f"{chapter}.md"
        if stored.get("source", {}).get(chapter) != _file_hash(source):
            stale.add(chapter)
            causes[chapter].append("source hash changed")
        contract = _read_json(root / "books" / book_id / "chapters" / f"{chapter}.json")
        for block_id in contract.get("imports", []):
            current = index["blocks"].get(block_id, {}).get("hash")
            if stored.get("canon", {}).get(chapter, {}).get(block_id) != current:
                stale.add(chapter)
                causes[chapter].append(f"canon import changed: {block_id}")
    boundary_audit: list[str] = []
    if stale and not global_changes:
        first = min(chapters.index(chapter) for chapter in stale)
        boundary_audit = [chapter for chapter in chapters[first + 1:] if chapter not in stale]
        for chapter in boundary_audit:
            causes[chapter].append(f"prior translated boundary may change after {chapters[first]}")
    state["current"] = not stale
    state["status"] = "current" if not stale else "stale"
    state["stale_prose"] = sorted(stale, key=chapters.index)
    state["boundary_audit"] = boundary_audit
    state["stale_causes"] = {chapter: values for chapter, values in causes.items() if values}
    _write_json(state_path, state)
    return {
        "book": book_id,
        "locale": canonical,
        "stale_prose": state["stale_prose"],
        "boundary_audit": boundary_audit,
        "causes": state["stale_causes"],
    }


def converge_translation_boundaries(
    project: Path | str,
    book_id: str,
    locale: str,
    *,
    changed_chapter: str,
    recomputed: dict[str, str],
) -> dict[str, object]:
    root = _project_root(project)
    canonical = _canonical_locale(locale)
    state_path = root / "books" / book_id / "translations" / canonical / "state.yaml"
    state = _read_json(state_path)
    chapters = list(state.get("completed_chapters", []))
    if changed_chapter not in chapters:
        raise BookForgeError(f"Unknown completed translated chapter: {changed_chapter}")
    stale = []
    boundary_audit = []
    index = chapters.index(changed_chapter)
    for position in range(index, len(chapters)):
        chapter = chapters[position]
        stale.append(chapter)
        if position == len(chapters) - 1:
            break
        if chapter not in recomputed:
            boundary_audit.append(chapters[position + 1])
            break
        supplied = recomputed[chapter]
        new_hash = supplied if re.fullmatch(r"[0-9a-f]{64}", supplied) else _sha256_bytes(supplied.encode())
        old_hash = state.get("boundary_hashes", {}).get(chapter)
        if new_hash == old_hash:
            break
    state["current"] = False
    state["status"] = "stale"
    state["stale_prose"] = stale
    state["boundary_audit"] = boundary_audit
    state["stale_causes"] = {
        chapter: ["direct input changed" if chapter == changed_chapter else f"prior boundary changed after {chapters[chapters.index(chapter) - 1]}"]
        for chapter in stale
    }
    _write_json(state_path, state)
    return {"book": book_id, "locale": canonical, "stale_prose": stale, "boundary_audit": boundary_audit, "causes": state["stale_causes"]}


def generate_audit_jobs(
    project: Path | str,
    *,
    book_id: str | None = None,
    relation_id: str | None = None,
    continuity_id: str | None = None,
    override: bool = False,
) -> list[dict[str, object]]:
    root = _project_root(project)
    books = {str(book["id"]): book for book in list_books(root)}
    relations_path = root / "universe" / "relations.yaml"
    relations = _read_json(relations_path).get("relations", [])
    jobs = []
    for relation in relations:
        endpoints = list(relation.get("endpoints", []))
        if relation_id and relation["id"] != relation_id:
            continue
        if book_id and book_id not in endpoints:
            continue
        if continuity_id and not any(books.get(endpoint, {}).get("continuity") == continuity_id for endpoint in endpoints):
            continue
        relation_hash = _sha256_bytes(_json_bytes(relation))
        jobs.append(
            {
                "id": f"JOB-{relation['id']}",
                "kind": "crossover-obligation" if relation["type"] == "crossover" else "relation-boundary",
                "books": endpoints,
                "relation": relation,
                "imports": [item["block"] for item in relation.get("imports", [])],
                "evidence": [{"location": f"universe/relations.yaml#{relation['id']}", "hash": relation_hash}],
            }
        )
    entity_books: dict[str, list[tuple[str, str, str]]] = {}
    for current_book in ([] if relation_id else books.values()):
        if book_id and current_book["id"] != book_id:
            continue
        if continuity_id and current_book["continuity"] != continuity_id:
            continue
        state_path = root / "books" / str(current_book["id"]) / "state.yaml"
        state = _read_json(state_path)
        for consequence in state.get("consequences", []):
            for entity in consequence.get("entities", []):
                entity_books.setdefault(str(entity), []).append((str(current_book["id"]), str(consequence.get("fact", "")), _file_hash(state_path) or ""))
    for entity, appearances in sorted(entity_books.items()):
        unique_books = []
        for appearance in appearances:
            if appearance[0] not in unique_books:
                unique_books.append(appearance[0])
        if len(unique_books) < 2:
            continue
        digest = hashlib.sha256(entity.encode()).hexdigest()[:8].upper()
        jobs.append(
            {
                "id": f"JOB-ENTITY-{digest}",
                "kind": "entity-transition",
                "entity": entity,
                "books": unique_books,
                "facts": [{"book": book, "fact": fact} for book, fact, _ in appearances],
                "imports": [],
                "evidence": [{"location": f"books/{book}/state.yaml", "hash": hash_value} for book, _, hash_value in appearances],
            }
        )
    events = _read_json(root / "universe" / "timeline" / "events.yaml").get("events", [])
    for event in ([] if relation_id else events):
        event_books = list(event.get("books", []))
        if len(event_books) > 1 and (not book_id or book_id in event_books):
            jobs.append(
                {
                    "id": f"JOB-TIMELINE-{event['id']}",
                    "kind": "timeline-overlap",
                    "books": event_books,
                    "event": event,
                    "imports": [],
                    "evidence": [{"location": f"universe/timeline/events.yaml#{event['id']}", "hash": _sha256_bytes(_json_bytes(event))}],
                }
            )
    return sorted(jobs, key=lambda job: str(job["id"]))


def _validate_audit_output(value: dict[str, object]) -> list[dict[str, object]]:
    findings = value.get("findings")
    if not isinstance(findings, list):
        raise BookForgeError("Audit output has no findings list")
    for finding in findings:
        if not isinstance(finding, dict) or not {"id", "severity", "issue", "evidence", "repair_scope"} <= finding.keys():
            raise BookForgeError("Audit finding is missing required fields")
        if finding["severity"] not in {"blocking", "warning", "note"} or not isinstance(finding["evidence"], list) or not finding["evidence"]:
            raise BookForgeError("Audit finding has invalid severity or no evidence")
        for evidence in finding["evidence"]:
            if not isinstance(evidence, dict) or not evidence.get("location") or not re.fullmatch(r"[0-9a-f]{64}", str(evidence.get("hash", ""))):
                raise BookForgeError("Audit evidence requires a stable location and SHA-256")
    return findings


def audit_continuity(
    project: Path | str,
    *,
    book_id: str | None = None,
    relation_id: str | None = None,
    continuity_id: str | None = None,
    max_jobs: int = 8,
    override: bool = False,
    provider=None,
) -> dict[str, object]:
    root = _project_root(project)
    if not 1 <= max_jobs <= 8:
        raise BookForgeError("Audit waves must contain between one and eight jobs")
    candidates = generate_audit_jobs(root, book_id=book_id, relation_id=relation_id, continuity_id=continuity_id, override=override)
    if len(candidates) > 20 and not override:
        raise BookForgeError(f"Audit has {len(candidates)} candidates; rerun with a manifest-recorded override")
    if override:
        _write_json(root / ".book-forge" / "audit-overrides.json", {"schema": 1, "candidate_count": len(candidates), "max_jobs": max_jobs, "scope": {"book": book_id, "relation": relation_id, "continuity": continuity_id}})
    runner = provider or run_opencode_role
    audit_id = f"AUD-{_sha256_bytes(_json_bytes([job['id'] for job in candidates]))[:10].upper()}"
    all_findings = []
    calls = 0
    jobs_run = []
    for job in candidates[:max_jobs]:
        task_id = f"AUDIT-{job['id']}"
        output_path = f"universe/audits/{audit_id}/{job['id']}.json"
        plan = _load_plan(root)
        if not any(task["id"] == task_id for task in plan["tasks"]):
            add_task(root, task_id, "canon-auditor", priority=90, outputs=[output_path])
        last_error = ""
        for attempt_number in (1, 2):
            capsule = {"job": job}
            if last_error:
                capsule["repair"] = last_error
            envelope = build_envelope(
                root,
                role="canon-auditor",
                task_capsule=capsule,
                imports=list(job.get("imports", [])),
                state={},
                tools=[],
                max_output_tokens=3000,
            )
            claim = claim_task(root, task_id, request_hash=str(envelope["hash"]))
            result = runner("canon-auditor", envelope, Path(claim["capsule"]).parent)
            calls += 1
            mark_provider_accepted(root, claim["attempt"], str(result["session_id"]))
            try:
                value = _parse_contract_json(str(result["text"]))
                findings = _validate_audit_output(value)
            except BookForgeError as exc:
                last_error = str(exc)
                _set_attempt_failure(root, claim["attempt"], block=attempt_number == 2, reason=last_error)
                if attempt_number == 2:
                    raise BookForgeError(f"Audit job {job['id']} blocked after repair: {last_error}") from exc
                continue
            record = {"schema": 1, "audit": audit_id, "job": job, "findings": findings}
            manifest = stage_outputs(root, claim["attempt"], {output_path: _json_bytes(record)})
            record_execution(
                root,
                claim["attempt"],
                claim["fence"],
                output_hash=_sha256_bytes(_json_bytes(manifest)),
                telemetry=_provider_telemetry(result, envelope, attempt_number),
            )
            promote_task(root, claim["attempt"], claim["fence"])
            all_findings.extend(findings)
            jobs_run.append(job["id"])
            for finding in findings:
                if finding["severity"] in {"blocking", "warning"}:
                    repair_id = f"REPAIR-{re.sub(r'[^A-Z0-9-]', '-', str(finding['id']).upper())}"
                    plan = _load_plan(root)
                    if not any(task["id"] == repair_id for task in plan["tasks"]):
                        add_task(root, repair_id, "reviser", deps=[task_id], priority=95, inputs=list(finding.get("repair_scope", [])))
            break
    return {"audit": audit_id, "candidate_count": len(candidates), "jobs": jobs_run, "calls": calls, "findings": all_findings}


def _normalize_text(value: str) -> str:
    return unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n")).rstrip() + "\n"


def assemble_edition(project: Path | str, book_id: str, language: str) -> dict[str, object]:
    root = _project_root(project)
    canonical = _canonical_locale(language)
    config = _read_json(root / "book-forge.yaml")
    source_language = _canonical_locale(str(config["source_language"]))
    book = next((item for item in list_books(root) if item["id"] == book_id), None)
    if not book:
        raise BookForgeError(f"Unknown book: {book_id}")
    contracts = sorted((root / "books" / book_id / "chapters").glob("CH-*.json"))
    expected = [path.stem for path in contracts]
    if not expected:
        raise BookForgeError("Publication refused: the book has no chapter contracts")
    translated = canonical != source_language
    metadata = None
    if translated:
        locale_root = root / "books" / book_id / "translations" / canonical
        locale_config_path = locale_root / "locale.yaml"
        state_path = locale_root / "state.yaml"
        metadata_path = locale_root / "metadata.yaml"
        if not all(path.is_file() for path in (locale_config_path, state_path, metadata_path)):
            raise BookForgeError("Publication refused: requested translation workspace is missing or incomplete")
        locale_config = _read_json(locale_config_path)
        state = _read_json(state_path)
        metadata = _read_json(metadata_path)
        if (
            locale_config.get("book") != book_id
            or _canonical_locale(str(locale_config.get("locale", ""))) != canonical
            or _canonical_locale(str(metadata.get("locale", ""))) != canonical
            or _canonical_locale(str(state.get("locale", ""))) != canonical
        ):
            raise BookForgeError("Publication refused: locale workspace contains mixed identity or language metadata")
        if (
            state.get("status") != "current"
            or state.get("current") is not True
            or state.get("stale_prose")
            or state.get("boundary_audit")
            or state.get("completed_chapters") != expected
        ):
            raise BookForgeError("Publication refused: translation is stale, incomplete, or awaiting a boundary audit")
        manuscript_root = locale_root / "chapters"
    else:
        state = _read_json(root / "books" / book_id / "state.yaml")
        if state.get("closed_chapters") != expected:
            raise BookForgeError("Publication refused: source chapters are incomplete, stale, or out of order")
        manuscript_root = root / "books" / book_id / "manuscript" / "chapters"
    present = [path.stem for path in sorted(manuscript_root.glob("CH-*.md"))]
    if expected != present:
        raise BookForgeError("Publication refused: edition chapters are missing, extra, or out of order")
    registry = _artifact_registry(root)
    if not translated and registry.get("artifacts"):
        try:
            stale = reconcile_artifacts(root)
        except BookForgeError as exc:
            raise BookForgeError(f"Publication refused by artifact currentness: {exc}") from exc
        source_ids = {f"SOURCE-{book_id}-{chapter}" for chapter in expected}
        if source_ids & set(stale):
            raise BookForgeError("Publication refused: source chapter artifact is stale")
    chapters = []
    input_hashes = {}
    for chapter_id in expected:
        path = manuscript_root / f"{chapter_id}.md"
        text_value = _normalize_text(path.read_text(encoding="utf-8"))
        chapters.append({"id": chapter_id, "title": next((line[2:].strip() for line in text_value.splitlines() if line.startswith("# ")), chapter_id), "markdown": text_value})
        input_hashes[str(path.relative_to(root))] = _sha256_bytes(text_value.encode())
    if translated:
        for name in ("locale.yaml", "metadata.yaml", "state.yaml", "style.md", "glossary.md"):
            path = locale_root / name
            input_hashes[str(path.relative_to(root))] = _file_hash(path)
        title = str(metadata.get("title", "")).strip()
        if not title:
            raise BookForgeError("Publication refused: localized title is missing")
    else:
        book_path = root / "books" / book_id / "book.yaml"
        input_hashes[f"books/{book_id}/book.yaml"] = _file_hash(book_path)
        title = str(book["title"])
    identity = str(uuid.uuid5(uuid.NAMESPACE_URL, f"book-forge:{config['universe']}:{book_id}:{canonical}:edition"))
    assembly = {
        "schema": 1,
        "universe": config["universe"],
        "book": book_id,
        "title": title,
        "author": str(config.get("author", "")),
        "language": canonical,
        "identifier": identity,
        "source_epoch": 946684800,
        "chapters": chapters,
        "input_hashes": dict(sorted(input_hashes.items())),
    }
    assembly["hash"] = _sha256_bytes(_json_bytes(assembly))
    return assembly


def _edition_dependencies(root: Path, assembly: dict[str, object]) -> list[str]:
    book_id = str(assembly["book"])
    language = str(assembly["language"])
    source_language = _canonical_locale(str(_read_json(root / "book-forge.yaml")["source_language"]))
    translated = language != source_language
    registry = _artifact_registry(root)
    dependencies = []
    for chapter in assembly["chapters"]:
        chapter_id = str(chapter["id"])
        if translated:
            artifact_id = f"TRANSLATION-{book_id}-{chapter_id}-{language}"
            path = root / "books" / book_id / "translations" / language / "chapters" / f"{chapter_id}.md"
            kind = "translation-chapter"
        else:
            artifact_id = f"SOURCE-{book_id}-{chapter_id}"
            path = root / "books" / book_id / "manuscript" / "chapters" / f"{chapter_id}.md"
            kind = "source-chapter"
        if artifact_id not in registry["artifacts"]:
            register_artifact(root, artifact_id, kind, path=path)
            registry = _artifact_registry(root)
        dependencies.append(artifact_id)
    return dependencies


def _markdown_xhtml(markdown: str) -> str:
    blocks = re.split(r"\n\s*\n", markdown.strip())
    rendered = []
    for block in blocks:
        stripped = block.strip()
        if stripped == "***":
            rendered.append('<p class="scene-break">* * *</p>')
        elif stripped.startswith("# "):
            rendered.append(f"<h1>{html.escape(stripped[2:].strip())}</h1>")
        elif stripped.startswith("## "):
            rendered.append(f"<h2>{html.escape(stripped[3:].strip())}</h2>")
        else:
            rendered.append(f"<p>{html.escape(' '.join(line.strip() for line in stripped.splitlines()))}</p>")
    return "\n".join(rendered)


def _xhtml_document(title: str, language: str, body: str, *, nav: bool = False) -> bytes:
    nav_namespace = ' xmlns:epub="http://www.idpf.org/2007/ops"' if nav else ""
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<html xmlns="http://www.w3.org/1999/xhtml"{nav_namespace} xml:lang="{html.escape(language)}" lang="{html.escape(language)}">\n'
        f'<head><title>{html.escape(title)}</title><link rel="stylesheet" type="text/css" href="styles/epub.css"/></head>\n'
        f"<body>{body}</body></html>\n"
    ).encode()


def _epub_members(assembly: dict[str, object]) -> list[tuple[str, bytes]]:
    chapters = assembly["chapters"]
    chapter_items = []
    spine_items = []
    nav_items = []
    members: list[tuple[str, bytes]] = [
        ("mimetype", b"application/epub+zip"),
        (
            "META-INF/container.xml",
            b'<?xml version="1.0" encoding="utf-8"?>\n<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>\n',
        ),
    ]
    for index, chapter in enumerate(chapters, start=1):
        filename = f"chapter-{index:04d}.xhtml"
        chapter_items.append(f'<item id="chapter-{index:04d}" href="{filename}" media-type="application/xhtml+xml"/>')
        spine_items.append(f'<itemref idref="chapter-{index:04d}"/>')
        nav_items.append(f'<li><a href="{filename}">{html.escape(str(chapter["title"]))}</a></li>')
        members.append((f"OEBPS/{filename}", _xhtml_document(str(chapter["title"]), str(assembly["language"]), _markdown_xhtml(str(chapter["markdown"])))))
    modified = "2000-01-01T00:00:00Z"
    opf = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id" xml:lang="{lang}">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '<dc:identifier id="book-id">urn:uuid:{identifier}</dc:identifier><dc:title>{title}</dc:title>'
        '<dc:language>{lang}</dc:language><dc:creator>{author}</dc:creator>'
        '<meta property="dcterms:modified">{modified}</meta></metadata>'
        '<manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
        '<item id="css" href="styles/epub.css" media-type="text/css"/>{items}</manifest>'
        '<spine>{spine}</spine></package>\n'
    ).format(
        lang=html.escape(str(assembly["language"])),
        identifier=assembly["identifier"],
        title=html.escape(str(assembly["title"])),
        author=html.escape(str(assembly["author"])),
        modified=modified,
        items="".join(chapter_items),
        spine="".join(spine_items),
    ).encode()
    nav_body = f'<nav epub:type="toc" id="toc"><h1>Contents</h1><ol>{"".join(nav_items)}</ol></nav>'
    css = (Path(__file__).resolve().parents[1] / "assets" / "publication" / "epub.css").read_bytes()
    members.extend(
        [
            ("OEBPS/content.opf", opf),
            ("OEBPS/nav.xhtml", _xhtml_document("Contents", str(assembly["language"]), nav_body, nav=True)),
            ("OEBPS/styles/epub.css", css),
        ]
    )
    first = members[:2]
    rest = sorted(members[2:], key=lambda item: item[0])
    return first + rest


def _deterministic_zip(members: list[tuple[str, bytes]]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED, strict_timestamps=True) as archive:
        for name, value in members:
            info = zipfile.ZipInfo(name, date_time=(2000, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.extra = b""
            info.comment = b""
            archive.writestr(info, value)
    return output.getvalue()


def validate_epub(path: Path | str, *, expected_chapters: int) -> dict[str, object]:
    target = Path(path)
    try:
        with zipfile.ZipFile(target) as archive:
            infos = archive.infolist()
            if not infos or infos[0].filename != "mimetype" or infos[0].compress_type != zipfile.ZIP_STORED:
                raise BookForgeError("EPUB mimetype must be the first stored member")
            if archive.read("mimetype") != b"application/epub+zip":
                raise BookForgeError("EPUB mimetype content is invalid")
            if any(info.date_time != (2000, 1, 1, 0, 0, 0) for info in infos):
                raise BookForgeError("EPUB contains nondeterministic member timestamps")
            names = {info.filename for info in infos}
            opf = ET.fromstring(archive.read("OEBPS/content.opf"))
            namespace = {"opf": "http://www.idpf.org/2007/opf"}
            chapter_items = []
            for item in opf.findall(".//opf:item", namespace):
                href = item.attrib["href"]
                member = f"OEBPS/{href}"
                if member not in names:
                    raise BookForgeError(f"EPUB manifest target is missing: {href}")
                if item.attrib.get("id", "").startswith("chapter-"):
                    chapter_items.append(member)
            if len(chapter_items) != expected_chapters:
                raise BookForgeError("EPUB chapter completeness check failed")
            for member in chapter_items + ["OEBPS/nav.xhtml"]:
                ET.fromstring(archive.read(member))
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
        raise BookForgeError(f"Invalid EPUB structure: {exc}") from exc
    return {"valid": True, "chapters": expected_chapters, "sha256": _file_hash(target)}


def _skill_commit() -> str:
    install_manifest = Path(__file__).resolve().parents[1] / "INSTALL-MANIFEST.json"
    if install_manifest.is_file():
        source_commit = str(_read_json(install_manifest).get("source_commit", ""))
        if re.fullmatch(r"[0-9a-f]{40}", source_commit):
            return source_commit
    result = subprocess.run(
        ["git", "-C", str(Path(__file__).resolve().parents[1]), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() or "uncommitted"


def export_epub(project: Path | str, book_id: str, language: str) -> dict[str, object]:
    root = _project_root(project)
    assembly = assemble_edition(root, book_id, language)
    members = _epub_members(assembly)
    epub_bytes = _deterministic_zip(members)
    output_dir = root / "dist" / book_id / str(assembly["language"])
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{book_id}.epub"
    _write_bytes_atomic(output_path, epub_bytes)
    validation = validate_epub(output_path, expected_chapters=len(assembly["chapters"]))
    manifest = {
        "schema": 1,
        "format": "epub",
        "book": book_id,
        "language": assembly["language"],
        "identifier": assembly["identifier"],
        "source_epoch": assembly["source_epoch"],
        "assembly_hash": assembly["hash"],
        "input_hashes": assembly["input_hashes"],
        "toolchain": {"builder": "book-forge-stdlib-epub-v1", "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"},
        "skill_commit": _skill_commit(),
        "output_sha256": validation["sha256"],
    }
    manifest_path = output_dir / f"{book_id}.epub.manifest.json"
    _write_json(manifest_path, manifest)
    dependencies = _edition_dependencies(root, assembly)
    registry = _artifact_registry(root)
    edition_id = f"EDITION-{book_id}-{assembly['language']}-EPUB"
    if edition_id not in registry["artifacts"]:
        register_artifact(root, edition_id, "epub-edition", path=output_path, dependencies=dependencies)
        registry = _artifact_registry(root)
    manifest_id = f"{edition_id}-MANIFEST"
    if manifest_id not in registry["artifacts"]:
        register_artifact(root, manifest_id, "publication-manifest", path=manifest_path, dependencies=[edition_id])
    return {"path": str(output_path), "manifest": str(manifest_path), "sha256": validation["sha256"], "chapters": len(assembly["chapters"]), "model_calls": 0}


PDF_FONT_HASHES = {
    "regular": "9d7583b7dc9e812afd32a14280c5cac3160012efe50c8d08938f4fea266ff67f",
    "bold": "0af0ff2be8f84910fb21ec5fe1b6b7395e3073250502a334baf6ca2f860c88fe",
}
PDF_FONT_PATHS = {
    "regular": Path("/usr/share/fonts/truetype/noto/NotoSerif-Regular.ttf"),
    "bold": Path("/usr/share/fonts/truetype/noto/NotoSerif-Bold.ttf"),
}


def _verify_pdf_fonts(font_paths: dict[str, Path]) -> dict[str, str]:
    observed = {}
    for style, expected in PDF_FONT_HASHES.items():
        path = Path(font_paths[style])
        if not path.is_file():
            raise BookForgeError(f"Pinned Noto Serif font is missing: {path}")
        value = _file_hash(path)
        if value != expected:
            raise BookForgeError(f"Pinned Noto Serif {style} hash drifted: expected {expected}, found {value}")
        observed[style] = str(value)
    return observed


def validate_pdf(path: Path | str, *, expected_titles: list[str]) -> dict[str, object]:
    target = Path(path)
    if not target.read_bytes().startswith(b"%PDF-"):
        raise BookForgeError("PDF signature is invalid")
    info = subprocess.run(["pdfinfo", "-box", str(target)], capture_output=True, text=True, check=False)
    size_match = re.search(r"Page size:\s+([0-9.]+) x ([0-9.]+) pts", info.stdout)
    if info.returncode != 0 or not size_match or abs(float(size_match.group(1)) - 419.53) > 1 or abs(float(size_match.group(2)) - 595.28) > 1:
        raise BookForgeError("PDF is unreadable or does not use A5 geometry")
    fonts = subprocess.run(["pdffonts", str(target)], capture_output=True, text=True, check=False)
    if fonts.returncode != 0:
        raise BookForgeError("PDF font table is unreadable")
    rows = [line for line in fonts.stdout.splitlines()[2:] if line.strip()]
    if not rows or not all("Book-Forge-Serif" in row for row in rows):
        raise BookForgeError("PDF contains an unexpected font family")
    for row in rows:
        parts = row.split()
        if len(parts) < 8 or parts[-5] != "yes" or parts[-3] != "yes":
            raise BookForgeError("PDF fonts must be embedded with Unicode maps")
    text_result = subprocess.run(["pdftotext", str(target), "-"], capture_output=True, text=True, check=False)
    if text_result.returncode != 0 or any(title not in text_result.stdout for title in expected_titles):
        raise BookForgeError("PDF text or chapter order validation failed")
    return {"valid": True, "sha256": _file_hash(target), "pages": next((line.split(":", 1)[1].strip() for line in info.stdout.splitlines() if line.startswith("Pages:")), None)}


def export_pdf(
    project: Path | str,
    book_id: str,
    language: str,
    *,
    font_paths: dict[str, Path] | None = None,
) -> dict[str, object]:
    root = _project_root(project)
    assembly = assemble_edition(root, book_id, language)
    selected_fonts = PDF_FONT_PATHS if font_paths is None else {key: Path(value) for key, value in font_paths.items()}
    font_hashes = _verify_pdf_fonts(selected_fonts)
    publication_root = Path(__file__).resolve().parents[1] / "assets" / "publication"
    toolchain = publication_root / "python"
    lock_path = toolchain / "uv.lock"
    renderer_path = toolchain / "render_pdf.py"
    css_path = publication_root / "pdf.css"
    if not all(path.is_file() for path in (lock_path, renderer_path, css_path)):
        raise BookForgeError("Pinned PDF publication toolchain is incomplete")
    renderer_assembly = {
        "hash": assembly["hash"],
        "language": assembly["language"],
        "title_html": html.escape(str(assembly["title"]), quote=True),
        "author_html": html.escape(str(assembly["author"]), quote=True),
        "chapters": [
            {"id": chapter["id"], "title": chapter["title"], "xhtml": f'<section id="{chapter["id"]}">{_markdown_xhtml(str(chapter["markdown"]))}</section>'}
            for chapter in assembly["chapters"]
        ],
    }
    machine_dir = root / ".book-forge" / "publication"
    machine_dir.mkdir(parents=True, exist_ok=True)
    assembly_path = machine_dir / f"{assembly['hash']}.pdf-assembly.json"
    _write_json(assembly_path, renderer_assembly)
    output_dir = root / "dist" / book_id / str(assembly["language"])
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{book_id}.pdf"
    temporary_path = output_dir / f".{book_id}.pdf.rendering"
    environment = dict(os.environ)
    environment.update({"TZ": "UTC", "LC_ALL": "C.UTF-8", "PYTHONHASHSEED": "0", "SOURCE_DATE_EPOCH": str(assembly["source_epoch"]), "UV_PYTHON": "3.13.12"})
    result = subprocess.run(
        [
            "uv",
            "run",
            "--locked",
            "--project",
            str(toolchain),
            "python",
            str(renderer_path),
            str(assembly_path),
            str(temporary_path),
            str(selected_fonts["regular"]),
            str(selected_fonts["bold"]),
            str(css_path),
        ],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )
    if result.returncode != 0 or not temporary_path.is_file():
        if temporary_path.exists():
            temporary_path.unlink()
        raise BookForgeError(f"Pinned PDF renderer failed: {result.stderr.strip()}")
    os.replace(temporary_path, output_path)
    validation = validate_pdf(output_path, expected_titles=[str(chapter["title"]) for chapter in assembly["chapters"]])
    toolchain_hashes = {
        "uv_lock": _file_hash(lock_path),
        "renderer": _file_hash(renderer_path),
        "css": _file_hash(css_path),
        "fonts": font_hashes,
    }
    manifest = {
        "schema": 1,
        "format": "pdf",
        "book": book_id,
        "language": assembly["language"],
        "identifier": assembly["identifier"],
        "source_epoch": assembly["source_epoch"],
        "assembly_hash": assembly["hash"],
        "input_hashes": assembly["input_hashes"],
        "toolchain": {"renderer": "weasyprint==69.0", "python": "3.13.12", "hashes": toolchain_hashes},
        "skill_commit": _skill_commit(),
        "output_sha256": validation["sha256"],
    }
    manifest_path = output_dir / f"{book_id}.pdf.manifest.json"
    _write_json(manifest_path, manifest)
    dependencies = _edition_dependencies(root, assembly)
    registry = _artifact_registry(root)
    edition_id = f"EDITION-{book_id}-{assembly['language']}-PDF"
    if edition_id not in registry["artifacts"]:
        register_artifact(root, edition_id, "pdf-edition", path=output_path, dependencies=dependencies)
        registry = _artifact_registry(root)
    manifest_id = f"{edition_id}-MANIFEST"
    if manifest_id not in registry["artifacts"]:
        register_artifact(root, manifest_id, "publication-manifest", path=manifest_path, dependencies=[edition_id])
    return {"path": str(output_path), "manifest": str(manifest_path), "sha256": validation["sha256"], "chapters": len(assembly["chapters"]), "model_calls": 0}


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
    runtime = commands.add_parser("runtime")
    runtime_commands = runtime.add_subparsers(dest="runtime_command", required=True)
    runtime_commands.add_parser("sync")
    migrate = commands.add_parser("migrate")
    migrate.add_argument("mode", choices=("check", "dry-run", "apply", "rollback"))
    pause = commands.add_parser("pause")
    pause.add_argument("--run")
    pause.add_argument("--emergency", action="store_true")
    resume = commands.add_parser("resume")
    resume.add_argument("--run")
    resume.add_argument("--resolve-unknown", action="append", default=[])
    resume.add_argument("--resolve-blocked", action="append", default=[])
    status = commands.add_parser("status")
    status.add_argument("--book")
    status.add_argument("--run")
    status.add_argument("--locale")
    status.add_argument("--repair-view", action="store_true")
    design = commands.add_parser("design")
    design.add_argument("scope", choices=("universe", "book"))
    design.add_argument("--book")
    design.add_argument("--brief", help="JSON string creating books/<book>/book-brief.json")
    design.add_argument("--no-chorus", action="store_true", help="Skip the default chorus ensemble")
    design.add_argument("--chorus-models", help="Comma-separated openrouter/... overrides for this chorus run")
    design.add_argument("--with-chorus-context", action="store_true", help="Inject latest chorus report into designer capsule")
    design.add_argument("--refresh", action="store_true", help="Universe only: re-run the design cycle against the current brief (pre-book only)")
    design.add_argument("--skip-brief", action="store_true", help="Bypass 00-BRIEF gate (or answer usa default)")
    run = commands.add_parser("run")
    run.add_argument("--book")
    run.add_argument("--task")
    run.add_argument("--next", action="store_true")
    translate = commands.add_parser("translate")
    translate.add_argument("action", choices=("add", "next", "run", "status"))
    translate.add_argument("book")
    translate.add_argument("locale")
    audit = commands.add_parser("audit")
    audit_scope = audit.add_mutually_exclusive_group()
    audit_scope.add_argument("--book")
    audit_scope.add_argument("--relation")
    audit_scope.add_argument("--continuity")
    audit.add_argument("--max-jobs", type=int, default=8)
    audit.add_argument("--override", action="store_true")
    chorus = commands.add_parser("chorus")
    chorus_commands = chorus.add_subparsers(dest="chorus_command", required=True)
    chorus_run = chorus_commands.add_parser("run")
    chorus_run.add_argument("--book")
    chorus_run.add_argument("--chorus-models", help="Comma-separated openrouter/... overrides for this run")
    chorus_run.add_argument("--no-chorus", action="store_true", help="No-op (keeps CLI parity)")
    chorus_status = chorus_commands.add_parser("status")
    chorus_status.add_argument("--book")
    chorus_synth = chorus_commands.add_parser("synthesize")
    chorus_synth.add_argument("--book")
    chorus_synth.add_argument("--chorus-models", help="Comma-separated overrides for this synthesize run")
    chorus_apply = chorus_commands.add_parser("apply")
    chorus_apply.add_argument("--pick", help="Comma-separated finding IDs to apply")
    chorus_apply.add_argument("--book")

    export = commands.add_parser("export")
    export.add_argument("book")
    export.add_argument("--lang", required=True)
    export.add_argument("--format", choices=("epub", "pdf", "all"), default="all")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command != "init":
            recover_transactions(args.project)
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
        elif args.command == "runtime" and args.runtime_command == "sync":
            print(json.dumps(sync_runtime(args.project), sort_keys=True))
        elif args.command == "migrate":
            print(json.dumps(migrate_project(args.project, args.mode), sort_keys=True))
        elif args.command == "pause":
            print(json.dumps(pause_run(args.project, run_id=args.run, emergency=args.emergency), sort_keys=True))
        elif args.command == "resume":
            resolutions = {}
            for value in args.resolve_unknown:
                if ":" not in value:
                    raise BookForgeError("--resolve-unknown must be TASK:retry or TASK:abandon")
                task, resolution = value.rsplit(":", 1)
                resolutions[task] = resolution
            blocked = {}
            for value in args.resolve_blocked:
                if ":" not in value:
                    raise BookForgeError("--resolve-blocked must be TASK:retry")
                task, resolution = value.rsplit(":", 1)
                blocked[task] = resolution
            print(json.dumps(resume_run(args.project, run_id=args.run, resolutions=resolutions, blocked_resolutions=blocked), sort_keys=True))
        elif args.command == "status":
            if args.repair_view:
                repair_plan_view(args.project)
            print(json.dumps(status_project(args.project, book_id=args.book, run_id=args.run, locale=args.locale), sort_keys=True))
        elif args.command == "design" and args.scope == "universe":
            print(json.dumps(execute_universe_design(args.project, chorus_models=args.chorus_models, no_chorus=args.no_chorus, with_chorus_context=args.with_chorus_context, refresh=args.refresh, skip_brief=args.skip_brief), sort_keys=True))
        elif args.command == "design" and args.scope == "book":
            if not args.book:
                raise BookForgeError("design book requires --book")
            if args.brief:
                _write_book_brief(args.project, args.book, args.brief)
            print(json.dumps(execute_book_design(args.project, args.book, chorus_models=args.chorus_models, no_chorus=args.no_chorus, with_chorus_context=args.with_chorus_context, skip_brief=args.skip_brief), sort_keys=True))
        elif args.command == "chorus" and args.chorus_command == "run":
            # Standalone chorus without designer
            if args.no_chorus:
                print(json.dumps({"skipped": True, "reason": "--no-chorus"}, sort_keys=True))
            else:
                # Build envelope like designer would, then run chorus
                root = _project_root(args.project)
                cfg = _read_json(root / "book-forge.yaml")
                models = _parse_chorus_models_arg(args.chorus_models, _chorus_models_from_config(cfg)) if args.chorus_models else _chorus_models_from_config(cfg)
                if args.book:
                    book_id = args.book
                    # Need book context like execute_book_design
                    book = next(row for row in list_books(root) if row["id"] == book_id)
                    brief = _book_brief(root, book_id)
                    index = rebuild_indexes(root)
                    context = _book_canon_context(root, book_id, index)
                    imports = sorted({row["id"] for row in context if row["id"] != "worldbuilding.md"})
                    worldbuilding = next((row["content"] for row in context if row["id"] == "worldbuilding.md"), None)
                    envelope = build_envelope(root, role="designer", task_capsule={"scope": "book", "book": book, "brief": brief, "worldbuilding": worldbuilding}, imports=imports, state={}, tools=[], max_output_tokens=3000)
                    scope = {"scope": "book", "book": book_id, "brief": brief}
                else:
                    brief = _read_json(root / "universe" / "design-brief.json")
                    envelope = build_envelope(root, role="designer", task_capsule={"scope": "universe", "brief": brief}, imports=["UNI-0001#kernel"], state={}, tools=[], max_output_tokens=3000)
                    scope = {"scope": "universe", "brief": brief}
                print(json.dumps(run_chorus(args.project, scope, envelope, models), sort_keys=True))
        elif args.command == "chorus" and args.chorus_command == "status":
            print(json.dumps(chorus_status(args.project, book_id=args.book), sort_keys=True))
        elif args.command == "chorus" and args.chorus_command == "synthesize":
            print(json.dumps(chorus_synthesize(args.project, book_id=args.book, chorus_models=args.chorus_models), sort_keys=True))
        elif args.command == "chorus" and args.chorus_command == "apply":
            # Advisory-only: apply is manual; for now just report status.
            # Future: patch selected findings into worldbuilding/brief.
            if args.pick:
                picks = [s.strip() for s in args.pick.split(",") if s.strip()]
                print(json.dumps({"applied": picks, "scope": args.book or "universe", "note": "manual apply — edit canon/brief with synthesis patches"}, sort_keys=True))
            else:
                print(json.dumps(chorus_status(args.project, book_id=args.book), sort_keys=True))
        elif args.command == "run":
            print(json.dumps(run_next(args.project, book_id=args.book, task_id=args.task), sort_keys=True))
        elif args.command == "translate" and args.action == "add":
            print(json.dumps(add_translation(args.project, args.book, args.locale), sort_keys=True))
        elif args.command == "translate" and args.action == "status":
            canonical = _canonical_locale(args.locale)
            print(json.dumps(_read_json(_project_root(args.project) / "books" / args.book / "translations" / canonical / "state.yaml"), sort_keys=True))
        elif args.command == "translate":
            print(json.dumps(translate_next(args.project, args.book, args.locale, run_all=args.action == "run"), sort_keys=True))
        elif args.command == "audit":
            print(json.dumps(audit_continuity(args.project, book_id=args.book, relation_id=args.relation, continuity_id=args.continuity, max_jobs=args.max_jobs, override=args.override), sort_keys=True))
        elif args.command == "export":
            results = {}
            if args.format in {"epub", "all"}:
                results["epub"] = export_epub(args.project, args.book, args.lang)
            if args.format in {"pdf", "all"}:
                results["pdf"] = export_pdf(args.project, args.book, args.lang)
            print(json.dumps(results, sort_keys=True))
        return 0
    except (BookForgeError, OSError, subprocess.SubprocessError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
