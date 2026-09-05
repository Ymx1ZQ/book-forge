#!/usr/bin/env python3
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import html
import hashlib
import io
import contextlib
import json
import os
import re
import shutil
import signal
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
VARIANT_EFFORTS = {"low": "low", "medium": "medium", "high": "high", "max": "max"}
DEFAULT_EFFORT = "high"
ROLE_SPECS = {
    "book-forge-orchestrator": ("primary", "max", 30),
    "designer": ("all", "medium", 10),
    "writer": ("all", "low", 8),
    "cold-reader": ("all", "low", 5),
    "technical-editor": ("all", "high", 7),
    "reviser": ("all", "low", 8),
    "canon-auditor": ("all", "high", 8),
    "translator": ("all", "low", 7),
    "translation-critic": ("all", "high", 6),
    # A reader, not a reviewer. It is given the translation and the locale style and
    # nothing else — see `_locale_reader_capsule` for why the denial is the design.
    "locale-reader": ("all", "medium", 4),
    "judge": ("all", "max", 6),
    "book-forge-smoke": ("primary", "low", 3),
}

# Chorus ensemble — default-on, opt-out via chorus.enabled or --no-chorus.
# Mirrors the user's global opencode.json catalog so every generated project
# exposes the same 7 models without hand-editing provider config.
CHORUS_SYNTHESIZER = "openrouter/deepseek/deepseek-v4-pro-0813"
STYLE_REVIEW_MODELS: list[str] = [
    "openrouter/openai/gpt-5.6-luna",
    "openrouter/z-ai/glm-5.3-flash",
    "openrouter/google/gemini-3.7-flash",
    "openrouter/qwen/qwen3.8-flash",
]
CHORUS_DEFAULT_MODELS: list[str] = [
    "openrouter/deepseek/deepseek-v4-flash-0731",
    "openrouter/deepseek/deepseek-v4-pro-0813",
    "openrouter/z-ai/glm-5.3-flash",
    "openrouter/qwen/qwen3.8-flash",
    "openrouter/moonshotai/kimi-k3",
    "openrouter/x-ai/grok-4.6",
    "openrouter/google/gemini-3.7-flash",
    "openrouter/openai/gpt-5.6-luna",
]
# Prose style presets. A project picks one in book-forge.yaml under `style.preset`;
# the named file is appended to the role prompt of every role that writes or judges
# prose, so the register is part of the envelope hash and a change to it makes
# unwritten work stale rather than silently mixing two registers in one book.
DEFAULT_STYLE_PRESET = "plain-concrete"
STYLE_PROMPT_ROLES = frozenset({"writer", "reviser", "style-review"})


# Per-model provider pin and reasoning ladder — taken from the global config.
# Each entry mirrors provider.openrouter.models[<id>] in ~/.config/opencode/opencode.json.
CHORUS_MODEL_CONFIGS: dict[str, dict[str, object]] = {
    "openrouter/deepseek/deepseek-v4-flash-0731": {
        "provider": {"order": ["deepseek", "baidu"], "only": ["deepseek", "baidu"], "allow_fallbacks": False},
        "default_effort": "high",
        "variants": {"low": "low", "medium": "medium", "high": "high", "max": "max"},
        "limit": {"context": 1310720, "output": 131072},
    },
    "openrouter/deepseek/deepseek-v4-pro-0813": {
        "provider": {"order": ["deepseek", "baidu"], "only": ["deepseek", "baidu"], "allow_fallbacks": False},
        "default_effort": "high",
        "variants": {"low": "low", "medium": "medium", "high": "high", "max": "max"},
    },
    "openrouter/z-ai/glm-5.3": {
        "provider": {"order": ["z-ai"], "only": ["z-ai"], "allow_fallbacks": False},
        "default_effort": "max",
        "variants": {"high": "high", "max": "max"},
    },
    "openrouter/z-ai/glm-5.3-flash": {
        "provider": {"order": ["z-ai"], "only": ["z-ai"], "allow_fallbacks": False},
        "default_effort": "high",
        "variants": {"low": "low", "medium": "medium", "high": "high", "max": "max"},
        "limit": {"context": 1048576, "output": 131072},
    },
    "openrouter/qwen/qwen3.8-max": {
        "provider": {"order": ["alibaba"], "only": ["alibaba"], "allow_fallbacks": False},
        "default_effort": "xhigh",
        "variants": {"medium": "medium", "high": "high", "xhigh": "xhigh"},
    },
    # The only model of the catalog whose OpenRouter parameters omit reasoning_effort:
    # it reasons, but the effort is not steerable, so it declares the one operating
    # point it has rather than a ladder whose steps would all behave the same.
    "openrouter/qwen/qwen3.8-flash": {
        "provider": {"order": ["alibaba"], "only": ["alibaba"], "allow_fallbacks": False},
        "default_effort": "high",
        "variants": {"high": "high"},
        "limit": {"context": 1000000, "output": 131072},
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
    # Released 2026-09-02. Reachable only from OpenCode 1.18.27 or newer: the 1.18.23
    # binary that shipped before it answered `Model not found` however the model was
    # written into the project's config, because the binary validates against a list
    # of its own rather than against `~/.cache/opencode/models.json`.
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


# Every model the catalog configures, not only the default fleet: a project may name
# any of them in chorus.models, and an advisor missing from these maps has no budget
# and no expected pin, so it dies as a non-blocking chorus failure.
CHORUS_ADVISOR_SPECS: dict[str, tuple[str, str, int]] = {
    _chorus_advisor_name(m): ("all", str(CHORUS_MODEL_CONFIGS[m].get("default_effort", DEFAULT_EFFORT)), 6)  # type: ignore[union-attr]
    for m in CHORUS_MODEL_CONFIGS
}
# Dedicated synthesizer agent (pro/max) for chorus synthesis.
CHORUS_SYNTHESIZER_AGENT = "chorus-synthesizer"
# Reverse map advisor agent name -> model id, for resolved-pin verification.
CHORUS_ADVISOR_MODELS: dict[str, str] = {_chorus_advisor_name(m): m for m in CHORUS_MODEL_CONFIGS}
# One writer agent per catalogue model. Drafting a chapter with several models at
# once needs several pins live in the same project, which a single `writer` agent
# cannot hold; these are that agent once per model, sharing its prompt, its budget
# and the project register, one pin apart.
def _writer_candidate_name(model: str) -> str:
    return f"writer-{_chorus_slug(model)}"


# Every model in the catalogue offers `high`, and it is the only step `qwen3.8-flash`
# offers at all. Pinning the candidates to it compares three models rather than
# three efforts, and the winner is kept at the effort its draft was read at.
BAKEOFF_VARIANT = "high"
WRITER_CANDIDATE_MODELS: dict[str, str] = {_writer_candidate_name(m): m for m in CHORUS_MODEL_CONFIGS}


def _project_config(root: Path) -> dict[str, object]:
    """The project's book-forge.yaml, or an empty config where there is none yet."""
    try:
        return _read_json(root / "book-forge.yaml")
    except (OSError, ValueError):
        return {}


def _role_overrides(config: dict[str, object] | None) -> dict[str, dict[str, object]]:
    roles = (config or {}).get("roles")
    if not isinstance(roles, dict):
        return {}
    return {str(name): value for name, value in roles.items() if isinstance(value, dict)}


def _role_pin(config: dict[str, object] | None, role: str) -> tuple[str, str]:
    """The (model, variant) a role runs under, as a full `openrouter/...` path.

    One constant used to answer for every role, so the writer was DeepSeek because
    the canon-auditor was, and the only way to change the prose model was to move
    the whole pipeline onto it. A project names its exception under `roles.<role>`
    in book-forge.yaml and nothing else moves.
    """
    if role in WRITER_CANDIDATE_MODELS:
        return WRITER_CANDIDATE_MODELS[role], BAKEOFF_VARIANT
    if role == CHORUS_SYNTHESIZER_AGENT:
        cfg = CHORUS_MODEL_CONFIGS.get(CHORUS_SYNTHESIZER, {})
        variant = str(cfg.get("default_effort", "max")) if isinstance(cfg, dict) else "max"
        return CHORUS_SYNTHESIZER, variant
    if role in CHORUS_ADVISOR_MODELS:
        return CHORUS_ADVISOR_MODELS[role], CHORUS_ADVISOR_SPECS[role][1]
    if role.startswith("advisor-"):
        # A project may name a chorus model the catalogue never heard of. It gets an
        # agent, a generic lens and the default ladder, and it must keep them: the
        # pin it runs under is the one its own project declared.
        for model in _chorus_models_from_config(config or {}):
            if _chorus_advisor_name(model) == role:
                cfg = CHORUS_MODEL_CONFIGS.get(model, {})
                return model, str(cfg.get("default_effort", DEFAULT_EFFORT))
    if role not in ROLE_SPECS:
        raise BookForgeError(f"Role cannot run headlessly: {role}")
    if role == "translation-critic":
        return _translation_critic_pin(config, _role_pin(config, "translator")[0])
    model, variant = MODEL, ROLE_SPECS[role][1]
    override = _role_overrides(config).get(role)
    if role == "reviser" and not override:
        # The reviser writes prose: it applies the cold reader's and the technical
        # editor's findings to a chapter, sentence by sentence. Choosing a writer by
        # reading three drafts of a chapter and then leaving the repairs to the
        # project default is two hands on the same paragraph — landfall wrote on
        # `glm-5.3-flash` at `high` and repaired on `deepseek-v4-flash-0731` at
        # `low`. A project that wants two hands still gets them, by saying so.
        writer = _role_overrides(config).get("writer")
        if writer:
            return _role_pin(config, "writer")
    if not override:
        return model, variant
    requested_model = str(override.get("model") or "").strip()
    if requested_model:
        if requested_model not in CHORUS_MODEL_CONFIGS:
            raise BookForgeError(
                f"roles.{role}.model names a model the catalogue does not configure: {requested_model}. "
                f"Known: {', '.join(sorted(CHORUS_MODEL_CONFIGS))}"
            )
        model = requested_model
    ladder = CHORUS_MODEL_CONFIGS[model].get("variants") or {}
    requested_variant = str(override.get("variant") or "").strip()
    if requested_variant:
        if requested_variant not in ladder:
            raise BookForgeError(
                f"roles.{role}.variant {requested_variant} is not a step {model} offers: "
                f"{', '.join(sorted(ladder))}"
            )
        variant = requested_variant
    elif variant not in ladder:
        # The role's own effort is not on the new model's ladder, and a step it does
        # not have cannot be asked for. Its declared operating point stands in.
        variant = str(CHORUS_MODEL_CONFIGS[model].get("default_effort", DEFAULT_EFFORT))
    return model, variant


def _translation_critic_pin(config: dict[str, object] | None, translator_model: str) -> tuple[str, str]:
    """The critic's pin, which may never be the translator's.

    A model rereading its own rendering shares the blind spots that produced it
    and approves them, so the pass costs a call and finds nothing. The default is
    the catalogue's judge-grade model, and it steps aside to the project pin when
    the translator already holds it.
    """
    override = _role_overrides(config).get("translation-critic")
    if override and str(override.get("model") or "").strip():
        model = str(override["model"]).strip()
        if model == translator_model:
            raise BookForgeError(
                f"roles.translation-critic.model is the translator's own model ({model}). "
                "A translation reread by the model that wrote it is approved, not audited: "
                "name a different catalogue model, or leave it unset for the default"
            )
        if model not in CHORUS_MODEL_CONFIGS:
            raise BookForgeError(
                f"roles.translation-critic.model names a model the catalogue does not configure: {model}"
            )
        ladder = CHORUS_MODEL_CONFIGS[model].get("variants") or {}
        variant = str(override.get("variant") or "").strip() or str(CHORUS_MODEL_CONFIGS[model].get("default_effort", DEFAULT_EFFORT))
        if variant not in ladder:
            raise BookForgeError(
                f"roles.translation-critic.variant {variant} is not a step {model} offers: {', '.join(sorted(ladder))}"
            )
        return model, variant
    model = CHORUS_SYNTHESIZER if CHORUS_SYNTHESIZER != translator_model else MODEL
    if model == translator_model:
        # Both defaults are the translator's. Any other catalogue model is a better
        # reader than the one being read, and the order is fixed so the choice is
        # the same on every machine.
        model = next(name for name in sorted(CHORUS_MODEL_CONFIGS) if name != translator_model)
    ladder = CHORUS_MODEL_CONFIGS[model].get("variants") or {}
    variant = ROLE_SPECS["translation-critic"][1]
    if variant not in ladder:
        variant = str(CHORUS_MODEL_CONFIGS[model].get("default_effort", DEFAULT_EFFORT))
    return model, variant


def _expected_pin(role: str, config: dict[str, object] | None = None) -> tuple[str, str]:
    """Expected (model_id, variant) of the resolved agent for a role, mirroring _write_agents."""
    model, variant = _role_pin(config, role)
    return model.split("/", 1)[1], variant


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


class ReasoningCeilingSpent(BookForgeError):
    """The model answered, was charged for it, and left no text to read.

    Measured over every translation-critic call landfall has made: 40 calls, 22 of
    which returned `output: 0` after exactly 32000 tokens of reasoning — $1.91 of
    the $3.36 the role has cost, for no characters. It is a third failure class,
    and the two remedies this engine already has are both wrong for it. Re-asking
    with what was wrong about the last answer is right for a malformed one and
    empty here, because there is no answer to say anything about. Waiting is right
    for a provider that went quiet and wrong here, because the provider replied and
    billed. The remedy is to change the question — which is what the designer, the
    audit and `_audit_proposal` each concluded before this.
    """


class ProviderProducedNothing(BookForgeError):
    """The call passed its clock with nothing accepted on the wire.

    Nothing was accepted, so nothing was paid for and the question can simply be
    asked again — unlike `ProviderOutcomeUnknown`, where a session id means a
    retry may pay twice and a person decides. Landfall's re-audit ended on this,
    six windows in, over a call that cost nothing and could have been re-asked.
    """


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
    text = path.read_text(encoding="utf-8")
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        # Option A: YAML-tolerant fallback for outline.yaml (converted to real YAML). pyyaml available.
        try:
            import yaml  # type: ignore
            value = yaml.safe_load(text)
        except Exception as exc:
            raise BookForgeError(f"Invalid project file {path}: {exc}") from exc
        if value is None:
            value = {}
    except OSError as exc:
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


def _next_attempt_id(root: Path, plan: dict[str, object]) -> str:
    """The next attempt id, counting what exists rather than what the plan lists.

    The plan is not the record of what exists: a reset drops the attempts of the
    tasks it drops and a settled run prunes more, while the directories stay
    because they are the audit trail. Allocating from the plan alone walks the
    counter back over occupied ground, and the first claim to land on an occupied
    id dies on the immutability guard that protects that evidence. Landfall hit it
    with 207 directories against 69 planned attempts.
    """
    existing = [str(row["id"]) for row in plan.get("attempts", [])]
    runs = root / ".book-forge" / "runs"
    if runs.is_dir():
        existing.extend(path.name for path in runs.glob("*/attempts/ATT-*") if path.is_dir())
    return _next_id(existing, "ATT-")


def _block_record(block: str) -> dict[str, str]:
    if not re.fullmatch(r"[A-Z][A-Z0-9-]*#[a-z0-9][a-z0-9-]*", block):
        raise BookForgeError(f"Invalid addressable block: {block}")
    return {"block": block, "hash": hashlib.sha256(block.encode()).hexdigest()}


def _opencode_config(chorus_models: list[str] | None = None, config: dict[str, object] | None = None) -> dict[str, object]:
    """Build opencode.json with primary model + chorus catalog + style review models (even if not in chorus.models)."""
    models = chorus_models if chorus_models is not None else CHORUS_DEFAULT_MODELS
    # A role pinned to a model outside the chorus would resolve against a catalogue
    # that never heard of it, and the agent would die on its first call.
    models = list(models)
    for role_name in ROLE_SPECS:
        pinned = _role_pin(config, role_name)[0]
        if pinned not in models:
            models.append(pinned)
    # Ensure primary MODEL is included even if caller filters.
    if MODEL not in models:
        models = [MODEL] + [m for m in models if m != MODEL]
    # Always include style review models (used for chapter style, may not be in chorus.models, e.g., grok for spicy)
    for sm in STYLE_REVIEW_MODELS:
        if sm not in models:
            models.append(sm)
    # Also include grok for spicy rewrite if not already (used via per-tag rule)
    spicy_grok = "openrouter/x-ai/grok-4.6"
    if spicy_grok not in models:
        models.append(spicy_grok)
    models_dict: dict[str, object] = {}
    for mid in models:
        cfg = CHORUS_MODEL_CONFIGS.get(mid)
        if cfg is None:
            # Unknown model: primary ladder, but no provider pin. Borrowing another
            # vendor's pin with allow_fallbacks disabled routes the model to providers
            # that cannot serve it, and the call dies as a non-blocking advisor error.
            cfg = {"default_effort": DEFAULT_EFFORT, "variants": VARIANT_EFFORTS}
        model_id = mid.split("/", 1)[1]
        variants = cfg["variants"]  # type: ignore[index]
        options: dict[str, object] = {"reasoningEffort": cfg["default_effort"]}
        if "provider" in cfg:
            options["provider"] = cfg["provider"]
        entry: dict[str, object] = {
            "options": options,
            "variants": {name: {"reasoningEffort": effort} for name, effort in variants.items()},  # type: ignore[union-attr]
        }
        if "limit" in cfg:
            entry["limit"] = cfg["limit"]  # type: ignore[index]
        models_dict[model_id] = entry
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


def _style_review_enabled(config: dict[str, object]) -> bool:
    """Style review via chorus on chapters: on by default, opt-out with chorus.style_review: false or {enabled:false}."""
    chorus = config.get("chorus")
    if isinstance(chorus, dict) and "style_review" in chorus:
        sr = chorus["style_review"]
        if isinstance(sr, dict):
            return bool(sr.get("enabled", True))
        return bool(sr)
    return True

def _style_review_models(config: dict[str, object]) -> list[str]:
    chorus = config.get("chorus")
    if isinstance(chorus, dict):
        sr = chorus.get("style_review")
        if isinstance(sr, dict) and isinstance(sr.get("models"), list):
            return [m for m in sr["models"] if isinstance(m, str) and "/" in m]
        if isinstance(sr, dict) and isinstance(sr.get("default_models"), list):
            return [m for m in sr["default_models"] if isinstance(m, str) and "/" in m]
    return list(STYLE_REVIEW_MODELS)

def _style_preset_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "assets" / "prompts" / "style"


def available_style_presets() -> list[str]:
    directory = _style_preset_dir()
    if not directory.is_dir():
        return []
    return sorted(path.stem for path in directory.glob("*.md"))


def _style_config(config: dict[str, object]) -> dict[str, object]:
    style = config.get("style")
    if style is None:
        return {}
    if not isinstance(style, dict):
        raise BookForgeError("book-forge.yaml: style must be an object")
    return style


def _style_preset_name(config: dict[str, object]) -> str:
    style = _style_config(config)
    preset = style.get("preset", DEFAULT_STYLE_PRESET)
    if not isinstance(preset, str) or not preset.strip():
        raise BookForgeError("book-forge.yaml: style.preset must be a non-empty string")
    return preset.strip()


def _style_directives(config: dict[str, object]) -> list[str]:
    style = _style_config(config)
    directives = style.get("directives", [])
    if not isinstance(directives, list) or any(not isinstance(row, str) for row in directives):
        raise BookForgeError("book-forge.yaml: style.directives must be a list of strings")
    return [row.strip() for row in directives if row.strip()]


def _style_block(config: dict[str, object]) -> str:
    """The project's prose register, as it is appended to a prose role's prompt.

    An unknown preset fails: falling back to the default would write a whole book
    in a register nobody chose, and the mistake would only surface in the prose.
    """
    preset = _style_preset_name(config)
    path = _style_preset_dir() / f"{preset}.md"
    if not path.is_file():
        known = ", ".join(available_style_presets()) or "none installed"
        raise BookForgeError(f"Unknown style preset: {preset} (available: {known})")
    body = path.read_text(encoding="utf-8").strip()
    lines = [body] if body else []
    directives = _style_directives(config)
    if directives and lines:
        lines.append("")
    lines.extend(f"- {directive}" for directive in directives)
    if not lines:
        return ""
    return "## Prose style\n\n" + "\n".join(lines)


def _style_review_rules(config: dict[str, object]) -> list[dict[str, object]]:
    chorus = config.get("chorus")
    if isinstance(chorus, dict):
        sr = chorus.get("style_review")
        if isinstance(sr, dict) and isinstance(sr.get("rules"), list):
            return [r for r in sr["rules"] if isinstance(r, dict)]
    return []

def _chorus_post_enabled(config: dict[str, object]) -> bool:
    chorus = config.get("chorus")
    if isinstance(chorus, dict) and "post_enabled" in chorus:
        return bool(chorus["post_enabled"])
    return _chorus_enabled(config)


def _prompt_chorus_models(default: list[str] | None = None) -> list[str]:
    """Prompt TTY for chorus model selection at setup start (M1). Returns validated list."""
    default = list(default or CHORUS_DEFAULT_MODELS)
    if not __import__("sys").stdin.isatty():
        return default
    import sys as _sys
    print("Select chorus models for this project:", file=_sys.stderr)
    for i, m in enumerate(CHORUS_DEFAULT_MODELS, 1):
        marker = " [default]" if m in default else ""
        print(f"  {i}. {m}{marker}", file=_sys.stderr)
    print("Enter numbers comma-separated (e.g. 1,3,5), 'all' (default), or 'none' to disable.", file=_sys.stderr)
    print("Choice [all]: ", file=_sys.stderr, end="", flush=True)
    try:
        ans = input().strip().lower()
    except EOFError:
        return default
    if not ans or ans == "all":
        return list(CHORUS_DEFAULT_MODELS)
    if ans == "none":
        return []
    selected: list[str] = []
    for part in ans.split(","):
        part = part.strip()
        if part.isdigit() and 1 <= int(part) <= len(CHORUS_DEFAULT_MODELS):
            selected.append(CHORUS_DEFAULT_MODELS[int(part)-1])
        elif part in CHORUS_DEFAULT_MODELS:
            if part not in selected:
                selected.append(part)
        elif part:
            # allow slug without prefix?
            for full in CHORUS_DEFAULT_MODELS:
                if full.endswith(part) and full not in selected:
                    selected.append(full)
                    break
    return selected or default


def _prompt_style_preset(default: str | None = None) -> str:
    """Prompt TTY for the prose register at setup. Returns a preset name."""
    default = default or DEFAULT_STYLE_PRESET
    presets = available_style_presets()
    if not presets or not __import__("sys").stdin.isatty():
        return default
    import sys as _sys
    print("Select the prose style for this project:", file=_sys.stderr)
    for index, name in enumerate(presets, 1):
        marker = " [default]" if name == default else ""
        print(f"  {index}. {name}{marker}", file=_sys.stderr)
    print(f"Enter a number or a name [{default}]: ", file=_sys.stderr, end="", flush=True)
    try:
        answer = input().strip()
    except EOFError:
        return default
    if not answer:
        return default
    if answer.isdigit() and 1 <= int(answer) <= len(presets):
        return presets[int(answer) - 1]
    if answer in presets:
        return answer
    return default


def _parse_chorus_csv(csv: str | None) -> list[str] | None:
    if csv is None:
        return None
    csv = csv.strip()
    low = csv.lower()
    if low == "none":
        return []
    if low == "all":
        return list(CHORUS_DEFAULT_MODELS)
    if not csv:
        return []
    parts = [s.strip() for s in csv.split(",") if s.strip()]
    # Validate openrouter/... shape
    out = []
    for m in parts:
        if m.startswith("openrouter/") and "/" in m:
            out.append(m)
        else:
            # try to match by slug
            for full in CHORUS_DEFAULT_MODELS:
                if m == full or m == full.split("/",1)[1] or m == _chorus_slug(full):
                    out.append(full)
                    break
    return out


def _write_agents(stage: Path, chorus_models: list[str] | None = None, config: dict[str, object] | None = None) -> None:
    # Ensure style review models have advisors even if not in chorus.models
    if chorus_models is not None:
        extended = list(chorus_models)
        for sm in STYLE_REVIEW_MODELS:
            if sm not in extended:
                extended.append(sm)
        if "openrouter/x-ai/grok-4.6" not in extended:
            extended.append("openrouter/x-ai/grok-4.6")
        chorus_models = extended
    agents = stage / ".opencode" / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    for name, (mode, _variant, steps) in ROLE_SPECS.items():
        model, variant = _role_pin(config, name)
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
            f"mode: {mode}\nmodel: {model}\nvariant: {variant}\nsteps: {steps}\n"
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
    # One writer per candidate model, so a bake-off has every pin it needs live at once.
    writer_mode, _writer_variant, writer_steps = ROLE_SPECS["writer"]
    for mid in models:
        _write_bytes_atomic(
            agents / f"{_writer_candidate_name(mid)}.md",
            (
                "---\n"
                f"description: Book Forge writer role, pinned to {mid}.\n"
                f"mode: {writer_mode}\nmodel: {mid}\nvariant: {BAKEOFF_VARIANT}\nsteps: {writer_steps}\n"
                'permission:\n  "*": deny\n'
                "---\n\n"
                "You are the Book Forge writer role. Return only the task's requested output contract. "
                "You have no tools and must not assume context outside the supplied envelope.\n"
            ).encode("utf-8"),
        )
    allowed = (
        set(ROLE_SPECS)
        | {_chorus_advisor_name(m) for m in models}
        | {_writer_candidate_name(m) for m in models}
        | {CHORUS_SYNTHESIZER_AGENT}
    )
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


def _build_project(stage: Path, title: str, source_language: str, initialize_git: bool, chorus_models: list[str] | None = None, style_preset: str | None = None) -> None:
    _cm = list(chorus_models) if chorus_models is not None else list(CHORUS_DEFAULT_MODELS)
    _style = style_preset or DEFAULT_STYLE_PRESET
    config = {
        "schema": SCHEMA_VERSION,
        "title": title,
        "universe": "UNI-0001",
        "default_continuity": "CNT-0001",
        "source_language": source_language,
        "model": MODEL,
        "context": {"writer_max_input_tokens": 12000, "cold_reader_max_input_tokens": 8000, "technical_editor_max_input_tokens": 10000, "design_max_input_tokens": 16000, "hard_fail_on_overflow": True},
        "audit": {"input_budget": 32000},
        "chorus": {"enabled": True, "post_enabled": True, "models": _cm, "synthesizer": CHORUS_SYNTHESIZER},
        "style": {"preset": _style, "directives": []},
    }
    _write_json(stage / "book-forge.yaml", config)
    _write_json(stage / "opencode.json", _opencode_config(_cm, config))
    _write_agents(stage, _cm, config)
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
    chorus_models: list[str] | None = None,
    style_preset: str | None = None,
) -> dict[str, object]:
    if chorus_models is None:
        chorus_models = _prompt_chorus_models()
    if style_preset is None:
        style_preset = _prompt_style_preset()
    known = available_style_presets()
    if known and style_preset not in known:
        raise BookForgeError(f"Unknown style preset: {style_preset} (available: {', '.join(known)})")
    target = Path(project).expanduser().resolve()
    language = _canonical_language(source_language)
    if target.exists() and any(target.iterdir()):
        return _validate_existing(target, title, language)

    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{target.name}-book-forge-", dir=target.parent))
    target_was_empty = target.exists()
    try:
        _build_project(stage, title, language, initialize_git=not _inside_git_repo(target.parent), chorus_models=chorus_models, style_preset=style_preset)
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
    _write_json(root / "opencode.json", _opencode_config(chorus_models, config))
    _write_agents(root, chorus_models, config)
    return {
        "synced": True,
        "project": str(root),
        "model": MODEL,
        "default_effort": DEFAULT_EFFORT,
        "variants": VARIANT_EFFORTS,
        "roles": {name: dict(zip(("model", "variant"), _role_pin(config, name))) for name in ROLE_SPECS},
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


def add_book(
    project: Path | str, title: str, *, continuity: str = "CNT-0001", author: str = ""
) -> dict[str, object]:
    root = _project_root(project)
    continuity_ids = {str(row["id"]) for row in _continuities(root)["continuities"]}
    if continuity not in continuity_ids:
        raise BookForgeError(f"Unknown continuity: {continuity}")
    books = list_books(root)
    book_id = _next_id([str(book["id"]) for book in books], "BOOK-")
    book = {"schema": SCHEMA_VERSION, "id": book_id, "title": title, "continuity": continuity, "order": len(books) + 1}
    if str(author).strip():
        book["author"] = str(author).strip()
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


# A model call that never answers used to hold the driver until a person noticed;
# one held it for two hours. Every opencode subprocess now runs under a clock.
OPENCODE_CALL_TIMEOUT = 900.0
OPENCODE_PROBE_TIMEOUT = 120.0
_OPENCODE_CONFIG_CACHE: dict[str, str] = {}


class OpencodeTimeout(BookForgeError):
    """An opencode subprocess passed its wall clock and was killed."""

    def __init__(self, what: str, timeout: float, stdout: str, stderr: str):
        super().__init__(f"OpenCode {what} produced no result in {int(timeout)}s")
        self.what = what
        self.timeout = timeout
        self.stdout = stdout
        self.stderr = stderr


def _opencode_config_source() -> Path | None:
    """The config file opencode would read on its own."""
    explicit = os.environ.get("OPENCODE_CONFIG")
    if explicit:
        candidate = Path(explicit)
        return candidate if candidate.is_file() else None
    directory = os.environ.get("OPENCODE_CONFIG_DIR")
    base = Path(directory) if directory else Path.home() / ".config" / "opencode"
    for name in ("opencode.json", "opencode.jsonc", "config.json"):
        candidate = base / name
        if candidate.is_file():
            return candidate
    return None


def _opencode_environment() -> dict[str, str]:
    """The environment every opencode subprocess runs in.

    Two things are taken out. The provider key, so a role cannot reach OpenRouter
    outside its pin. And the operator's MCP servers: opencode starts every server
    the config declares and waits for all of them before it opens a session, which
    `--pure` does not change — that flag disables plugins, not servers. A run stalled
    for two hours in that wait, on a server installed as `uvx <package>@latest` which
    resolves the package over the network at every launch. Ten of them started per
    call, and every book-forge role builds its envelope with no tools and calls none,
    so they were cost and risk with no use. Everything else the operator wrote — the
    provider, the model pin, the permissions — is passed through untouched.
    """
    environment = dict(os.environ)
    environment.pop("OPENROUTER_API_KEY", None)
    source = _opencode_config_source()
    if source is None:
        return environment
    cached = _OPENCODE_CONFIG_CACHE.get(str(source))
    if cached is None or not Path(cached).is_file():
        try:
            config = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return environment
        if not isinstance(config, dict):
            return environment
        config.pop("mcp", None)
        target = Path(tempfile.gettempdir()) / f"book-forge-opencode-{_sha256_bytes(_json_bytes(config))[:16]}.json"
        _write_bytes_atomic(target, _json_bytes(config))
        cached = str(target)
        _OPENCODE_CONFIG_CACHE[str(source)] = cached
    environment["OPENCODE_CONFIG"] = cached
    return environment


def _run_opencode_process(argv: list[str], *, cwd: Path | str, env: dict[str, str], timeout: float, what: str) -> subprocess.CompletedProcess:
    """Run one opencode subprocess, killing its whole group if the clock runs out.

    The group and not the child: opencode is a supervisor, and killing it alone
    leaves whatever it started running.
    """
    process = subprocess.Popen(
        argv,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            process.kill()
        stdout, stderr = process.communicate()
        raise OpencodeTimeout(what, timeout, stdout or "", stderr or "")
    return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)


def _session_id_in(stream: str) -> str | None:
    """The first session id opencode put on the wire, if it got that far."""
    for line in (stream or "").splitlines():
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("sessionID"):
            return str(event["sessionID"])
    return None


def _opencode_binary() -> str:
    binary = shutil.which("opencode")
    if binary:
        return binary
    fallback = Path.home() / ".opencode" / "bin" / "opencode"
    if fallback.is_file():
        return str(fallback)
    raise BookForgeError("OpenCode is not installed")


OPENCODE_MINIMUM = (1, 18, 18)
# What the engine actually calls. A CLI without one of these does not fail as a
# missing capability, it fails as something else entirely: an argv whose `--file`
# swallowed the prompt reported `File not found: Process the attached envelope`.
OPENCODE_RUN_FLAGS = ("--agent", "--file", "--format", "--variant", "--dir")
_OPENCODE_CHECKED: set[str] = set()


def _opencode_version(binary: str) -> tuple[str, tuple[int, ...]]:
    raw = subprocess.run([binary, "--version"], capture_output=True, text=True, check=True).stdout.strip()
    return raw, tuple(int(value) for value in re.findall(r"\d+", raw)[:3])


def _verify_opencode_cli(binary: str) -> None:
    """Check once per process that the CLI can do what the engine calls.

    Cheap by design — a version string and two help texts, no network — because it
    runs before the first dispatch and its whole purpose is to turn an unmet
    requirement into a sentence that names the flag.
    """
    if binary in _OPENCODE_CHECKED:
        return
    raw, numbers = _opencode_version(binary)
    if numbers < OPENCODE_MINIMUM:
        raise BookForgeError(
            f"book-forge requires OpenCode {'.'.join(map(str, OPENCODE_MINIMUM))} or newer; found {raw}"
        )
    help_result = subprocess.run([binary, "run", "--help"], capture_output=True, text=True, check=True)
    help_text = help_result.stdout + help_result.stderr
    missing = [flag for flag in OPENCODE_RUN_FLAGS if flag not in help_text]
    if missing:
        raise BookForgeError(
            f"OpenCode {raw} does not support {', '.join(missing)} on `run`; book-forge dispatches every "
            "role through it and cannot run without them"
        )
    probe = subprocess.run([binary, "debug", "agent", "--help"], capture_output=True, text=True)
    if probe.returncode != 0:
        raise BookForgeError(
            f"OpenCode {raw} has no `debug agent` subcommand; book-forge verifies each role's model pin "
            "with it before every call"
        )
    _OPENCODE_CHECKED.add(binary)


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
    for required in ("--format", "--session", *OPENCODE_RUN_FLAGS):
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
    if (
        role not in ROLE_SPECS and role not in CHORUS_ADVISOR_SPECS and role not in WRITER_CANDIDATE_MODELS
    ) or role in {"book-forge-orchestrator", "book-forge-smoke"}:
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


# A deterministic failure is one a retry can answer: the answer was truncated, or
# unparseable, or failed validation. `outcome_unknown` is not one of them — the
# provider accepted the call and a retry may pay for it twice, which is a judgement
# about money and belongs to a person.
AUTO_RECOVERABLE_ATTEMPT_STATES = frozenset({"failed_length", "validation_failed", "orphaned"})
MAX_AUTO_RETRIES = 3


def _task_needs_a_person(plan: dict[str, object]) -> list[str]:
    """Tasks whose state only a person can resolve."""
    unknown = {str(row["task"]) for row in plan.get("attempts", []) if row.get("state") == "outcome_unknown"}
    return sorted(unknown | {str(row["id"]) for row in plan["tasks"] if row.get("state") == "outcome_unknown"})


def _last_failure(plan: dict[str, object], task_id: str) -> dict[str, object] | None:
    rows = [row for row in plan.get("attempts", []) if str(row.get("task")) == task_id and row.get("failure")]
    return rows[-1] if rows else None


def recover_before_dispatch(project: Path | str, *, task_id: str | None = None, now: float | None = None) -> dict[str, object]:
    """Undo the parking a deterministic failure left behind, so the next call proceeds.

    Three things used to stop a book and wait for a person to type what the engine
    already knew: an attempt whose lease expired and which the provider never
    accepted, a task blocked by a truncated or unparseable answer, and a run blocked
    by nothing but those. All three are cleared here, up to MAX_AUTO_RETRIES per task.
    An `outcome_unknown` anywhere is left exactly as it is.
    """
    root = _project_root(project)
    # A stale claim splits in two, and only `recover_run` knows the difference: an
    # attempt the provider never accepted goes back to pending, while one it did
    # accept becomes outcome_unknown and blocks the run, because a retry may pay for
    # a call that already completed. Without this the accepted case sat `running` for
    # ever and the next command answered `Task is not ready` — the one failure a
    # person must judge was the one nobody was told about.
    stale = recover_run(root, now=now)
    plan = _load_plan(root)
    changed = False
    recovered: list[str] = []
    exhausted: list[dict[str, object]] = []
    blocked = [row for row in plan["tasks"] if row.get("state") == "blocked"]
    for task in blocked:
        if task_id is not None and str(task["id"]) != task_id:
            continue
        failure = _last_failure(plan, str(task["id"]))
        if failure is not None and str(failure.get("state")) not in AUTO_RECOVERABLE_ATTEMPT_STATES:
            continue
        used = int(task.get("auto_retries", 0))
        if used >= MAX_AUTO_RETRIES:
            exhausted.append({"task": str(task["id"]), "retries": used, "failure": str((failure or {}).get("failure", ""))})
            continue
        task["auto_retries"] = used + 1
        task["state"] = "pending"
        task.pop("attempt", None)
        recovered.append(str(task["id"]))
        changed = True
    if changed:
        _save_plan(root, plan)
        render_plan(root)
    if recovered:
        print(f"[recover] returned to pending after a recoverable failure: {', '.join(recovered)}", file=sys.stderr)
    control = _control(root)
    if control.get("active_run"):
        run_path = _run_path(root, str(control["active_run"]))
        run = _read_json(run_path)
        still_blocked = [row for row in plan["tasks"] if row.get("state") == "blocked"]
        if run.get("state") == "blocked" and not still_blocked and not _task_needs_a_person(plan):
            run["state"] = "running"
            run["desired_state"] = "running"
            _write_json(run_path, run)
    return {
        "recovered": sorted(set(recovered) | set(_task_of(plan, stale["orphaned"]))),
        "exhausted": exhausted,
        "needs_a_person": _task_needs_a_person(plan),
    }


def _task_of(plan: dict[str, object], attempt_ids: list[str]) -> list[str]:
    index = {str(row["id"]): str(row.get("task", "")) for row in plan.get("attempts", [])}
    return [index[value] for value in attempt_ids if index.get(value)]


# A lease is not a timeout, and 300 seconds was being used as one. It exists so a
# claim abandoned by a dead process can be reclaimed, which means it has to outlive
# the longest a *live* call can legitimately take — and that length is not a matter
# of opinion, it is the point at which this engine itself gives up.
#
# Measured over 294 calls on one book, against the 300s this used to be:
#   translation-critic  51 calls, median 433s, max 674s — 46 over the lease
#   reviser             52 calls, median 229s, max 609s — 14 over
#   writer              18 calls, median 309s, max 900s —  9 over
#   canon-auditor       24 calls, median 176s, max 900s —  5 over
#   technical-editor    28 calls, median 251s, max 308s —  4 over
# Half the roles ran routinely with a lapsed claim, and whether that became a
# failure was decided by whether anything called recovery inside the window. It
# surfaced as `Only a running attempt can be marked accepted`, three times in one
# night, looking like an intermittent defect of one role.
#
# The cost of the other direction, stated: a genuinely dead process holds its claim
# for a third longer before anyone can reclaim it. That is the right side to err on
# — reclaiming early breaks work that is still running.
LEASE_SECONDS = OPENCODE_CALL_TIMEOUT * 4 / 3


def claim_task(
    project: Path | str,
    task_id: str,
    *,
    request_hash: str,
    now: float | None = None,
    lease_seconds: float = LEASE_SECONDS,
) -> dict[str, object]:
    root = _project_root(project)
    current_time = time.time() if now is None else now
    if not provider_ready(root, now=current_time):
        raise BookForgeError("Provider is rate-limited; dispatch is not yet eligible")
    recover_before_dispatch(root, task_id=task_id, now=current_time)
    run = start_run(root, now=current_time)
    if run["state"] != "running":
        raise BookForgeError(f"Run does not accept dispatch while {run['state']}")
    if not re.fullmatch(r"[0-9a-f]{64}", request_hash):
        raise BookForgeError("request_hash must be a lowercase SHA-256")
    plan = _load_plan(root)
    active_attempts = [row for row in plan["attempts"] if row["state"] in {"running", "promotion_pending"}]
    if len(active_attempts) >= 4:
        raise BookForgeError("Maximum subagent concurrency is four")
    ready_ids = {str(task["id"]) for task in ready_frontier(root)}
    if task_id not in ready_ids:
        raise BookForgeError(f"Task is not ready: {task_id}")
    control = _control(root)
    control["fencing_counter"] = int(control["fencing_counter"]) + 1
    fence = int(control["fencing_counter"])
    attempt_id = _next_attempt_id(root, plan)
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
        "lease_seconds": float(lease_seconds),
        # Who is holding this. A stopped driver's claim used to be held for the rest
        # of its lease although the process was demonstrably gone.
        "owner_pid": os.getpid(),
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
        expected_model, expected_variant = _role_pin(_project_config(root), role)
        expected_models = {expected_model, expected_model.split("/", 1)[1]}
        observed_model = str(telemetry.get("model"))
        if telemetry.get("provider") != "openrouter" or observed_model not in expected_models:
            raise BookForgeError("Provider receipt does not match the pinned OpenRouter model")
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


def _scoped_git_commit(root: Path, paths: list[str], transaction_id: str, *, message: str | None = None) -> tuple[str | None, bool]:
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
        ["git", "-C", str(root), "commit", "-m", message or f"book-forge: promote {transaction_id}", "--", *paths],
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


def _refresh_registry_hashes(root: Path, rows: list[dict[str, object]]) -> None:
    """Keep the artifact registry in step with the pipeline's own promoted writes.

    A promoted transaction is the only sanctioned way a derived file changes, so
    an artifact registered on one of its paths must adopt the installed hash.
    Without this the row stays pinned to the first promote and the next
    `reconcile_artifacts` reads the pipeline's write as a hand edit."""
    registry_path = root / ".book-forge" / "artifact-deps.json"
    if not registry_path.is_file():
        return
    registry = _artifact_registry(root)
    installed = {str(row["path"]): str(row["target_hash"]) for row in rows}
    changed = False
    for artifact in registry.get("artifacts", {}).values():
        promoted_hash = installed.get(str(artifact["path"]))
        if promoted_hash is not None and promoted_hash != artifact["hash"]:
            artifact["hash"] = promoted_hash
            changed = True
    if changed:
        _write_json(registry_path, registry)


def _promoted_path_hashes(root: Path) -> dict[str, set[str]]:
    """Hashes the pipeline itself installed at each path, from transaction journals.

    Provenance for `reconcile_artifacts`: a derived file whose current hash was
    installed by a transaction is a pipeline write, not tampering."""
    promoted: dict[str, set[str]] = {}
    transactions = root / ".book-forge" / "transactions"
    if not transactions.is_dir():
        return promoted
    for path in sorted(transactions.glob("TXN-*/journal.json")):
        try:
            journal = _read_json(path)
        except (OSError, ValueError, BookForgeError):
            continue
        installed = {str(value) for value in journal.get("installed", [])}
        for row in journal.get("files", []):
            if str(row.get("path")) in installed:
                promoted.setdefault(str(row["path"]), set()).add(str(row["target_hash"]))
    return promoted


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

    _refresh_registry_hashes(root, journal["files"])

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
    # Chorus rounds are billed but bypass the attempt machinery, so their telemetry
    # is collected from the round file instead of an execution receipt.
    for path in sorted((root / ".book-forge" / "repairs").glob("*/*/repair-telemetry.json")):
        round_value = _read_json(path)
        for entry in round_value.get("advisors", []):
            receipts.append({**entry, "task": f"REPAIR-{round_value.get('book', '')}", "_run": "repair", "_path": str(path.relative_to(root)), "_role": "designer", "book": round_value.get("book")})
    for path in sorted((root / ".book-forge" / "chorus").glob("*/*/chorus-telemetry.json")):
        round_value = _read_json(path)
        for entry in round_value.get("advisors", []):
            if not isinstance(entry, dict):
                continue
            row = dict(entry)
            row["task"] = str(round_value.get("task", ""))
            row["_run"] = f"chorus/{path.parts[-3]}/{path.parts[-2]}"
            row["_path"] = str(path.relative_to(root))
            row["_role"] = str(entry.get("role", "unknown"))
            receipts.append(row)

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
        # A chorus advisor and the style-review models run their own pinned model by
        # design; measuring them against the primary pin turned every style review into
        # a violation. Each is checked against its own pin instead.
        try:
            own = _expected_pin(role, _project_config(root))[0]
            pinned = {own, f"openrouter/{own}"}
        except BookForgeError:
            pinned = set()
        if receipt.get("provider") != "openrouter" or (pinned and str(receipt.get("model")) not in pinned):
            violations.append({"code": "model_pin", "task": task_id, "role": role, "detail": "provider or model differs from the role's OpenRouter pin"})
        try:
            expected_variant = _expected_pin(role, _project_config(root))[1]
        except BookForgeError:
            expected_variant = None
        if expected_variant and receipt.get("variant") != expected_variant:
            violations.append({"code": "variant_pin", "task": task_id, "detail": f"expected {expected_variant}, found {receipt.get('variant')}"})
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
    if len(active) > 4:
        violations.append({"code": "concurrency", "detail": f"{len(active)} active attempts > 4"})
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


def _orphan_stale_attempts(plan: dict[str, object]) -> bool:
    """Orphan running attempts that never got provider acceptance and whose lease expired (definitively dead)."""
    import time as _time
    now = _time.time()
    changed = False
    for attempt in plan.get("attempts", []):
        if attempt.get("state") != "running":
            continue
        if attempt.get("provider_accepted"):
            continue
        lease = attempt.get("lease_expires_at")
        if isinstance(lease, (int, float)) and lease < now:
            attempt["state"] = "orphaned"
            # Also reset the task to pending so it can be retried
            task_id = attempt.get("task")
            for task in plan.get("tasks", []):
                if task.get("id") == task_id and task.get("state") == "running":
                    task["state"] = "pending"
                    break
            changed = True
    return changed

def _settle_run(project: Path | str) -> dict[str, object] | None:
    root = _project_root(project)
    # Auto-heal: orphan stale never-accepted attempts so ordinary pause can drain
    try:
        plan = _load_plan(root)
        if _orphan_stale_attempts(plan):
            _save_plan(root, plan)
            render_plan(root)
    except Exception:
        pass
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
    current = time.time() if now is None else now
    attempt["accepted_at"] = current
    # One claim can cover many calls — a design is a spine and five chapter slices,
    # twenty minutes against a five-minute lease — and nothing else renews it. Past
    # the fifth minute a working attempt looked abandoned, and any recovery running
    # in that window converted live work into an unknown outcome and threw it away.
    # A provider answering is the one moment the work is demonstrably alive.
    attempt["heartbeat_at"] = current
    window = float(attempt.get("lease_seconds", LEASE_SECONDS))
    attempt["lease_expires_at"] = max(float(attempt.get("lease_expires_at", 0.0)), current + window)
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
    # Ordinary pause should not wait forever on dead never-accepted attempts
    try:
        plan = _load_plan(root)
        if _orphan_stale_attempts(plan):
            _save_plan(root, plan)
            render_plan(root)
    except Exception:
        pass
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


def _collect_validation_failures(plan: dict[str, object], task_id: str, limit: int = 5) -> list[object]:
    rows = [row for row in plan["attempts"] if row.get("task") == task_id]
    seen: set[str] = set()
    out: list[object] = []
    for row in reversed(rows):
        if row.get("state") not in {"validation_failed", "orphaned"}:
            continue
        failure = row.get("failure")
        if not failure:
            continue
        key = str(failure)[:500]
        if key in seen:
            continue
        seen.add(key)
        out.append(failure)
        if len(out) >= limit:
            break
    return out


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
    # A killed driver leaves the run marked running with an accepted attempt whose
    # lease has expired. Recovering first turns that into the outcome_unknown the
    # caller is here to resolve, instead of refusing on a state resume can reach
    # itself and making them find `pause --emergency` by reading the source.
    recover_run(root)
    run_path = _run_path(root, str(control["active_run"]))
    run = _read_json(run_path)
    if run["state"] not in {"paused", "blocked"}:
        raise BookForgeError(
            f"Run cannot resume while {run['state']}: nothing is waiting on a decision. "
            "Use `pause` to stop it first, or let `advance` drive it."
        )
    plan = _load_plan(root)
    unknown_tasks = {str(task["id"]): task for task in plan["tasks"] if task["state"] == "outcome_unknown"}
    choices = resolutions or {}
    if set(unknown_tasks) != set(choices):
        raise BookForgeError("Every outcome_unknown task requires an explicit retry or abandon resolution")
    for task_id, task in unknown_tasks.items():
        choice = choices[task_id]
        if choice not in {"retry", "abandon"}:
            raise BookForgeError(f"Invalid unknown resolution for {task_id}: {choice}")
        # The task may carry no attempt: lease recovery marks a task
        # outcome_unknown from its attempt's side, and `_set_attempt_failure` pops
        # the pointer, so the two together produce a task in the one state that
        # requires a resolution and no attempt to resolve. Landfall reached it, and
        # `resume` died on `KeyError: 'attempt'` — the recovery command crashing on
        # the state its own recovery writes. The most recent attempt of the task is
        # the one the resolution is about.
        attempt = None
        if task.get("attempt"):
            attempt = _attempt(plan, str(task["attempt"]))
        else:
            owned = [row for row in plan["attempts"] if str(row.get("task")) == task_id]
            attempt = owned[-1] if owned else None
        if choice == "retry":
            if attempt is not None:
                attempt["state"] = "orphaned"
                attempt["resolution"] = "retry"
            task["state"] = "pending"
            task.pop("attempt", None)
        else:
            if attempt is not None:
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
        if attempt["state"] != "running":
            continue
        expired = current_time > float(attempt.get("lease_expires_at", current_time + 1))
        owner = attempt.get("owner_pid")
        # A claim whose owner is no longer running is stale now, not when the clock
        # says so. The lease remains the fallback for a claim this machine cannot
        # answer for.
        orphaned_owner = isinstance(owner, int) and owner != os.getpid() and not _pid_alive(owner)
        if expired or orphaned_owner:
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


def _source_chapter_artifact(root: Path, book_id: str, chapter_id: str) -> tuple[str, dict[str, object]]:
    """The one true row for a source chapter, wherever it gets registered from."""
    contract_path = root / "books" / book_id / "chapters" / f"{chapter_id}.json"
    contract = _read_json(contract_path) if contract_path.is_file() else {}
    pov = contract.get("pov")
    return (
        f"SOURCE-{book_id}-{chapter_id}",
        {
            "kind": "source-chapter",
            "path": root / "books" / book_id / "manuscript" / "chapters" / f"{chapter_id}.md",
            "dependencies": list(contract.get("imports", [])),
            "entities": [str(pov)] if pov else [],
        },
    )


def _translation_chapter_artifact(
    root: Path, book_id: str, chapter_id: str, locale: str, previous_id: str | None = None
) -> tuple[str, dict[str, object]]:
    dependencies = [
        f"SOURCE-{book_id}-{chapter_id}",
        f"LOCALE-STYLE-{book_id}-{locale}",
        f"LOCALE-GLOSSARY-{book_id}-{locale}",
        f"LOCALE-METADATA-{book_id}-{locale}",
    ]
    if previous_id:
        dependencies.append(previous_id)
    return (
        f"TRANSLATION-{book_id}-{chapter_id}-{locale}",
        {
            "kind": "translation-chapter",
            "path": root / "books" / book_id / "translations" / locale / "chapters" / f"{chapter_id}.md",
            "dependencies": dependencies,
            "entities": [],
        },
    )


def _ensure_artifact(root: Path, artifact_id: str, spec: dict[str, object]) -> bool:
    """Register a missing row, or complete one an earlier call site left partial.

    Registration is opportunistic — export knows a chapter's path but not its
    canon imports — and `if id not in registry` used to make the first caller's
    partial knowledge permanent, leaving rows that can never go stale. Returns
    True when the registry changed."""
    target = Path(str(spec["path"]))
    registry = _artifact_registry(root)
    row = registry["artifacts"].get(artifact_id)
    if row is None:
        if not target.is_file():
            return False
        register_artifact(
            root,
            artifact_id,
            str(spec["kind"]),
            path=target,
            dependencies=list(spec.get("dependencies") or []),
            entities=list(spec.get("entities") or []),
        )
        return True
    known = list(row.get("dependencies", []))
    missing = [dependency for dependency in (spec.get("dependencies") or []) if dependency not in known]
    entities = [entity for entity in (spec.get("entities") or []) if entity not in row.get("entities", [])]
    if not missing and not entities:
        return False
    index = rebuild_indexes(root)
    dependencies = known + missing
    row["dependencies"] = dependencies
    row["dependency_hashes"] = {
        dependency: _dependency_hash(root, dependency, registry, index) for dependency in dependencies
    }
    row["entities"] = list(row.get("entities", [])) + entities
    registry["edges"] = sorted(
        [{"from": dependency, "to": target_id} for target_id, artifact in registry["artifacts"].items() for dependency in artifact.get("dependencies", [])],
        key=lambda edge: (edge["from"], edge["to"]),
    )
    _write_json(root / ".book-forge" / "artifact-deps.json", registry)
    _write_derived_dependency_views(root)
    return True


def _ensure_translation_artifacts(root: Path, book_id: str, locale: str, chapter_ids: list[str]) -> list[str]:
    """Register the SOURCE/TRANSLATION chain for chapters already promoted.

    Rows are written after the promote, so a chapter translated before the
    registry existed leaves a hole the next chapter cannot depend on: its
    `previous` dependency dangles and registration raises with the output
    already on disk. Walking the promoted chapters in order closes the chain."""
    _ensure_locale_artifacts(root, book_id, locale)
    changed: list[str] = []
    previous_id: str | None = None
    for chapter_id in chapter_ids:
        source_id, source_spec = _source_chapter_artifact(root, book_id, chapter_id)
        if _ensure_artifact(root, source_id, source_spec):
            changed.append(source_id)
        if source_id not in _artifact_registry(root)["artifacts"]:
            continue
        translation_id, translation_spec = _translation_chapter_artifact(root, book_id, chapter_id, locale, previous_id)
        if not Path(str(translation_spec["path"])).is_file():
            continue
        if _ensure_artifact(root, translation_id, translation_spec):
            changed.append(translation_id)
        previous_id = translation_id
    return changed


def backfill_artifacts(project: Path | str, *, book: str | None = None, locale: str | None = None) -> dict[str, object]:
    """Complete the artifact registry for work promoted before it tracked that work.

    Idempotent: registers rows that are missing, completes rows whose
    dependencies were never recorded, and leaves everything else untouched."""
    root = _project_root(project)
    changed: list[str] = []
    for book_path in sorted((root / "books").glob("*/book.yaml")):
        book_id = book_path.parent.name
        if book and book_id != book:
            continue
        chapters = [path.stem for path in sorted((book_path.parent / "manuscript" / "chapters").glob("CH-*.md"))]
        for chapter_id in chapters:
            artifact_id, spec = _source_chapter_artifact(root, book_id, chapter_id)
            if _ensure_artifact(root, artifact_id, spec):
                changed.append(artifact_id)
        for state_path in sorted((book_path.parent / "translations").glob("*/state.yaml")):
            locale_id = state_path.parent.name
            if locale and locale_id != locale:
                continue
            state = _read_json(state_path)
            completed = [str(value) for value in state.get("completed_chapters", [])]
            ordered = [chapter for chapter in chapters if chapter in completed]
            changed.extend(_ensure_translation_artifacts(root, book_id, locale_id, ordered))
    return {"backfilled": sorted(set(changed)), "count": len(set(changed))}


def reconcile_artifacts(project: Path | str) -> list[str]:
    root = _project_root(project)
    index = rebuild_indexes(root)
    registry = _artifact_registry(root)
    direct_stale: set[str] = set()
    promoted_hashes: dict[str, set[str]] | None = None
    for artifact_id, artifact in registry["artifacts"].items():
        target = root / artifact["path"]
        current_hash = _file_hash(target)
        if current_hash != artifact["hash"]:
            if not artifact.get("authored"):
                # A registry desynced by an earlier promote is repairable: accept the
                # hash only if a transaction journal shows the pipeline installed it.
                if promoted_hashes is None:
                    promoted_hashes = _promoted_path_hashes(root)
                if current_hash not in promoted_hashes.get(str(artifact["path"]), set()):
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
    "designer": (20000, 20000),
    "writer": (12000, 6000),
    "cold-reader": (8000, 2500),
    "technical-editor": (10000, 3000),
    "reviser": (14000, 8000),
    "canon-auditor": (32000, 3500),
    "translator": (16000, 6000),
    # Every finding quotes the source, the translation and the replacement, so a
    # chapter's worth of them is long. Landfall's first critic answer was cut
    # mid-string at 3000 and the whole pass was lost.
    "translation-critic": (24000, 9000),
    # It reads one chapter and answers in a few quoted stumbles: a small question
    # deliberately, since a reader who is asked for an essay starts writing one.
    "locale-reader": (16000, 3000),
    "judge": (10000, 2000),
}
# Chorus advisors reuse designer/auditor budgets (advisory, same context).
for _adv in list(CHORUS_ADVISOR_SPECS):
    ROLE_BUDGETS[_adv] = (16000, 3000)
ROLE_BUDGETS[CHORUS_SYNTHESIZER_AGENT] = (16000, 4000)
# A writer candidate is the writer: same envelope, same allowance, another pin.
for _cand in WRITER_CANDIDATE_MODELS:
    ROLE_BUDGETS[_cand] = ROLE_BUDGETS["writer"]


def _enforce_budgets(root: Path) -> bool:
    """Whether the advisory ceilings are walls for this project.

    They were, and a book stopped every time its canon outgrew a number chosen
    months earlier. Off by default: the only wall that cannot be argued with is
    what the model can physically accept.
    """
    config_path = root / "book-forge.yaml"
    if not config_path.is_file():
        return False
    ctx = _read_json(config_path).get("context")
    return bool(ctx.get("enforce_budgets", False)) if isinstance(ctx, dict) else False


def _model_input_window(role: str, max_output_tokens: int, model: str = MODEL) -> int:
    """What the pinned model can actually accept, less its own answer.

    A quarter of the window is the hard wall: far above any real envelope, so it
    never stops a book, and low enough that a runaway accumulation still trips it
    instead of buying a million-token call.
    """
    limits = CHORUS_MODEL_CONFIGS.get(model, {}).get("limit") or {}
    context_window = int(limits.get("context") or 0)
    if context_window <= 0:
        return ROLE_BUDGETS[role][0] * 8
    return max(ROLE_BUDGETS[role][0], context_window // 4 - max_output_tokens - 768)


def _envelope_input_budget(root: Path, role: str) -> int:
    """Per-role advisory envelope size; project override wins over ROLE_BUDGETS.

    `book-forge.yaml` may raise any role's envelope ceiling under
    `context.<role>_max_input_tokens` (role dashes become underscores, e.g.
    `context.technical_editor_max_input_tokens` for the technical-editor).
    Legacy aliases remain: `context.design_max_input_tokens` (designer and
    chorus advisors, which share the same context contract) and
    `audit.input_budget` (canon-auditor). Defaults to the fixed role budget.
    Fail closed on a malformed override value."""
    default_input, _ = ROLE_BUDGETS[role]
    config_path = root / "book-forge.yaml"
    if config_path.is_file():
        config = _read_json(config_path)
        ctx = config.get("context")
        knob_name = f"{role.replace('-', '_')}_max_input_tokens"
        if isinstance(ctx, dict):
            knob = ctx.get(knob_name)
            if knob is not None:
                try:
                    return int(knob)
                except (TypeError, ValueError):
                    raise BookForgeError(f"context.{knob_name} must be an integer, got {knob!r}")
            if role == "designer" or role.startswith("advisor-"):
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
    prompt_role: str | None = None,
) -> dict[str, object]:
    root = _project_root(project)
    if role not in ROLE_BUDGETS:
        raise BookForgeError(f"Role has no envelope budget: {role}")
    config = _project_config(root)
    try:
        pinned_model, pinned_variant = _role_pin(config, role)
    except BookForgeError:
        # An advisory role the project never declared has no pin to resolve. The
        # envelope still gets built and the call still runs; what it records is the
        # engine default, which is what it recorded for every role before pins were
        # per-role. A role that must account for itself is checked at the receipt.
        pinned_model, pinned_variant = MODEL, DEFAULT_EFFORT
    # A writer candidate is the writer with another pin: it reads the same prompt,
    # is held to the same register, and is measured against the same budget. Asking
    # it under its own name would give it a smaller envelope than the role it is
    # standing in for, and the comparison would be of two envelopes.
    base_role = "writer" if role in WRITER_CANDIDATE_MODELS else role
    if prompt_role is None and role in WRITER_CANDIDATE_MODELS:
        prompt_role = "writer"
    default_input, output_budget = ROLE_BUDGETS[base_role]
    budget = default_input if input_budget is None else input_budget
    if input_budget is None:
        budget = _envelope_input_budget(root, base_role)
    if max_output_tokens <= 0 or max_output_tokens > output_budget:
        raise BookForgeError(f"Output allowance {max_output_tokens} exceeds {role} budget {output_budget}")
    # The style review keeps each reviewer's model pin but not its chorus lens: the
    # instruction is what decides whether a pass asks for less or for more.
    prompt_path = Path(__file__).resolve().parents[1] / "assets" / "prompts" / f"{prompt_role or role}.md"
    if not prompt_path.is_file() and role.startswith("advisor-"):
        # An advisor's lens is pinned by filename, so a chorus model without its own
        # prompt would drop out of every run as a non-blocking failure. Let it advise
        # with the generic lens instead; every other role still fails hard.
        prompt_path = prompt_path.parent / "chorus-advisor.md"
    if not prompt_path.is_file():
        raise BookForgeError(f"Missing pinned role prompt: {prompt_path.name}")
    role_prompt = prompt_path.read_text(encoding="utf-8").strip()
    # The register is the project's, not the role's: a writer, a reviser and the
    # style pass must all judge sentences by the same standard, or the pass that
    # is meant to hold the register is the one that erodes it.
    if (prompt_role or role) in STYLE_PROMPT_ROLES:
        style_block = _style_block(_read_json(root / "book-forge.yaml"))
        if style_block:
            role_prompt = f"{role_prompt}\n\n{style_block}"
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
        "model": pinned_model,
        "variant": pinned_variant,
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
    hard_ceiling = budget if (input_budget is not None or _enforce_budgets(root)) else _model_input_window(base_role, max_output_tokens, pinned_model)
    if estimate > hard_ceiling:
        raise ContextOverflowError(estimate, hard_ceiling, contributors)
    if estimate > budget:
        # Above the advisory ceiling but inside what the model accepts. Say so and
        # keep going: a number chosen before the book was written must not end it.
        print(
            f"[{role}] note, not an error: envelope {estimate} tokens is over the advisory "
            f"budget {budget}; the model accepts {hard_ceiling} and the call proceeds. "
            f"Largest contributor {contributors[0]['name']}. Do not raise the budget in "
            "book-forge.yaml — it is advisory by design",
            file=sys.stderr,
        )
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
    for row in eras:
        # An era named but not dated leaves the writer to choose a century. A brief
        # saying "contemporary" produced a novel with a postmistress writing arrivals
        # into a book, because nothing downstream ever stated a year.
        if not str(row.get("when") or "").strip():
            findings.append({"code": "era.undated", "severity": "blocking", "era": row["id"]})
        material = row.get("material")
        if not isinstance(material, list) or len([x for x in material if str(x).strip()]) < 3:
            findings.append({"code": "era.material-thin", "severity": "warning", "era": row["id"]})
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
# Chapters per book-design call. Small enough that a heavy reasoning burn still
# leaves room for the slice's own output.
BOOK_DESIGN_SLICE_SIZE = 4
# The width the engine starts from before it knows anything about this book, and
# not the width it uses all the way through. Four rather than eight because eight
# is what landfall measured as too wide: its four-chapter slices all answered,
# producing 3151, 3732, 3833, 4011 and 3588 tokens of output, while eight-chapter
# slices had to be halved. Every later slice is sized from what the finished ones
# actually cost — see `_design_slice_width`.
#
# What a slice may spend on output before it is narrowed. Landfall's answering
# slices came in between 2420 and 4011 tokens, so this is the top of the band that
# worked rather than a ceiling nobody has reached.
DESIGN_SLICE_OUTPUT_TARGET = 4000
# A slice holding a chapter where something is revealed is narrowed before it is
# called rather than after it fails. Measured on landfall: 17-24 split to 17-20,
# then to 17-18, because CH-0017 and CH-0018 carry the first two withheld layers
# and their contracts hold far heavier plants and reveals than a chapter of
# crossing does. Three empty calls to discover what the withheld rows already said.
DESIGN_REVEAL_SLICE_SIZE = 2
# Measured in production, not on a probe: ten chapters failed at 9508 tokens of
# input with reasoning 31999 and no output, and five answered at 7638 with 16816 of
# reasoning. The first request has to be the size that answers.
# Measured again on landfall, where five almost never answered: window-6-10 came
# back empty, then 6-8, then 6-7, and only 6-6 and 7-7 answered — in a minute each.
# It is not the payload. A five-chapter window is 48400 bytes against the design's
# 150000, and a one-chapter window is 41803. What fails is the judgment: reading a
# run of chapters for contradictions is a question this model spends its whole
# completion budget on, and above a width it emits nothing. Headroom is deliberately
# on the small side — a window too narrow costs one extra call, a window too wide
# costs three empty ones and then the narrow calls anyway.
BOOK_AUDIT_SLICE_SIZE = 2
# One-line outline rows are small, so a slice can hold more of them than a slice
# of full chapter contracts can.
BOOK_OUTLINE_SLICE_SIZE = 12
# How far on either side of its own range a slice sees. The repair has used this
# rule since it stopped sending the whole book to rewrite one chapter.
DESIGN_NEIGHBOURS = 4
AUDIT_NEIGHBOURS = 4
# A schedule pass reads this many chapters and carries forward what they left
# open, so a promise made in chapter three is still checked at chapter forty
# without any one call reading the whole book.
# Measured across two full runs of landfall: an eight-chapter fold never once
# answered on this book. 1-8, 5-8, 17-24, 17-20, 21-24 and 25-26 all came back
# empty in both runs and were halved anyway, so eight bought three empty calls and
# then the narrow calls it would have made regardless. Four is the width that
# answered.
SCHEDULE_WINDOW_SIZE = 4
MAX_OPEN_PROMISES = 60
# What a promise looks like when it names the chapter it falls due in.
CHAPTER_REFERENCE = re.compile(r"CH-\d+", re.IGNORECASE)
# What one chunk may add to the envelope on top of the capsule every chunk
# shares. Measured before the call: over this, the engine splits rather than
# spending a question that cannot be answered.
CHUNK_PAYLOAD_TOKEN_BOUND = 6000
# What a chunk does not read. The base capsule is built for the call that needs
# the most and every other call carries it: the withheld chunk was handed 85102
# bytes of worldbuilding to return four rows, and came back empty three times.
CHUNK_DOES_NOT_READ = {
    "withheld": ("worldbuilding",),
}
# What the engine takes away when a chunk it cannot halve comes back empty. These
# are context rather than instruction: dropping them asks the same question with
# less in front of it, which is what has worked every time this ceiling was hit.
LAST_RESORT_CUT = ("worldbuilding", "chorus_report")


def _call_cache_path(root: Path, task_id: str, envelope: dict[str, object]) -> Path:
    return root / ".book-forge" / "call-cache" / str(task_id) / f"{envelope['hash']}.json"


def _cached_call(root: Path, task_id: str, envelope: dict[str, object]) -> dict[str, object] | None:
    """An answer this project already paid for, or None.

    A book design is around thirty calls and an hour and a half, and it writes its
    artifacts once, at the end. Landfall's was killed at the twenty-seventh call
    and the other twenty-six were lost: their answers sat on disk as raw text that
    nothing read back. The key is the envelope's hash, so a changed brief, canon or
    spine misses the cache — it cannot serve a stale answer to a question that has
    moved.
    """
    path = _call_cache_path(root, task_id, envelope)
    if not path.is_file():
        return None
    try:
        entry = _read_json(path)
    except (OSError, ValueError):
        return None
    result = entry.get("result")
    if not isinstance(result, dict) or not str(result.get("text") or "").strip():
        return None
    # The run that paid for this already counted it; charging it again would make
    # a resumed design look like it cost twice what it did.
    return {**result, "cost": 0.0, "cached": True}


def _remember_call(
    root: Path,
    task_id: str,
    envelope: dict[str, object],
    result: dict[str, object],
    chunk: dict[str, object] | None = None,
) -> None:
    """Remember an answer that was accepted, and only that.

    A truncation or an empty body must stay a failure: remembering one would
    freeze it in place, and no retry could ever get past it.
    """
    if str(result.get("finish")) == "length" or not str(result.get("text") or "").strip():
        return
    path = _call_cache_path(root, task_id, envelope)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, {
        "schema": 1,
        "hash": str(envelope["hash"]),
        "role": str(envelope.get("role", "")),
        # Which pass this was, so a repair can forget the passes it moved rather
        # than every pass the audit ever made.
        "chunk": {key: chunk.get(key) for key in ("category", "first_order", "last_order")} if isinstance(chunk, dict) else None,
        "remembered_at": time.time(),
        "result": {key: value for key, value in result.items() if key != "cached"},
    })


def backfill_call_cache(project: Path | str, *, run: str | None = None) -> dict[str, object]:
    """Remember answers a run paid for before the cache existed.

    Landfall's design was killed after twenty-six accepted answers that nothing
    read back. They are still on disk beside the envelopes that produced them,
    and an envelope's hash is the sha256 of exactly the bytes that were written,
    so the entries the cache would have made can be made now. A hash that no
    longer matches simply never hits: the worst this can do is nothing.
    """
    root = _project_root(project)
    runs_dir = root / ".book-forge" / "runs"
    run_ids = [run] if run else sorted(path.name for path in runs_dir.glob("RUN-*") if path.is_dir())
    remembered: list[str] = []
    skipped: list[str] = []

    def accepted_answers(attempt_dir: Path) -> int:
        return sum(1 for path in attempt_dir.glob("raw-*.txt") if "-attempt" not in path.name and path.stat().st_size > 0)

    for run_id in run_ids:
        # Most complete attempt first. Two attempts of the same run can answer the
        # identical question differently — both valid — and every later chunk
        # carries the spine in its capsule, so keeping the wrong one strands that
        # attempt's whole chain. Landfall lost fourteen chapter-contract answers
        # that way, to an attempt chosen by directory order. The answer worth
        # keeping is the one the rest of its attempt was built on.
        attempts = sorted((runs_dir / run_id).glob("attempts/*"), key=lambda path: (-accepted_answers(path), path.name))
        for attempt_dir in attempts:
            intent_path = attempt_dir / "intent.json"
            if not intent_path.is_file():
                continue
            task_id = str(_read_json(intent_path).get("task") or "")
            if not task_id:
                continue
            for envelope_path in sorted(attempt_dir.glob("envelope-*.json")):
                slug = envelope_path.name[len("envelope-"):-len(".json")]
                raw_path = attempt_dir / f"raw-{slug}.txt"
                where = f"{run_id}/{attempt_dir.name}/{slug}"
                if not raw_path.is_file() or not raw_path.read_text(encoding="utf-8", errors="replace").strip():
                    skipped.append(f"{where}: no accepted answer")
                    continue
                envelope_bytes = envelope_path.read_bytes()
                try:
                    role = str(_read_json(envelope_path).get("role") or "designer")
                except (OSError, ValueError):
                    skipped.append(f"{where}: envelope is not readable")
                    continue
                envelope = {"hash": _sha256_bytes(envelope_bytes), "role": role}
                if _call_cache_path(root, task_id, envelope).is_file():
                    skipped.append(f"{where}: already remembered")
                    continue
                _remember_call(root, task_id, envelope, {
                    "text": raw_path.read_text(encoding="utf-8", errors="replace"),
                    "finish": "stop",
                    "cost": 0.0,
                    "session_id": f"backfilled-{run_id}-{attempt_dir.name}",
                    "provider": "openrouter",
                    "model": MODEL,
                    "variant": ROLE_SPECS.get(role, ("all", "high", 5))[1],
                    "tokens": {},
                })
                remembered.append(f"{where} ({accepted_answers(attempt_dir)} accepted) -> {task_id}")
    return {"remembered": remembered, "skipped": skipped, "runs": run_ids}


def _forget_task_calls(root: Path, task_id: str, *, touching: list[int] | None = None) -> int:
    """Forget what a task was told, because what it will be asked has changed.

    The audit's passes are remembered so that a hung call or a kill costs the call
    and not the run. That is only sound while the proposal stands still: a repair
    rewrites chapters, and the auditor is never shown a chapter's beats, so its
    question can come out byte-identical and a remembered verdict would be handed
    straight back — the repair loop would spin without making a call.

    `touching` names the chapter orders a repair rewrote, and then only the passes
    those orders can reach are forgotten: a window whose range, widened by the
    neighbourhood it reads, contains one of them, and every fold from the earliest
    of them onward, because a fold carries its promises forward. A window on
    chapters twenty-one and twenty-two asks a question a change at chapter eight
    cannot reach. Without `touching`, everything goes — forgetting the whole audit
    is still what an audit-wide change deserves.
    """
    directory = root / ".book-forge" / "call-cache" / str(task_id)
    if not directory.is_dir():
        return 0
    changed = sorted(int(order) for order in (touching or []))
    forgotten = 0
    for entry in directory.glob("*.json"):
        if changed and not _pass_is_reached_by(entry, changed):
            continue
        entry.unlink()
        forgotten += 1
    return forgotten


def _pass_is_reached_by(entry: Path, changed: list[int]) -> bool:
    """Whether a remembered pass would answer differently now."""
    try:
        chunk = _read_json(entry).get("chunk")
    except (OSError, ValueError):
        return True
    if not isinstance(chunk, dict) or chunk.get("first_order") is None or chunk.get("last_order") is None:
        # Recorded before this was tracked, so it cannot be judged and goes.
        return True
    first, last = int(chunk["first_order"]), int(chunk["last_order"])
    if str(chunk.get("category")) == "schedule":
        return last >= changed[0]
    return any(first - AUDIT_NEIGHBOURS <= order <= last + AUDIT_NEIGHBOURS for order in changed)


def _caching_runner(root: Path, task_id: str, runner):
    """A runner that answers from the cache, and remembers what parses.

    Used for the chorus, whose advisors are advisory and whose failures are
    tolerated: an answer that did not parse is returned but never remembered, so
    the next run asks that advisor again rather than inheriting its bad reply.
    """
    def call(role, envelope, attempt_dir):
        cached = _cached_call(root, task_id, envelope)
        if cached is not None:
            return cached
        result = runner(role, envelope, attempt_dir)
        try:
            json.loads(str(result.get("text") or ""), strict=False)
        except ValueError:
            return result
        _remember_call(root, task_id, envelope, result)
        return result

    return call

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
    max_output_tokens: int = 12288,
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
        parsed, telemetry, chunk_results = _run_design_chunk(
            root, task_id, claim, attempt_dir, base_capsule, chunk, imports, runner, max_output_tokens
        )
        results.extend(chunk_results)
        chunk_telemetry.append(telemetry)
        merged = _merge_design_chunks(merged, parsed)
    return claim, merged, results, chunk_telemetry


def _run_design_chunk(
    root: Path,
    task_id: str,
    claim: dict[str, object],
    attempt_dir: Path,
    base_capsule: dict[str, object],
    chunk: dict[str, object],
    imports: list[str],
    runner,
    max_output_tokens: int,
) -> tuple[dict[str, object], dict[str, object], list[dict[str, object]]]:
    """Run the designer for one chunk under an already-claimed task.

    Length truncation is retried locally up to three times. A chunk carrying a
    range of chapters is then handed back to the caller to be halved. A chunk
    carrying none — the spine, the withheld list, a repair — has no halving to
    fall back on, and used to block the whole design: landfall's withheld chunk
    came back empty three times and the driver restarted from the spine, paying
    nine chorus calls to arrive at the same wall. So it is asked once more with
    the bulk of its capsule removed before the task is blocked.
    """
    slug = _chunk_slug(chunk)
    unread = CHUNK_DOES_NOT_READ.get(str(chunk.get("category")), ())
    capsule = {key: value for key, value in base_capsule.items() if key not in unread}
    capsule["chunk"] = chunk
    # What this chunk adds on top of the capsule every chunk shares. A truncation
    # discovered by the provider costs three calls and a blocked task; the same
    # answer measured here costs nothing, so a chunk that is plainly too big is
    # split before it is asked.
    payload_tokens = max(0, len(_json_bytes(capsule)) - len(_json_bytes(dict(base_capsule)))) // 4
    if payload_tokens > CHUNK_PAYLOAD_TOKEN_BOUND and _halve_chunk(chunk):
        print(
            f"[designer] {slug} carries {payload_tokens} tokens of its own, over the {CHUNK_PAYLOAD_TOKEN_BOUND} bound; splitting before the call",
            file=sys.stderr,
        )
        raise DesignChunkTruncated(chunk, [])

    results: list[dict[str, object]] = []

    def ask(value: dict[str, object], suffix: str = "") -> tuple[dict[str, object] | None, dict[str, object]]:
        envelope = build_envelope(
            root,
            role="designer",
            task_capsule=value,
            imports=imports,
            state={},
            tools=[],
            max_output_tokens=max_output_tokens,
        )
        _write_bytes_atomic(attempt_dir / f"envelope-{slug}{suffix}.json", envelope["bytes"])
        remembered = _cached_call(root, task_id, envelope)
        if remembered is not None:
            print(f"[designer] {slug}{suffix} answered from a call this project already paid for", file=sys.stderr)
            results.append(remembered)
            return remembered, envelope
        answer = None
        for attempt in range(3):
            try:
                answer = runner("designer", envelope, attempt_dir)
            except ProviderProducedNothing as timeout:
                # Nothing accepted, nothing paid for. A call that goes quiet is the
                # same event as an answer that came back empty, and the caller below
                # already splits, then asks for less, on exactly that.
                print(f"[designer] {slug}{suffix}: {timeout}", file=sys.stderr)
                return None, envelope
            results.append(answer)
            mark_provider_accepted(root, str(claim["attempt"]), str(answer["session_id"]))
            if answer["finish"] != "length":
                break
            _write_bytes_atomic(attempt_dir / f"raw-{slug}{suffix}-attempt{attempt + 1}.txt", str(answer.get("text", "")).encode())
        return answer, envelope

    result, envelope = ask(capsule)
    if result is None or _is_length_finish(result):
        if "first_order" in chunk and "last_order" in chunk:
            raise DesignChunkTruncated(chunk, results)
        dropped = [key for key in LAST_RESORT_CUT if key in capsule]
        if dropped:
            print(
                f"[designer] {slug} came back empty and cannot be halved; asking once more without {', '.join(dropped)}",
                file=sys.stderr,
            )
            result, envelope = ask({key: value for key, value in capsule.items() if key not in dropped}, suffix="-reduced")
    if result is None or _is_length_finish(result):
        _block_task_failed_length(root, task_id, claim)
        raise BookForgeError(f"Design {task_id} failed_length on chunk {slug}")
    _write_bytes_atomic(attempt_dir / f"raw-{slug}.txt", str(result.get("text", "")).encode())
    telemetry = {
        "chunk": slug,
        "estimated_input_tokens": envelope["estimated_input_tokens"],
        "tokens": result.get("tokens") or {},
    }
    try:
        # The engine decides the split now, so the only meaningful ceiling on one
        # answer is what a single call can physically produce.
        parsed = _parse_chunked_contract(str(result.get("text", "")), max_bytes=max_output_tokens * 4)
    except BookForgeError as exc:
        _set_attempt_failure(root, str(claim["attempt"]), block=True, reason=str(exc))
        raise
    _remember_call(root, task_id, envelope, result)
    return parsed, telemetry, results


class DesignChunkTruncated(BookForgeError):
    """A chapter slice did not fit in one answer; the caller may ask for less."""

    def __init__(self, chunk: dict[str, object], results: list[dict[str, object]]):
        super().__init__(f"Design chunk {_chunk_slug(chunk)} truncated")
        self.chunk = chunk
        self.results = results


def _ranged_chunks(
    category: str, first: int, last: int, width: int, reveal_orders: frozenset[int] = frozenset()
) -> list[dict[str, object]]:
    """Chunks of `width` over a range, narrowed where something is revealed.

    A slice that holds a reveal chapter is built narrow rather than discovered to
    be too wide: the withheld rows name the chapter each layer surfaces in, and the
    engine has them before it calls.
    """
    width = max(1, int(width))
    chunks: list[dict[str, object]] = []
    start = int(first)
    while start <= int(last):
        end = min(start + width - 1, int(last))
        if reveal_orders and any(order in reveal_orders for order in range(start, end + 1)):
            end = min(start + max(1, DESIGN_REVEAL_SLICE_SIZE) - 1, int(last))
        chunks.append({"category": category, "part": f"{start}-{end}", "first_order": start, "last_order": end})
        start = end + 1
    return chunks


def _design_slice_width(measured: list[tuple[int, int]]) -> int | None:
    """How wide the next slice may be, from what the finished ones actually cost.

    Sized by the heaviest chapter seen and not by the average, because the chapter
    that overruns a slice is the one that had most to say, and an average lets it
    hide behind the light chapters beside it. Landfall's per-chapter output ran
    788 tokens at chapters 1-4 and 1558 at 23-24 — a factor of two inside one book,
    which is why no single typed number is right for the next one.
    """
    heaviest = 0.0
    for span, output in measured:
        if span > 0 and output > 0:
            heaviest = max(heaviest, output / span)
    if heaviest <= 0:
        return None
    return max(1, min(BOOK_DESIGN_SLICE_SIZE, int(DESIGN_SLICE_OUTPUT_TARGET // heaviest)))


def _reveal_orders(spine: dict[str, object], outline: list[object]) -> frozenset[int]:
    """The chapter orders the withheld rows say something is revealed in."""
    by_id: dict[str, int] = {}
    for row in outline:
        if isinstance(row, dict) and row.get("id") and row.get("order"):
            by_id[str(row["id"]).upper()] = int(row["order"])
    orders: set[int] = set()
    for row in spine.get("withheld", []) if isinstance(spine.get("withheld"), list) else []:
        if not isinstance(row, dict):
            continue
        for match in CHAPTER_REFERENCE.findall(str(row.get("revealed_in") or "")):
            order = by_id.get(str(match).upper())
            if order:
                orders.add(order)
    return frozenset(orders)


def _book_design_chunks(
    chapter_count: int, *, width: int = BOOK_DESIGN_SLICE_SIZE, reveal_orders: frozenset[int] = frozenset()
) -> list[dict[str, object]]:
    """One chunk per slice of full chapter contracts, in order."""
    return _ranged_chunks("chapters", 1, chapter_count, width, reveal_orders)


def _book_outline_chunks(chapter_count: int) -> list[dict[str, object]]:
    """One chunk per slice of the book's one-line outline."""
    chunks: list[dict[str, object]] = []
    for start in range(1, chapter_count + 1, BOOK_OUTLINE_SLICE_SIZE):
        end = min(start + BOOK_OUTLINE_SLICE_SIZE - 1, chapter_count)
        chunks.append({"category": "outline", "part": f"{start}-{end}", "first_order": start, "last_order": end})
    return chunks


def _order_window(rows: list[object], first: int, last: int, neighbours: int) -> list[dict[str, object]]:
    """The rows around a slice's own range, and no more of the book than that."""
    low, high = first - neighbours, last + neighbours
    return [row for row in rows if isinstance(row, dict) and low <= int(row.get("order") or 0) <= high]


def _chapter_count_of(spine: dict[str, object]) -> int:
    try:
        return int(str(spine.get("chapter_count")).strip())
    except (TypeError, ValueError):
        return 0


def _outline_rows(parsed: object) -> list[dict[str, object]]:
    """The outline rows out of whatever shape the answer arrived in."""
    value = parsed
    if isinstance(value, dict):
        for key in ("chapter_outline", "outline", "chapters", "rows"):
            if isinstance(value.get(key), list):
                value = value[key]
                break
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


# Where a book does its telling is the author's decision. The engine keeps one
# rule — never the first chapter, because a truth told there was withheld from
# nobody — and offers the default an author who says nothing most likely means.
DEFAULT_REVEAL_WINDOW = (2 / 3, 1.0)
REVEAL_CANDIDATE_CAP = 12


def _reveal_window(brief: object) -> tuple[float, float]:
    value = brief.get("reveal_window") if isinstance(brief, dict) else None
    if isinstance(value, dict):
        value = [value.get("from"), value.get("to")]
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return DEFAULT_REVEAL_WINDOW
    try:
        first, last = float(value[0]), float(value[1])
    except (TypeError, ValueError):
        return DEFAULT_REVEAL_WINDOW
    first, last = max(0.0, min(1.0, first)), max(0.0, min(1.0, last))
    return (first, last) if first <= last else (last, first)


def _reveal_candidates(outline: list[dict[str, object]], chapter_count: int, brief: object = None) -> list[dict[str, object]]:
    """The chapters a withholding book may do its telling in.

    Bounded on purpose. The withheld chunk needs somewhere the author considers
    plausible, not the book: handing it the whole outline would make the one call
    whose answer is short depend on the book's length again.
    """
    first_fraction, last_fraction = _reveal_window(brief)
    first = max(2, int(chapter_count * first_fraction) or 2)
    last = max(first, min(chapter_count, int(round(chapter_count * last_fraction)) or chapter_count))
    inside = [row for row in outline if first <= int(row.get("order") or 0) <= last]
    return inside[:REVEAL_CANDIDATE_CAP]


def _run_ranged_chunks(
    chunks: list[dict[str, object]],
    *,
    run,
    capsule_for,
    collect,
    results: list[dict[str, object]],
    telemetry: list[dict[str, object]],
    on_unhalvable,
    resize=None,
) -> None:
    """Run a list of ranged chunks, asking for less from any that does not fit.

    The outline and the chapter contracts go through the same loop: both are a
    range of chapters, both come back truncated sometimes, and in both cases the
    answer is to ask for half rather than for the same thing again.
    """
    pending = list(chunks)
    while pending:
        chunk = pending.pop(0)
        try:
            parsed, chunk_telemetry, chunk_results = run(capsule_for(chunk), chunk)
        except DesignChunkTruncated as exc:
            halves = _halve_chunk(chunk)
            if not halves:
                on_unhalvable(chunk)
            print(
                f"[designer] {_chunk_slug(chunk)} truncated; splitting into "
                f"{', '.join(_chunk_slug(half) for half in halves)}",
                file=sys.stderr,
            )
            results.extend(exc.results)
            pending = halves + pending
            continue
        results.extend(chunk_results)
        telemetry.append(chunk_telemetry)
        collect(parsed, chunk)
        if resize is not None and pending:
            # What the slice just finished cost is the only measurement of this
            # book there is, and it arrives before the slices that would fail.
            pending = resize(pending, chunk, chunk_telemetry)


def _run_book_design_chunked(
    root: Path,
    task_id: str,
    base_capsule: dict[str, object],
    imports: list[str],
    runner,
    *,
    max_output_tokens: int = 12288,
) -> tuple[dict[str, object], dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    """Design a book in slices whose size does not follow the book's length.

    A whole 40-chapter proposal does not fit in one call. Measured on three
    consecutive attempts, reasoning consumed 27045, 29441 and 31998 tokens of a
    ceiling near 32000, leaving 4955, 2559 and finally zero tokens of output. So
    the engine decides the split rather than asking the model to split its own
    answer, which cannot help: several JSON objects share one output budget.

    The first split was spine-then-chapters, and it left the spine carrying one
    outline row per chapter — an answer whose size is the book's size. That is
    what failed on landfall: 15822 bytes cut off mid-sentence, then twice
    `input 42241, reasoning 31999, output 0`, and the spine is the one chunk
    `_halve_chunk` cannot rescue because it carries no range to halve. So the
    spine now returns only what is constant — premise, entry state, arc, exit
    boundary and how many chapters there are — the outline is sliced like
    everything else, and what a book withholds is a third chunk asked once the
    outline exists, so its `revealed_in` names a chapter that is real.

    Every slice reads a window: the outline rows and the digest of the chapters
    within `DESIGN_NEIGHBOURS` of its own range, never the whole book. What one
    slice cannot see, the audit's fold over the finished book does.
    """
    request_hash = _sha256_bytes(_json_bytes({"task": task_id, "chunks": ["spine", "outline", "withheld", "chapters"]}))
    claim = claim_task(root, task_id, request_hash=request_hash)
    attempt_dir = Path(claim["capsule"]).parent
    results: list[dict[str, object]] = []
    chunk_telemetry: list[dict[str, object]] = []

    def run(capsule, chunk):
        return _run_design_chunk(root, task_id, claim, attempt_dir, capsule, chunk, imports, runner, max_output_tokens)

    def unhalvable(chunk):
        _block_task_failed_length(root, task_id, claim)
        raise BookForgeError(f"Design {task_id} failed_length on chunk {_chunk_slug(chunk)}")

    spine, telemetry, spine_results = run(base_capsule, {"category": "spine"})
    spine = _unwrap_chunk(spine, "spine")
    results.extend(spine_results)
    chunk_telemetry.append(telemetry)

    # A spine that answered with the outline anyway is taken at its word: the rows
    # are paid for and correct, and asking for them again would cost calls to
    # arrive at what is already in hand.
    outline = _outline_rows(spine.get("chapter_outline"))
    chapter_count = _chapter_count_of(spine) or len(outline)
    if not chapter_count:
        _set_attempt_failure(root, str(claim["attempt"]), block=True, reason="spine returned neither a chapter count nor an outline")
        raise BookForgeError("Book design spine returned no chapter count")
    spine_core = {key: value for key, value in spine.items() if key not in {"chapter_outline", "chapter_count"}}

    if not outline:
        collected: list[dict[str, object]] = []
        _run_ranged_chunks(
            _book_outline_chunks(chapter_count),
            run=run,
            capsule_for=lambda chunk: {
                **base_capsule,
                "spine": spine_core,
                "chapter_count": chapter_count,
                "outline_so_far": _order_window(collected, int(chunk["first_order"]), int(chunk["last_order"]), DESIGN_NEIGHBOURS),
            },
            collect=lambda parsed, chunk: collected.extend(_outline_rows(parsed)),
            results=results,
            telemetry=chunk_telemetry,
            on_unhalvable=unhalvable,
        )
        by_order: dict[int, dict[str, object]] = {}
        for row in collected:
            by_order[int(row.get("order") or 0)] = row
        outline = [by_order[order] for order in sorted(by_order) if order]

    missing = [order for order in range(1, chapter_count + 1) if order not in {int(row.get("order") or 0) for row in outline}]
    if missing:
        reason = f"outline is missing chapters {missing[:10]} of {chapter_count}"
        _set_attempt_failure(root, str(claim["attempt"]), block=True, reason=reason)
        raise BookForgeError(f"Book design {reason}")

    brief = base_capsule.get("brief") if isinstance(base_capsule.get("brief"), dict) else {}
    if str(brief.get("reader_knowledge") or "").strip():
        parsed, telemetry, withheld_results = run(
            {
                **base_capsule,
                "spine": spine_core,
                "chapter_count": chapter_count,
                "reveal_candidates": _reveal_candidates(outline, chapter_count, brief),
            },
            {"category": "withheld"},
        )
        results.extend(withheld_results)
        chunk_telemetry.append(telemetry)
        rows = parsed.get("withheld") if isinstance(parsed, dict) else parsed
        spine_core["withheld"] = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []

    merged: dict[str, object] = dict(spine_core)
    # A snapshot, not the accumulator: `_merge_design_chunks` mutates `merged` in
    # place, so sharing it would append each slice's chapters to the spine the next
    # slice receives — and a designer handed thirty-two chapters inside the field
    # meant to hold the book's spine stops writing and tries to re-read its envelope.
    spine_snapshot = json.loads(json.dumps(merged))
    # The withheld rows name the chapter each layer surfaces in, so the slices that
    # carry a reveal are built narrow instead of being discovered to be too wide.
    reveal_orders = _reveal_orders(spine_core, outline)
    if reveal_orders:
        print(
            f"[designer] narrowing the slices holding chapters "
            f"{', '.join(str(order) for order in sorted(reveal_orders))}: the withheld rows reveal there",
            file=sys.stderr,
        )
    measured: list[tuple[int, int]] = []

    def resize(pending, chunk, row):
        if str(chunk.get("category")) != "chapters" or not pending:
            return pending
        span = int(chunk["last_order"]) - int(chunk["first_order"]) + 1
        output = int(((row.get("tokens") or {}) or {}).get("output") or 0)
        if span > 0 and output > 0:
            measured.append((span, output))
        width = _design_slice_width(measured)
        if width is None:
            return pending
        rebuilt = _ranged_chunks(
            "chapters", int(pending[0]["first_order"]), int(pending[-1]["last_order"]), width, reveal_orders
        )
        if [(_chunk_slug(one)) for one in rebuilt] != [(_chunk_slug(one)) for one in pending]:
            print(
                f"[designer] {span} chapter(s) cost {output} output token(s); "
                f"the rest of the book goes {width} at a time",
                file=sys.stderr,
            )
        return rebuilt

    _run_ranged_chunks(
        _book_design_chunks(chapter_count, reveal_orders=reveal_orders),
        run=run,
        capsule_for=lambda chunk: {
            **base_capsule,
            "spine": spine_snapshot,
            "chapter_outline": _order_window(outline, int(chunk["first_order"]), int(chunk["last_order"]), DESIGN_NEIGHBOURS),
            "written_so_far": _design_digest(
                _order_window(merged.get("chapters", []), int(chunk["first_order"]), int(chunk["last_order"]), DESIGN_NEIGHBOURS)
            ),
        },
        collect=lambda parsed, chunk: _merge_design_chunks(merged, _unwrap_chunk(parsed, "chapters")),
        results=results,
        telemetry=chunk_telemetry,
        on_unhalvable=unhalvable,
        resize=resize,
    )
    return claim, merged, results, chunk_telemetry


def _halve_chunk(chunk: dict[str, object]) -> list[dict[str, object]]:
    """Split a chunk that covers a range of chapters in two.

    A chunk with no range — the design's spine — cannot be halved, and neither can
    a range of one. The audit reuses this: its passes carry the same two fields, so
    a pass that comes back empty is asked for half as much rather than for the same
    thing again.
    """
    if "first_order" not in chunk or "last_order" not in chunk:
        return []
    first, last = int(chunk["first_order"]), int(chunk["last_order"])
    if last <= first:
        return []
    middle = first + (last - first) // 2
    category = chunk.get("category", "chapters")
    return [
        {"category": category, "part": f"{first}-{middle}", "first_order": first, "last_order": middle},
        {"category": category, "part": f"{middle + 1}-{last}", "first_order": middle + 1, "last_order": last},
    ]


def _unwrap_chunk(value: object, name: str) -> object:
    """Take the answer however the model chose to label it.

    Asked for the book's spine, a designer replied `{"spine": {...}}` — the whole
    thing, correct, wrapped in the name of what it was asked for. The driver read the
    top level, found no outline and blocked the task, twice, discarding forty rows
    that had been paid for. `_merge_design_chunks` already unwraps this shape for the
    universe design's `tail`; there is no reason for the spine to be treated worse.
    """
    if isinstance(value, dict) and len(value) == 1 and name in value and isinstance(value[name], dict):
        return value[name]
    return value


def _design_digest(chapters: list[object]) -> list[dict[str, object]]:
    """What the slices before this one committed the book to.

    A slice used to see the spine and a one-line summary per chapter and nothing
    else, so a detail invented inside one slice's beats was invisible to the next:
    a grave held a man in one slice and a young woman in another. The digest carries
    identity and the promises — plants and reveals — and never the beats, so it stays
    small as the book grows.
    """
    digest = []
    for chapter in chapters:
        if not isinstance(chapter, dict):
            continue
        digest.append(
            {
                "id": chapter.get("id"),
                "order": chapter.get("order"),
                "title": chapter.get("title"),
                "pov": chapter.get("pov"),
                "plants": chapter.get("plants", []),
                "reveals": chapter.get("reveals", []),
            }
        )
    return digest


def _synthetic_chunk_result(results: list[dict[str, object]], merged: dict[str, object], *, role: str = "designer") -> dict[str, object]:
    """Aggregate per-chunk results into one result record for completion telemetry.

    The variant is the one the role is pinned to, not the designer's: completion
    verifies the receipt against the pin, and an audit reported under the designer's
    variant is rejected by the check that exists to catch a model swap."""
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
        "variant": ROLE_SPECS[role][1],
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
    # An era's date and its material facts are the two blocks a scene is answerable
    # to, and they are the reason the era is written as canon at all.
    when = row.get("when")
    if isinstance(when, (str, int)) and str(when).strip():
        body += f"\n<!-- bf:block when -->\n{str(when).strip()}\n"
    material = row.get("material")
    if isinstance(material, list) and material:
        lines = "\n".join(f"- {str(value).strip()}" for value in material if str(value).strip())
        if lines:
            body += f"\n<!-- bf:block material -->\n{lines}\n"
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
    # An era must be addressable or its date reaches nobody: only markdown under
    # universe/canon becomes a block, and a chapter is told to import the era it
    # happens in.
    for row in proposal["eras"]:
        outputs[f"universe/canon/eras/{row['id']}.md"] = _canon_markdown(row, continuity="CNT-0001")
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
    allowed = {"schema", "premise", "characters", "plot", "tone", "length_notes", "reader_knowledge", "reveal_window"}
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
        if _title_is_beat_prefix(chapter):
            findings.append({"code": "chapter.title-from-beat", "severity": "warning", "chapter": chapter.get("id"), "title": chapter.get("title")})
    index = rebuild_indexes(root)
    known_blocks = set(index["blocks"])
    known_characters = {value.split("#", 1)[0] for value in known_blocks if value.startswith("CHR-")}
    for chapter in chapters:
        imports = [str(value) for value in chapter.get("imports", []) if isinstance(value, str)]
        unknown = sorted(value for value in imports if value not in known_blocks)
        if unknown:
            findings.append({"code": "chapter.import-unknown", "severity": "blocking", "chapter": chapter.get("id"), "imports": unknown})
        pov = str(chapter.get("pov") or "")
        # A chapter is only checkable by what it carries: the writer, the technical
        # editor and the reviser all build their envelope from this list, so a chapter
        # that imports nothing is written and judged with no world in front of it.
        # Asked of the character, not of the block. It used to be asked only for a
        # block already in the index, so the requirement disappeared exactly when
        # the block was missing: landfall reached six chapters whose POV had no
        # voice in canon at all, and nothing said so. A POV who is not in canon at
        # all is a different hole, and `chapter.import-unknown` is where it lands.
        missing = [
            value for value in (f"{pov}#summary", f"{pov}#voice")
            if pov in known_characters and value not in imports
        ]
        if missing:
            findings.append({"code": "chapter.import-pov", "severity": "blocking", "chapter": chapter.get("id"), "missing": missing})
        if any(value.startswith("PLC-") for value in known_blocks) and not any(value.startswith("PLC-") for value in imports):
            findings.append({"code": "chapter.import-place", "severity": "blocking", "chapter": chapter.get("id")})
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
    for row in _withheld_rows(proposal):
        if not row.get("id") or not str(row.get("fact") or "").strip() or not str(row.get("seen_as") or "").strip():
            findings.append({"code": "withheld.incomplete", "severity": "blocking", "withheld": row.get("id")})
        never = row.get("never_write", [])
        if not isinstance(never, list) or any(not isinstance(word, str) or not word.strip() for word in never):
            findings.append({"code": "withheld.never-write-shape", "severity": "blocking", "withheld": row.get("id")})
        target = str(row.get("revealed_in") or "")
        if target not in ids:
            findings.append({"code": "withheld.reveal-unknown", "severity": "blocking", "withheld": row.get("id"), "revealed_in": target})
        elif ids.index(target) == 0:
            # A truth revealed in chapter one was never withheld from anyone.
            findings.append({"code": "withheld.reveal-first-chapter", "severity": "blocking", "withheld": row.get("id")})
        told_by = str(row.get("told_by") or "")
        # Checked only where the project has characters at all, the way the place
        # import is: a project with no CHR- blocks has nobody to name as a teller.
        if told_by and any(value.startswith("CHR-") for value in known_blocks) and f"{told_by}#summary" not in known_blocks:
            findings.append({"code": "withheld.teller-unknown", "severity": "blocking", "withheld": row.get("id"), "told_by": told_by})
    if not proposal.get("premise") or len(proposal.get("arc", [])) < 3 or not proposal.get("entry_state") or not proposal.get("exit_boundary"):
        findings.append({"code": "book.arc-incomplete", "severity": "blocking"})
    return findings


def _withheld_rows(proposal: dict[str, object]) -> list[dict[str, object]]:
    rows = proposal.get("withheld")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _withheld_for_chapter(rows: list[dict[str, object]], chapter_id: str, orders: dict[str, int]) -> list[dict[str, object]]:
    """The withheld list cut to what this chapter's writer is allowed to know.

    Before the chapter that reveals a row the cut carries `seen_as` — what a
    person living in the world experiences — and not `fact`. A writer cannot
    leak a truth it was never given, and before the reveal it does not need
    one: the clue it must drop is already written into that chapter's plants
    by the designer, who does know.
    """
    here = orders.get(chapter_id)
    cut: list[dict[str, object]] = []
    for row in rows:
        target = orders.get(str(row.get("revealed_in")))
        if here is None or target is None or here < target:
            status = "withheld"
        elif here == target:
            status = "revealed here"
        else:
            status = "known"
        item: dict[str, object] = {
            "id": row.get("id"),
            "seen_as": row.get("seen_as"),
            "revealed_in": row.get("revealed_in"),
            "told_by": row.get("told_by"),
            "status": status,
        }
        if status != "withheld":
            item["fact"] = row.get("fact")
        elif row.get("never_write"):
            item["never_write"] = row.get("never_write")
        cut.append(item)
    return cut


def _withheld_for_reader(contract: dict[str, object]) -> dict[str, object]:
    """The contract as the cold-reader gets it: no withheld fact, at any chapter.

    The cold-reader is the fresh reader. It is told which rows are deliberately
    withheld so that it stops reporting them as missing setup, and it is never
    told what they are — including at the chapter that reveals one, where its
    job is to say whether the prose delivered the revelation on its own.
    """
    rows = contract.get("withheld")
    if not isinstance(rows, list):
        return contract
    return {
        **contract,
        "withheld": [{key: value for key, value in row.items() if key not in {"fact", "never_write"}} for row in rows if isinstance(row, dict)],
    }


def _book_design_outputs(root: Path, book_id: str, proposal: dict[str, object]) -> dict[str, str | bytes]:
    obligations, relation_imports = _book_obligations(root, book_id)
    chapters = sorted(proposal["chapters"], key=lambda row: int(row["order"]))
    withheld = _withheld_rows(proposal)
    chapter_orders = {str(chapter["id"]): int(chapter["order"]) for chapter in chapters}
    # Withheld is written before Arc because both are one JSON line and the Arc
    # reader is greedy: a second list after it would be swallowed into the arc.
    withheld_section = f"## Withheld\n\n{json.dumps(withheld, ensure_ascii=False)}\n\n" if withheld else ""
    outputs: dict[str, str | bytes] = {
        f"books/{book_id}/design.md": (
            f"---\nid: {book_id}\ncontinuity: {next(book['continuity'] for book in list_books(root) if book['id'] == book_id)}\n---\n\n"
            f"# Premise\n\n<!-- bf:block premise -->\n{proposal['premise']}\n\n"
            f"{withheld_section}"
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
        # title is optional but preserved when designer provides it; writer uses it verbatim
        # when present. A title that is only the opening of its own beat is dropped: with the
        # field absent the writer produces a real heading, which beats a beat fragment.
        contract = {
            "schema": 1,
            "book": book_id,
            **{key: value for key, value in chapter.items() if not (key == "title" and _title_is_beat_prefix(chapter))},
            "imports": sorted(set(chapter.get("imports", []) + relation_imports)),
        }
        cut = _withheld_for_chapter(withheld, str(chapter["id"]), chapter_orders)
        if cut:
            contract["withheld"] = cut
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
    withheld_match = re.search(r"^## Withheld\s*\n+(\[.*\])\s*$", design_text, re.MULTILINE)
    return {
        "premise": premise_match.group(1).strip() if premise_match else "",
        "withheld": json.loads(withheld_match.group(1)) if withheld_match else [],
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


def _promise_chapters(*promise_lists: object) -> dict[str, str]:
    """Where each open promise was made.

    The schedule fold hands the auditor a vocabulary it did not have before — a
    promise with an id — and it cites one as evidence, which is the natural thing
    to do with an identifier it was just given. A promise is not an artifact, so
    the binder refused it and the whole audit died. The chapter that made the
    promise is an artifact, and the engine knows which one it is.
    """
    lookup: dict[str, str] = {}
    for rows in promise_lists:
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict) and str(row.get("id") or "").strip() and str(row.get("chapter") or "").strip():
                lookup[str(row["id"])] = str(row["chapter"])
    return lookup


def _bind_audit_evidence(
    root: Path,
    scope: dict[str, object],
    value: dict[str, object],
    promises: dict[str, str] | None = None,
) -> dict[str, object]:
    findings = value.get("findings")
    if not isinstance(findings, list):
        return value
    promises = promises or {}
    unverifiable: list[dict[str, object]] = []
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
        unresolved: list[str] = []
        for item in evidence:
            if not isinstance(item, dict):
                continue
            location = promises.get(str(item.get("location", "")), str(item.get("location", "")))
            target = _resolve_evidence_target(root, book_id, design_artifact, location)
            if target is None:
                # Dropped, not raised. Failing closed on a citation nobody can look
                # up is right — a repair aimed at nothing is worse than no repair —
                # but enforcing it over the whole audit made one mistyped prefix
                # cost twenty-five completed passes. `PL-0001#summary` did exactly
                # that, on a project whose places are PLC-.
                unresolved.append(location)
                continue
            fixed.append({**item, "location": location, "hash": _file_hash(target)})
        if not fixed:
            # Nothing left to look up, so this cannot stand as a blocking finding.
            # It is set aside rather than dropped: the record keeps it, and a person
            # reads what the auditor was trying to say.
            unverifiable.append({**finding, "evidence": evidence, "unresolved": sorted(set(unresolved))})
            continue
        finding["evidence"] = fixed
        if unresolved:
            finding["unresolved_evidence"] = sorted(set(unresolved))
        bound.append(finding)
    return {"findings": bound, "unverifiable": unverifiable}


def _audit_digest(chapters: list[object]) -> list[dict[str, object]]:
    """One line per chapter, so a pass can place its window inside the whole book."""
    return [
        {key: chapter.get(key) for key in ("id", "order", "title", "pov")}
        for chapter in chapters
        if isinstance(chapter, dict)
    ]


def _audit_ledger(chapters: list[object]) -> list[dict[str, object]]:
    """What a contradiction between two distant chapters is made of.

    A grave that holds a man in chapter four and a young woman in chapter thirty-one
    is visible in what each chapter plants and reveals, and in nothing else the
    contract carries. Reading only these two fields lets one pass cover the whole
    book at a fifth of its weight.
    """
    return [
        {key: chapter.get(key) for key in ("id", "order", "title", "plants", "reveals")}
        for chapter in chapters
        if isinstance(chapter, dict)
    ]


def _book_audit_chunks(chapter_count: int) -> list[dict[str, object]]:
    """Windows of chapters read in full, then the book's promises read as a fold.

    The schedule pass used to be one call over every chapter's plants and reveals.
    That call's size is the book's size: it halved its way down from forty chapters
    to about ten, paying two or three empty calls per audit to discover at run time
    what can be decided here. It is now a walk in fixed windows, each handed what
    the previous one left open.
    """
    chunks: list[dict[str, object]] = []
    for start in range(1, chapter_count + 1, BOOK_AUDIT_SLICE_SIZE):
        end = min(start + BOOK_AUDIT_SLICE_SIZE - 1, chapter_count)
        chunks.append({"category": "window", "part": f"{start}-{end}", "first_order": start, "last_order": end})
    for start in range(1, chapter_count + 1, SCHEDULE_WINDOW_SIZE):
        end = min(start + SCHEDULE_WINDOW_SIZE - 1, chapter_count)
        chunks.append({"category": "schedule", "part": f"{start}-{end}", "first_order": start, "last_order": end})
    return chunks


def _audit_chunk_scope(
    scope: dict[str, object],
    chunk: dict[str, object],
    open_promises: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """The scope one audit pass reads: its own chapters, and the book near them."""
    proposal = scope.get("proposal") if isinstance(scope.get("proposal"), dict) else {}
    chapters = [row for row in proposal.get("chapters", []) if isinstance(row, dict)]
    first, last = int(chunk["first_order"]), int(chunk["last_order"])
    window = [row for row in chapters if first <= int(row.get("order") or 0) <= last]
    # The book's opening and its intended end bound the chapters at the book's
    # edges, and nothing else. Handed to a pass in the middle they read as its own
    # boundaries: a window on chapters nine and ten reported that the Candle was
    # "still cold in the Counting nave" and that Binta "does not yet know the Heart
    # exists" — the book's first page, quoted against its tenth chapter as a
    # contradiction. Three of landfall's four blocking findings were that mistake.
    orders = [int(row.get("order") or 0) for row in chapters] or [0]
    edges = set()
    if first <= min(orders) <= last:
        edges.add("entry_state")
    if first <= max(orders) <= last:
        edges.add("exit_boundary")
    rest = {
        key: value
        for key, value in proposal.items()
        if key != "chapters" and (key not in {"entry_state", "exit_boundary"} or key in edges)
    }
    sliced = dict(scope)
    if chunk.get("category") == "schedule":
        sliced["proposal"] = {**rest, "chapters": _audit_ledger(window)}
        sliced["open_promises"] = list(open_promises or [])
        sliced["pass"] = {
            "reading": f"chapters {first} to {last}, only what each one plants and reveals, against the promises still open when chapter {first - 1} ended",
            "look_for": "a promise on the open list answered here by a fact that contradicts it, revealed here having never been planted, or planted here a second time",
            "also_return": (
                "paid: the ids from open_promises that these chapters answer, as a list of id strings and nothing else. "
                "added: the promises these chapters make, each {\"id\",\"chapter\",\"promise\",\"expected_in\"} with one sentence for the promise. "
                "expected_in is a chapter id from this book or empty — never a chapter number you expect the book to reach. "
                "Return only what changed here — never the whole ledger back"
            ),
        }
    else:
        sliced["proposal"] = {**rest, "chapters": window}
        sliced["neighbourhood_digest"] = _audit_digest(_order_window(chapters, first, last, AUDIT_NEIGHBOURS))
        sliced["pass"] = {
            "reading": f"chapters {first} to {last} in full, against the arc and the chapters immediately around them",
            "look_for": "a contradiction inside these chapters, or one of them standing where the arc does not place it",
        }
    return sliced


def _carry_open_promises(
    carried: list[dict[str, object]],
    value: dict[str, object],
    slug: str,
    chapter_ids: set[str] | None = None,
) -> list[dict[str, object]]:
    """What this schedule window leaves open for the next one.

    The pass returns the difference — the ids it saw answered and the promises
    these chapters make — and the engine applies it. It used to be asked for the
    whole open set on the grounds that a difference would make the engine guess
    which promise a sentence meant. Promises carry ids, so it guesses nothing;
    and the whole set made the answer grow with the book, which is what killed
    landfall's audit at `schedule-11-11`: input 6087 tokens, reasoning 32000,
    output nothing, after an attempt that stopped mid-list on its eleventh
    promise. A window's answer is now the size of what that window changed.

    A pass that returns neither key keeps the carried set rather than dropping
    it: losing it silently would turn an unpaid promise into a clean book.

    A promise is dropped when it falls due in a chapter the book does not have.
    Thirty-nine of landfall's fifty-nine promises named CH-0030, CH-0033, CH-0035
    or CH-0040 in a twenty-six chapter book, and the auditor then reasoned soundly
    from a false premise — promised at forty, paid at twenty-three, so it fires
    early — and blocked six chapters on the last repair round available. The
    engine knows which chapters exist; a promise that names another one is a row
    it cannot use. An unspecified `expected_in` is kept: a promise the book has
    not yet placed is a real thing, and only a named chapter is checked — a value
    that is not a chapter id at all, "unknown" or "the finale", is read as
    unspecified rather than as a phantom, since what did the damage was a
    well-formed id for a chapter that is not there.
    """
    paid = value.get("paid")
    added = value.get("added")
    if not isinstance(paid, list) and not isinstance(added, list):
        # An older shape, or a pass that said nothing about the ledger.
        rows = value.get("open_promises")
        if not isinstance(rows, list):
            return carried
        return [row for row in rows if isinstance(row, dict) and str(row.get("promise") or "").strip()][:MAX_OPEN_PROMISES]
    settled = {str(row) for row in paid if str(row).strip()} if isinstance(paid, list) else set()
    unplaceable = sorted(settled - {str(row.get("id")) for row in carried if isinstance(row, dict)})
    if unplaceable:
        # A mistyped id costs that promise's bookkeeping, never the audit.
        print(
            f"[canon-auditor] {slug} reports paying {', '.join(unplaceable)}, which nothing carried; ignored",
            file=sys.stderr,
        )
    kept = [row for row in carried if isinstance(row, dict) and str(row.get("id")) not in settled]
    for row in added if isinstance(added, list) else []:
        if not (isinstance(row, dict) and str(row.get("promise") or "").strip()):
            continue
        phantom = sorted(
            {
                str(row[key]).strip()
                for key in ("chapter", "expected_in")
                if CHAPTER_REFERENCE.fullmatch(str(row.get(key) or "").strip())
                and str(row[key]).strip() not in chapter_ids
            }
        ) if chapter_ids else []
        if phantom:
            print(
                f"[canon-auditor] {slug} sets aside {row.get('id') or 'a promise'}: it falls due in "
                f"{', '.join(phantom)}, which this book does not have",
                file=sys.stderr,
            )
            continue
        kept.append(row)
    if len(kept) > MAX_OPEN_PROMISES:
        print(
            f"[canon-auditor] {slug} leaves {len(kept)} promises open, over the {MAX_OPEN_PROMISES} a pass may hold; "
            "carrying the most recent",
            file=sys.stderr,
        )
        kept = kept[-MAX_OPEN_PROMISES:]
    return kept


DESIGN_VOICE_SLICE_SIZE = 4


def _canon_block_text(path: Path, block: str) -> str | None:
    """The body of one `bf:block` in a canon file, or None if it is not there."""
    if not path.is_file():
        return None
    text = path.read_text()
    match = re.search(rf"<!--\s*bf:block\s+{re.escape(block)}\s*-->\n([\s\S]*?)(?=\n<!--\s*bf:block|\Z)", text)
    return match.group(1).strip() if match else None


def _with_canon_block(text: str, block: str, body: str) -> str:
    """A canon file with one block added, or replaced where it already stands.

    Returned rather than written: the file is an output of the task that produced
    it, so it is staged and promoted like every other, and a call that fails after
    the write leaves nothing half-changed on disk.
    """
    marker = re.compile(rf"<!--\s*bf:block\s+{re.escape(block)}\s*-->\n[\s\S]*?(?=\n<!--\s*bf:block|\Z)")
    replacement = f"<!-- bf:block {block} -->\n{body.strip()}\n"
    return marker.sub(replacement, text) if marker.search(text) else f"{text.rstrip()}\n\n{replacement}"


def _missing_pov_voices(root: Path, proposal: dict[str, object]) -> list[dict[str, object]]:
    """The POV characters this book takes whose canon has no voice.

    Landfall carried ten characters and one voice block. Three of its four points
    of view — Weyr, Ren, Flint — had none, so six chapters were about to be
    written with the character's summary and nothing about how they sound. The
    guard that should have caught it is the reason it passed: `validate` asks a
    chapter to import its POV's `#summary` and `#voice`, but only for a block
    that is in the index, so the requirement disappears exactly when the block is
    missing. A character canon does not describe at all is a different hole and
    stays with validation — there is no file here to write into.
    """
    index = rebuild_indexes(root)
    known = set(index["blocks"])
    taken: dict[str, list[str]] = {}
    for chapter in proposal.get("chapters", []) if isinstance(proposal.get("chapters"), list) else []:
        if not isinstance(chapter, dict):
            continue
        pov = str(chapter.get("pov") or "").strip()
        if pov and f"{pov}#summary" in known and f"{pov}#voice" not in known:
            taken.setdefault(pov, []).append(str(chapter.get("id") or ""))
    rows: list[dict[str, object]] = []
    for pov, chapters in sorted(taken.items()):
        path = root / "universe" / "canon" / "characters" / f"{pov}.md"
        name = next((line[2:].strip() for line in path.read_text().splitlines() if line.startswith("# ")), pov)
        rows.append({
            "id": pov,
            "name": name,
            "summary": _canon_block_text(path, "summary") or "",
            "chapters": sorted(chapters),
        })
    return rows


def _fill_missing_pov_voices(
    root: Path,
    book_id: str,
    proposal: dict[str, object],
    runner,
) -> list[str]:
    """Write the voice of every POV character the canon does not describe.

    A book cannot ask its designer for a block that does not exist — the ids it
    may import are the ones in the index — so the hole is filled after the design
    and before it is validated. The cast bounds the call, and the call is sliced,
    so this is the size of the points of view a book has and not of the book.
    """
    missing = _missing_pov_voices(root, proposal)
    if not missing:
        return []
    # The book's prose style belongs in a question about how someone sounds, but a
    # project need not have one yet.
    style = [value for value in ("STYLE-0001#prose",) if value in set(rebuild_indexes(root)["blocks"])]
    task_id = f"VOICES-{book_id}"
    plan = _load_plan(root)
    if not any(task["id"] == task_id for task in plan["tasks"]):
        add_task(root, task_id, "designer", priority=35, outputs=[
            f"universe/canon/characters/{row['id']}.md" for row in missing
        ])
    elif next(task["state"] for task in plan["tasks"] if task["id"] == task_id) == "succeeded":
        _reopen_task(root, task_id)
    written: list[str] = []
    outputs: dict[str, str | bytes] = {}
    for start in range(0, len(missing), DESIGN_VOICE_SLICE_SIZE):
        chunk = missing[start:start + DESIGN_VOICE_SLICE_SIZE]
        capsule = {
            "task": "voice",
            "characters": [
                {"id": row["id"], "name": row["name"], "summary": row["summary"], "pov_of": row["chapters"]}
                for row in chunk
            ],
            "required_output": {
                "voices": [
                    {
                        "id": "CHR-0000",
                        "voice": "One paragraph: the register this character narrates in, the rhythm of their sentences, "
                                 "what they notice first in a room, what they never say aloud, and one sample line in "
                                 "their own words. Written to be read by whoever writes their chapters.",
                    }
                ]
            },
        }
        envelope = build_envelope(
            root,
            role="designer",
            task_capsule=capsule,
            imports=[f"{row['id']}#summary" for row in chunk] + style,
            state={},
            tools=[],
            max_output_tokens=2048,
        )
        claim, result = _run_design_role(root, task_id, "designer", envelope, runner)
        try:
            value = _parse_contract_json(str(result["text"]))
        except BookForgeError as exc:
            _set_attempt_failure(root, str(claim["attempt"]), block=True, reason=str(exc))
            raise
        voices = {
            str(row.get("id")): str(row.get("voice") or "").strip()
            for row in (value.get("voices") or [])
            if isinstance(row, dict) and str(row.get("voice") or "").strip()
        }
        for row in chunk:
            body = voices.get(str(row["id"]))
            if not body:
                # One voice the designer skipped costs that character its block,
                # never the book's design: validation names it as a hole.
                print(f"[designer] no voice returned for {row['id']}; it stays missing", file=sys.stderr)
                continue
            path = root / "universe" / "canon" / "characters" / f"{row['id']}.md"
            outputs[f"universe/canon/characters/{row['id']}.md"] = _with_canon_block(path.read_text(), "voice", body)
            written.append(str(row["id"]))
        _complete_model_task(root, task_id, claim, outputs, result, envelope)
        if start + DESIGN_VOICE_SLICE_SIZE < len(missing):
            _reopen_task(root, task_id)
    if written:
        rebuild_indexes(root)
        for chapter in proposal.get("chapters", []) if isinstance(proposal.get("chapters"), list) else []:
            pov = str(chapter.get("pov") or "").strip()
            if pov in written:
                imports = [str(value) for value in chapter.get("imports", []) if isinstance(value, str)]
                if f"{pov}#voice" not in imports:
                    chapter["imports"] = sorted({*imports, f"{pov}#voice"})
        print(
            f"[designer] wrote the missing voice of {', '.join(written)}, and gave it to the chapters they narrate",
            file=sys.stderr,
        )
    return written


def _run_book_audit_chunked(
    root: Path,
    task_id: str,
    scope: dict[str, object],
    imports: list[str],
    runner,
    *,
    max_output_tokens: int = 3000,
) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]], dict[str, object]]:
    """Audit a book in engine-controlled passes under one claim.

    A forty-chapter design asked as one question came back empty five times: input
    34822 tokens, reasoning 32000, output 0, and the same at 18079 once the payload
    was cut. The same design asked ten chapters at a time answered at 10763 tokens
    with reasoning to spare. The question is not made easier by being asked again,
    so the engine asks it in pieces — and no piece is sized by the book: the window
    passes read a neighbourhood rather than the whole digest, and the schedule pass
    walks the book carrying its open promises forward.
    """
    proposal = scope.get("proposal") if isinstance(scope.get("proposal"), dict) else {}
    chapters = [row for row in proposal.get("chapters", []) if isinstance(row, dict)]
    request_hash = _sha256_bytes(_json_bytes({"task": task_id, "audit_passes": len(chapters)}))
    claim = claim_task(root, task_id, request_hash=request_hash)
    attempt_dir = Path(claim["capsule"]).parent
    results: list[dict[str, object]] = []
    findings: list[dict[str, object]] = []
    unverifiable: list[dict[str, object]] = []
    envelope: dict[str, object] = {}
    open_promises: list[dict[str, object]] = []
    # The chapters this book actually has, so a promise falling due outside them
    # is set aside rather than reasoned with.
    chapter_ids = {str(row.get("id")).strip() for row in chapters if str(row.get("id") or "").strip()}
    pending = list(_book_audit_chunks(len(chapters)))
    while pending:
        chunk = pending.pop(0)
        slug = _chunk_slug(chunk)
        required: dict[str, object] = {"findings": []}
        if chunk.get("category") == "schedule":
            required["paid"] = []
            required["added"] = []
        sliced_scope = _audit_chunk_scope(scope, chunk, open_promises)
        envelope = build_envelope(
            root,
            role="canon-auditor",
            task_capsule={"design_scope": sliced_scope, "required_output": required},
            imports=imports,
            state={},
            tools=[],
            max_output_tokens=max_output_tokens,
        )
        _write_bytes_atomic(attempt_dir / f"envelope-{slug}.json", envelope["bytes"])
        # Remembered, because five audits of this book died five different ways and
        # every retry re-ran all of it: roughly eight hours of provider time for a
        # verdict that never landed. Between a hung call and its retry the proposal
        # is identical, so replaying a paid answer is the same verdict to the same
        # question. What makes that sound is that a repair forgets first — see
        # `_forget_task_calls` — since a repair is the one moment the question moves
        # while the auditor's view of it does not.
        result = _cached_call(root, task_id, envelope)
        silent: BookForgeError | None = None
        if result is not None:
            print(f"[canon-auditor] {slug} answered from a call this project already paid for", file=sys.stderr)
        else:
            try:
                result = runner("canon-auditor", envelope, attempt_dir)
            except ProviderProducedNothing as timeout:
                # Nothing was accepted, so nothing was paid for and this is a pass
                # that gave no answer — which the rescue below already knows how to
                # handle. It used to end the run: landfall's re-audit died here with
                # six windows already answered.
                print(f"[canon-auditor] {slug}: {timeout}", file=sys.stderr)
                silent = timeout
        if silent is None:
            results.append(result)
            mark_provider_accepted(root, str(claim["attempt"]), str(result["session_id"]))
            _write_bytes_atomic(attempt_dir / f"raw-{slug}.txt", str(result.get("text", "")).encode())
        try:
            if silent is not None:
                raise silent
            value = _parse_contract_json(str(result["text"]))
        except BookForgeError as exc:
            halves = _halve_chunk(chunk)
            if halves:
                print(
                    f"[canon-auditor] {slug} returned no answer; splitting into "
                    f"{', '.join(_chunk_slug(half) for half in halves)}",
                    file=sys.stderr,
                )
                pending = halves + pending
                continue
            # A window of one chapter cannot be halved, and an audit that gives up
            # there ends the design and burns one of three attempts — landfall's
            # first audit died exactly that way on window-11-11. So it is asked once
            # more about the chapter alone, without the neighbourhood it was being
            # read against and without the canon blocks: a narrower question than
            # the one that went unanswered, which is the only thing that has ever
            # worked at this ceiling.
            print(
                f"[canon-auditor] {slug} cannot be split further; asking once more about it alone",
                file=sys.stderr,
            )
            reduced = {
                "design_scope": {
                    key: value_
                    for key, value_ in sliced_scope.items()
                    if key not in {"neighbourhood_digest", "book_digest", "open_promises"}
                },
                "required_output": required,
            }
            envelope = build_envelope(
                root,
                role="canon-auditor",
                task_capsule=reduced,
                imports=[],
                state={},
                tools=[],
                max_output_tokens=max_output_tokens,
            )
            _write_bytes_atomic(attempt_dir / f"envelope-{slug}-alone.json", envelope["bytes"])
            alone_exc = None
            value = None
            # The last resort keeps having no next resort for an answer that will not
            # parse: this model's common failure is a whole budget spent on reasoning,
            # and asking the identical question again buys the identical nothing.
            # Silence is the other failure and it is a window, so it is waited out
            # once — the same distinction every other retry here now makes.
            for alone_attempt in (1, 2):
                try:
                    result = runner("canon-auditor", envelope, attempt_dir)
                    results.append(result)
                    mark_provider_accepted(root, str(claim["attempt"]), str(result["session_id"]))
                    _write_bytes_atomic(attempt_dir / f"raw-{slug}-alone.txt", str(result.get("text", "")).encode())
                    value = _parse_contract_json(str(result["text"]))
                    alone_exc = None
                    break
                except BookForgeError as caught:
                    alone_exc = caught
                    if alone_attempt == 2 or not _is_silence(caught):
                        break
                    _wait_before_retry("canon-auditor", slug, alone_attempt, caught, runner)
            if alone_exc is not None:
                # The last resort has no next resort. Whatever comes back from it —
                # nothing, or something that will not parse — the window is recorded
                # as unread and the audit moves on. Ending here puts every pass that
                # did answer on the floor and asks a person, which is the thing this
                # whole line of work removes. The rescue used to cover only a silent
                # provider, and this model's common failure is the other one: an
                # answer that arrives with its whole budget spent on reasoning.
                silent_provider = _is_silence(alone_exc)
                print(
                    f"[canon-auditor] {slug} was asked again and "
                    + ("answered neither time" if silent_provider else "its second answer could not be read")
                    + "; the window is set aside unread",
                    file=sys.stderr,
                )
                unverifiable.append({
                    "id": f"A-{slug}-unread",
                    "pass": slug,
                    "severity": "note",
                    "issue": (
                        f"This pass was asked twice and produced no answer: {alone_exc}"
                        if silent_provider
                        else f"This pass was asked twice and its second answer could not be read: {alone_exc}"
                    ),
                    "unresolved": [slug],
                })
                continue
        try:
            bound = _bind_audit_evidence(root, scope, value, _promise_chapters(open_promises, value.get("open_promises")))
            rows = _validate_audit_output(bound)
            if chunk.get("category") == "schedule":
                open_promises = _carry_open_promises(open_promises, value, slug, chapter_ids)
        except BookForgeError as exc:
            _set_attempt_failure(root, str(claim["attempt"]), block=True, reason=f"{slug}: {exc}")
            raise
        _remember_call(root, task_id, envelope, result, chunk)
        for row in bound.get("unverifiable", []):
            row["id"] = f"A-{slug}-{row.get('id', '000')}"
            row["pass"] = slug
            print(
                f"[canon-auditor] {slug} set aside {row['id']} ({row.get('severity')}): "
                f"it cites {', '.join(row.get('unresolved', []))}, which cannot be looked up",
                file=sys.stderr,
            )
        unverifiable.extend(bound.get("unverifiable", []))
        for row in rows:
            # Five passes each numbering its findings from 001 would hand the repair
            # five different requests answering to one identifier; four style
            # reviewers already cost a chapter's worth of dispositions that way.
            row["id"] = f"A-{slug}-{row.get('id', '000')}"
            row["pass"] = slug
        findings.extend(rows)
    return claim, findings, results, envelope, unverifiable


def _auditor_question_hash() -> str:
    """What the auditor is asked, as one hash.

    A verdict on disk has no memory of what produced it, so a design whose audit
    already blocked repaired against findings written by an auditor that had just
    been corrected — three of landfall's four came from a pass reading the book's
    opening as its own boundary, and the fix that removed that reading left the
    conclusions standing. The call cache solves this shape for calls by keying on
    the envelope; a verdict needs the same key.
    """
    prompt = Path(__file__).resolve().parents[1] / "assets" / "prompts" / "canon-auditor.md"
    try:
        return _sha256_bytes(prompt.read_bytes())
    except OSError:
        return ""


def _design_audit_record(
    root: Path,
    task_id: str,
    scope: dict[str, object],
    imports: list[str],
    runner,
    output_path: str,
    *,
    raise_on_blocked: bool = True,
) -> dict[str, object]:
    # The cut lives here and nowhere else. It used to be applied by the callers, two
    # of the three remembered to, and the third — the path that runs when the design
    # is already promoted and only the audit is left — sent the whole proposal:
    # 34694 bytes of beats and 12034 of imports that no continuity check reads.
    # Every audit that failed took that path.
    if isinstance(scope.get("proposal"), dict):
        scope = {**scope, "proposal": _audit_proposal(scope["proposal"])}
    chapters = [row for row in (scope.get("proposal") or {}).get("chapters", []) if isinstance(row, dict)]
    if len(chapters) > BOOK_AUDIT_SLICE_SIZE:
        claim, findings, results, envelope, unverifiable = _run_book_audit_chunked(root, task_id, scope, imports, runner)
        result = _synthetic_chunk_result(results, {"findings": findings}, role="canon-auditor")
    else:
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
            bound = _bind_audit_evidence(root, scope, value)
            findings = _validate_audit_output(bound)
            unverifiable = bound.get("unverifiable", [])
        except BookForgeError as exc:
            _set_attempt_failure(root, str(claim["attempt"]), block=True, reason=str(exc))
            raise
    if unverifiable:
        # A citation nobody can look up is recorded and the run goes on. It used to
        # be a third verdict, `needs_review`, which asked a person — and which the
        # driver could not leave, since the gate that clears a design accepts only
        # `design_clean`, so the design stage was re-dispatched to be audited into
        # the same state again. The rows are on disk with the citations that did
        # not resolve; the verdict is taken on the findings the engine could bind.
        print(
            f"[canon-auditor] {len(unverifiable)} finding(s) set aside, cited nothing that resolves: "
            f"{', '.join(str(row.get('id')) for row in unverifiable)}. Recorded in {output_path}",
            file=sys.stderr,
        )
    record = {
        "schema": 1,
        "state": (
            "blocked" if any(row["severity"] == "blocking" for row in findings)
            else "design_clean"
        ),
        "findings": findings,
        "unverifiable": unverifiable,
        # What was asked, so that correcting the auditor invalidates its own
        # conclusions rather than leaving them to be repaired against.
        "question": _auditor_question_hash(),
    }
    _complete_model_task(root, task_id, claim, {output_path: _json_bytes(record)}, result, envelope)
    if record["state"] == "blocked" and raise_on_blocked:
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
        telemetry: dict[str, object] | None = None
        try:
            result = runner(advisor, adv_envelope, tmp)
            telemetry = _chorus_telemetry(result, adv_envelope)
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
            return advisor, {"findings": bound_findings, "suggestions": validated["suggestions"], "raw": raw, "envelope_hash": adv_envelope["hash"], "telemetry": telemetry}
        except Exception as exc:
            # Advisory-only: a malformed single advisor must not kill the run. The call
            # was still billed if it reached the provider, so its telemetry is kept.
            return advisor, {"findings": [], "suggestions": [], "error": str(exc), "envelope_hash": adv_envelope["hash"], "telemetry": telemetry}
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
    # A chorus call is billed like any other; without this the whole round is spend
    # nobody can account for, which is how "what did grok cost" became an estimate.
    _write_json(
        chorus_dir / "chorus-telemetry.json",
        {
            "schema": 1,
            "scope": scope_id,
            "timestamp": timestamp,
            "task": f"CHORUS-{scope_id}",
            "advisors": [
                {"role": advisor, **data["telemetry"]}
                for advisor, data in sorted(results.items())
                if isinstance(data.get("telemetry"), dict)
            ],
        },
    )
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

def _post_design_scope_id(scope: dict[str, object]) -> str:
    if scope.get("book"):
        return f"book-{scope['book']}"
    return str(scope.get("scope", "universe"))


def run_chorus_post_design(
    project: Path | str,
    scope: dict[str, object],
    product: dict[str, object],
    chorus_models: list[str],
    *,
    provider=None,
) -> dict[str, object]:
    """Post-design ensemble: re-reads the designer product at per-chapter granularity (M2)."""
    root = _project_root(project)
    runner = provider or run_opencode_role
    scope_id = _post_design_scope_id(scope)
    # Build product-centric envelope — writer must be able to execute without inference.
    # For books, surface each chapter's beats/pov/plants/reveals inline so cheap flash/low gets complete instructions.
    task_capsule: dict[str, object] = {"scope": scope, "product": product}
    # Include chapter summary for per-chapter verification
    if isinstance(product.get("chapters"), list):
        task_capsule["chapters"] = product["chapters"]
    if isinstance(product.get("premise"), str):
        task_capsule["premise"] = product["premise"]
    if isinstance(product.get("arc"), list):
        task_capsule["arc"] = product["arc"]
    imports = scope.get("imports") or []
    if not isinstance(imports, list):
        imports = []
    # Use available canon imports as envelope imports (bounded by design_max_input_tokens)
    # product itself is already in capsule; imports provide LAW/character grounding
    # Map to run_chorus scope shape: it expects scope dict + envelope
    # Build a dedicated envelope for advisors: they see product, not brief
    # Reuse run_chorus internals but with product capsule
    base_envelope = build_envelope(
        root,
        role="designer",
        task_capsule=task_capsule,
        imports=list(imports)[:30],
        state={},
        tools=[],
        max_output_tokens=3000,
    )
    # Dispatch with post suffix so outputs go to -post dir
    # We call run_chorus with a post-scoped scope id
    post_scope = {**scope, "_post": True}
    # Run chorus but rename dir after
    result = run_chorus(project, {**scope, "product": product}, base_envelope, chorus_models, provider=runner)
    # Rename timestamp dir to -post to distinguish
    # run_chorus already wrote to .book-forge/chorus/<scope_id>/<ts> ; move to <ts>-post
    try:
        orig = Path(result["dir"])
        post_dir = Path(str(orig) + "-post")
        if orig.exists() and not post_dir.exists():
            orig.rename(post_dir)
            result["dir"] = str(post_dir)
            # Also update latest symlink file
            report = post_dir / "chorus-report.md"
            if report.is_file():
                (Path(result["dir"]).parent / f"chorus-{scope_id}-latest-post.md").write_bytes(report.read_bytes())
    except Exception:
        pass
    # Enrich result with blocking check
    # Collect findings from post dir
    findings = []
    try:
        pd = Path(result["dir"])
        for jf in pd.glob("advisor-*.json"):
            import json as _js
            data = _js.loads(jf.read_text(encoding="utf-8"))
            findings.extend(data.get("findings", []))
    except Exception:
        pass
    result["findings"] = findings
    result["blocking_or_warning"] = [f for f in findings if str(f.get("severity")) in ("blocking","warning")]
    return result


def _enforce_post_chorus_gate(post_result: dict[str, object], scope_id: str) -> None:
    blockers = post_result.get("blocking_or_warning", [])
    if blockers:
        import json as _js
        raise BookForgeError(f"Post-design chorus blocked ({scope_id}): {len(blockers)} blocking|warning findings — run chorus synthesize and apply, or pass --no-post-chorus to bypass. Sample: {_js.dumps(blockers[:3], sort_keys=True)[:800]}")



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


def execute_universe_design(project: Path | str, *, provider=None, chorus_models: str | None = None, no_chorus: bool = False, no_post_chorus: bool = False, with_chorus_context: bool = False, refresh: bool = False, skip_brief: bool = False) -> dict[str, object]:
    root = _project_root(project)
    runner = provider or run_opencode_role
    tasks = schedule_universe_design(root)
    if refresh:
        _reset_universe_design_tasks(root)
    elif all(task["state"] == "succeeded" for task in tasks):
        # Only a clean verdict is a finished job, and only while it answers the
        # question the auditor asks today: correcting the auditor has to invalidate
        # its own conclusions rather than leave them to be built on.
        record = _read_json(root / "universe" / "design-audit.json")
        if record.get("state") == "design_clean" and record.get("question") == _auditor_question_hash():
            return {**record, "calls": 0}
        if record.get("state") == "design_clean":
            print("[canon-auditor] the stored verdict was written under a different auditor; auditing again", file=sys.stderr)
        _reopen_task(root, "AUDIT-UNI-0001")
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
    _failures = _collect_validation_failures(plan, "DESIGN-UNI-0001", limit=5)
    if _failures:
        # Scope-aware hint: book design fails on chunk size / JSON, not tier words
        is_chunk_error = any("chunk exceeds" in str(f) or "chapters.empty" in str(f) or "not contract JSON" in str(f) for f in _failures)
        if is_chunk_error:
            hint = "emit the proposal as multiple top-level JSON objects each <15360 bytes (15KB); list keys (chapters) concatenate across objects in order; keep each object valid JSON; for 40 chapters emit e.g. one object with premise/arc/entry_state/exit_boundary and 2-3 objects with slices of chapters"
        else:
            hint = "word count is combined across summary+voice+appearance+past+want+need+flaw+wound+arc+secret joined with space (validate.py word_count with word-boundary regex); tier.*.words and tier.*.count are enforced; include tier field"
        repair_context = {"repair": {"validation_errors": _failures, "validation_error": str(_failures[0]), "hint": hint}}
    else:
        repair_context = {}
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
                "events": "EVT-#### rows: {id, name, summary, era, order} — era must be the stable ERA-#### id of an era you emitted",
                "places": "PLC-#### rows: {id, name, summary, sensory, tier} — tiered: L1 3-5, L2 5-8, L3 6-12, total >= 14 places",
                "factions": "FAC-#### rows: {id, name, summary}",
                "characters": "CHR-#### rows: {id, name, tier, summary, voice, appearance, past, want, need, flaw, wound, arc, secret} — tiered cast (M4): L1 1-3 protagonists 250-350 words each (combined across summary+voice+appearance+past+want+need+flaw+wound+arc+secret joined with space, counted as word-boundary regex exactly as validate.py) must include want/need/flaw/wound/arc/voice/secret, L2 4-7 secondaries 150-200 words combined same count, L3 6-12 recurring 60-90 words combined, L4 10-20 walk-ons one line (<20 words combined), total named characters >= 22; emit characters in at most two sub-chunks (L1+L2, then L3+L4) if needed to stay <15KB each",
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
        max_output_tokens=12288,
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
    # M2: post-design ensemble — re-read product at per-chapter granularity (places/characters/themes)
    if (not no_chorus) and (not no_post_chorus) and _chorus_post_enabled(config):
        _log_step(7, 7, "post-chorus", "→")
        try:
            post = run_chorus_post_design(root, {"scope": "universe", "imports": ["UNI-0001#kernel"]}, proposal, _chorus_effective, provider=runner)
            chorus_synthesize(root, book_id=None)  # synthesize post run as well (dedup)
            _enforce_post_chorus_gate(post, "universe")
            _log_step(7, 7, "post-chorus", "✓")
        except BookForgeError:
            _log_step(7, 7, "post-chorus", "✗")
            raise
        except Exception as exc:
            print(f"Post-chorus advisory failed (non-blocking): {exc}", file=__import__("sys").stderr)
            _log_step(7, 7, "post-chorus", "✗ (advisory)")
    # M3 summary
    arts = list(_universe_design_outputs(proposal).keys()) + ["universe/design-audit.json"]
    _log_summary(arts)
    return {**audit, "calls": len(results) + 1}


def _book_design_base_capsule(
    root: Path,
    book_id: str,
    *,
    repair_context: dict[str, object] | None = None,
    chorus_report: dict[str, object] | None = None,
) -> tuple[dict[str, object], list[str]]:
    """The designer's view of a book, and the canon it is given, built from disk.

    It used to be a local of `execute_book_design`, which meant the repair round
    could only run on the path that had just designed the book. A design that is
    already promoted and fails its audit later reaches the repair with no capsule to
    rebuild from, and the engine refused the book instead of fixing the four chapters
    the findings named. Both paths read the same world now.
    """
    book = next(row for row in list_books(root) if row["id"] == book_id)
    brief = _book_brief(root, book_id)
    obligations, relation_imports = _book_obligations(root, book_id)
    index = rebuild_indexes(root)
    context = _book_canon_context(root, book_id, index)
    worldbuilding = next((row["content"] for row in context if row["id"] == "worldbuilding.md"), None)
    imports = sorted({row["id"] for row in context if row["id"] != "worldbuilding.md"})
    chapter_imports = sorted(set(["UNI-0001#kernel", *relation_imports]))
    config = _read_json(root / "book-forge.yaml")
    repair_context = repair_context or {}
    capsule = {
            "scope": "book",
            # The brief is the author talking to the engine and may be in any language;
            # the book is written in this one. Without it the designer guesses from the
            # brief and returns forty titles in the wrong language.
            "source_language": str(config.get("source_language", "en")),
            # The context rows are summaries only, so without this the designer cannot
            # know that a voice block or an era block exists, and validation demands a
            # name it was never shown. Names cost bytes; content costs the envelope.
            "available_blocks": sorted(index["blocks"]),
            "book": book,
            "brief": brief,
            "worldbuilding": worldbuilding,
            **repair_context,
            "relations": [row for row in _read_json(root / "universe" / "relations.yaml").get("relations", []) if book_id in row.get("endpoints", [])],
            "obligations": list(obligations.values()),
            "required_output": {
                "premise": "string",
                "chapter_count": "how many chapters this book has; a number, decided in the spine and fixed from then on",
                "withheld": [
                    {
                        "id": "WH-0001",
                        "fact": "the truth, stated plainly",
                        "seen_as": "what a person living in the world experiences in its place",
                        "revealed_in": "the chapter that tells it, never CH-0001",
                        "told_by": "stable character ID of whoever says it",
                        "never_write": ["words that give the fact away and must not appear before revealed_in"],
                    }
                ],
                "entry_state": {},
                "arc": ["at least three causal turns"],
                "exit_boundary": {},
                "chapters": [
                    {
                        "id": "CH-0001",
                        "order": 1,
                        "title": "two to six words naming what the chapter is about; never the opening words of a beat, never a truncated sentence, never a chapter number or numeral prefix (order carries the sequence)",
                        "pov": "stable character ID",
                        "beats": ["causal beat"],
                        "plants": [],
                        "reveals": [],
                        "target_words": 2000,
                        "imports": (
                            "the ids of the canon blocks this chapter depends on, taken from the context you were given: "
                            f"always {chapter_imports}, plus the POV character's #summary and #voice, plus every place the "
                            "chapter is set in, plus the era it happens in. Whoever writes and whoever checks this chapter "
                            "sees only what you list here"
                        ),
                        "obligations": "identifiers taken from the task's obligations list and nothing else; empty when that list is empty. Your own setups go in plants and their payoffs in reveals",
                        "pivotal": None,
                    }
                ],
            },
    }
    if chorus_report:
        capsule["chorus_report"] = chorus_report
    return capsule, imports


def execute_book_design(project: Path | str, book_id: str, *, provider=None, chorus_models: str | None = None, no_chorus: bool = False, no_post_chorus: bool = False, with_chorus_context: bool = False, skip_brief: bool = False) -> dict[str, object]:
    root = _project_root(project)
    runner = provider or run_opencode_role
    tasks = schedule_book_design(root, book_id)
    if all(task["state"] == "succeeded" for task in tasks):
        record = _read_json(root / "books" / book_id / "design-audit.json")
        # A blocking verdict is a job that ran, not a job that finished. Returning it
        # here left the book with no way forward that did not involve reopening a task
        # by hand: the repair rounds live further down this function and were never
        # reached again. Reopening the audit costs a re-audit, which is what the
        # caller asked for by invoking the design at all.
        # Only a clean verdict is a finished job. A blocked one has a repair to run,
        # and returning it here left the book with no way forward that did not
        # involve reopening a task by hand.
        #
        # And clean is not enough on its own: the verdict has to answer the
        # question the auditor asks today. The check for that lives further down,
        # behind this return, so it was reachable only by a verdict that was not
        # clean — which is every case where it does not matter.
        if record.get("state") == "design_clean" and record.get("question") == _auditor_question_hash():
            return {**record, "calls": 0}
        if record.get("state") == "design_clean":
            print("[canon-auditor] the stored verdict was written under a different auditor; auditing again", file=sys.stderr)
        _reopen_task(root, f"AUDIT-{book_id}")
    plan = _load_plan(root)
    design_task = next(task for task in plan["tasks"] if task["id"] == f"DESIGN-{book_id}")
    if design_task["state"] == "succeeded":
        proposal = _book_proposal_from_artifacts(root, book_id)
        if _fill_missing_pov_voices(root, book_id, proposal, runner):
            # The contracts are already on disk here, so the imports the fill just
            # added have to be written back before anything reads them again.
            _write_book_design_outputs(root, book_id, proposal)
        base_capsule, imports = _book_design_base_capsule(root, book_id)
        stored = _read_json(root / "books" / book_id / "design-audit.json") if (root / "books" / book_id / "design-audit.json").is_file() else {}
        if stored and stored.get("question") != _auditor_question_hash():
            # The auditor has changed since this verdict was written, so its findings
            # answer a question the engine no longer asks. A record from before this
            # was recorded at all has no question and is stale by the same rule.
            print("[canon-auditor] the stored verdict was written under a different auditor; auditing again", file=sys.stderr)
            _reopen_task(root, f"AUDIT-{book_id}")
            stored = {}
        # A blocking verdict already on disk is the list to repair against. Auditing
        # first spends eleven calls to rediscover it, and the auditor does not name
        # the same chapters twice running, so the round would aim at a target that
        # moves between rounds. The re-audit still happens, at the end, to check the
        # work rather than to restate the problem.
        audit = stored if _blocking(stored) else _design_audit_record(
            root,
            f"AUDIT-{book_id}",
            {"scope": "book", "book": book_id, "proposal": proposal},
            imports,
            runner,
            f"books/{book_id}/design-audit.json",
            raise_on_blocked=False,
        )
        # Reaching the audit on this path used to cost the book its repair: it raised
        # on the first blocking finding, while the path that had just designed the
        # book handed the same findings to the designer and asked for the named
        # chapters again. A design does not deserve less help for being older.
        proposal, audit = _repair_blocked_design(root, book_id, proposal, audit, base_capsule, imports, runner)
        if _blocking(audit):
            raise BookForgeError(f"Independent design audit found blocking issues: {json.dumps(_blocking(audit), sort_keys=True)}")
        return {**audit, "calls": 1}
    if _should_brief_gate(root, "book", book_id=book_id, skip_flag=skip_brief):
        raise BookForgeError(f"brief.missing: 00-BRIEF gate blocks design book {book_id} — answer 7 questions in books/{book_id}/book-brief.json or pass --skip-brief / usa default")
    brief = _book_brief(root, book_id)
    config = _read_json(root / "book-forge.yaml")
    _chorus_default = _chorus_models_from_config(config)
    _chorus_effective = _parse_chorus_models_arg(chorus_models, _chorus_default) if chorus_models else _chorus_default
    should_chorus = (not no_chorus) and _chorus_enabled(config)
    _failures = _collect_validation_failures(plan, f"DESIGN-{book_id}", limit=5)
    if _failures:
        # Scope-aware hint: book design fails on chunk size / JSON, not tier words
        is_import_error = any("chapter.import" in str(f) for f in _failures)
        is_chunk_error = any("chunk exceeds" in str(f) or "chapters.empty" in str(f) or "not contract JSON" in str(f) for f in _failures)
        if is_import_error:
            hint = ("every chapter's imports must name ids from available_blocks in this task, and must include "
                    "UNI-0001#kernel, the POV character's #summary AND #voice, at least one PLC-* block, and the "
                    "era block for when the chapter happens; the context rows you see are summaries only, so read "
                    "the ids from available_blocks rather than assuming which blocks exist")
        elif is_chunk_error:
            hint = "emit the proposal as multiple top-level JSON objects each <15360 bytes (15KB); list keys (chapters) concatenate across objects in order; keep each object valid JSON; for 40 chapters emit e.g. one object with premise/arc/entry_state/exit_boundary and 2-3 objects with slices of chapters"
        else:
            hint = "word count is combined across summary+voice+appearance+past+want+need+flaw+wound+arc+secret joined with space (validate.py word_count with word-boundary regex); tier.*.words and tier.*.count are enforced; include tier field"
        repair_context = {"repair": {"validation_errors": _failures, "validation_error": str(_failures[0]), "hint": hint}}
    else:
        repair_context = {}
    base_capsule, imports = _book_design_base_capsule(
        root,
        book_id,
        repair_context=repair_context,
        chorus_report=_latest_chorus_report(root, f"book-{book_id}") if with_chorus_context else None,
    )
    envelope = build_envelope(
        root,
        role="designer",
        task_capsule=base_capsule,
        imports=imports,
        state={},
        tools=[],
        max_output_tokens=12288,
    )
    task_id = f"DESIGN-{book_id}"
    _log_step(1, 7, "brief gate", "✓")
    _log_step(2, 7, "chorus", "→")
    if should_chorus:
        try:
            run_chorus(root, {"scope": "book", "book": book_id, "brief": brief}, envelope, _chorus_effective, provider=_caching_runner(root, task_id, runner))
            _log_step(2, 7, "chorus", "✓")
        except Exception as exc:
            print(f"Chorus advisory failed (non-blocking): {exc}", file=sys.stderr)
            _log_step(2, 7, "chorus", "✗")
    else:
        _log_step(2, 7, "chorus", "✓ (skipped)")
    _log_step(3, 7, "designer envelope", "✓")
    _log_step(4, 7, "designer call", "→")
    claim, merged, results, chunk_telemetry = _run_book_design_chunked(root, task_id, base_capsule, imports, runner)
    result = _synthetic_chunk_result(results, merged)
    result["chunk_telemetry"] = chunk_telemetry
    _log_step(4, 7, "designer call", f"✓ ({len(chunk_telemetry)} slices)")
    _log_step(5, 7, "validate", "→")
    try:
        proposal = merged
        # The designer may only import ids that are in the index, so a POV whose
        # voice was never written cannot be imported by the book that needs it.
        # The hole is filled here, before the guard that now requires it.
        _fill_missing_pov_voices(root, book_id, proposal, runner)
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
        raise_on_blocked=False,
    )
    proposal, audit = _repair_blocked_design(
        root, book_id, proposal, audit, base_capsule, imports, runner
    )
    if _blocking(audit):
        _log_step(7, 7, "audit", "✗")
        raise BookForgeError(
            f"Independent design audit found blocking issues: {json.dumps(audit['findings'], sort_keys=True)}"
        )
    _log_step(7, 7, "audit", "✓")
    # M2: post-design ensemble — re-read book product (arc + chapters per-chapter beats/POV)
    if (not no_chorus) and (not no_post_chorus) and _chorus_post_enabled(config):
        _log_step(7, 7, "post-chorus", "→")
        try:
            post = run_chorus_post_design(root, {"scope": "book", "book": book_id, "imports": imports}, proposal, _chorus_effective, provider=runner)
            chorus_synthesize(root, book_id=book_id)
            _enforce_post_chorus_gate(post, f"book-{book_id}")
            _log_step(7, 7, "post-chorus", "✓")
        except BookForgeError:
            _log_step(7, 7, "post-chorus", "✗")
            raise
        except Exception as exc:
            print(f"Post-chorus advisory failed (non-blocking): {exc}", file=__import__("sys").stderr)
            _log_step(7, 7, "post-chorus", "✗ (advisory)")
    arts = list(_book_design_outputs(root, book_id, proposal).keys()) + [f"books/{book_id}/design-audit.json"]
    _log_summary(arts)
    return {**audit, "calls": 2}


AUDIT_CHAPTER_DROP = ("imports", "beats")


def _audit_proposal(proposal: dict[str, object]) -> dict[str, object]:
    """What a continuity audit reads, and nothing else.

    A forty-chapter proposal made the auditor spend its whole ceiling thinking:
    input 41478 tokens, reasoning 32000, output 0. Measured field by field, the
    chapters were beats 34694 bytes, plants 17232, imports 12034, reveals 10924.
    Imports go because `validate_book_design` already owns them; beats go because
    they are the staging, and a contradiction between chapters lives in what each
    one plants, reveals and promises. An auditor that answers catches more than one
    that runs out of room.
    """
    chapters = [
        {key: value for key, value in chapter.items() if key not in AUDIT_CHAPTER_DROP}
        for chapter in proposal.get("chapters", [])
        if isinstance(chapter, dict)
    ]
    return {**proposal, "chapters": chapters}


MAX_DESIGN_REPAIR_ROUNDS = 2


def _blocking(audit: dict[str, object]) -> list[dict[str, object]]:
    return [row for row in audit.get("findings", []) if row.get("severity") == "blocking"]


# The repair asked for ten chapter contracts in one answer and got an empty file.
REPAIR_SLICE_SIZE = 4


def _repair_chunk(ids: list[str]) -> dict[str, object]:
    return {"category": "repair", "ids": list(ids), "part": ids[0] if len(ids) == 1 else f"{ids[0]}-{ids[-1]}"}


def _repair_slices(scope: list[str]) -> list[dict[str, object]]:
    """The chapters a round must rewrite, a few per call."""
    return [_repair_chunk(scope[index:index + REPAIR_SLICE_SIZE]) for index in range(0, len(scope), REPAIR_SLICE_SIZE)]


def _halve_repair_slice(chunk: dict[str, object]) -> list[dict[str, object]]:
    """Ask for half as many chapters. One chapter cannot be split further."""
    ids = list(chunk.get("ids") or [])
    if len(ids) <= 1:
        return []
    middle = len(ids) // 2
    return [_repair_chunk(ids[:middle]), _repair_chunk(ids[middle:])]


# Two either side: enough for a rewritten chapter to know what it is handed and what
# it must hand on, without carrying the book.
REPAIR_NEIGHBOURS = 2


def _repair_neighbourhood(proposal: dict[str, object], ids: list[str], findings: list[dict[str, object]]) -> list[dict[str, object]]:
    """The chapters one repair slice actually reasons about.

    It used to be handed a digest of every chapter it was not rewriting. Measured on
    a one-chapter repair: 34787 bytes of a 75216-byte envelope, against 2530 for the
    chapter being rewritten. Halving the slice cannot touch that, because the part
    that dominates is the part that does not shrink with the slice — and a repair
    that is refused at one chapter has nowhere left to go.

    What a slice needs is what it reasons about: the chapters its findings name, and
    the ones on either side of what it rewrites, so a promise made just before and
    collected just after still holds.
    """
    chapters = [row for row in proposal.get("chapters", []) if isinstance(row, dict)]
    orders = {str(row.get("id")): int(row.get("order") or 0) for row in chapters}
    wanted = {str(value) for finding in findings for value in finding.get("repair_scope", [])}
    for value in ids:
        centre = orders.get(value)
        if centre is None:
            continue
        wanted.update(
            str(row.get("id")) for row in chapters
            if abs(int(row.get("order") or 0) - centre) <= REPAIR_NEIGHBOURS
        )
    rewriting = set(ids)
    return _design_digest([row for row in chapters if str(row.get("id")) in wanted and str(row.get("id")) not in rewriting])


def _repair_blocked_design(root, book_id, proposal, audit, base_capsule, imports, runner):
    """Rewrite the chapters a blocking finding names, then audit again.

    Every finding already says which chapters it touches, so stopping to ask a
    person which four chapters to fix asks them to read what the engine was told.
    Bounded: if the audit still blocks after the rounds are spent, the caller halts
    with the findings, as before.

    Sliced, because a single call asking for ten rewritten contracts against a
    34473-token envelope returned an empty file. Each slice carries only the
    findings that name its chapters; a slice that comes back unusable is halved and
    asked again, and one that cannot be halved raises rather than returning as
    though the repair had nothing to do — which is how the empty answer was read.
    """
    for round_number in range(1, MAX_DESIGN_REPAIR_ROUNDS + 1):
        findings = _blocking(audit)
        if not findings:
            return proposal, audit
        scope = sorted({str(row) for finding in findings for row in finding.get("repair_scope", []) if str(row).startswith("CH-")})
        if not scope:
            return proposal, audit
        chapters = {str(row["id"]): row for row in proposal.get("chapters", [])}
        targets = [value for value in scope if value in chapters]
        if not targets:
            return proposal, audit
        _log_step(7, 7, f"audit repair {round_number}/{MAX_DESIGN_REPAIR_ROUNDS} on {', '.join(targets)}", "→")
        round_dir = root / ".book-forge" / "repairs" / book_id / f"round-{round_number}"
        round_dir.mkdir(parents=True, exist_ok=True)
        spine = {key: value for key, value in proposal.items() if key != "chapters"}
        rewritten: dict[str, object] = {}
        advisors: list[dict[str, object]] = []
        pending = _repair_slices(targets)
        while pending:
            chunk = pending.pop(0)
            ids = list(chunk["ids"])
            slug = str(chunk["part"])
            slice_findings = [row for row in findings if set(str(v) for v in row.get("repair_scope", [])) & set(ids)]
            repair_capsule = {
                "reason": "the independent canon audit found blocking contradictions",
                "findings": slice_findings,
                "rewrite_only": ids,
            }
            if chunk.get("correction"):
                repair_capsule["correction"] = chunk["correction"]
            capsule = {
                **base_capsule,
                "chunk": {"category": "repair", "part": slug},
                "spine": spine,
                "written_so_far": _repair_neighbourhood(proposal, ids, slice_findings),
                "repair": repair_capsule,
                "chapters_to_rewrite": [chapters[value] for value in ids],
            }
            repair_envelope = build_envelope(
                root, role="designer", task_capsule=capsule, imports=imports, state={}, tools=[], max_output_tokens=12288
            )
            _write_bytes_atomic(round_dir / f"envelope-repair-{slug}.json", repair_envelope["bytes"])
            try:
                repaired = runner("designer", repair_envelope, round_dir)
            except ProviderProducedNothing as timeout:
                # Nothing accepted, nothing paid for: the same event as an answer
                # that will not parse, and the halving below is what handles it.
                print(f"[designer] repair {slug}: {timeout}", file=sys.stderr)
                repaired = {"text": ""}
            else:
                advisors.append({"role": "designer", "slice": slug, **_chorus_telemetry(repaired, repair_envelope)})
            _write_bytes_atomic(round_dir / f"raw-repair-{slug}.txt", str(repaired.get("text", "")).encode())
            try:
                value = _parse_chunked_contract(str(repaired.get("text", "")), max_bytes=12288 * 4)
                rows = {str(row["id"]): row for row in value.get("chapters", []) if isinstance(row, dict) and row.get("id")}
            except BookForgeError:
                rows = {}
            if not rows:
                halves = _halve_repair_slice(chunk)
                if not halves:
                    _write_json(
                        round_dir / "repair-telemetry.json",
                        {"schema": 1, "book": book_id, "round": round_number, "advisors": advisors},
                    )
                    raise BookForgeError(f"Design repair for {slug} produced no usable answer after halving to one chapter")
                print(
                    f"[designer] repair {slug} returned no answer; splitting into "
                    f"{', '.join(str(half['part']) for half in halves)}",
                    file=sys.stderr,
                )
                pending = halves + pending
                continue
            moved = sorted(
                f"{key} was sent at order {chapters[key].get('order')} and came back at order {row.get('order')}"
                for key, row in rows.items()
                if key in chapters and row.get("order") != chapters[key].get("order")
            )
            if moved:
                # The designer's instinct is right — the event does belong earlier —
                # but a chapter cannot move: ids carry the reading order, other
                # chapters point at these by id, and the writer is handed its past by
                # id. Ask again for the same fix expressed as an exchange of content.
                if chunk.get("correction"):
                    raise BookForgeError(f"Design repair for {slug} renumbered chapters twice: {'; '.join(moved)}")
                print(f"[designer] repair {slug} renumbered chapters; asking again in place", file=sys.stderr)
                pending = [{**chunk, "correction": {
                    "problem": moved,
                    "rule": "every chapter keeps the id and the order it was given",
                    "instead": "exchange what the chapters contain, so the earlier chapter carries the earlier event and both keep their number",
                }}] + pending
                continue
            rewritten.update(rows)
        # The repair runs outside the DAG, like a chorus round: its own attempt is
        # already promoted, so its cost is recorded beside it and folded into the
        # report rather than being lost.
        _write_json(
            round_dir / "repair-telemetry.json",
            {"schema": 1, "book": book_id, "round": round_number, "advisors": advisors},
        )
        proposal = {**proposal, "chapters": [rewritten.get(str(row.get("id")), row) for row in proposal.get("chapters", [])]}
        blocking_findings = [row for row in validate_book_design(root, book_id, proposal) if row["severity"] == "blocking"]
        if blocking_findings:
            raise BookForgeError(f"Repaired design has blocking findings: {json.dumps(blocking_findings, sort_keys=True)}")
        _write_book_design_outputs(root, book_id, proposal)
        # The proposal changed, so the audit that judged the old one is stale and the
        # task is genuinely due again — and what it was told is stale with it, or the
        # remembered verdict would answer a question the repair has just moved.
        _reopen_task(root, f"AUDIT-{book_id}")
        touched = sorted(
            int(row.get("order") or 0)
            for row in proposal.get("chapters", [])
            if str(row.get("id")) in rewritten
        )
        forgotten = _forget_task_calls(root, f"AUDIT-{book_id}", touching=touched)
        if forgotten:
            print(
                f"[designer] repair round {round_number}: forgot {forgotten} audit passes that chapters "
                f"{', '.join(str(order) for order in touched)} can reach",
                file=sys.stderr,
            )
        audit = _design_audit_record(
            root,
            f"AUDIT-{book_id}",
            {"scope": "book", "book": book_id, "proposal": proposal},
            imports,
            runner,
            f"books/{book_id}/design-audit.json",
            raise_on_blocked=False,
        )
    return proposal, audit

def _reopen_task(root: Path, task_id: str) -> None:
    """Return a completed task to the frontier because its input changed."""
    plan = _load_plan(root)
    task = next((row for row in plan["tasks"] if str(row["id"]) == task_id), None)
    if task is None:
        return
    task["state"] = "pending"
    task.pop("attempt", None)
    task.pop("execution_receipt", None)
    _save_plan(root, plan)
    render_plan(root)


def _write_book_design_outputs(root: Path, book_id: str, proposal: dict[str, object]) -> None:
    """Rewrite the promoted design artifacts after a repair round."""
    for path, value in _book_design_outputs(root, book_id, proposal).items():
        _write_bytes_atomic(root / path, value.encode() if isinstance(value, str) else value)
    rebuild_indexes(root)


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
        value, _ = json.JSONDecoder(strict=False).raw_decode(stripped[start:])
    except json.JSONDecodeError as exc:
        raise BookForgeError(f"Model output is not contract JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise BookForgeError("Model output contract must be an object")
    return value


def _parse_chunked_contract(text_value: str, *, max_bytes: int = DESIGN_CHUNK_MAX_BYTES) -> dict[str, object]:
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
    decoder = json.JSONDecoder(strict=False)
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
        if chunk_size > max_bytes:
            raise BookForgeError(f"Design chunk exceeds {max_bytes} bytes: {chunk_size}")
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


# A numbering marker needs its separator, so "Six Spoke, and the Sky Screamed" is a
# title while "III — Six Spoke..." and "Chapter Two — ..." are numbering.
_TITLE_NUMBERING = re.compile(r"^(?:[Cc]hapter\s+\S+|[IVXLCDM]+|\d+)\s*[—–:.)-]\s*\S")


def _invented_title_problem(contract: dict[str, object], prose: str) -> str | None:
    """Hold the writer to the title rule when there is no contract title to fall back on.

    `_with_contract_heading` repairs a heading only when the contract names one,
    and the design-time guard never sees this chapter again, so a chapter designed
    without a title takes whatever the writer invents with nothing behind it."""
    if str(contract.get("title") or "").strip():
        return None
    first = prose.lstrip().split("\n", 1)[0]
    if not first.startswith("#"):
        return "Writer output has no chapter title line"
    heading = first.lstrip("# ").strip()
    if not heading:
        return "Writer output has an empty chapter title"
    if _TITLE_NUMBERING.match(heading):
        return f"Invented title carries a numbering prefix: {heading!r}"
    if _title_is_beat_prefix({"title": heading, "beats": contract.get("beats", [])}):
        return f"Invented title repeats the opening of a beat: {heading!r}"
    return None


def _never_write_hit(word: str, prose: str) -> bool:
    if word == word.lower():
        return bool(re.search(rf"\b{re.escape(word)}\b", prose, re.IGNORECASE))
    spellings = "|".join(re.escape(value) for value in dict.fromkeys((word, word.upper())))
    return bool(re.search(rf"\b(?:{spellings})\b", prose))


def _withheld_leak(contract: dict[str, object], prose: str) -> dict[str, object] | None:
    """The one mechanical check standing behind a withheld fact.

    The truth is in the canon every chapter imports — LAW-0001 states a whole
    Landing in one sentence — so cutting `fact` out of the contract removes the
    temptation, not the knowledge, and a prompt rule is otherwise the only thing
    between it and the page. A withheld row may name the words that give it away.
    Before the chapter that reveals it, any of those words in the prose fails the
    draft, and the writer is told which one it used.
    """
    rows = contract.get("withheld")
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, dict) or row.get("status") != "withheld":
            continue
        words = [str(word).strip() for word in (row.get("never_write") or []) if str(word).strip()]
        # A word the author capitalised is a name and is matched as written, plus
        # its all-caps rendering for headings and epigraphs; an all-lowercase word
        # is matched in any case. Without the distinction the entry `Earth` also
        # rejects the earth under a character's feet, sending a correct chapter
        # back to be written again.
        found = sorted(word for word in words if _never_write_hit(word, prose))
        if found:
            return {"id": row.get("id"), "revealed_in": row.get("revealed_in"), "words": ", ".join(found)}
    return None


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
    leak = _withheld_leak(contract, prose)
    if leak:
        raise BookForgeError(
            f"Prose uses what {leak['id']} withholds until {leak['revealed_in']}: {leak['words']}. "
            "Write what the people notice and do instead; the reader is not told this yet"
        )
    title_problem = _invented_title_problem(contract, prose)
    if title_problem:
        raise BookForgeError(title_problem)
    words = len(re.findall(r"\b[\w’'-]+\b", prose, re.UNICODE))
    target = int(contract["target_words"])
    lower = max(1, int(target * 0.70))
    upper = int(target * 1.40)
    if not lower <= words <= upper:
        raise BookForgeError(f"Writer output word count {words} is outside {lower}..{upper}")
    value["word_count"] = words
    return value


# `opencode run` truncates every line of an attached file at 2000 characters, and a
# compact envelope is one line, so a role would receive its first 2000 characters and
# never see its own task. Indenting does not save it: JSON escapes the newlines inside
# a canon block, so an 85 KB markdown value stays on one line however the document is
# formatted. The wire rendering below bounds every line for any content whatsoever.
WIRE_MAX_LINE = 1200
WIRE_CHUNK = 700
WIRE_CHUNK_KEY = "__chunks__"
# `opencode run` also truncates a whole attachment at about 50 KB, and JSON keys are
# serialised in sorted order, so on a large envelope `task` — the contract — is exactly
# what gets cut. The envelope is therefore delivered in as many parts as it needs,
# smallest first, so the contract always arrives in the first one.
WIRE_MAX_ATTACHMENT = 36000
WIRE_PROMPT = (
    "Process the attached envelope and return the requested output contract. "
    "The envelope may arrive split across several attached files: merge them in the "
    "order given — later objects add keys, and values that are lists concatenate. "
    f'A value written as {{"{WIRE_CHUNK_KEY}": ["...", "..."]}} is one string split for '
    "transport: concatenate its parts in order, adding nothing between them."
)


def _wire_split(value: str, chunk: int) -> list[str]:
    """Cut a string into pieces of at most `chunk` characters, preferring a cut just
    after a newline so the pieces read as the lines they already are. Concatenating
    the pieces returns the original exactly — no separator is introduced."""
    pieces: list[str] = []
    start = 0
    while start < len(value):
        end = min(start + chunk, len(value))
        if end < len(value):
            newline = value.rfind("\n", start + 1, end + 1)
            if newline > start:
                end = newline + 1
        pieces.append(value[start:end])
        start = end
    return pieces


def _wire_encode(value: object, chunk: int) -> object:
    if isinstance(value, str):
        if len(value) <= chunk:
            return value
        return {WIRE_CHUNK_KEY: _wire_split(value, chunk)}
    if isinstance(value, list):
        return [_wire_encode(row, chunk) for row in value]
    if isinstance(value, dict):
        return {key: _wire_encode(row, chunk) for key, row in value.items()}
    return value


def _wire_decode(value: object) -> object:
    if isinstance(value, dict):
        if set(value) == {WIRE_CHUNK_KEY} and isinstance(value[WIRE_CHUNK_KEY], list):
            return "".join(str(part) for part in value[WIRE_CHUNK_KEY])
        return {key: _wire_decode(row) for key, row in value.items()}
    if isinstance(value, list):
        return [_wire_decode(row) for row in value]
    return value


def _wire_merge(base: object, part: object) -> object:
    """Merge one transport part into the whole. Inverse of `_wire_partition`."""
    if isinstance(base, dict) and isinstance(part, dict):
        if WIRE_CHUNK_KEY in base and WIRE_CHUNK_KEY in part:
            return {WIRE_CHUNK_KEY: list(base[WIRE_CHUNK_KEY]) + list(part[WIRE_CHUNK_KEY])}
        merged = dict(base)
        for key, value in part.items():
            merged[key] = _wire_merge(merged[key], value) if key in merged else value
        return merged
    if isinstance(base, list) and isinstance(part, list):
        return base + part
    return part


def _wire_partition(value: object, budget: int) -> list[object]:
    """Split a structure into parts that each serialise under `budget`.

    Smallest first: a dict emits everything that already fits in one part before it
    descends into the keys that do not, so the contract is never in the tail. Merging
    the parts in order returns the original.
    """
    if _wire_size(value) <= budget:
        return [value]
    if isinstance(value, dict):
        if WIRE_CHUNK_KEY in value and isinstance(value[WIRE_CHUNK_KEY], list):
            return [{WIRE_CHUNK_KEY: piece} for piece in _wire_group(value[WIRE_CHUNK_KEY], budget)]
        small = {key: item for key, item in value.items() if _wire_size({key: item}) <= budget}
        parts: list[object] = []
        for group in _wire_group([{key: item} for key, item in sorted(small.items())], budget):
            merged: dict[str, object] = {}
            for row in group:
                merged.update(row)
            if merged:
                parts.append(merged)
        for key, item in value.items():
            if key in small:
                continue
            parts.extend({key: piece} for piece in _wire_partition(item, budget))
        return parts or [value]
    if isinstance(value, list):
        parts = []
        for group in _wire_group(value, budget):
            parts.extend([group] if _wire_size(group) <= budget or len(group) == 1 else [[row] for row in group])
        return parts or [value]
    return [value]


def _wire_hoist_contract(parts: list[object]) -> list[object]:
    """Pull the small head of the task into the first part.

    Every part is attached and every part arrives, but the first one is what a reader
    sees first, and it should be the one that says what to do rather than the bulk of
    the worldbuilding.
    """
    if len(parts) < 2 or not isinstance(parts[0], dict):
        return parts
    for index in range(1, len(parts)):
        candidate = parts[index]
        if not isinstance(candidate, dict) or set(candidate) != {"task"}:
            continue
        rest = parts[1:index] + parts[index + 1:]
        merged = _wire_merge(parts[0], candidate)
        if _wire_size(merged) <= WIRE_MAX_ATTACHMENT:
            return [merged] + rest
        # The head did not fit beside the canon context. The context is bulk and the
        # contract is not, so the context moves out and the contract stays first.
        head = {key: value for key, value in parts[0].items() if key != "context"}
        evicted = {key: value for key, value in parts[0].items() if key == "context"}
        merged = _wire_merge(head, candidate)
        if evicted and _wire_size(merged) <= WIRE_MAX_ATTACHMENT:
            return [merged, evicted] + rest
        break
    return parts


def _wire_size(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=1))


def _wire_group(rows: list, budget: int) -> list[list]:
    """Greedily pack rows into groups that each serialise under `budget`."""
    groups: list[list] = []
    current: list = []
    for row in rows:
        candidate = current + [row]
        if current and _wire_size(candidate) > budget:
            groups.append(current)
            current = [row]
        else:
            current = candidate
    if current:
        groups.append(current)
    return groups


def _wire_attachments(payload: object, directory: Path) -> list[Path]:
    """Write the envelope as one or more attachments, contract first.

    The parts are decoded and merged back before the call; a rendering that does not
    reproduce the canonical payload is refused rather than sent.
    """
    encoded = json.loads(_wire_bytes(payload).decode())
    # Wrapping a piece back under its key costs bytes the recursion did not budget
    # for, so the split is verified and the budget halved until every part fits.
    budget = WIRE_MAX_ATTACHMENT
    while True:
        parts = _wire_partition(encoded, budget)
        if all(_wire_size(part) <= WIRE_MAX_ATTACHMENT for part in parts) or budget <= 512:
            break
        budget = max(512, budget // 2)
    parts = _wire_hoist_contract(parts)
    oversized = [part for part in parts if _wire_size(part) > WIRE_MAX_ATTACHMENT]
    if oversized:
        # One indivisible value is larger than a single attachment. Refusing is the
        # honest answer: sending it means the provider silently truncates it.
        raise BookForgeError(
            f"Envelope holds a single value of {_wire_size(oversized[0])} bytes that cannot be split "
            f"below the {WIRE_MAX_ATTACHMENT}-byte attachment limit; shorten it at the source"
        )
    rebuilt: object = {}
    for part in parts:
        rebuilt = _wire_merge(rebuilt, part)
    if _wire_decode(rebuilt) != payload:
        raise BookForgeError("Wire attachments do not merge back to the canonical envelope")
    paths: list[Path] = []
    for index, part in enumerate(parts, 1):
        name = "envelope.wire.json" if len(parts) == 1 else f"envelope.wire.part{index:02d}.json"
        path = directory / name
        _write_bytes_atomic(path, (json.dumps(part, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode())
        paths.append(path)
    return paths


def _wire_bytes(payload: object) -> bytes:
    """Render an envelope so that no line can exceed WIRE_MAX_LINE.

    A chunk is measured in source characters, but a line is measured after JSON
    escaping, and an escape can double a character. So the rendering is checked and
    the chunk halved until it holds — the loop terminates because a one-character
    chunk serialises to a bounded line.
    """
    chunk = WIRE_CHUNK
    while True:
        rendered = json.dumps(_wire_encode(payload, chunk), ensure_ascii=False, sort_keys=True, indent=1) + "\n"
        if max((len(line) for line in rendered.split("\n")), default=0) <= WIRE_MAX_LINE or chunk <= 1:
            break
        chunk = max(1, chunk // 2)
    decoded = _wire_decode(json.loads(rendered))
    if decoded != payload:
        raise BookForgeError("Wire envelope does not decode back to the canonical envelope")
    return rendered.encode()


def run_opencode_role(role: str, envelope: dict[str, object], attempt_dir: Path) -> dict[str, object]:
    # Chorus advisors are allowed despite not being in ROLE_SPECS.
    if (
        role not in ROLE_SPECS
        and role not in CHORUS_ADVISOR_SPECS
        and role not in WRITER_CANDIDATE_MODELS
        and role != CHORUS_SYNTHESIZER_AGENT
    ):
        raise BookForgeError(f"Role cannot run headlessly: {role}")
    if role in ROLE_SPECS and ROLE_SPECS[role][0] not in {"all", "primary"}:
        raise BookForgeError(f"Role cannot run headlessly: {role}")
    root = _project_root_from(attempt_dir)
    binary = _opencode_binary()
    _verify_opencode_cli(binary)
    environment = _opencode_environment()
    resolved_result = _run_opencode_process(
        [binary, "--pure", "debug", "agent", role],
        cwd=root,
        env=environment,
        timeout=OPENCODE_PROBE_TIMEOUT,
        what=f"agent probe for {role}",
    )
    if resolved_result.returncode != 0:
        raise BookForgeError(f"OpenCode could not resolve agent {role}: {resolved_result.stderr.strip()}")
    resolved = json.loads(resolved_result.stdout)
    resolved_model = resolved.get("model", {})
    expected_model_id, expected_variant = _expected_pin(role, _project_config(root))
    if (
        resolved.get("name") != role
        or resolved_model.get("providerID") != "openrouter"
        or resolved_model.get("modelID") != expected_model_id
        or resolved.get("variant") != expected_variant
    ):
        raise BookForgeError(
            f"OpenCode resolves {role} to "
            f"{resolved_model.get('providerID')}/{resolved_model.get('modelID')} variant "
            f"{resolved.get('variant')}, but book-forge pins {expected_model_id} variant "
            f"{expected_variant}. The project's .opencode/agents are stale — run "
            "`book-forge runtime sync` to regenerate them"
        )
    started = time.monotonic()
    envelope_path = attempt_dir / "envelope.json"
    _write_bytes_atomic(envelope_path, envelope["bytes"])
    # The canonical bytes stay the audit surface and keep the hash on the receipt; the
    # wire rendering is what the provider is handed, and it is refused unless it decodes
    # back to those same bytes.
    for stale in attempt_dir.glob("envelope.wire.part*.json"):
        stale.unlink()
    wire_paths = _wire_attachments(json.loads(envelope["bytes"]), attempt_dir)
    argv = [
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
            # `opencode run` declares `-f, --file` as a yargs array, so it consumes
            # every following non-flag token. A prompt placed after it is parsed as
            # a second file path and the call dies with "File not found: Process the
            # attached envelope...". The message positional goes first.
            WIRE_PROMPT,
            "--file",
            *[str(path) for path in wire_paths],
    ]
    try:
        result = _run_opencode_process(
            argv, cwd=root, env=environment, timeout=OPENCODE_CALL_TIMEOUT, what=f"call for {role}"
        )
    except OpencodeTimeout as exc:
        _write_bytes_atomic(attempt_dir / "provider-events.jsonl", exc.stdout.encode())
        # Whether this costs money decides how it is reported. A session id on the
        # wire means the provider accepted the call and a retry may pay for it twice,
        # which is a judgement for a person. Nothing on the wire means nothing was
        # accepted and the attempt can simply be tried again.
        session_id = _session_id_in(exc.stdout)
        if session_id:
            raise ProviderOutcomeUnknown(session_id, str(exc)) from exc
        raise ProviderProducedNothing(str(exc)) from exc
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
    try:
        export = _run_opencode_process(
            [binary, "export", session_id], cwd=root, env=environment, timeout=OPENCODE_PROBE_TIMEOUT, what="transcript export"
        )
    except OpencodeTimeout:
        # The answer is already in hand; a transcript that will not come back is not
        # worth losing it over.
        export = subprocess.CompletedProcess([binary, "export", session_id], 1, "", "")
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
            _wait_before_retry("writer", chapter_id, call_number, exc, runner)
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


def _resolve_catalogue_model(name: str) -> str:
    """A catalogue model from what a person would type for it."""
    if name in CHORUS_MODEL_CONFIGS:
        return name
    for candidate in CHORUS_MODEL_CONFIGS:
        if name in {candidate.split("/", 1)[1], candidate.split("/")[-1], _chorus_slug(candidate)}:
            return candidate
    raise BookForgeError(
        f"Not a catalogue model: {name}. Known: {', '.join(sorted(CHORUS_MODEL_CONFIGS))}"
    )


def draft_bakeoff(
    project: Path | str,
    book_id: str,
    chapter_id: str,
    models: list[str],
    *,
    provider=None,
) -> dict[str, object]:
    """Draft one chapter under several models and promote none of them.

    Which prose convinces is the one judgement in this pipeline that belongs to a
    person, so this route stops at three drafts on disk. Every candidate is handed
    the identical capsule at the identical effort, and what each one cost is
    recorded beside its draft, because a model that reads better and costs four
    times as much is a different decision from one that only reads better.
    """
    root = _project_root(project)
    runner = provider or run_opencode_role
    contract = _read_json(root / "books" / book_id / "chapters" / f"{chapter_id}.json")
    if contract.get("book") != book_id or contract.get("id") != chapter_id:
        raise BookForgeError("Chapter contract identity mismatch")
    resolved: list[str] = []
    for name in models:
        model = _resolve_catalogue_model(str(name).strip())
        if model not in resolved:
            resolved.append(model)
    if len(resolved) < 2:
        raise BookForgeError("A bake-off compares at least two models")
    config = _project_config(root)
    # The candidates must be resolvable before they are claimed: a model outside the
    # project's chorus has no agent and no catalogue entry, and would die at the probe
    # with a claim already taken. Regenerating the runtime over the union is the same
    # operation `runtime sync` performs, so the state stays reproducible from config.
    catalogue = list(_chorus_models_from_config(config))
    union = catalogue + [model for model in resolved if model not in catalogue]
    _write_json(root / "opencode.json", _opencode_config(union, config))
    _write_agents(root, union, config)

    prefix = f"books/{book_id}/work/{chapter_id}/bakeoff"
    claims = []
    for model in resolved:
        slug = _chorus_slug(model)
        role = _writer_candidate_name(model)
        task_id = f"BAKE-{slug}-{book_id}-{chapter_id}"
        outputs = [f"{prefix}/{slug}/draft.md", f"{prefix}/{slug}/beat-map.json", f"{prefix}/{slug}/consequences.json"]
        plan = _load_plan(root)
        if not any(task["id"] == task_id for task in plan["tasks"]):
            add_task(root, task_id, role, priority=40, outputs=outputs)
        envelope = build_envelope(
            root,
            role=role,
            prompt_role="writer",
            task_capsule=dict(contract),
            imports=list(contract.get("imports", [])),
            state={
                "book_state": _read_json(root / "books" / book_id / "state.yaml"),
                "previous_chapter_tail": "",
            },
            tools=[],
            max_output_tokens=min(6000, max(1000, int(contract["target_words"]) * 2)),
        )
        claim = claim_task(root, task_id, request_hash=str(envelope["hash"]))
        claims.append((model, slug, role, task_id, outputs, envelope, claim, Path(claim["capsule"]).parent))

    def _ask(entry):
        """The provider call and nothing else.

        The plan is one file behind one hash, and three threads writing it raced:
        each read a plan the next had already replaced, and the third died on a
        hash mismatch with two drafts paid for. Every mutation is made on the way
        back, in order, where the bookkeeping is single-file again.
        """
        _model, _slug, role, _task_id, _outputs, envelope, _claim, attempt_dir = entry
        _write_bytes_atomic(attempt_dir / "envelope.json", envelope["bytes"])
        started = time.monotonic()
        try:
            return {"result": runner(role, envelope, attempt_dir), "seconds": round(time.monotonic() - started, 1)}
        except BookForgeError as exc:
            return {"error": str(exc), "seconds": round(time.monotonic() - started, 1)}

    with ThreadPoolExecutor(max_workers=len(claims)) as executor:
        answers = list(executor.map(_ask, claims))

    outcomes = []
    for entry, answer in zip(claims, answers):
        model, slug = entry[0], entry[1]
        claim = entry[6]
        if "error" in answer:
            outcomes.append({"model": model, "slug": slug, "state": "no_answer", "detail": answer["error"], "seconds": answer["seconds"]})
            continue
        result = answer["result"]
        mark_provider_accepted(root, claim["attempt"], str(result.get("session_id") or ""))
        try:
            parsed = validate_writer_output(contract, str(result["text"]))
        except BookForgeError as exc:
            # A candidate that will not produce a usable chapter is a result about
            # that candidate, not a reason to throw away the drafts that landed.
            outcomes.append({"model": model, "slug": slug, "state": "unusable", "detail": str(exc), "seconds": answer["seconds"], "result": result})
            continue
        outcomes.append({"model": model, "slug": slug, "state": "drafted", "parsed": parsed, "result": result, "seconds": answer["seconds"]})

    candidates = []
    for entry, outcome in zip(claims, outcomes):
        model, slug, role, task_id, outputs, envelope, claim, _attempt_dir = entry
        row = {
            "model": model,
            "variant": BAKEOFF_VARIANT,
            "slug": slug,
            "task": task_id,
            "state": outcome["state"],
            "seconds": outcome["seconds"],
        }
        if outcome["state"] != "drafted":
            row["detail"] = outcome.get("detail", "")
            _set_attempt_failure(root, claim["attempt"], block=False, reason=str(row["detail"]))
            candidates.append(row)
            print(f"[bakeoff] {slug} produced no usable draft: {row['detail']}", file=sys.stderr)
            continue
        parsed, result = outcome["parsed"], outcome["result"]
        prose = str(parsed["prose_markdown"]).rstrip() + "\n"
        manifest = stage_outputs(root, claim["attempt"], {
            outputs[0]: prose,
            outputs[1]: _json_bytes({"schema": 1, "chapter": chapter_id, "beats": parsed["beat_map"]}),
            outputs[2]: _json_bytes({"schema": 1, "chapter": chapter_id, "consequences": parsed["consequences"]}),
        })
        record_execution(
            root,
            claim["attempt"],
            claim["fence"],
            output_hash=_sha256_bytes(_json_bytes(manifest)),
            telemetry=_provider_telemetry(result, envelope),
        )
        promote_task(root, claim["attempt"], claim["fence"])
        row.update({
            "draft": outputs[0],
            "words": len(prose.split()),
            "target_words": int(contract["target_words"]),
            "cost": result.get("cost"),
            "tokens": result.get("tokens"),
        })
        candidates.append(row)

    index = {
        "schema": 1,
        "book": book_id,
        "chapter": chapter_id,
        "title": contract.get("title"),
        "variant": BAKEOFF_VARIANT,
        "promoted": None,
        "candidates": sorted(candidates, key=lambda row: str(row["slug"])),
    }
    _write_json(root / prefix / "bakeoff.json", index)
    drafted = [row for row in candidates if row["state"] == "drafted"]
    print(
        f"[bakeoff] {len(drafted)}/{len(candidates)} drafts of {chapter_id} in {prefix}/. "
        "Nothing was promoted and the chapter is not closed.",
        file=sys.stderr,
    )
    return index


ADVANCE_STAGES = ("design", "chapters", "translate", "export")
MAX_STAGE_ATTEMPTS = 3


class AdvanceBusy(BookForgeError):
    """Another driver already holds this book."""


def _advance_lock_path(root: Path, book_id: str) -> Path:
    return root / ".book-forge" / f"advance-{book_id}.lock"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@contextlib.contextmanager
def _advance_lock(root: Path, book_id: str):
    """Refuse a second driver on the same book.

    Two `advance` processes contend for the same claims: one orphans the other's
    attempt and both pay for work that is thrown away. A lock naming the live pid
    turns that into a sentence instead of a corrupted run. A lock left by a dead
    process is stale and taken over.
    """
    path = _advance_lock_path(root, book_id)
    if path.is_file():
        try:
            holder = int(path.read_text(encoding="utf-8").split()[0])
        except (ValueError, IndexError, OSError):
            holder = 0
        if holder and holder != os.getpid() and _pid_alive(holder):
            raise AdvanceBusy(
                f"another advance is already driving {book_id} (pid {holder}); "
                "wait for it rather than starting a second one — two drivers on one book "
                "contend for the same claims"
            )
    _write_bytes_atomic(path, f"{os.getpid()}\n".encode())
    try:
        yield
    finally:
        try:
            if path.is_file() and path.read_text(encoding="utf-8").strip() == str(os.getpid()):
                path.unlink()
        except OSError:
            pass


class AdvanceHalted(BookForgeError):
    """The driver stopped on something only a person can decide."""


def _halt_if_a_person_is_needed(state: dict[str, object], *, context: str = "") -> None:
    """Every halt names the failure, the task, and the command that resolves it."""
    suffix = f" ({context})" if context else ""
    if state["needs_a_person"]:
        raise AdvanceHalted(
            "outcome unknown for "
            + ", ".join(state["needs_a_person"])
            + " — the provider accepted the call and a retry may pay twice; resolve with "
            f"`resume --resolve-unknown TASK:retry|abandon`{suffix}"
        )
    if state["exhausted"]:
        row = state["exhausted"][0]
        raise AdvanceHalted(
            f"{row['task']} failed {row['retries']} times in a row and will not be retried again: {row['failure']}{suffix}"
        )


def _advance_needs_design(root: Path, book_id: str) -> bool:
    outline = root / "books" / book_id / "outline.yaml"
    if not outline.is_file():
        return True
    if not _read_json(outline).get("chapters"):
        return True
    if not any((root / "books" / book_id / "chapters").glob("CH-*.json")):
        return True
    # Contracts on disk are not a finished design. A book whose audit has never
    # succeeded reported "stages none" and did nothing, so the check that clears it
    # could never be reached by the stage that owns it.
    states = {str(task["id"]): str(task["state"]) for task in _load_plan(root)["tasks"]}
    if states.get(f"AUDIT-{book_id}") != "succeeded":
        return True
    # And an audit that ran and blocked is not a finished design either. Reported as
    # done, the stage that owns the repair was never dispatched, and the driver
    # printed "stages none" beside five blocking findings it had just listed.
    audit_path = root / "books" / book_id / "design-audit.json"
    if not audit_path.is_file():
        return True
    return _read_json(audit_path).get("state") != "design_clean"


def advance_book(
    project: Path | str,
    book_id: str,
    *,
    locales: list[str] | None = None,
    until: str = "export",
    provider=None,
    max_steps: int = 4000,
) -> dict[str, object]:
    """Carry a book from where it stands to where it is asked to stop.

    Every stage recovers before it dispatches, so a truncated answer, an
    unparseable one or a claim whose lease expired costs a retry instead of a
    person at the keyboard. The driver halts on exactly two things: a task whose
    outcome only a person can resolve, and a task that has spent its retries.
    """
    if until not in ADVANCE_STAGES:
        raise BookForgeError(f"Unknown stage: {until} ({', '.join(ADVANCE_STAGES)})")
    root = _project_root(project)
    runner = provider or run_opencode_role
    if book_id not in {str(book["id"]) for book in list_books(root)}:
        raise BookForgeError(f"Unknown book: {book_id}")
    wanted = ADVANCE_STAGES[: ADVANCE_STAGES.index(until) + 1]
    done: dict[str, object] = {"book": book_id, "stages": [], "chapters": 0, "halted": None}
    lock = _advance_lock(root, book_id)
    lock.__enter__()

    def guard() -> None:
        state = recover_before_dispatch(root)
        _halt_if_a_person_is_needed(state)

    def stage(name: str, action) -> object:
        """Run one stage, recovering and retrying when it fails.

        Recovery used to happen only between stages, so a failure inside one
        reached the caller as the engine's own message with the run left blocked
        and nothing said about what to do next.
        """
        last = ""
        for attempt in range(MAX_STAGE_ATTEMPTS):
            guard()
            try:
                return action()
            except AdvanceHalted:
                raise
            except BookForgeError as exc:
                last = str(exc)
                state = recover_before_dispatch(root)
                _halt_if_a_person_is_needed(state, context=f"{name} failed: {last}")
                # Recovery is not the licence to retry — a healthy run is. A failure
                # that settles cleanly leaves nothing to recover, which is the
                # better-behaved case and used to be the fatal one: the technical
                # editor spent its ceiling on CH-0005 and the stage gave up on the
                # first ask, on a role that answers 15 times in 18 and once answered
                # the identical envelope that had just come back empty.
                how = "recovered and retrying" if state["recovered"] else "retrying"
                if attempt + 2 <= MAX_STAGE_ATTEMPTS:
                    print(
                        f"[advance] {name} failed ({last}); {how} {attempt + 2}/{MAX_STAGE_ATTEMPTS}",
                        file=sys.stderr,
                    )
        raise AdvanceHalted(
            f"{name} failed {MAX_STAGE_ATTEMPTS} times in a row: {last}. "
            "Read the attempt's raw output before spending another call."
        )

    if "design" in wanted and _advance_needs_design(root, book_id):
        _log_step(1, len(wanted), "design", "→")
        stage("design", lambda: execute_book_design(root, book_id, provider=runner))
        done["stages"].append("design")

    if "chapters" in wanted:
        for step in range(max_steps):
            try:
                stage("chapters", lambda: run_next(root, book_id=book_id, provider=runner))
            except AdvanceHalted as exc:
                if "No ordinary chapter draft is ready" in str(exc):
                    break
                raise
            done["chapters"] = int(done["chapters"]) + 1
            _log_step(2, len(wanted), f"chapters ({done['chapters']} steps)", "→")
        else:
            raise AdvanceHalted(f"chapter loop did not settle within {max_steps} steps")
        done["stages"].append("chapters")

    targets = list(locales or [])
    if "translate" in wanted and targets:
        for locale in targets:
            _log_step(3, len(wanted), f"translate {locale}", "→")
            stage(f"translate {locale}", lambda locale=locale: translate_next(root, book_id, locale, provider=runner, run_all=True))
        done["stages"].append("translate")

    if "export" in wanted:
        editions = {}
        source_language = str(_read_json(root / "book-forge.yaml").get("source_language", "en"))
        for language in [source_language, *targets]:
            _log_step(4, len(wanted), f"export {language}", "→")
            editions[language] = {
                "epub": export_epub(root, book_id, language),
                "pdf": export_pdf(root, book_id, language),
            }
        done["editions"] = editions
        done["stages"].append("export")

    lock.__exit__(None, None, None)
    done["ready"] = _advance_receipt(root, book_id)
    _log_receipt(done)
    return done


def _advance_receipt(root: Path, book_id: str) -> dict[str, object]:
    """What the driver produced, so the caller does not have to go and look."""
    book = root / "books" / book_id
    outline = book / "outline.yaml"
    chapters = sorted(outline.parent.glob("chapters/CH-*.json"))
    plan = _load_plan(root)
    states = {str(task["id"]): str(task["state"]) for task in plan["tasks"] if book_id in str(task["id"])}
    receipt = {
        "outline_chapters": len(_read_json(outline).get("chapters", [])) if outline.is_file() else 0,
        "chapter_contracts": len(chapters),
        "manuscript_chapters": len(list((book / "manuscript" / "chapters").glob("CH-*.md"))),
        "tasks": states,
        "cost": round(float(telemetry_report(root).get("by_book", {}).get(book_id, {}).get("cost", 0.0)), 4),
    }
    audit_path = book / "design-audit.json"
    audit = _read_json(audit_path) if audit_path.is_file() else {}
    blocking = [row for row in audit.get("findings", []) if row.get("severity") == "blocking"]
    receipt["design_audit"] = {"state": audit.get("state"), "blocking": len(blocking), "ran": audit_path.is_file()}
    # Contracts on disk are not readiness. The independent audit reads the design
    # against canon, and a blocking finding there means the book would be written
    # around a contradiction.
    receipt["ready_to_write"] = bool(
        receipt["outline_chapters"]
        and receipt["chapter_contracts"] == receipt["outline_chapters"]
        and states.get(f"DESIGN-{book_id}") == "succeeded"
        # An absent verdict is not a clean one: a book was reported ready to write on
        # the strength of an audit that had never run.
        and audit_path.is_file()
        and not blocking
    )
    if blocking:
        receipt["blocked_by"] = [
            {"id": row.get("id"), "issue": str(row.get("issue", ""))[:200], "chapters": row.get("repair_scope", [])}
            for row in blocking
        ]
    return receipt


def _log_receipt(done: dict[str, object]) -> None:
    ready = done.get("ready") or {}
    print(
        f"[advance] stages {', '.join(done['stages']) or 'none'} · "
        f"outline {ready.get('outline_chapters', 0)} chapters · "
        f"contracts {ready.get('chapter_contracts', 0)} · "
        f"manuscript {ready.get('manuscript_chapters', 0)} · "
        f"cost ${ready.get('cost', 0)} · "
        f"{'ready to write' if ready.get('ready_to_write') else 'NOT ready to write'}"
        + (f" — design audit blocking on {', '.join(str(row['id']) for row in ready.get('blocked_by', []))}" if ready.get("blocked_by") else ""),
        file=sys.stderr,
    )


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
                if _closed_style_pending(root, str(book["id"]), str(contract["id"])):
                    return recheck_style_closed_chapter(root, str(book["id"]), str(contract["id"]), contract, provider or run_opencode_role)
                continue
            if contract.get("pivotal"):
                return produce_pivotal_chapter(root, str(book["id"]), str(contract["id"]), provider=provider)
            if draft_path.exists() and not contract.get("pivotal"):
                return review_and_close_chapter(root, str(book["id"]), str(contract["id"]), provider=provider)
            if not draft_path.exists() and not contract.get("pivotal"):
                return draft_chapter(root, str(book["id"]), str(contract["id"]), provider=provider)
    raise BookForgeError("No ordinary chapter draft is ready; design a book or use the pivotal workflow")


def _closed_style_pending(root: Path, book_id: str, chapter_id: str) -> bool:
    """A closed chapter is pending style recheck when style review is enabled
    and its STYLE-* advisory outputs are not materialized, or its style-only
    revision has not landed yet."""
    try:
        config = _read_json(root / "book-forge.yaml")
    except Exception:
        config = {}
    if not _style_review_enabled(config):
        return False
    plan = _load_plan(root)
    reviser_id = f"REVISE-STYLE-{book_id}-{chapter_id}"
    if any(t["id"] == reviser_id and t["state"] in {"pending", "running"} for t in plan["tasks"]):
        return True
    slugs = [model.split("/")[-1].replace(".", "-") for model in STYLE_REVIEW_MODELS]
    return not any((root / f"books/{book_id}/reviews/{chapter_id}/style-{slug}.json").is_file() for slug in slugs)


def _with_contract_heading(prose: str, contract: dict[str, object]) -> str:
    """Promote a chapter under its contract title, whichever path wrote the prose.

    The title used to be enforced only on the branch where the style check found
    nothing, so a chapter that went through the reviser kept whatever heading the
    model returned: Landfall shipped `Chapter Two — ...` and `III — ...` against
    contract titles carrying neither prefix, three conventions in one book."""
    title = str(contract.get("title") or "").strip()
    lines = prose.split("\n")
    if not title or not lines or not lines[0].startswith("#"):
        return prose
    if lines[0].lstrip("# ").strip() == title:
        return prose
    lines[0] = f"# {title}"
    return "\n".join(lines)


def _title_is_beat_prefix(chapter: dict[str, object]) -> bool:
    """True when a designer's title is only the opening words of its own beat.

    Measured on Landfall's twenty-one designer titles: the beat heads run from two
    words (`At waelu`) to six (`At the counting the floor is`), so a four-word floor
    caught none of the short ones. At floors 3 and 2 alike, none of the six titles
    known to be good is flagged — including the three-word `The Mistimed Dawn`.
    The floor is 2 because the errors are not symmetric: a false positive costs a
    suggestion and the writer names the chapter instead, a false negative ships a
    broken title through both editions and the translation. One word is left alone;
    a single common word coincides with a beat's opening too easily to mean anything."""
    title = re.sub(r"\s+", " ", str(chapter.get("title") or "")).strip()
    if len(title.split()) < 2:
        return False
    beats = chapter.get("beats")
    if not isinstance(beats, list):
        return False
    return any(re.sub(r"\s+", " ", str(beat)).strip().casefold().startswith(title.casefold()) for beat in beats)


def recheck_style_closed_chapter(
    root: Path,
    book_id: str,
    chapter_id: str,
    contract: dict[str, object],
    runner,
) -> dict[str, object]:
    """Style-check a closed chapter (advisory). If findings surface, re-revise
    the manuscript prose with the reviser; never re-opens state.yaml/reader-state."""
    ms_path = root / "books" / book_id / "manuscript" / "chapters" / f"{chapter_id}.md"
    if not ms_path.is_file():
        raise BookForgeError(f"No manuscript prose for closed chapter {chapter_id}")
    prose = ms_path.read_text(encoding="utf-8")
    style_findings = _call_style_review(root, book_id, chapter_id, contract, prose, runner) + _repetition_findings(prose)
    title = str(contract.get("title") or "").strip()
    if not style_findings and title:
        lines = prose.split("\n")
        if lines and lines[0].startswith("#") and lines[0].lstrip("# ").strip() != title:
            lines[0] = f"# {title}"
            # Deterministic repair, no model call: still atomic, still recorded in the
            # registry and in git, so it cannot desync the artifact hash the way a bare
            # write_text did.
            relative = str(ms_path.relative_to(root))
            payload = ("\n".join(lines).rstrip() + "\n").encode()
            _write_bytes_atomic(ms_path, payload)
            _refresh_registry_hashes(root, [{"path": relative, "target_hash": _sha256_bytes(payload)}])
            _scoped_git_commit(root, [relative], f"heading-{chapter_id}", message=f"book-forge: repair heading {book_id} {chapter_id}")
            return {"state": "style_clean", "book": book_id, "chapter": chapter_id, "findings": 0, "heading": title}
        return {"state": "style_clean", "book": book_id, "chapter": chapter_id, "findings": 0}
    if not style_findings:
        return {"state": "style_clean", "book": book_id, "chapter": chapter_id, "findings": 0}
    reviser_id = f"REVISE-STYLE-{book_id}-{chapter_id}"
    plan = _load_plan(root)
    if not any(t["id"] == reviser_id for t in plan["tasks"]):
        add_task(
            root,
            reviser_id,
            "reviser",
            deps=[],
            priority=70,
            outputs=[
                f"books/{book_id}/manuscript/chapters/{chapter_id}.md",
                f"books/{book_id}/reviews/{chapter_id}/style-dispositions.json",
            ],
        )
    envelope = build_envelope(
        root,
        role="reviser",
        task_capsule={"book": book_id, "chapter": chapter_id, "contract": contract, "draft": prose, "findings": style_findings, "mode": "style-only"},
        imports=list(contract.get("imports", [])),
        state={},
        tools=[],
        max_output_tokens=_reviser_budget(contract, style_findings),
    )
    claim = claim_task(root, reviser_id, request_hash=str(envelope["hash"]))
    attempt_dir = Path(claim["capsule"]).parent
    _write_bytes_atomic(attempt_dir / "envelope.json", envelope["bytes"])
    result = runner("reviser", envelope, attempt_dir)
    mark_provider_accepted(root, claim["attempt"], str(result["session_id"]))
    try:
        value = _parse_contract_json(str(result["text"]))
        validated = _validate_revision(contract, value, style_findings, [], baseline_prose=prose)
    except BookForgeError as exc:
        _set_attempt_failure(root, claim["attempt"], block=True, reason=str(exc))
        raise
    outputs = {
        f"books/{book_id}/manuscript/chapters/{chapter_id}.md": _with_contract_heading(str(validated["prose_markdown"]), contract).rstrip() + "\n",
        f"books/{book_id}/reviews/{chapter_id}/style-dispositions.json": _json_bytes({"schema": 1, "chapter": chapter_id, "dispositions": value["dispositions"]}),
    }
    manifest = stage_outputs(root, claim["attempt"], outputs)
    receipt = record_execution(
        root,
        claim["attempt"],
        claim["fence"],
        output_hash=_sha256_bytes(_json_bytes(manifest)),
        telemetry=_provider_telemetry(result, envelope),
    )
    promote_task(root, claim["attempt"], claim["fence"])
    return {"state": "style_revised", "book": book_id, "chapter": chapter_id, "calls": 4, "findings": len(style_findings), "receipt": receipt["attempt"]}


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


def _chorus_telemetry(result: dict[str, object], envelope: dict[str, object]) -> dict[str, object]:
    """Telemetry for an advisory call, tolerant by design.

    `_provider_telemetry` indexes the provider's answer and is right to: a promoted
    task must account for itself. A chorus advisor is advisory, and the run already
    refuses to die on a malformed one — so it must not die on a missing telemetry
    field either. Whatever the provider reported is recorded, the rest is None."""
    telemetry = {key: result.get(key) for key in ("provider", "model", "variant", "session_id", "tokens", "cost", "latency_ms", "finish")}
    telemetry.update({"envelope_hash": envelope["hash"], "estimated_input_tokens": envelope["estimated_input_tokens"]})
    return telemetry


REVIEW_FINDING_FIELDS = frozenset({"id", "dimension", "severity", "evidence", "issue", "fix_required"})


def _validate_findings(
    value: dict[str, object], *, technical: bool
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """The findings this review can be acted on, and the ones it cannot.

    Raising on the first unreadable finding threw away the readable ones with it.
    Measured on CH-0004, the first chapter written after the writer and the reviser
    were put on one hand: the cold reader answered in well-formed JSON with several
    usable findings, one of them carrying `evidence` as a sentence instead of the
    object the contract asks for and no `fix_required`. That one field discarded the
    review, then the chapter, then a run of twenty-six.

    This is the rule the rest of the engine already follows — what a model returns
    that cannot be used is set aside and recorded, and the run goes on. The critic
    does it for a finding that cites nothing, the auditor for evidence it cannot
    resolve. A review where *nothing* survives is still a failure, because that is
    an answer nobody can act on and the retry exists for it.
    """
    findings = value.get("findings")
    if not isinstance(findings, list):
        raise BookForgeError("Review output has no findings list")
    usable: list[dict[str, object]] = []
    set_aside: list[dict[str, object]] = []
    seen = set()
    for index, finding in enumerate(findings, start=1):
        if not isinstance(finding, dict):
            set_aside.append({"position": index, "why": "the finding is not an object", "finding": finding})
            continue
        missing = sorted(REVIEW_FINDING_FIELDS - finding.keys())
        if technical and "objective" not in finding:
            missing.append("objective")
        if missing:
            set_aside.append({
                "position": index,
                "id": finding.get("id"),
                "why": f"missing {', '.join(missing)}",
                "finding": finding,
            })
            continue
        if finding["id"] in seen or finding["severity"] not in {"blocking", "warning", "note"}:
            set_aside.append({
                "position": index,
                "id": finding.get("id"),
                "why": "duplicate id or invalid severity",
                "finding": finding,
            })
            continue
        seen.add(finding["id"])
        usable.append(finding)
    if findings and not usable:
        raise BookForgeError("Review finding is missing required evidence fields")
    return usable, set_aside


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
    # A pass of two roles can half-succeed, and the resume above only understood
    # total success. On CH-0005 the cold reader answered, was validated and
    # promoted, the technical editor beside it spent its ceiling and raised, and
    # the retry re-claimed both — dying on `Only a running attempt can be marked
    # accepted` for the one already promoted. A partial result is not no result:
    # whatever answered is reused, and only what did not is asked again.
    if materialized:
        print(
            f"[review] {chapter_id}: reusing the {', '.join(sorted(materialized))} answer already paid for",
            file=sys.stderr,
        )
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
        if role in materialized:
            continue
        capsule = {
            "book": book_id, "chapter": chapter_id, "contract": contract, "prose": draft,
            # The bound the engine owns, in the question rather than only in the
            # prompt. Measured on the translation critic across twelve calls: the
            # unbounded question answered 0 of 4 and stopped at the reasoning
            # ceiling every time, the bounded one answered 4 of 4, and halving the
            # text it read did not help. This role gates a chapter, so it cannot be
            # set aside when it fails to answer.
            "answer_bound": f"Report at most {REVIEW_MAX_FINDINGS} findings, most severe first.",
        }
        if role == "cold-reader":
            capsule["contract"] = _withheld_for_reader(contract)
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
    def ask(role, envelope, attempt_dir):
        """One reviewer's answer, re-asked while it spends its ceiling and says nothing.

        Bounded, and only for this failure: a malformed answer has its own remedy
        upstream, and silence has the backoff. This is the third class — the model
        answered, was charged, and left no room to write — and for this role it is
        variance, so the same question asked again is a question that gets answered.
        """
        last = None
        for attempt in range(1, REVIEW_CEILING_REASKS + 1):
            result = runner(role, envelope, attempt_dir)
            try:
                _refuse_empty_answer(role, role, result)
                return result
            except ReasoningCeilingSpent as spent:
                last = spent
                if attempt < REVIEW_CEILING_REASKS:
                    print(
                        f"[{role}] spent its ceiling with nothing written; asking again "
                        f"{attempt + 1}/{REVIEW_CEILING_REASKS}",
                        file=sys.stderr,
                    )
        raise last  # type: ignore[misc]

    # Held from the moment they are claimed, and dropped as each is promoted. The
    # calls themselves can raise — a reviewer that spends its ceiling on every
    # re-ask does — and a claim left behind by that becomes `outcome_unknown` and
    # stops the run for a person.
    unsettled = {task_id: claim for _, task_id, _, claim, _ in jobs}

    def abandon(reason: str) -> None:
        for _, claim in unsettled.items():
            try:
                _set_attempt_failure(root, claim["attempt"], block=False, reason=reason)
            except BookForgeError:
                pass

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {executor.submit(ask, role, envelope, attempt_dir): (role, task_id, envelope, claim) for role, task_id, envelope, claim, attempt_dir in jobs}
            results = []
            for future, metadata in futures.items():
                results.append((*metadata, future.result()))
    except BookForgeError as unanswered:
        abandon(str(unanswered))
        raise
    parsed: dict[str, dict[str, object]] = dict(materialized)
    receipts = []
    # Every claim this pass holds, dropped as each one is promoted. Whatever is left
    # when the pass raises is settled before the exception leaves: an answer that
    # came back and could not be used is a *failed* attempt, and the sibling role's
    # claim — accepted and never looked at, because the loop raised before reaching
    # it — is not an unknown outcome either. Left unsettled, both become
    # `outcome_unknown` and halt the run for a person, which is right only when the
    # engine does not know what happened. Here it does.
    try:
        for role, task_id, envelope, claim, result in results:
            mark_provider_accepted(root, claim["attempt"], str(result["session_id"]))
            _refuse_empty_answer(role, task_id, result)
            value = _parse_contract_json(str(result["text"]))
            usable, set_aside = _validate_findings(value, technical=role == "technical-editor")
            if set_aside:
                print(
                    f"[{role}] {len(set_aside)} finding(s) set aside as unreadable, "
                    f"{len(usable)} kept: {'; '.join(str(row['why']) for row in set_aside)}",
                    file=sys.stderr,
                )
            # The review is acted on through what survived, and what did not is
            # carried beside it rather than dropped on the floor.
            value["findings"] = usable
            value["set_aside"] = set_aside
            if role == "technical-editor" and not isinstance(value.get("consequences"), list):
                raise BookForgeError("Technical review has no independent consequence extraction")
            parsed[role] = value
            receipts.append(_materialize_review_result(root, task_id, claim, envelope, result, value))
            unsettled.pop(task_id, None)
    except BookForgeError as unusable:
        # Nothing here may raise on the way out: the caller must see the failure
        # that actually happened, not one invented by the cleanup.
        abandon(str(unusable))
        raise
    return parsed["cold-reader"], parsed["technical-editor"], receipts


# What one chapter review may return. The same lever the translation critic's bound
# came from, and the same evidence: across twelve calls the unbounded question
# answered 0 of 4 and stopped at exactly 32000 reasoning tokens every time, the
# bounded one answered 4 of 4, and halving the text changed nothing. The technical
# editor spent its ceiling on two chapters running before this existed, and unlike
# the critic it gates the chapter rather than advising it.
REVIEW_MAX_FINDINGS = 6
# What the monolingual reader may return. Small for the same reason the critic's is:
# an answer bounded in the question is an answer that arrives.
LOCALE_READER_MAX_FINDINGS = 6


def _locale_reader_capsule(chapter_id: str, translated: str, style: str) -> dict[str, object]:
    """What the reader is given, and — the point of the role — what it is denied.

    The critic reads the source and the translation side by side, and that is why it
    passed `vai a contare il tuo gesso` for `go count your chalk`: with the English in
    front of you the calque is legible, and you supply the sense the Italian does not
    carry. The defect exists only for a reader who does not have the original, and no
    role in this engine was that reader. Nine broken constructions shipped in two
    pages of landfall's first Italian chapter, past a locale style that forbids
    exactly them and a critic that had read it.

    So: no `source_markdown`, because seeing the source makes a calque parse. And no
    glossary, because a term that is unreadable in the target language has to be
    reported as unreadable rather than excused as agreed — the glossary is the
    critic's authority and this role exists to be outside it.
    """
    return {
        "chapter": chapter_id,
        "translated_markdown": translated,
        "locale_style": style,
        "answer_bound": f"Report at most {LOCALE_READER_MAX_FINDINGS} stumbles, worst first.",
    }


def _locale_reader_findings(value: object) -> list[dict[str, object]]:
    """Its stumbles, in the shape the repair already takes.

    Marked `origin: reader` so the two sources can be counted apart: a defect only
    the monolingual reader finds is the measure of whether this role earns its call.
    """
    rows = value.get("stumbles") if isinstance(value, dict) else None
    findings: list[dict[str, object]] = []
    for index, row in enumerate(rows if isinstance(rows, list) else [], start=1):
        if not isinstance(row, dict):
            continue
        quoted = str(row.get("sentence") or "").strip()
        if not quoted:
            # A stumble that quotes nothing cannot be repaired and cannot be checked.
            continue
        findings.append({
            "id": f"R-{index:02d}",
            "severity": str(row.get("severity") or "warning"),
            "kind": "readability",
            "origin": "reader",
            "source": "",
            "translated": quoted,
            "rule": "reads as the target language",
            "issue": str(row.get("why") or ""),
            "fix": "",
        })
    return findings


# What one style advisor may return. Measured on CH-0008, the first stage a run
# could not retry its way out of: the reviser was handed 45 findings, 30 of them
# from the four style advisors, and had to disposition 21 — fifteen of those from
# the chorus. It answered with 6155 output tokens and missed three, three times
# running. The gate is right to be strict, so the demand is what has to come down,
# and four advisors at this bound still outnumber the two roles that gate the
# chapter, which is what a chorus is for.
STYLE_MAX_FINDINGS = 4
# How many times a chapter reviewer is asked again when it spends its reasoning
# ceiling and writes nothing. Measured over 18 calls of the technical editor on one
# book: 15 answered, and ATT-0260 and ATT-0262 came back differently on the
# identical envelope — for this role the failure is variance and a second ask is
# worth making. That is the opposite of the translation critic, which returned
# nothing on 4 identical asks out of 4 and therefore keeps its single ask.
#
# The stage above also retries, but each of its attempts costs a fresh call of
# every unfinished role. Re-asking here costs one call.
REVIEW_CEILING_REASKS = 3


# What one disposition costs the reviser: the finding id, the action taken, the
# evidence for it, what was lost and what it supersedes. Measured on CH-0013, whose
# three answers were cut at 5251, 5771 and 6069 output tokens against a budget of
# 4000: about 2700 tokens of rewritten chapter and the rest bookkeeping, over some
# twenty findings.
REVISER_TOKENS_PER_DISPOSITION = 160


def _reviser_budget(contract: dict[str, object], findings: list[object]) -> int:
    """Room for the chapter *and* the dispositions it is being asked to write.

    The budget used to be `target_words * 2`, which sizes the answer as if it were
    only the rewritten prose. It is the prose plus one disposition per finding, and
    a budget blind to that half produces a truncation the gate then refuses — three
    paid calls on CH-0013 that could not have fitted.

    Still capped by the role's declared ceiling: a budget that grows without limit
    is how a role stops answering at all, which this engine has measured on four
    roles now.
    """
    prose = max(1000, int(contract.get("target_words") or 0) * 2)
    return min(ROLE_BUDGETS["reviser"][1], prose + len(findings) * REVISER_TOKENS_PER_DISPOSITION)


# How many times the translator is asked for a chapter before it is set aside. One
# first pass and two repairs, each carrying what the gate refused.
TRANSLATION_ATTEMPTS = 3


class TranslationRefused(BookForgeError):
    """A chapter the locale's own rules will not accept, after every repair.

    Kept apart from the errors that mean the engine is broken, because this one
    means the engine worked: a rule was written, the gate held it, and the chapter
    is the thing at fault. It is recorded and skipped so the chapters behind it are
    still translated — CH-0005 carried `i suoi occhi` twice and took thirteen
    chapters down with it before this existed.
    """


REPETITION_MIN_WORDS = 4
REPETITION_STOPWORDS = frozenset(
    "the a an and or but of to in on at for with from by as is was were be been it its "
    "he she they him her them his their that this these those not no so if then than "
    "had has have do did does said says say what who which when where how".split()
)


def _repetition_findings(prose: str) -> list[dict[str, object]]:
    """Count what four paid reviewers did not mention once.

    Measured on two chapters of a finished book: one word five times, one phrase three
    times, and the same image twice within twelve lines. Repetition is the cheapest
    defect to find and it survived every model that read the chapter, so it is found
    by counting instead of by asking.
    """
    body = "\n".join(line for line in prose.splitlines() if not line.startswith("#"))
    words = re.findall(r"[^\W\d_]+(?:'[^\W\d_]+)?", body.lower(), re.UNICODE)
    seen: dict[str, int] = {}
    for size in (REPETITION_MIN_WORDS, REPETITION_MIN_WORDS + 1):
        for start in range(len(words) - size + 1):
            window = words[start : start + size]
            if all(word in REPETITION_STOPWORDS for word in window):
                continue
            if sum(1 for word in window if word not in REPETITION_STOPWORDS) < 2:
                continue
            phrase = " ".join(window)
            seen[phrase] = seen.get(phrase, 0) + 1
    repeated = sorted(((phrase, count) for phrase, count in seen.items() if count > 1), key=lambda row: (-row[1], row[0]))
    covered: list[str] = []
    findings = []
    for phrase, count in repeated:
        if any(phrase in longer for longer in covered):
            continue
        covered.append(phrase)
        findings.append(
            {
                "id": f"R-{len(findings) + 1:04d}",
                "dimension": "style",
                "severity": "note",
                "evidence": phrase,
                "issue": f"the phrase appears {count} times in this chapter",
                "fix_required": False,
                "review": "repetition",
            }
        )
        if len(findings) >= 6:
            break
    # A single distinctive word carried through a chapter is the commoner tic and the
    # phrase window cannot see it: one chapter used the same verb five times.
    # A name recurring is not a tic, so proper nouns are left alone: they are the words
    # that appear capitalised where a sentence did not just begin.
    proper = {
        match.group(1).lower()
        for match in re.finditer(r"(?<![.!?…]\s)(?<!^)(?<![\"«—-])\b([A-Z][^\W\d_]{2,})", body, re.UNICODE | re.MULTILINE)
    }
    counts: dict[str, int] = {}
    for word in words:
        if len(word) >= 6 and word not in REPETITION_STOPWORDS and word not in proper:
            counts[word] = counts.get(word, 0) + 1
    for word, count in sorted(((w, c) for w, c in counts.items() if c >= 5), key=lambda row: (-row[1], row[0]))[:4]:
        if any(word in row["evidence"] for row in findings):
            continue
        # A note, never a warning: the reviser owes a disposition for warnings, and a
        # recurring word is worth seeing without being worth an obligation.
        findings.append(
            {
                "id": f"R-{len(findings) + 1:04d}",
                "dimension": "style",
                "severity": "note",
                "evidence": word,
                "issue": f"the word appears {count} times in this chapter",
                "fix_required": False,
                "review": "repetition",
            }
        )
    return findings


def _call_style_review(root, book_id, chapter_id, contract, draft, runner):
    """Chorus style review on chapters: tag-aware, advisory only (note/warning, never blocking). On by default, opt-out via chorus.style_review: false. Supports per-tag rules with rewrite."""
    try:
        config = _read_json(root / "book-forge.yaml")
    except Exception:
        config = {}
    if not _style_review_enabled(config):
        return []
    # Resolve tag-aware models/rules (e.g., spicy -> grok with rewrite)
    chapter_tags = [str(t).lower() for t in contract.get("tags", []) if isinstance(t, str)]
    rules = _style_review_rules(config)
    matched_rule = None
    for rule in rules:
        rule_tags = [str(t).lower() for t in rule.get("tags", []) if isinstance(t, str)]
        if any(t in chapter_tags for t in rule_tags):
            matched_rule = rule
            break
    if matched_rule:
        style_models = [str(matched_rule.get("reviewer"))] if matched_rule.get("reviewer") else _style_review_models(config)
        # prompt override handled via style_model param; allow_rewrite checked later
    else:
        style_models = _style_review_models(config)
    # Drop stale STYLE tasks for models no longer in the ensemble (never-started only).
    current_slugs = {model.split("/")[-1].replace(".", "-") for model in style_models}
    plan = _load_plan(root)
    for task in [t for t in plan["tasks"] if t["id"].startswith(f"STYLE-{book_id}-{chapter_id}-") and t["state"] == "pending" and t["id"].rsplit("-", 1)[-1] not in current_slugs]:
        plan["tasks"].remove(task)
    _save_plan(root, plan)
    capsule = {
        "book": book_id, "chapter": chapter_id, "contract": contract, "prose": draft, "mode": "style",
        # The last unbounded producer of findings in the chapter pipeline, and the
        # one that was overflowing the reviser downstream of it.
        "answer_bound": f"Report at most {STYLE_MAX_FINDINGS} findings, most severe first.",
    }
    findings = []

    def _normalize(f, slug):
        f = dict(f)
        f["dimension"] = "style"
        if f.get("severity") == "blocking":
            f["severity"] = "warning"
        # Every reviewer numbers its own findings from 01, so without the reviewer's
        # name four of them share one identifier: the reviser is asked to disposition
        # four different requests that answer to `S-01`, and three vanish whatever it
        # does. The name of who raised it makes each finding its own.
        f["id"] = f"S-{slug}-{f.get('id', '000')}"
        f["reviewer"] = slug
        return f

    for model in style_models:
        role = _chorus_advisor_name(model)
        slug = model.split("/")[-1].replace(".", "-")
        task_id = f"STYLE-{book_id}-{chapter_id}-{slug}"
        out_path = root / f"books/{book_id}/reviews/{chapter_id}/style-{slug}.json"
        try:
            plan = _load_plan(root)
            task = next((row for row in plan["tasks"] if row["id"] == task_id), None)
            if out_path.is_file() and task and task["state"] == "succeeded":
                value = _read_json(out_path)
                findings.extend(_normalize(f, slug) for f in value.get("findings", []))
                continue
            if not task:
                add_task(root, task_id, role, deps=[], priority=65, outputs=[f"books/{book_id}/reviews/{chapter_id}/style-{slug}.json"])
        except Exception:
            pass
        envelope = build_envelope(root, role=role, task_capsule={**capsule, "style_model": model}, imports=list(contract.get("imports", [])), state={}, tools=[], max_output_tokens=2000, prompt_role="style-review")
        try:
            claim = claim_task(root, task_id, request_hash=str(envelope["hash"]))
            attempt_dir = Path(claim["capsule"]).parent
            _write_bytes_atomic(attempt_dir / "envelope.json", envelope["bytes"])
            result = runner(role, envelope, attempt_dir)
            mark_provider_accepted(root, claim["attempt"], str(result["session_id"]))
            value = _parse_contract_json(str(result["text"]))
            findings.extend(_normalize(f, slug) for f in value.get("findings", []))
            try:
                _materialize_review_result(root, task_id, claim, envelope, result, value)
            except Exception:
                pass
        except Exception:
            # Advisory style review must not leave running attempts that block parallel reviews
            try:
                plan = _load_plan(root)
                attempt = next((a for a in plan["attempts"] if a["id"] == claim["attempt"]), None) if 'claim' in locals() else None
                if attempt and attempt.get("state") == "running":
                    attempt["state"] = "failed"
                    task = next((t for t in plan["tasks"] if t["id"] == task_id), None)
                    if task:
                        task["state"] = "failed"
                    _save_plan(root, plan)
            except Exception:
                pass
            continue
    return [f for f in findings if f.get("severity") in ("note", "warning")]

def _validate_revision(
    contract: dict[str, object],
    value: dict[str, object],
    findings: list[dict[str, object]],
    technical_consequences: list[dict[str, object]],
    *,
    baseline_prose: str | None = None,
) -> dict[str, object]:
    # A style pass is required to propose only replacements shorter than what they
    # replace, so measuring it against the contract's target forbids it from removing
    # anything once a chapter is already under target — which is when it has most to
    # remove. It is measured against the prose it was handed instead; a reviser that
    # throws half the chapter away is still caught.
    measured = contract
    if baseline_prose is not None:
        baseline_words = len(re.findall(r"\b[\w’'-]+\b", baseline_prose, re.UNICODE))
        measured = {**contract, "target_words": max(1, int(baseline_words / 1.05))}
    validated = validate_writer_output(measured, json.dumps(value))
    dispositions = value.get("dispositions")
    if not isinstance(dispositions, list):
        raise BookForgeError("Revision has no finding dispositions")
    by_finding = {str(row.get("finding")): row for row in dispositions if isinstance(row, dict)}
    # A note is an observation, not a request for a change — one of them read
    # "both plants are seeded cleanly with no contradiction". Owing a formal
    # action/evidence/loss record for praise crowded out the actual revision.
    owed = {str(finding["id"]) for finding in findings if finding.get("severity") in {"blocking", "warning"}}
    known = {str(finding["id"]) for finding in findings}
    if not owed <= set(by_finding):
        missing = ", ".join(sorted(owed - set(by_finding)))
        raise BookForgeError(f"Revision must disposition every blocking and warning finding exactly once; missing {missing}")
    if not set(by_finding) <= known:
        stray = ", ".join(sorted(set(by_finding) - known))
        raise BookForgeError(f"Revision dispositions a finding that was not raised: {stray}")
    for finding in findings:
        disposition = by_finding.get(str(finding["id"]))
        if disposition is None:
            continue
        required = {"action", "evidence", "loss"}
        if not required <= disposition.keys():
            raise BookForgeError(f"Incomplete disposition for {finding['id']}")
        disposition.setdefault("supersedes", [])
        # Preserve supersedes via get with default for validated copy (JSON round-trip)
        validated_dispositions = validated.get("dispositions") if isinstance(validated.get("dispositions"), list) else []
        validated_by = {str(row.get("finding")): row for row in validated_dispositions if isinstance(row, dict)}
        validated_row = validated_by.get(str(finding["id"]))
        if isinstance(validated_row, dict):
            validated_row.setdefault("supersedes", disposition.get("supersedes", []))
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
    style_findings = _call_style_review(root, book_id, chapter_id, contract, draft, runner)
    style_findings = style_findings + _repetition_findings(draft)
    cold, technical, receipts = _call_parallel_reviews(root, book_id, chapter_id, contract, draft, writer_consequences, runner)
    technical_findings = []
    for position, finding in enumerate(technical["findings"], start=1):
        renamed = dict(finding)
        renamed["id"] = f"T-{position:04d}"
        renamed["review"] = "technical"
        technical_findings.append(renamed)
    findings = list(style_findings) + list(cold["findings"]) + technical_findings
    # Feedback loop: if previous verification exists (retry after failed verify), inject its blocking/warning findings so reviser sees them
    try:
        prev_verif_path = root / f"books/{book_id}/reviews/{chapter_id}/verification.json"
        if prev_verif_path.is_file():
            prev_verif = _read_json(prev_verif_path)
            prev_findings = prev_verif.get("findings") or []
            # Only inject findings that verifier still reports (avoid stale)
            findings.extend([f for f in prev_findings if f.get("severity") in ("blocking", "warning")])
    except Exception:
        pass
    reviser_id = f"REVISE-{book_id}-{chapter_id}"
    envelope = build_envelope(
        root,
        role="reviser",
        task_capsule={"book": book_id, "chapter": chapter_id, "contract": contract, "draft": draft, "findings": findings, "technical_consequences": technical["consequences"]},
        imports=list(contract.get("imports", [])),
        state=_read_json(root / "books" / book_id / "state.yaml"),
        tools=[],
        max_output_tokens=_reviser_budget(contract, findings),
    )
    claim = claim_task(root, reviser_id, request_hash=str(envelope["hash"]))
    attempt_dir = Path(claim["capsule"]).parent
    _write_bytes_atomic(attempt_dir / "envelope.json", envelope["bytes"])
    result = runner("reviser", envelope, attempt_dir)
    mark_provider_accepted(root, claim["attempt"], str(result["session_id"]))
    try:
        value = _parse_contract_json(str(result["text"]))
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
        f"books/{book_id}/manuscript/chapters/{chapter_id}.md": _with_contract_heading(str(validated["prose_markdown"]), contract).rstrip() + "\n",
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
        verification_findings = verification.get("findings") or []
        # Gate: only blocking findings fail promotion; warning/note are advisory (verifier is stochastic/pignolo)
        blocking_findings = [f for f in verification_findings if f.get("severity") == "blocking"]
        if verification.get("verified") is not True or blocking_findings:
            _set_attempt_failure(root, verify_claim["attempt"], block=True, reason="Independent semantic verification failed")
            raise BookForgeError("Independent semantic verification failed; chapter remains unpromoted")
        # Always materialize verification even on success (for traceability)
        
        receipts.append(_materialize_review_result(root, verify_id, verify_claim, verification_envelope, verification_result, verification))
        calls += 1
    promote_task(root, claim["attempt"], claim["fence"])
    machine_state = _read_json(root / ".book-forge" / "state.json")
    machine_state["source_locked"] = True
    machine_state["source_language"] = _read_json(root / "book-forge.yaml")["source_language"]
    _write_json(root / ".book-forge" / "state.json", machine_state)
    _ensure_artifact(root, *_source_chapter_artifact(root, book_id, chapter_id))
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


LOCALE_STYLE_STUB = "Define register, dialogue punctuation, narrative tense, and voice-preservation decisions here."


def _require_locale_style(root: Path, book_id: str, locale: str) -> None:
    """A translation does not start before someone has decided how the book speaks.

    Left unedited, the translator improvises: one book came back mixing the formal
    and familiar registers inside sentences that also used the formal address, with
    a masculine adjective on a female character and English title case on a heading.
    """
    path = root / "books" / book_id / "translations" / locale / "style.md"
    if not path.is_file() or LOCALE_STYLE_STUB in path.read_text(encoding="utf-8"):
        raise BookForgeError(
            f"Locale style is still the generated stub: {path.relative_to(root)}. "
            "Decide the register, how dialogue is punctuated, and which voices are preserved, "
            "before any prose is translated"
        )


TITLE_CASE_LOCALES_EXEMPT = ("en",)


def _heading_case_problem(translated: str, locale: str) -> str | None:
    """English title case on a heading in a language that does not use it."""
    if locale.split("-")[0].lower() in TITLE_CASE_LOCALES_EXEMPT:
        return None
    for line in translated.splitlines():
        if not line.startswith("#"):
            continue
        words = [w for w in re.findall(r"[^\W\d_]+", line[1:], re.UNICODE) if len(w) > 3]
        if len(words) >= 3 and all(w[:1].isupper() for w in words):
            return f"heading uses English title case: {line.strip()!r}"
    return None


# What a locale can say to a machine. The engine carries the mechanism; the rules
# are the project's, in `translations/<locale>/checks.yaml`, because a skill that
# hardcodes one language's tense law is a skill nobody else can install.
LOCALE_CHECKS_STUB = "Record the target language's machine-checkable rules here."


def _locale_checks(locale_root: Path) -> dict[str, object]:
    """The locale's machine-checkable rules, or nothing if it declares none."""
    path = locale_root / "checks.yaml"
    if not path.is_file():
        return {}
    try:
        value = _read_json(path)
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _forbidden_form_problems(translated: str, checks: dict[str, object]) -> list[str]:
    """Forms the locale forbids outright.

    Exact, free, and never wrong about what it found: the pattern either matches
    the delivered text or it does not. Landfall's `stette` sat in three chapters
    that every other gate passed, because no gate read the target language.
    """
    problems = []
    for row in checks.get("forbidden", []) if isinstance(checks.get("forbidden"), list) else []:
        if not isinstance(row, dict):
            continue
        pattern = str(row.get("pattern") or "").strip()
        if not pattern:
            continue
        try:
            found = re.findall(pattern, translated, re.IGNORECASE | re.UNICODE)
        except re.error:
            problems.append(f"locale checks: {pattern} is not a usable pattern")
            continue
        if found:
            seen = sorted({str(match if isinstance(match, str) else match[0]) for match in found})
            reason = str(row.get("reason") or "forbidden by the locale checks")
            problems.append(f"forbidden form {', '.join(seen[:4])}: {reason}")
    return problems


def _glossary_terms(glossary: str) -> list[tuple[list[str], list[str]]]:
    """The glossary's rows as (source alternatives, target alternatives)."""
    rows = []
    for line in glossary.splitlines():
        if not line.startswith("- **") or "** → " not in line:
            continue
        source_part, rest = line[4:].split("**", 1)
        target_part = rest.split("→", 1)[1].split(" — ", 1)[0]
        def _clean(piece: str) -> str:
            # A gloss in brackets belongs to neither side of the row. Stripping it
            # from the source only left `i ripetitori a specchio (via degli specchi)`
            # being looked for with its own explanation attached.
            return re.sub(r"\([^)]*\)", "", piece).strip()

        # A source side carrying the row's note separator has its braces in the
        # wrong place, and which half is the term cannot be told apart from which
        # half is the note: `**wind / foggia — the boatman's rig**` made `wind` a
        # glossary term and flagged every chapter containing one of the commonest
        # words in English. A row nobody can read is a row nobody checks against.
        if "—" in source_part:
            continue
        sources = [_clean(piece) for piece in source_part.split("/")]
        targets = [_clean(piece) for piece in re.split(r"[/,]", target_part)]
        sources = [value for value in sources if len(value) >= 4]
        targets = [value for value in targets if len(value) >= 4]
        if sources and targets:
            # Longest first, so a row offering both `fen-gate` and `the gate` is
            # judged on the specific alternative when the chapter contains it.
            rows.append((sorted(sources, key=len, reverse=True), targets))
    return rows


# Italian and its neighbours inflect, so a rendering is looked for by its content
# words with the ending left open: `gesso di marea` must also match `gessi di marea`.
# What separates an inflected form from a different word: one letter of ending.
INFLECTION_TAIL = r"\w?"
_GLOSSARY_FUNCTION_WORDS = {"il", "lo", "la", "i", "gli", "le", "un", "una", "di", "del", "della", "dei", "delle", "da", "a", "e", "the", "of", "l'"}


def _term_pattern(term: str, *, drop_leading_article: bool = False) -> str:
    r"""A term as its content words, joined loosely and left open at the end.

    `tide-chalk` must match the hyphen the source writes and the space another
    text writes, and `gesso di marea` must also match `gessi di marea`, so a word
    long enough to inflect gives up its last letter.

    The leading article is dropped rather than required: the row says `il registro
    di riva` and the chapter says `del registro di riva`, and requiring the row's
    own article reported a term as missing while it sat in the sentence. A
    four-letter word inflects too when the term has more than one content word —
    `mano della palude` must recognise `mani della palude` — and stays literal on
    its own, where `man\w*` would match half the dictionary.

    The article is dropped from the rendering being looked for and never from the
    term being looked up. English uses it to tell a proper noun from a common one:
    `the Wall` is the returning tide and `wall` is a wall, and dropping the article
    on that side reported the row against six ordinary walls.
    """
    words = re.findall(r"[\w']+", term, re.UNICODE)
    content = [word for word in words if word.casefold() not in _GLOSSARY_FUNCTION_WORDS]
    while drop_leading_article and words and words[0].casefold() in _GLOSSARY_FUNCTION_WORDS:
        words = words[1:]
    pieces = []
    for word in words:
        if word.casefold() in _GLOSSARY_FUNCTION_WORDS:
            pieces.append(re.escape(word))
        elif len(word) >= 5 or (len(word) >= 4 and len(content) > 1):
            # One letter, not any number of them. Inflection changes an ending;
            # derivation replaces it, and an open tail read `watch-lieutenancy`
            # as the term `watch-lieutenant` and called a correct rendering of
            # the office a missing rendering of the person.
            pieces.append(re.escape(word[:-1]) + INFLECTION_TAIL)
        else:
            pieces.append(re.escape(word) + INFLECTION_TAIL)
    # Anchored at the end, or the bounded tail buys nothing: the pattern is not
    # anchored by default, so `lieutenan\w?` still matches the first ten letters
    # of `lieutenancy` and the term is read into a word that is not it.
    return r"[\s\-\u2010-\u2015]+".join(pieces) + r"\b" if pieces else ""


def _glossary_compliance(source: str, translated: str, glossary: str) -> list[str]:
    """Terms the source uses whose agreed rendering never reaches the translation.

    Advisory, not a gate: the match tolerates inflection and can therefore be
    wrong, and a heuristic inside a blocking check is how a book deadlocks. It is
    exact enough to be worth a repair call and not to be trusted with a refusal.
    """
    def _flags(term: str) -> int:
        # A capitalised term is a name, and English tells `the Wall` from `wall`
        # by the capital alone. Folding the case there turns every ordinary wall
        # into a missing proper noun.
        capitalised = any(word[:1].isupper() for word in re.findall(r"[\w']+", term)[1:] or re.findall(r"[\w']+", term))
        return re.UNICODE if capitalised else re.IGNORECASE | re.UNICODE

    findings = []
    for sources, targets in _glossary_terms(glossary):
        used = next(
            (value for value in sources if re.search(_term_pattern(value), source, _flags(value))),
            None,
        )
        if not used:
            continue
        if any(
            re.search(_term_pattern(value, drop_leading_article=True), translated, _flags(value))
            for value in targets
        ):
            continue
        findings.append(f"glossary: the source uses {used!r} and the translation never renders it as {targets[0]!r}")
    return findings


def _translation_validation(source: str, value: dict[str, object], checks: dict[str, object] | None = None) -> list[str]:
    translated = value.get("translated_markdown")
    problems = []
    if not isinstance(translated, str) or not translated.strip():
        return ["missing translated_markdown"]
    if not isinstance(value.get("glossary_updates"), list):
        problems.append("missing glossary_updates")
    if not isinstance(value.get("boundary"), str) or not value["boundary"].strip():
        problems.append("missing translated boundary")
    heading = _heading_case_problem(translated, str(value.get("_locale") or ""))
    if heading:
        problems.append(heading)
    problems.extend(_forbidden_form_problems(translated, checks or {}))
    # A locale writes 5,8 where the source writes 5.8. Comparing the literal strings
    # made a correctly localized number look like a changed one, and since the repair
    # attempt carries the failure reason, the loop taught the translator to keep the
    # source's separator — which is how an Italian edition ends up writing 0.2%.
    # Normalizing keeps 131 and 1.31 distinct, and order and count still hold.
    def _numbers(text_value: str) -> list[str]:
        return [value.replace(",", ".") for value in re.findall(r"(?<!\w)\d+(?:[.,]\d+)?", text_value)]

    if _numbers(source) != _numbers(translated):
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



def _translation_review_enabled(config: dict[str, object]) -> bool:
    section = config.get("translation")
    if isinstance(section, dict) and "review" in section:
        return bool(section["review"])
    return True



# What a failure needs. An unusable answer is a question that was heard and
# answered badly, so it is asked again at once, carrying what was wrong with the
# last answer. Silence is a window, and tonight the windows were minutes long:
# two writer calls quiet for 900s each while the identical envelope answered in
# 340, and a critic that produced no text twice in a row and read the same
# chapter fine on the next command. Asking again inside the window spends a call
# to be told the same nothing and burns the retry before the window closes.
SILENCE_RETRY_DELAYS = {1: 60.0, 2: 180.0}
# Three asks: a dead provider costs four minutes of waiting, not a night.
CRITIC_ATTEMPTS = 3
# How many findings one critic call may return. Not a preference — measured.
# Twelve calls on the chapter this role failed most, four repetitions of three
# arms, every call at `medium` on the same model: the question as it was asked
# answered 0 of 4 and stopped at exactly 32000 reasoning tokens every time; the
# same question with this bound lowered to four answered 4 of 4; half the chapter
# at twelve answered 3 of 4 and the failure was at 31999, on half the text. So it
# is the size of the answer demanded that decides whether the model reaches the
# ceiling, and not the size of the text it is given — which is why the chapter is
# still read whole. Raising this buys more findings per call and, past some point
# this measurement does not locate, buys none at all.
CRITIC_MAX_FINDINGS = 4


def _is_silence(exc: BaseException) -> bool:
    """Whether the provider gave nothing, as opposed to something unusable."""
    if isinstance(exc, ReasoningCeilingSpent):
        # It answered and it billed. Waiting out a window that never opened would
        # add four minutes to a failure that is the same every time.
        return False
    if isinstance(exc, (ProviderProducedNothing, ProviderOutcomeUnknown)):
        return True
    text = str(exc)
    return "produced no result" in text or "no observable text" in text


def _refuse_empty_answer(role: str, subject: str, result: dict[str, object]) -> None:
    """Raise when a paid-for call came back with nothing written in it.

    Told apart from a malformed answer by the counters the provider returns: text
    that is empty while reasoning tokens were spent is a model that thought until
    it had no room left to speak, and asking it again spends the same amount to be
    told the same nothing.
    """
    if str(result.get("text") or "").strip():
        return
    tokens = result.get("tokens") if isinstance(result.get("tokens"), dict) else {}
    reasoning = int(tokens.get("reasoning") or 0)
    output = int(tokens.get("output") or 0)
    if not reasoning:
        return
    raise ReasoningCeilingSpent(
        f"{role} answered {subject} with {output} output token(s) after spending {reasoning} on reasoning: "
        "the ceiling went on thinking and left no room to write"
    )


def _wait_before_retry(role: str, subject: str, failed_attempt: int, exc: BaseException, runner=None) -> float:
    """Sleep before asking again, but only when the last answer was silence.

    Returns what it waited, so a caller can report it. The claim of the failed
    attempt is settled before this is called, never across it, so a run killed
    during the wait leaves nothing half-held.

    Only a real provider is waited for. A substituted runner has no window to
    wait out — it answered the way it was told to — and making the engine sleep
    for one turned a two-minute suite into a timeout.
    """
    if runner is not None and runner is not run_opencode_role:
        return 0.0
    if not _is_silence(exc):
        return 0.0
    delay = SILENCE_RETRY_DELAYS.get(failed_attempt, 0.0)
    if delay <= 0:
        return 0.0
    print(
        f"[{role}] {subject}: the provider answered nothing; waiting {int(delay)}s before asking again",
        file=sys.stderr,
    )
    time.sleep(delay)
    return delay


def _cited_findings(findings: object) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Split what the critic returned into what can be acted on and what cannot.

    A finding that quotes no source and no translation names nothing the repair
    could substitute, so it is set aside and recorded rather than argued with —
    the same treatment the canon auditor gives evidence that resolves to nothing.
    """
    kept, aside = [], []
    for row in findings if isinstance(findings, list) else []:
        if not isinstance(row, dict):
            continue
        quoted = str(row.get("translated") or "").strip()
        rule = str(row.get("rule") or "").strip()
        (kept if quoted and rule else aside).append(row)
    return kept, aside




# How many times a chapter may be read back before the route stops on its own.
REVIEW_PASS_CAP = 4
ACTIONABLE_SEVERITIES = frozenset({"blocking", "warning"})


def _finding_fingerprint(finding: dict[str, object]) -> str:
    """What makes two findings the same finding across two passes.

    The kind and the span it quotes, with spacing and case flattened: a critic
    that reports the same defect twice will not word its `issue` identically, and
    the quoted span is the part it cannot paraphrase without pointing elsewhere.
    """
    quoted = re.sub(r"\s+", " ", str(finding.get("translated") or finding.get("issue") or "")).strip().casefold()
    return f"{finding.get('kind') or '?'}:{_sha256_bytes(quoted.encode())[:16]}"


def _actionable(findings: list[dict[str, object]]) -> list[dict[str, object]]:
    return [row for row in findings if str(row.get("severity")) in ACTIONABLE_SEVERITIES]


def _pass_state_path(root: Path, book_id: str, locale: str, chapter_id: str) -> Path:
    """Where a pass leaves what the next pass needs to compare against.

    Beside the review rather than inside it: the review is a promoted artifact
    with a hash on its receipt, and the outcome of the repair is only known after
    that receipt is written.
    """
    return root / "books" / book_id / "translations" / locale / "reviews" / f"{chapter_id}.state.json"


def _previous_pass(root: Path, book_id: str, locale: str, chapter_id: str) -> dict[str, object]:
    try:
        return _read_json(_pass_state_path(root, book_id, locale, chapter_id))
    except (OSError, ValueError):
        return {}


def _record_pass_state(
    root: Path, book_id: str, locale: str, chapter_id: str, convergence: dict[str, object], repaired: bool, text: str
) -> None:
    """What this pass leaves for the next one, and what it must not take away.

    A pass whose critic never answered knows nothing about the chapter, so it
    writes down that it did not read it and leaves the previous reading's
    fingerprints and count where they are. Overwriting them with the empty set a
    failed pass produces would tell the next pass that a chapter it has never
    seen read has nothing in it — which is how `unread` came to be recorded as
    `clean` in the first place.
    """
    record = {
        "schema": 1,
        "chapter": chapter_id,
        "state": convergence["state"],
        "reason": convergence["reason"],
        "actionable": convergence["actionable"],
        "fingerprints": convergence["fingerprints"],
        "repaired": bool(repaired),
        "text_sha256": _sha256_bytes(text.encode()),
        "verdict_inconsistent": convergence["verdict_inconsistent"],
        "not_landed": convergence["not_landed"],
    }
    if not convergence.get("read", True):
        previous = _previous_pass(root, book_id, locale, chapter_id)
        record["asks"] = int(convergence.get("asks", 0))
        # Which failure it was, in the file that survives the run: the review
        # artifact is only written by a pass that succeeded, so a pass that failed
        # outright has nowhere else to say what happened to it.
        record["unread_because"] = str(convergence.get("unread_because") or "")
        record["actionable"] = previous.get("actionable", convergence["actionable"])
        record["fingerprints"] = previous.get("fingerprints", convergence["fingerprints"])
        # Whose reading those fingerprints came from, so the carry-over is legible
        # on disk rather than looking like this pass produced them.
        record["carried_from"] = str(previous.get("state") or "no earlier pass")
    _write_json(_pass_state_path(root, book_id, locale, chapter_id), record)


def _convergence(
    previous: dict[str, object],
    findings: list[dict[str, object]],
    verdict: str,
    repaired_before: bool,
    *,
    asks: int = 0,
) -> dict[str, object]:
    """What this pass learned by being compared with the one before it.

    A route that always finds something needs a way to tell a chapter that is
    finished from one that still has defects, or the decision of when to stop
    reading falls to whoever is watching — by feel, which is the judgement this
    engine exists to remove. CH-0001 was read four times and returned 17 findings,
    then 6, then 12, and nobody could say whether that was three improvements or
    three inventions.
    """
    fingerprints = {_finding_fingerprint(row) for row in _actionable(findings)}
    before = {str(value) for value in previous.get("fingerprints", [])}
    before_count = int(previous.get("actionable", -1))
    count = len(fingerprints)
    repeated = sorted(fingerprints & before)
    # A reading that did not happen and a reading that found nothing both arrive
    # here with an empty finding set, and they are opposite outcomes: one says the
    # chapter is finished, the other says the pass failed. Two consecutive reviews
    # of landfall's CH-0001 failed all three asks apiece and were recorded as
    # `clean`, reason `nothing left to act on` — on a chapter nobody had read.
    read = str(verdict).casefold() != "unread"
    state = "more-to-do"
    reason = f"{count} finding(s) to act on"
    if not read:
        state = "unread"
        reason = (
            f"the critic was not read in {asks} ask(s)" if asks else "the critic has not been asked yet"
        )
    elif not count:
        state, reason = "clean", "nothing left to act on"
    elif before_count >= 0 and count >= before_count:
        state = "no-progress"
        reason = f"{count} finding(s), and the pass before found {before_count}"
    # A repair that said it applied a finding, and the same finding coming back,
    # is worse than a repair that refused: the refusal was at least recorded.
    not_landed = sorted(repeated) if repaired_before else []
    inconsistent = bool(
        str(verdict).casefold() == "faithful"
        and any(str(row.get("severity")) == "blocking" or str(row.get("kind")) == "meaning" for row in findings)
    )
    return {
        "state": state,
        "reason": reason,
        "read": read,
        "asks": asks,
        "actionable": count,
        "repeated": len(repeated),
        "new": len(fingerprints - before),
        "gone": len(before - fingerprints),
        "not_landed": not_landed if read else [],
        "verdict_inconsistent": inconsistent,
        "fingerprints": sorted(fingerprints),
    }


def _ask_locale_reader(
    root: Path, book_id: str, locale: str, chapter_id: str, translated: str, style: str, runner
) -> list[dict[str, object]]:
    """The chapter read by someone who cannot see where it came from.

    Advisory and never a stop: a reader that fails leaves the critic's findings
    standing, because a chapter with no second opinion is worse read, not unread.
    """
    task_id = f"LOCREAD-{book_id}-{chapter_id}-{locale}"
    plan = _load_plan(root)
    if not any(task["id"] == task_id for task in plan["tasks"]):
        add_task(root, task_id, "locale-reader", priority=80, outputs=[])
    else:
        _reopen_task(root, task_id)
    claim = None
    try:
        envelope = build_envelope(
            root,
            role="locale-reader",
            task_capsule=_locale_reader_capsule(chapter_id, translated, style),
            imports=[],
            state={},
            tools=[],
            max_output_tokens=ROLE_BUDGETS["locale-reader"][1],
        )
        claim = claim_task(root, task_id, request_hash=str(envelope["hash"]))
        attempt_dir = Path(claim["capsule"]).parent
        result = runner("locale-reader", envelope, attempt_dir)
        mark_provider_accepted(root, claim["attempt"], str(result.get("session_id") or ""))
        _refuse_empty_answer("locale-reader", chapter_id, result)
        value = _parse_contract_json(str(result["text"]))
        findings = _locale_reader_findings(value)
        if not value.get("followed", True):
            # A reader who cannot say what the chapter is about has found the largest
            # defect in it, and it lives in no single sentence.
            print(
                f"[locale-reader] {chapter_id}: could not follow the chapter — {str(value.get('summary') or '')[:120]}",
                file=sys.stderr,
            )
        if findings:
            print(
                f"[locale-reader] {chapter_id}: {len(findings)} stumble(s) a reader without the source hit",
                file=sys.stderr,
            )
        _set_attempt_failure(root, claim["attempt"], block=False, reason="advisory pass complete")
        return findings
    except Exception as unread:
        # Broad on purpose. This pass advises and nothing downstream needs it, so it
        # must not be able to stop a translation by any route — not a refused answer,
        # not a provider that has never heard of the role. Everything else in this
        # engine that fails advisory-only is settled with `block=False` and the run
        # goes on; this one cannot even raise.
        if claim is not None:
            try:
                _set_attempt_failure(root, claim["attempt"], block=False, reason=str(unread)[:200])
            except BookForgeError:
                pass
        print(f"[locale-reader] {chapter_id} was not read: {str(unread)[:160]}", file=sys.stderr)
        return []


def _score_machine_findings(
    machine: list[dict[str, object]], verdicts: object
) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, int]]:
    """Split the mechanical findings by what the reader they feed made of them.

    The checks are cheap and sometimes wrong, and nothing here knew how often.
    On landfall's three Italian chapters the glossary check raised twelve and was
    right about five, and that number was counted by hand — so the next time it
    drifted, the person who found out would have been whoever read the book.

    The critic has both texts open and the cited rule in front of it, which the
    check did not, so its verdict is the cheapest true measurement available:
    it is already producing an answer, and this is a few tokens more of it.
    Silence is not a refutation — an unanswered finding holds.
    """
    ruling = {}
    for row in verdicts if isinstance(verdicts, list) else []:
        if isinstance(row, dict) and str(row.get("id") or "").strip():
            ruling[str(row["id"]).strip()] = row
    held, mistaken = [], []
    for finding in machine:
        row = ruling.get(str(finding.get("id")))
        if row and str(row.get("verdict") or "").strip().casefold() == "mistaken":
            mistaken.append({**finding, "verdict": "mistaken", "why": str(row.get("why") or "")})
        else:
            held.append(finding)
    return held, mistaken, {
        "raised": len(machine),
        "held": len(held),
        "mistaken": len(mistaken),
    }


def _review_translation(
    root: Path,
    book_id: str,
    locale: str,
    chapter_id: str,
    contract: dict[str, object],
    source: str,
    translated: str,
    *,
    runner,
) -> dict[str, object]:
    """Read the translation back against the source, and repair what is cited.

    The prose has a review stack and a translation had one call and nobody reading
    it. Half of this needs no model: the glossary is machine-readable, so a term
    the source uses and the translation never renders is an exact finding. The
    other half is judgement — a calque is grammatical, breaks no listed rule, and
    is still wrong — and that is what the critic is for.

    Advisory throughout. A critic that cannot be reached, an answer that will not
    parse, a repair that comes back worse: each is recorded beside the chapter and
    the translation that already validated is kept. Nothing here stops a run and
    nothing asks a person.
    """
    locale_root = root / "books" / book_id / "translations" / locale
    glossary = (locale_root / "glossary.md").read_text(encoding="utf-8")
    style = (locale_root / "style.md").read_text(encoding="utf-8")
    findings: list[dict[str, object]] = [
        {
            "id": f"G-{index:02d}",
            "severity": "warning",
            "kind": "glossary",
            "rule": "the locale glossary",
            "issue": problem,
            "source": "",
            "translated": "",
            "fix": "",
        }
        for index, problem in enumerate(_glossary_compliance(source, translated, glossary), start=1)
    ]
    # The locale's own rules run here too, not only while a chapter is translated.
    # A rule written after a translation exists is exactly the rule that chapter
    # never met: landfall's review repaired forty-eight findings and left an
    # un-contracted preposition standing, because `checks.yaml` was never opened.
    findings.extend(
        {
            "id": f"L-{index:02d}",
            "severity": "warning",
            "kind": "style",
            "rule": "the locale checks",
            "issue": problem,
            "source": "",
            "translated": "",
            "fix": "",
        }
        for index, problem in enumerate(_forbidden_form_problems(translated, _locale_checks(locale_root)), start=1)
    )
    set_aside: list[dict[str, object]] = []
    verdict = "unread"
    machine_score = {"raised": len(findings), "held": len(findings), "mistaken": 0}
    # Read once, before the asks: every convergence below is measured against the
    # last pass that actually read this chapter, and a pass that fails must not be
    # the one that decides what the next pass compares with.
    previous = _previous_pass(root, book_id, locale, chapter_id)
    convergence = _convergence(previous, findings, verdict, False)
    task_id = f"TRANSCRIT-{book_id}-{chapter_id}-{locale}"
    review_path = f"books/{book_id}/translations/{locale}/reviews/{chapter_id}.json"
    plan = _load_plan(root)
    if not any(task["id"] == task_id for task in plan["tasks"]):
        add_task(
            root,
            task_id,
            "translation-critic",
            priority=82,
            chapter_order=int(contract.get("order", 0)),
            outputs=[review_path],
        )
    else:
        # A review is repeatable by nature: a locale rule written after a chapter
        # was translated is exactly the rule that chapter never met. Without this
        # a chapter can be read back once in its life, and the second pass finds
        # its own task already succeeded.
        _reopen_task(root, task_id)
    # The critic's output is the most structured this engine asks for, which makes
    # it the most likely to come back malformed, and it was the only role with no
    # second ask. Two of landfall's three chapters went unread for want of one.
    unreadable = ""
    for attempt_number in range(1, CRITIC_ATTEMPTS + 1):
        claim = None
        try:
            capsule = {
                "book": book_id,
                "chapter": chapter_id,
                "target_locale": locale,
                "source_markdown": source,
                "translated_markdown": translated,
                "locale_style": style,
                "glossary": glossary,
                # Labelled as the machine's, not mixed into the critic's own, so it
                # judges them instead of inheriting them.
                "machine_findings": [
                    {"id": row["id"], "rule": row["rule"], "issue": row["issue"]} for row in findings
                ],
                # In the question rather than only in the prompt, so the bound the
                # engine enforces and the bound the model is told are one value.
                "answer_bound": f"Report at most {CRITIC_MAX_FINDINGS} findings, most severe first.",
            }
            if unreadable:
                capsule["retry"] = {
                    "attempt": attempt_number,
                    "why_the_last_answer_was_unusable": unreadable,
                    "instruction": "Return one JSON object and nothing else. No prose before or after it.",
                }
            envelope = build_envelope(
                root,
                role="translation-critic",
                task_capsule=capsule,
                imports=[],
                state={},
                tools=[],
                max_output_tokens=9000,
            )
            claim = claim_task(root, task_id, request_hash=str(envelope["hash"]))
            attempt_dir = Path(claim["capsule"]).parent
            result = runner("translation-critic", envelope, attempt_dir)
            mark_provider_accepted(root, claim["attempt"], str(result.get("session_id") or ""))
            _refuse_empty_answer("translation-critic", chapter_id, result)
            value = _parse_contract_json(str(result["text"]))
            held, mistaken, machine_score = _score_machine_findings(findings, value.get("machine_findings"))
            if mistaken:
                print(
                    f"[translation-critic] {chapter_id}: {len(mistaken)} of {machine_score['raised']} machine "
                    f"finding(s) called mistaken and dropped before the repair",
                    file=sys.stderr,
                )
            if machine_score["raised"] >= 4 and machine_score["held"] * 2 < machine_score["raised"]:
                print(
                    f"[translation-critic] {chapter_id}: the mechanical checks were right "
                    f"{machine_score['held']} time(s) out of {machine_score['raised']} — a check that is mostly "
                    "wrong is a defect in the check",
                    file=sys.stderr,
                )
            findings = held
            cited, aside = _cited_findings(value.get("findings"))
            findings.extend(cited)
            set_aside.extend(aside)
            findings.extend(_ask_locale_reader(root, book_id, locale, chapter_id, translated, style, runner))
            verdict = str(value.get("verdict") or "repairable")
            convergence = _convergence(previous, findings, verdict, bool(previous.get("repaired")))
            if convergence["verdict_inconsistent"]:
                print(
                    f"[translation-critic] {chapter_id}: the verdict says faithful beside findings that change "
                    "meaning; the findings stand and the verdict is recorded as inconsistent",
                    file=sys.stderr,
                )
            if convergence["not_landed"]:
                print(
                    f"[translation-critic] {chapter_id}: {len(convergence['not_landed'])} finding(s) came back "
                    "after a repair that claimed to apply them",
                    file=sys.stderr,
                )
            manifest = stage_outputs(root, claim["attempt"], {review_path: _json_bytes(
                {
                    "schema": 1, "chapter": chapter_id, "verdict": verdict, "findings": findings,
                    "set_aside": set_aside, "machine_findings": machine_score, "mistaken": mistaken,
                    "convergence": convergence,
                }
            )})
            record_execution(
                root,
                claim["attempt"],
                claim["fence"],
                output_hash=_sha256_bytes(_json_bytes(manifest)),
                telemetry=_provider_telemetry(result, envelope),
            )
            promote_task(root, claim["attempt"], claim["fence"])
            break
        except BookForgeError as exc:
            unreadable = str(exc)
            if claim is not None:
                # `block=False`, always. This pass advises; a reading that fails is
                # a chapter without advice, and it must not be a run that stops for
                # every chapter after it. Landfall lost two that way.
                _set_attempt_failure(root, claim["attempt"], block=False, reason=unreadable)
            # An identical envelope that exhausted the ceiling exhausts it again, so
            # the remaining asks are not spent. Two of every three calls on this
            # failure bought nothing before this line existed.
            spent = isinstance(exc, ReasoningCeilingSpent)
            if spent or attempt_number == CRITIC_ATTEMPTS:
                print(
                    f"[translation-critic] {chapter_id} was not read, asked {attempt_number} time(s): {unreadable}",
                    file=sys.stderr,
                )
                set_aside.append({
                    "id": "C-exhausted" if spent else "C-unread",
                    "severity": "note",
                    "kind": "critic",
                    "issue": unreadable,
                })
                convergence = _convergence(previous, findings, "unread", False, asks=attempt_number)
                convergence["unread_because"] = unreadable
                break
            _wait_before_retry("translation-critic", chapter_id, attempt_number, exc, runner)
    if set_aside:
        print(
            f"[translation-critic] {chapter_id}: {len(set_aside)} finding(s) set aside, cited nothing that resolves",
            file=sys.stderr,
        )
    return {
        "findings": findings,
        "set_aside": set_aside,
        "verdict": verdict,
        "machine": machine_score,
        "convergence": convergence,
    }




def _record_unapplied(root: Path, book_id: str, locale: str, chapter_id: str, findings: list[dict[str, object]]) -> None:
    """What the repair could not apply, beside the chapter rather than in a log line.

    A finding the pipeline raised and could not act on is the one thing a person
    might still want to see, and a line on stderr is gone the moment the terminal
    scrolls.
    """
    _write_json(
        root / "books" / book_id / "translations" / locale / "reviews" / f"{chapter_id}.unapplied.json",
        {"schema": 1, "chapter": chapter_id, "unapplied": findings},
    )


def _repair_translation(
    root: Path,
    book_id: str,
    locale: str,
    chapter_id: str,
    contract: dict[str, object],
    source: str,
    value: dict[str, object],
    findings: list[dict[str, object]],
    *,
    runner,
) -> dict[str, object] | None:
    """One repair call carrying the cited findings, or None if it did not improve.

    The repair is held to the same gate the translation was: if what comes back
    does not validate, the translation that did is kept. A review that makes a
    chapter worse is a review that costs a call, not a chapter.
    """
    locale_root = root / "books" / book_id / "translations" / locale
    task_id = f"TRANSFIX-{book_id}-{chapter_id}-{locale}"
    plan = _load_plan(root)
    if not any(task["id"] == task_id for task in plan["tasks"]):
        add_task(root, task_id, "translator", priority=84, chapter_order=int(contract.get("order", 0)))
    else:
        _reopen_task(root, task_id)
    # Everything else here that produces text is told what was wrong with it and
    # asked again. The repair was the one call that was judged and never answered:
    # landfall's CH-0003 came back carrying a forbidden form, was rightly refused,
    # and took thirteen findings — ten of them meaning — down with it.
    refused = ""
    for attempt_number in range(1, CRITIC_ATTEMPTS + 1):
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
            "repair": {
                "reason": "a critic read this translation against its source",
                "previous_output": str(value["translated_markdown"]),
                "findings": findings,
                "instruction": (
                    "Apply every finding whose fix you accept and leave the rest of the chapter untouched. "
                    "Return the whole chapter, not a diff."
                ),
            },
        }
        if refused:
            capsule["repair"]["refused"] = {
                "attempt": attempt_number,
                "why_the_last_repair_was_rejected": refused,
                "instruction": "Apply the findings without introducing what was rejected.",
            }
        claim = None
        try:
            envelope = build_envelope(
                root,
                role="translator",
                task_capsule=capsule,
                imports=list(contract.get("imports", [])),
                state={},
                tools=[],
                max_output_tokens=min(6000, max(1000, int(contract.get("target_words", 2000)) * 2)),
            )
            claim = claim_task(root, task_id, request_hash=str(envelope["hash"]))
            attempt_dir = Path(claim["capsule"]).parent
            result = runner("translator", envelope, attempt_dir)
            mark_provider_accepted(root, claim["attempt"], str(result.get("session_id") or ""))
            repaired = _parse_contract_json(str(result["text"]))
            problems = _translation_validation(source, {**repaired, "_locale": locale}, _locale_checks(locale_root))
            if problems:
                raise BookForgeError("; ".join(problems))
        except BookForgeError as exc:
            refused = str(exc)
            if claim is not None:
                _set_attempt_failure(root, claim["attempt"], block=False, reason=refused)
            if attempt_number == CRITIC_ATTEMPTS:
                print(
                    f"[translation-critic] {chapter_id}: the repair was refused every time and the accepted "
                    f"translation kept: {refused}",
                    file=sys.stderr,
                )
                return None
            _wait_before_retry("translation-critic", f"{chapter_id} repair", attempt_number, exc, runner)
            continue
        _set_attempt_failure(root, claim["attempt"], block=False, reason="repair merged into the translation")
        return repaired
    return None


def _previous_translated_chapter(root: Path, book_id: str, chapter_id: str, completed: list) -> str | None:
    """The latest completed chapter that comes *before* this one in the book.

    It was the last chapter completed, full stop — history rather than structure.
    Reset the first chapter and the second is the last one completed, so
    re-translating the first made its task depend on the second while the second
    still depended on the first, and the frontier's depth walk recursed until
    Python stopped it. Reading the order instead keeps the skip that a refused
    chapter needs — the next chapter leans on the latest one that did land — while
    a dependency can only ever point backwards.
    """
    order: dict[str, int] = {}
    outline = root / "books" / book_id / "outline.yaml"
    if outline.is_file():
        for row in _read_json(outline).get("chapters", []):
            if isinstance(row, dict) and row.get("id") is not None:
                order[str(row["id"])] = int(row.get("order", 0))
    def position(chapter: str) -> tuple[int, str]:
        # The id is the fallback ordering: `CH-%04d` sorts the way the book reads,
        # so a chapter the outline has lost still lands in the right place.
        return (order.get(chapter, 0), chapter)

    here = position(chapter_id)
    earlier = [str(item) for item in completed if position(str(item)) < here]
    return max(earlier, key=position) if earlier else None


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
    previous_chapter = _previous_translated_chapter(root, book_id, chapter_id, state.get("completed_chapters", []))
    previous_id = f"TRANSLATION-{book_id}-{previous_chapter}-{locale}" if previous_chapter else None
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
    # Two repairs, not one. Every other role that produces text and is judged gets
    # told what was wrong and asked again — the review's repair does, and that
    # second ask has landed twice in production on exactly these locale rules,
    # `stette` and `dovette`. The translator faces the same gate and had one.
    for attempt_number in (1, 2, TRANSLATION_ATTEMPTS):
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

        def _translator_envelope(task_capsule: dict[str, object]) -> dict[str, object]:
            return build_envelope(
                root,
                role="translator",
                task_capsule=task_capsule,
                imports=list(contract.get("imports", [])),
                state={"previous_boundary": previous},
                tools=[],
                max_output_tokens=min(6000, max(1000, int(contract.get("target_words", 2000)) * 2)),
            )

        try:
            envelope = _translator_envelope(capsule)
        except ContextOverflowError:
            # The repair attempt carries the whole previous translation on top of a
            # capsule that already holds the full source, so it is the retry — the
            # thing that exists to rescue a failed translation — that cannot be
            # built. Drop it and say so; an overflow without it is a real one.
            repair = capsule.get("repair")
            if not isinstance(repair, dict) or "previous_output" not in repair:
                raise
            capsule = {**capsule, "repair": {"reason": repair["reason"], "previous_output_omitted": True}}
            envelope = _translator_envelope(capsule)
        claim = claim_task(root, task_id, request_hash=str(envelope["hash"]))
        attempt_dir = Path(claim["capsule"]).parent
        result = runner("translator", envelope, attempt_dir)
        calls += 1
        mark_provider_accepted(root, claim["attempt"], str(result["session_id"]))
        _write_bytes_atomic(attempt_dir / "raw-output.txt", str(result["text"]).encode())
        try:
            value = _parse_contract_json(str(result["text"]))
            problems = _translation_validation(source, {**value, "_locale": locale}, _locale_checks(locale_root))
            if problems:
                raise BookForgeError("; ".join(problems))
        except BookForgeError as exc:
            last_error = str(exc)
            final = attempt_number == TRANSLATION_ATTEMPTS
            # `block=False` even on the last attempt: the chapter is set aside and
            # recorded, and a blocked run would stop the chapters behind it — which
            # is the defect this whole entry is about. Publication still refuses an
            # incomplete locale, so nothing ships past this quietly.
            _set_attempt_failure(root, claim["attempt"], block=False, reason=last_error)
            if final:
                raise TranslationRefused(
                    f"Translation refused after {TRANSLATION_ATTEMPTS - 1} repair(s): {last_error}"
                ) from exc
            previous_output = str(result["text"]) if "result" in dir() else ""
            _wait_before_retry("translator", chapter_id, attempt_number, exc, runner)
            continue
        if must_review and attempt_number == 1:
            previous_output = value
            _set_attempt_failure(root, claim["attempt"], block=False, reason="pivotal-review-requested")
            continue
        if _translation_review_enabled(_read_json(root / "book-forge.yaml")):
            review = _review_translation(
                root, book_id, locale, chapter_id, contract, source, str(value["translated_markdown"]), runner=runner
            )
            actionable = [row for row in review["findings"] if str(row.get("severity")) in {"blocking", "warning"}]
            if actionable:
                repaired = _repair_translation(
                    root, book_id, locale, chapter_id, contract, source, value, actionable, runner=runner
                )
                if repaired is not None:
                    calls += 1
                    value = repaired
                else:
                    _record_unapplied(root, book_id, locale, chapter_id, actionable)
            calls += 1
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
        # Close the whole promoted chain, not just this chapter: an earlier chapter
        # translated before the registry existed would leave `previous` dangling.
        _ensure_translation_artifacts(root, book_id, locale, completed)
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
    _require_locale_style(root, book_id, canonical)
    if not (locale_root / "locale.yaml").is_file():
        raise BookForgeError("Translation workspace does not exist; run translate add explicitly")
    _ensure_locale_artifacts(root, book_id, canonical)
    results = []
    refused: list[dict[str, object]] = []
    while True:
        source_chapters = sorted((root / "books" / book_id / "manuscript" / "chapters").glob("CH-*.md"))
        next_source = next(
            (path for path in source_chapters
             if not (locale_root / "chapters" / path.name).is_file()
             and path.stem not in {str(row["chapter"]) for row in refused}),
            None,
        )
        if not next_source:
            break
        try:
            results.append(_translate_one(root, book_id, canonical, next_source.stem, provider=provider))
        except TranslationRefused as no:
            # The gate worked and the chapter is what is wrong. Record it and carry
            # on: a locale rule stops a chapter, never a book.
            refused.append({"chapter": next_source.stem, "why": str(no)})
            print(f"[translator] {next_source.stem} set aside: {no}", file=sys.stderr)
            _write_json(
                locale_root / "refused.json",
                {"schema": 1, "locale": canonical, "refused": refused},
            )
            if not run_all:
                raise
        if not run_all:
            break
    if not results and not refused:
        return {"state": "current", "book": book_id, "locale": canonical, "calls": 0, "chapters": [], "refused": []}
    if refused:
        print(
            f"[translator] {len(refused)} chapter(s) the locale would not accept: "
            f"{', '.join(str(row['chapter']) for row in refused)}",
            file=sys.stderr,
        )
    return {
        "state": _read_json(locale_root / "state.yaml")["status"],
        "book": book_id,
        "locale": canonical,
        "calls": sum(int(result["calls"]) for result in results),
        "chapters": [result["chapter"] for result in results],
        "refused": refused,
    }



def review_translation(
    project: Path | str,
    book_id: str,
    locale: str,
    *,
    provider=None,
    chapter_id: str | None = None,
    until_clean: bool = False,
) -> dict[str, object]:
    """Read an existing translation back against its source, and repair what is cited.

    The critic runs inside a translation, which leaves every chapter translated
    before it was written unreachable. This route reaches them: it reviews what is
    on disk, applies the repairs that validate, and reports what it found — the
    same pass, on work already done.
    """
    root = _project_root(project)
    runner = provider or run_opencode_role
    canonical = _canonical_locale(locale)
    locale_root = root / "books" / book_id / "translations" / canonical
    if not (locale_root / "locale.yaml").is_file():
        raise BookForgeError("Translation workspace does not exist; run translate add explicitly")
    _require_locale_style(root, book_id, canonical)
    chapters = sorted((locale_root / "chapters").glob("CH-*.md"))
    if chapter_id:
        chapters = [path for path in chapters if path.stem == chapter_id]
        if not chapters:
            raise BookForgeError(f"{chapter_id} is not translated into {canonical}")
    if not chapters:
        raise BookForgeError(f"Nothing is translated into {canonical} yet")
    reviewed = []
    for path in chapters:
        chapter = path.stem
        source_path = root / "books" / book_id / "manuscript" / "chapters" / f"{chapter}.md"
        if not source_path.is_file():
            continue
        contract = _read_json(root / "books" / book_id / "chapters" / f"{chapter}.json")
        source = source_path.read_text(encoding="utf-8")
        review = {}
        repaired = None
        ended = "cap"
        passes = 0
        # Sticky across the passes: a critic that contradicted itself once did so,
        # and the pass that followed cannot unsay it. Reporting only the last pass
        # hid it exactly where it mattered.
        inconsistent_seen = False
        not_landed_seen = 0
        for _pass in range(1, (REVIEW_PASS_CAP if until_clean else 1) + 1):
            passes += 1
            # Re-read: the pass before this one may have rewritten the chapter.
            translated = path.read_text(encoding="utf-8")
            review = _review_translation(root, book_id, canonical, chapter, contract, source, translated, runner=runner)
            actionable = _actionable(review["findings"])
            repaired = None
            if actionable:
                repaired = _repair_translation(
                    root, book_id, canonical, chapter, contract, source,
                    {"translated_markdown": translated}, actionable, runner=runner,
                )
            if repaired is None and actionable:
                _record_unapplied(root, book_id, canonical, chapter, actionable)
            if repaired is not None:
                _execute_materialized_task(
                    root,
                    f"TRANSFIX-{book_id}-{chapter}-{canonical}",
                    {f"books/{book_id}/translations/{canonical}/chapters/{chapter}.md": str(repaired["translated_markdown"]).rstrip() + "\n"},
                )
            _record_pass_state(
                root, book_id, canonical, chapter, review["convergence"], repaired is not None, translated
            )
            inconsistent_seen = inconsistent_seen or bool(review["convergence"]["verdict_inconsistent"])
            not_landed_seen = max(not_landed_seen, len(review["convergence"]["not_landed"] or []))
            state = str(review["convergence"]["state"])
            if str(review["verdict"]) == "unread":
                ended = "unread"
                break
            if state in {"clean", "no-progress"}:
                ended = state
                break
            if repaired is None:
                # Nothing was applied, so the next pass would read the same text and
                # ask the same question.
                ended = "nothing-applied"
                break
        machine = review.get("machine") or {}
        convergence = review.get("convergence") or {}
        reviewed.append({
            "chapter": chapter,
            "verdict": review.get("verdict"),
            "machine_checks": machine,
            "findings": len(review.get("findings", [])),
            "by_kind": {kind: sum(1 for row in review.get("findings", []) if str(row.get("kind")) == kind) for kind in sorted({str(row.get("kind") or "?") for row in review.get("findings", [])})},
            "set_aside": len(review.get("set_aside", [])),
            "repaired": repaired is not None,
            "passes": passes,
            "ended": ended,
            "converged": ended == "clean",
            "why": convergence.get("reason"),
            "repeated": convergence.get("repeated"),
            "not_landed": not_landed_seen,
            "verdict_inconsistent": inconsistent_seen,
        })
    raised = sum(int((row.get("machine_checks") or {}).get("raised", 0)) for row in reviewed)
    held = sum(int((row.get("machine_checks") or {}).get("held", 0)) for row in reviewed)
    return {
        "book": book_id,
        "locale": canonical,
        "reviewed": reviewed,
        # How often the cheap checks were right, across the pass. Nothing measured
        # this before, so a check that drifted was found by whoever read the book.
        "machine_checks": {"raised": raised, "held": held, "mistaken": raised - held},
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


AUDIT_FINDING_FIELDS = ("id", "severity", "issue", "evidence", "repair_scope")


def _validate_audit_output(value: dict[str, object]) -> list[dict[str, object]]:
    """The findings the engine can use, with the rest set aside in `value`.

    A row it cannot use is not fatal. An audit of thirty-three completed passes
    died on a finding that had an id, a severity, an issue and evidence, lacked
    only `repair_scope`, and whose text said nothing was wrong — and the driver
    retried it twice more. The same shape arrived earlier as evidence that would
    not resolve and as a promise id the engine had handed out, each fixed where
    it bit. Set aside and recorded, the run reaches its verdict on the rows the
    engine could bind, and the ones it could not are written to `unverifiable`
    on the same record with the citations that did not resolve.

    A response that is not a findings list at all still raises. That is not a bad
    row; it is not an answer.
    """
    findings = value.get("findings")
    if not isinstance(findings, list):
        raise BookForgeError("Audit output has no findings list")
    usable: list[dict[str, object]] = []
    for finding in findings:
        if not isinstance(finding, dict):
            _set_aside(value, {"row": finding}, "the row is not an object")
            continue
        missing = [field for field in AUDIT_FINDING_FIELDS if field not in finding]
        if missing:
            _set_aside(value, finding, f"missing {', '.join(missing)}")
            continue
        if finding["severity"] not in {"blocking", "warning", "note"}:
            _set_aside(value, finding, f"severity {finding['severity']!r} is not one the engine knows")
            continue
        if not isinstance(finding["evidence"], list) or not finding["evidence"]:
            _set_aside(value, finding, "no evidence")
            continue
        bad = [
            evidence for evidence in finding["evidence"]
            if not isinstance(evidence, dict) or not evidence.get("location")
            or not re.fullmatch(r"[0-9a-f]{64}", str(evidence.get("hash", "")))
        ]
        if bad:
            _set_aside(value, finding, "evidence without a stable location and SHA-256")
            continue
        usable.append(finding)
    return usable


def _set_aside(value: dict[str, object], finding: object, why: str) -> None:
    """Keep a row the engine cannot use, and say why, so a person can read it."""
    rows = value.setdefault("unverifiable", [])
    if isinstance(rows, list):
        row = dict(finding) if isinstance(finding, dict) else {"row": finding}
        rows.append({**row, "set_aside": why})


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


def assemble_edition(project: Path | str, book_id: str, language: str, draft: bool = False) -> dict[str, object]:
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
    # Draft mode: export whatever chapters are currently available for review
    export_chapters: list[str] = expected
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
        if draft:
            completed = state.get("completed_chapters") or []
            if not isinstance(completed, list) or not completed:
                raise BookForgeError("Draft publication refused: no completed chapters available for review")
            # A chapter the book does not have must never publish. Its *position*,
            # though, is the outline's business and not the log's: `completed_chapters`
            # records when a chapter finished, and a chapter refused once and retried
            # finishes late — which is what setting a chapter aside and carrying on
            # was built to allow. Landfall's Italian read `… CH-0009, CH-0011,
            # CH-0007, CH-0010 …` and was refused for it, on a state the engine's own
            # retry produces routinely.
            if not all(ch in expected for ch in completed):
                raise BookForgeError("Draft publication refused: completed chapters contain unknown chapter")
            export_chapters = [str(ch) for ch in expected if ch in set(completed)]
            manuscript_root = locale_root / "chapters"
        else:
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
        if draft:
            closed = state.get("closed_chapters") or []
            if not isinstance(closed, list) or not closed:
                raise BookForgeError("Draft publication refused: no closed chapters available for review (write at least one chapter)")
            # The same reading the translated branch above already takes: the log
            # records when a chapter closed, and a chapter rewritten after the book
            # moved on closes last. `reset --chapter` makes that ordinary rather than
            # rare — landfall's read `CH-0004 … CH-0017, CH-0001, CH-0002, CH-0003`
            # after the first three were redone. A chapter the book does not have is
            # still refused; where a chapter sits is the outline's business.
            if not all(ch in expected for ch in closed):
                raise BookForgeError("Draft publication refused: closed chapters contain unknown chapter")
            export_chapters = [str(ch) for ch in expected if ch in set(closed)]
            manuscript_root = root / "books" / book_id / "manuscript" / "chapters"
        else:
            if state.get("closed_chapters") != expected:
                raise BookForgeError("Publication refused: source chapters are incomplete, stale, or out of order")
            manuscript_root = root / "books" / book_id / "manuscript" / "chapters"
    present = [path.stem for path in sorted(manuscript_root.glob("CH-*.md"))]
    if draft:
        if export_chapters != present:
            raise BookForgeError(f"Draft publication refused: expected {export_chapters} but found {present} on disk")
    else:
        if expected != present:
            raise BookForgeError("Publication refused: edition chapters are missing, extra, or out of order")
    registry = _artifact_registry(root)
    if not translated and not draft and registry.get("artifacts"):
        try:
            stale = reconcile_artifacts(root)
        except BookForgeError as exc:
            raise BookForgeError(f"Publication refused by artifact currentness: {exc}") from exc
        source_ids = {f"SOURCE-{book_id}-{chapter}" for chapter in expected}
        if source_ids & set(stale):
            raise BookForgeError("Publication refused: source chapter artifact is stale")
    chapters = []
    input_hashes = {}
    for chapter_id in export_chapters:
        path = manuscript_root / f"{chapter_id}.md"
        text_value = _normalize_text(path.read_text(encoding="utf-8"))
        contract_path = root / "books" / book_id / "chapters" / f"{chapter_id}.json"
        contract = _read_json(contract_path) if contract_path.is_file() else {}
        # The number is the edition's, never the prose's: the format can change
        # without touching a manuscript, and a translation inherits it unretranslated.
        number = int(contract.get("order") or len(chapters) + 1)
        chapters.append({"id": chapter_id, "number": number, "title": next((line[2:].strip() for line in text_value.splitlines() if line.startswith("# ")), chapter_id), "markdown": text_value})
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
        # The project's author, unless this book names one. A universe can hold books
        # by different hands — a collection, an anthology, a pseudonym for one of them
        # — and four editions have shipped from here with no author at all because
        # the project-level field was the only one and nobody had a reason to set it
        # for the whole universe.
        "author": str(book.get("author") or config.get("author") or ""),
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
    chapter_ids = [str(chapter["id"]) for chapter in assembly["chapters"]]
    # Go through the shared specs: registering here with only a path is what left
    # rows carrying no dependencies, which can never be invalidated.
    if translated:
        _ensure_translation_artifacts(root, book_id, language, chapter_ids)
    else:
        for chapter_id in chapter_ids:
            _ensure_artifact(root, *_source_chapter_artifact(root, book_id, chapter_id))
    dependencies = []
    for chapter_id in chapter_ids:
        if translated:
            dependencies.append(f"TRANSLATION-{book_id}-{chapter_id}-{language}")
        else:
            dependencies.append(f"SOURCE-{book_id}-{chapter_id}")
    return dependencies


def _edition_stem(assembly: dict[str, object]) -> str:
    """Name an edition after the book and its language, not after the id.

    `BOOK-0001.draft.pdf` says nothing to whoever opens or receives the file, and
    two languages differ only by a path segment."""
    folded = unicodedata.normalize("NFKD", str(assembly.get("title") or ""))
    ascii_only = "".join(ch for ch in folded if not unicodedata.combining(ch))
    slug = re.sub(r"[^A-Za-z0-9]+", "-", ascii_only).strip("-").lower()
    return f"{slug or str(assembly['book']).lower()}-{assembly['language']}"


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


def _chapter_number_html(chapter: dict[str, object]) -> str:
    """The chapter's number as an element of the edition, styled by the templates."""
    number = chapter.get("number")
    return f'<p class="chapter-number">{html.escape(str(number))}</p>' if number else ""


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
    ncx_points: list[str] = []
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
        number = html.escape(str(chapter.get("number", "")))
        label = f'{number}. {html.escape(str(chapter["title"]))}'
        nav_items.append(f'<li><a href="{filename}">{label}</a></li>')
        # EPUB 2 navigation as well: an EPUB 3 is valid with the XHTML nav alone, but
        # every Adobe RMSDK reader — Kobo, PocketBook, Nook, Sony, Digital Editions —
        # reads the NCX, and stalls without it.
        ncx_points.append(
            f'<navPoint id="navPoint-{index}" playOrder="{index}">'
            f'<navLabel><text>{label}</text></navLabel><content src="{filename}"/></navPoint>'
        )
        members.append((f"OEBPS/{filename}", _xhtml_document(str(chapter["title"]), str(assembly["language"]), _chapter_number_html(chapter) + _markdown_xhtml(str(chapter["markdown"])))))
    modified = "2000-01-01T00:00:00Z"
    opf = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id" xml:lang="{lang}">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '<dc:identifier id="book-id">urn:uuid:{identifier}</dc:identifier><dc:title>{title}</dc:title>'
        '<dc:language>{lang}</dc:language>{creator}'
        '<meta property="dcterms:modified">{modified}</meta></metadata>'
        '<manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
        '<item id="css" href="styles/epub.css" media-type="text/css"/>{items}</manifest>'
        '<spine toc="ncx">{spine}</spine></package>\n'
    ).format(
        lang=html.escape(str(assembly["language"])),
        identifier=assembly["identifier"],
        title=html.escape(str(assembly["title"])),
        creator=f'<dc:creator>{html.escape(str(assembly["author"]))}</dc:creator>' if str(assembly.get("author") or "").strip() else "",
        modified=modified,
        items="".join(chapter_items),
        spine="".join(spine_items),
    ).encode()
    nav_body = f'<nav epub:type="toc" id="toc"><h1>Contents</h1><ol>{"".join(nav_items)}</ol></nav>'
    css = (Path(__file__).resolve().parents[1] / "assets" / "publication" / "epub.css").read_bytes()
    members.extend(
        [
            ("OEBPS/content.opf", opf),
            (
                "OEBPS/toc.ncx",
                (
                    '<?xml version="1.0" encoding="utf-8"?>\n'
                    '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1" xml:lang="{lang}">'
                    '<head><meta name="dtb:uid" content="urn:uuid:{identifier}"/><meta name="dtb:depth" content="1"/>'
                    '<meta name="dtb:totalPageCount" content="0"/><meta name="dtb:maxPageNumber" content="0"/></head>'
                    '<docTitle><text>{title}</text></docTitle><navMap>{points}</navMap></ncx>\n'
                ).format(
                    lang=html.escape(str(assembly["language"])),
                    identifier=assembly["identifier"],
                    title=html.escape(str(assembly["title"])),
                    points="".join(ncx_points),
                ).encode(),
            ),
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
            # Both navigations, or the Adobe RMSDK readers stall on the package.
            ncx_ids = {
                item.attrib.get("id")
                for item in opf.findall(".//opf:item", namespace)
                if item.attrib.get("media-type") == "application/x-dtbncx+xml"
            }
            spine = opf.find(".//opf:spine", namespace)
            if not ncx_ids or spine is None or spine.attrib.get("toc") not in ncx_ids:
                raise BookForgeError("EPUB has no spine-referenced NCX navigation")
            ncx = ET.fromstring(archive.read("OEBPS/toc.ncx"))
            points = ncx.findall(".//{http://www.daisy.org/z3986/2005/ncx/}navPoint")
            if len(points) != expected_chapters:
                raise BookForgeError("EPUB NCX navigation is incomplete")
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


def export_epub(project: Path | str, book_id: str, language: str, draft: bool = False) -> dict[str, object]:
    root = _project_root(project)
    assembly = assemble_edition(root, book_id, language, draft=draft)
    members = _epub_members(assembly)
    epub_bytes = _deterministic_zip(members)
    output_dir = root / "dist" / book_id / str(assembly["language"])
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = ".draft" if draft else ""
    output_path = output_dir / f"{_edition_stem(assembly)}{suffix}.epub"
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
        "draft": draft,
        "partial": draft,
    }
    manifest_path = output_dir / f"{_edition_stem(assembly)}{suffix}.epub.manifest.json"
    _write_json(manifest_path, manifest)
    if draft:
        # Draft exports are for review only, not registered as final edition artifacts
        return {"path": str(output_path), "manifest": str(manifest_path), "sha256": validation["sha256"], "chapters": len(assembly["chapters"]), "model_calls": 0, "draft": True}
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


def _pdf_text_key(value: str, *, packed: bool = False) -> str:
    """Read a PDF the way a reader does, not the way pdftotext cuts it.

    Extraction breaks a line wherever the renderer wrapped and keeps the font's
    ligatures, so a raw substring check fails for every title long enough to wrap
    and every title containing ff, fi or fl. NFKC resolves the ligatures."""
    folded = unicodedata.normalize("NFKC", value).replace("\u00ad", "")
    if packed:
        return re.sub(r"\s+", "", folded)
    return re.sub(r"\s+", " ", folded).strip()


def _missing_pdf_titles(text: str, expected_titles: list[str]) -> list[str]:
    spaced_text, packed_text = _pdf_text_key(text), _pdf_text_key(text, packed=True)
    missing = []
    for title in expected_titles:
        if _pdf_text_key(title) in spaced_text:
            continue
        # A wrap can swallow the space around the break; compare without spaces
        # before calling a rendered title absent.
        if _pdf_text_key(title, packed=True) in packed_text:
            continue
        missing.append(title)
    return missing


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
    if text_result.returncode != 0:
        raise BookForgeError("PDF text extraction failed")
    missing = _missing_pdf_titles(text_result.stdout, expected_titles)
    if missing:
        raise BookForgeError(f"PDF text validation failed; titles not found: {', '.join(missing)}")
    return {"valid": True, "sha256": _file_hash(target), "pages": next((line.split(":", 1)[1].strip() for line in info.stdout.splitlines() if line.startswith("Pages:")), None)}


def export_pdf(
    project: Path | str,
    book_id: str,
    language: str,
    *,
    font_paths: dict[str, Path] | None = None,
    draft: bool = False,
) -> dict[str, object]:
    root = _project_root(project)
    assembly = assemble_edition(root, book_id, language, draft=draft)
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
            {"id": chapter["id"], "title": chapter["title"], "xhtml": f'<section id="{chapter["id"]}">{_chapter_number_html(chapter)}{_markdown_xhtml(str(chapter["markdown"]))}</section>'}
            for chapter in assembly["chapters"]
        ],
    }
    machine_dir = root / ".book-forge" / "publication"
    machine_dir.mkdir(parents=True, exist_ok=True)
    assembly_path = machine_dir / f"{assembly['hash']}.pdf-assembly.json"
    _write_json(assembly_path, renderer_assembly)
    output_dir = root / "dist" / book_id / str(assembly["language"])
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = ".draft" if draft else ""
    output_path = output_dir / f"{_edition_stem(assembly)}{suffix}.pdf"
    temporary_path = output_dir / f".{_edition_stem(assembly)}{suffix}.pdf.rendering"
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
        "draft": draft,
        "partial": draft,
    }
    manifest_path = output_dir / f"{_edition_stem(assembly)}{suffix}.pdf.manifest.json"
    _write_json(manifest_path, manifest)
    if draft:
        return {"path": str(output_path), "manifest": str(manifest_path), "sha256": validation["sha256"], "chapters": len(assembly["chapters"]), "model_calls": 0, "draft": True}
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


RESET_KEPT = (
    "universe canon",
    "books/<book>/book.yaml",
    "books/<book>/book-brief.json",
    "books/<book>/continuity.yaml",
    "books/<book>/translations/<locale>/{glossary,style,metadata}",
)


def _chapter_workspace(book: Path, directory: str, chapter: str) -> list[Path]:
    """One chapter's entries under a per-chapter working directory.

    The three directories name a chapter differently — `reviews/CH-0004` is a
    directory, `coldread-state/CH-0004.md` a file — so match the name itself and
    anything suffixed onto it rather than assuming either shape.
    """
    root = book / directory
    if not root.is_dir():
        return []
    return sorted(path for path in root.glob(f"{chapter}*") if path.name == chapter or path.name.startswith(f"{chapter}."))


def _reset_paths(root: Path, book_id: str, scope: str, locale: str | None = None, chapter: str | None = None) -> list[Path]:
    """Every derived path a reset removes, in the order it removes them."""
    book = root / "books" / book_id
    targets: list[Path] = []
    if scope == "translation":
        # Only what this locale derived. The manuscript it was translated from is
        # an input here, and re-translating five minutes of work must never cost
        # the hundred minutes that wrote the prose.
        pattern = f"translations/{locale}/chapters/{chapter}.md" if chapter else f"translations/{locale}/chapters/*.md"
        targets.extend(sorted(book.glob(pattern)))
        editions = root / "dist" / book_id / str(locale)
        targets.extend(sorted(path for path in editions.glob("*") if path.exists()))
        return targets
    if chapter:
        # One chapter and what was derived from it, in every language. The editions
        # go too: each one contains this chapter, so each one is now stale — and an
        # edition is minutes to rebuild against the hours the other chapters cost.
        source = book / "manuscript" / "chapters" / f"{chapter}.md"
        if source.exists():
            targets.append(source)
        targets.extend(sorted(book.glob(f"translations/*/chapters/{chapter}.md")))
        for directory in ("reviews", "work", "coldread-state"):
            targets.extend(_chapter_workspace(book, directory, chapter))
        editions = root / "dist" / book_id
        targets.extend(sorted(path for path in editions.glob("*") if path.exists()))
        return targets
    targets.extend(sorted(book.glob("manuscript/chapters/*.md")))
    targets.extend(sorted(book.glob("translations/*/chapters/*.md")))
    for directory in ("reviews", "work", "coldread-state"):
        targets.extend(sorted(path for path in (book / directory).glob("*") if path.exists()))
    editions = root / "dist" / book_id
    targets.extend(sorted(path for path in editions.glob("*") if path.exists()))
    if scope == "design":
        targets.extend(sorted(book.glob("chapters/*.json")))
        audit = book / "design-audit.json"
        if audit.is_file():
            targets.append(audit)
    return targets


def _task_names_chapter(task_id: str, chapter: str) -> bool:
    """Whether a task id carries this chapter as one of its segments.

    Substring matching is what a five-digit chapter would break, so the chapter
    has to sit between two dashes or end the id: `DRAFT-BOOK-0001-CH-0004`,
    `STYLE-BOOK-0001-CH-0004-<model>`, `TRANSLATE-BOOK-0001-CH-0004-it`.
    """
    return f"-{chapter}-" in task_id or task_id.endswith(f"-{chapter}")


def _reset_task_ids(plan: dict[str, object], book_id: str, scope: str, locale: str | None = None, chapter: str | None = None) -> list[str]:
    dropped = []
    for task in plan["tasks"]:
        task_id = str(task["id"])
        if book_id not in task_id:
            continue
        if chapter and not _task_names_chapter(task_id, chapter):
            continue
        if scope == "translation":
            # `TRANSLATE-<book>-<chapter>-<locale>`: this locale's translations and
            # nothing else, so a book translated into three languages loses one.
            if task_id.startswith("TRANSLATE-") and task_id.endswith(f"-{locale}"):
                dropped.append(task_id)
            continue
        if scope == "prose" and task_id.startswith(("DESIGN-", "AUDIT-")):
            continue
        dropped.append(task_id)
    return sorted(dropped)


def _forget_chapter_in_locale(state_path: Path, chapter: str) -> None:
    """Remove one chapter from a locale's state without disturbing the others.

    `boundary` is the end-state the next chapter is translated against, and it
    belongs to whichever chapter was translated last. Removing a chapter from the
    middle leaves it correct; removing the last one leaves it describing prose the
    locale no longer has, so it is cleared and the next translation starts from
    nothing — the same position chapter one is always in.
    """
    state = _read_json(state_path)
    completed = [str(item) for item in state.get("completed_chapters", [])]
    if chapter not in completed:
        return
    was_last = completed[-1] == chapter
    state["completed_chapters"] = [item for item in completed if item != chapter]
    state["boundary_hashes"] = {key: value for key, value in state.get("boundary_hashes", {}).items() if key != chapter}
    hashes = state.get("input_hashes")
    if isinstance(hashes, dict):
        for section in ("source", "canon"):
            recorded = hashes.get(section)
            if isinstance(recorded, dict):
                recorded.pop(chapter, None)
    if was_last:
        state["boundary"] = ""
    state["status"] = "in_progress" if state["completed_chapters"] else "empty"
    state["current"] = True
    _write_json(state_path, state)


def reset_book(project: Path | str, book_id: str, *, scope: str = "prose", confirm: bool = False, locale: str | None = None, chapter: str | None = None) -> dict[str, object]:
    """Return a book to its pre-writing state without leaving the control plane
    claiming work whose output is gone.

    A hand-deleted manuscript leaves the plan reporting every DRAFT task as
    succeeded, so the writer is never re-run and the restart silently does
    nothing. Six registries move together here: the files, the plan, the book
    state, each translation workspace, the artifact registry and its derived
    views. Canon, the brief, the continuity and the locale aids are input and
    are never touched.

    `chapter` narrows `prose` and `translation` to one chapter, so a rule added
    after the writing costs the chapter that broke it rather than the book.
    """
    if scope not in {"prose", "design", "translation"}:
        raise BookForgeError(f"Unknown reset scope: {scope} (prose, design, translation)")
    if not confirm:
        raise BookForgeError("reset removes written work; pass --yes to confirm")
    root = _project_root(project)
    book = root / "books" / book_id
    if not (book / "book.yaml").is_file():
        raise BookForgeError(f"Unknown book: {book_id}")
    if chapter:
        # A rule written after the prose is exactly the rule that prose never met,
        # so one chapter has to be redoable at the cost of one chapter. Design has
        # no per-chapter unit — the outline is written whole — and narrowing it
        # would delete a chapter's design while the outline still promises it.
        if scope == "design":
            raise BookForgeError("reset --chapter is not available with --scope design; the outline is written whole")
        known_chapters = [str(row.get("id")) for row in _read_json(book / "outline.yaml").get("chapters", [])]
        if chapter not in known_chapters:
            raise BookForgeError(f"Unknown chapter: {chapter}. This book has: {', '.join(known_chapters) or 'none'}")
    if scope == "translation":
        # Guessing the language would delete the wrong one, and a translation is
        # the one thing here that a person cannot tell apart by looking at the plan.
        known = sorted(path.parent.name for path in book.glob("translations/*/locale.yaml"))
        if not locale:
            raise BookForgeError(
                f"reset --scope translation needs --locale. This book has: {', '.join(known) or 'none'}"
            )
        locale = _canonical_locale(locale)
        if locale not in known:
            raise BookForgeError(f"Unknown translation locale: {locale}. This book has: {', '.join(known) or 'none'}")
    title = str(_read_json(book / "book.yaml").get("title", book_id))
    continuity = str(_read_json(book / "book.yaml").get("continuity", "CNT-0001"))

    removed = []
    for path in _reset_paths(root, book_id, scope, locale, chapter):
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
        removed.append(str(path.relative_to(root)))

    plan = _load_plan(root)
    dropped = _reset_task_ids(plan, book_id, scope, locale, chapter)
    gone = set(dropped)
    plan["tasks"] = [task for task in plan["tasks"] if str(task["id"]) not in gone]
    plan["attempts"] = [row for row in plan.get("attempts", []) if str(row.get("task")) not in gone]
    for task in plan["tasks"]:
        # A surviving task pointing at a dropped one waits for something that will
        # never arrive, and the frontier's depth walk reads a task id that is no
        # longer in the plan.
        task["deps"] = [dep for dep in task.get("deps", []) if str(dep) not in gone]
    _save_plan(root, plan)

    locales = []
    if scope == "translation" and chapter:
        state_path = book / "translations" / str(locale) / "state.yaml"
        _forget_chapter_in_locale(state_path, chapter)
        locales.append(str(locale))
    elif scope == "translation":
        # The book's own state records which chapters are closed in the source
        # language, and this reset did not touch one of them.
        state_path = book / "translations" / str(locale) / "state.yaml"
        _write_json(state_path, {"schema": 1, "locale": locale, "completed_chapters": [], "current": True, "boundary_hashes": {}})
        locales.append(str(locale))
    elif chapter:
        state_path = book / "state.yaml"
        state = _read_json(state_path)
        closed = [str(item) for item in state.get("closed_chapters", [])]
        was_last = bool(closed) and closed[-1] == chapter
        state["closed_chapters"] = [item for item in closed if item != chapter]
        if was_last:
            # The tail is what the next chapter is written against, and it was this
            # chapter's. Recover it from the chapter that is now last rather than
            # leaving the writer two thousand characters of deleted prose.
            state["previous_chapter_tail"] = ""
            if state["closed_chapters"]:
                previous = book / "manuscript" / "chapters" / f"{state['closed_chapters'][-1]}.md"
                if previous.is_file():
                    state["previous_chapter_tail"] = previous.read_text(encoding="utf-8")[-2000:]
        # `consequences` is left whole on purpose: the rows carry no chapter, and
        # the sixteen chapters that stay are written against them.
        _write_json(state_path, state)
        for state_path in sorted(book.glob("translations/*/state.yaml")):
            _forget_chapter_in_locale(state_path, chapter)
            locales.append(state_path.parent.name)
    else:
        _write_json(book / "state.yaml", {"schema": SCHEMA_VERSION, "closed_chapters": []})
        for state_path in sorted(book.glob("translations/*/state.yaml")):
            name = state_path.parent.name
            _write_json(state_path, {"schema": 1, "locale": name, "completed_chapters": [], "current": True, "boundary_hashes": {}})
            locales.append(name)

    if scope == "design":
        _write_json(book / "outline.yaml", {"schema": SCHEMA_VERSION, "chapters": []})
        (book / "design.md").write_text(
            f"---\nid: {book_id}\ncontinuity: {continuity}\n---\n\n# {title}\n\n<!-- bf:block premise -->\n",
            encoding="utf-8",
        )
        (book / "reader-state.md").write_text("# Reader State\n", encoding="utf-8")

    registry = _artifact_registry(root)
    artifacts = registry.get("artifacts", {})
    surviving = {}
    dropped_artifacts = []
    for artifact_id, artifact in artifacts.items():
        path = str(artifact.get("path", ""))
        owned = path.startswith(f"books/{book_id}/") or path.startswith(f"dist/{book_id}/")
        if owned and not (root / path).exists():
            dropped_artifacts.append(str(artifact_id))
            continue
        surviving[str(artifact_id)] = artifact
    for artifact in surviving.values():
        # The same requirement the plan's `deps` carry, on the registry. Chapter
        # two's translation depends on chapter one's — the "previous chapter" chain
        # again — so dropping one artifact left the other pointing at nothing, and
        # the next translation was written to disk and then refused registration.
        # Canon block ids live in this list too and are not artifacts: only an id
        # this reset actually dropped comes out.
        deps = artifact.get("dependencies")
        if isinstance(deps, list):
            artifact["dependencies"] = [dep for dep in deps if str(dep) not in set(dropped_artifacts)]
    registry["artifacts"] = surviving
    registry["edges"] = [
        edge for edge in registry.get("edges", [])
        if str(edge.get("to")) in surviving and str(edge.get("from")) not in set(dropped_artifacts)
    ]
    _write_json(root / ".book-forge" / "artifact-deps.json", registry)
    currentness = _read_json(root / ".book-forge" / "currentness.json")
    currentness["artifacts"] = {key: value for key, value in currentness.get("artifacts", {}).items() if key in surviving}
    _write_json(root / ".book-forge" / "currentness.json", currentness)
    _write_derived_dependency_views(root)
    render_plan(root)

    return {
        "book": book_id,
        "scope": scope,
        "chapter": chapter or "",
        "removed_paths": removed,
        "dropped_tasks": dropped,
        "dropped_artifacts": sorted(dropped_artifacts),
        "reset_locales": locales,
        "kept": list(RESET_KEPT),
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
    init.add_argument("--chorus-models", help="Comma-separated openrouter/... models; when omitted and TTY, prompts interactively")
    init.add_argument("--style", help="Prose style preset; when omitted and TTY, prompts interactively")
    reset = commands.add_parser("reset")
    reset.add_argument("--book", required=True)
    reset.add_argument("--scope", choices=("prose", "design", "translation"), default="prose")
    reset.add_argument("--locale", help="Required with --scope translation: the locale to redo")
    reset.add_argument("--chapter", help="Narrow prose or translation to one chapter, e.g. CH-0001")
    reset.add_argument("--yes", action="store_true", help="Required: reset removes written work")
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
    add_book_command.add_argument("--author", default="", help="Who wrote it; the project's author stands in when a book names none")
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
    _backfill_cache = runtime_commands.add_parser("backfill-cache")
    _backfill_cache.add_argument("--run", help="Only this run; default every run in the project")
    artifacts = commands.add_parser("artifacts")
    artifacts_commands = artifacts.add_subparsers(dest="artifacts_command", required=True)
    artifacts_backfill = artifacts_commands.add_parser("backfill")
    artifacts_backfill.add_argument("--book")
    artifacts_backfill.add_argument("--locale")
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
    design.add_argument("--no-post-chorus", action="store_true", help="Skip post-design ensemble (keeps pre-design)")
    design.add_argument("--chorus-models", help="Comma-separated openrouter/... overrides for this chorus run")
    design.add_argument("--with-chorus-context", action="store_true", help="Inject latest chorus report into designer capsule")
    design.add_argument("--refresh", action="store_true", help="Universe only: re-run the design cycle against the current brief (pre-book only)")
    design.add_argument("--skip-brief", action="store_true", help="Bypass 00-BRIEF gate (or answer usa default)")
    run = commands.add_parser("run")
    run.add_argument("--book")
    run.add_argument("--task")
    run.add_argument("--next", action="store_true")
    translate = commands.add_parser("translate")
    translate.add_argument("action", choices=("add", "next", "run", "status", "review"))
    translate.add_argument("--chapter", help="With review: read back one chapter instead of every translated one")
    translate.add_argument("--until-clean", action="store_true", help="With review: keep reading a chapter back until it converges, makes no progress, or hits the pass cap")
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
    chorus_run.add_argument("--post-design", action="store_true", help="Re-read the last design product instead of the brief")
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

    advance = commands.add_parser("advance")
    advance.add_argument("--book", required=True)
    advance.add_argument("--locale", action="append", default=[], help="Translate into this locale; repeatable")
    advance.add_argument("--until", choices=ADVANCE_STAGES, default="export")
    bakeoff = commands.add_parser("bakeoff")
    bakeoff.add_argument("book")
    bakeoff.add_argument("chapter")
    bakeoff.add_argument("--models", required=True, help="Comma-separated models to draft this chapter with; nothing is promoted")
    export = commands.add_parser("export")
    export.add_argument("book")
    export.add_argument("--lang", required=True)
    export.add_argument("--format", choices=("epub", "pdf", "all"), default="all")
    export.add_argument("--draft", action="store_true", help="Allow partial export of available chapters for review (draft, not registered as final edition)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command != "init":
            recover_transactions(args.project)
        if args.command == "init":
            title = args.title or args.project.name.replace("-", " ").title()
            cm = _parse_chorus_csv(args.chorus_models) if getattr(args, "chorus_models", None) is not None else None
            print(json.dumps(init_project(args.project, title, args.source_language, chorus_models=cm, style_preset=getattr(args, "style", None)), sort_keys=True))
        elif args.command == "continuity" and args.continuity_command == "add":
            print(json.dumps(add_continuity(args.project, args.name, kind=args.kind, fork_from=args.fork_from, imports=args.imports), sort_keys=True))
        elif args.command == "reset":
            print(json.dumps(reset_book(args.project, args.book, scope=args.scope, confirm=args.yes, locale=args.locale, chapter=args.chapter), sort_keys=True))
        elif args.command == "add-book":
            print(json.dumps(add_book(args.project, args.title, continuity=args.continuity, author=args.author), sort_keys=True))
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
        elif args.command == "runtime" and args.runtime_command == "backfill-cache":
            print(json.dumps(backfill_call_cache(args.project, run=args.run), sort_keys=True))
        elif args.command == "artifacts" and args.artifacts_command == "backfill":
            print(json.dumps(backfill_artifacts(args.project, book=args.book, locale=args.locale), sort_keys=True))
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
            print(json.dumps(execute_universe_design(args.project, chorus_models=args.chorus_models, no_chorus=args.no_chorus, no_post_chorus=args.no_post_chorus, with_chorus_context=args.with_chorus_context, refresh=args.refresh, skip_brief=args.skip_brief), sort_keys=True))
        elif args.command == "design" and args.scope == "book":
            if not args.book:
                raise BookForgeError("design book requires --book")
            if args.brief:
                _write_book_brief(args.project, args.book, args.brief)
            print(json.dumps(execute_book_design(args.project, args.book, chorus_models=args.chorus_models, no_chorus=args.no_chorus, no_post_chorus=args.no_post_chorus, with_chorus_context=args.with_chorus_context, skip_brief=args.skip_brief), sort_keys=True))
        elif args.command == "chorus" and args.chorus_command == "run":
            # Standalone chorus without designer
            if args.no_chorus:
                print(json.dumps({"skipped": True, "reason": "--no-chorus"}, sort_keys=True))
            elif getattr(args, "post_design", False):
                root = _project_root(args.project)
                cfg = _read_json(root / "book-forge.yaml")
                models = _parse_chorus_models_arg(args.chorus_models, _chorus_models_from_config(cfg)) if args.chorus_models else _chorus_models_from_config(cfg)
                if args.book:
                    book_id = args.book
                    proposal = _book_proposal_from_artifacts(root, book_id)
                    imports = sorted({row["id"] for row in _book_canon_context(root, book_id, rebuild_indexes(root)) if row["id"] != "worldbuilding.md"})
                    print(json.dumps(run_chorus_post_design(args.project, {"scope": "book", "book": book_id, "imports": imports}, proposal, models), sort_keys=True))
                else:
                    proposal = _read_json(root / "universe" / "design.json")
                    print(json.dumps(run_chorus_post_design(args.project, {"scope": "universe", "imports": ["UNI-0001#kernel"]}, proposal, models), sort_keys=True))
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
        elif args.command == "translate" and args.action == "review":
            print(json.dumps(review_translation(args.project, args.book, args.locale, chapter_id=args.chapter, until_clean=args.until_clean), sort_keys=True))
        elif args.command == "translate" and args.action == "status":
            canonical = _canonical_locale(args.locale)
            print(json.dumps(_read_json(_project_root(args.project) / "books" / args.book / "translations" / canonical / "state.yaml"), sort_keys=True))
        elif args.command == "translate":
            print(json.dumps(translate_next(args.project, args.book, args.locale, run_all=args.action == "run"), sort_keys=True))
        elif args.command == "audit":
            print(json.dumps(audit_continuity(args.project, book_id=args.book, relation_id=args.relation, continuity_id=args.continuity, max_jobs=args.max_jobs, override=args.override), sort_keys=True))
        elif args.command == "advance":
            print(json.dumps(advance_book(args.project, args.book, locales=args.locale, until=args.until), sort_keys=True))
        elif args.command == "bakeoff":
            print(json.dumps(draft_bakeoff(args.project, args.book, args.chapter, [m.strip() for m in args.models.split(",") if m.strip()]), sort_keys=True))
        elif args.command == "export":
            results = {}
            if args.format in {"epub", "all"}:
                results["epub"] = export_epub(args.project, args.book, args.lang, draft=args.draft)
            if args.format in {"pdf", "all"}:
                results["pdf"] = export_pdf(args.project, args.book, args.lang, draft=args.draft)
            print(json.dumps(results, sort_keys=True))
        return 0
    except (BookForgeError, OSError, subprocess.SubprocessError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
