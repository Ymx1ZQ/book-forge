"""Brief gate — 00-BRIEF, 7 questions, default ON, bypass via --skip-brief or "usa default"."""
from __future__ import annotations

import json
from pathlib import Path

BRIEF_QUESTIONS = [
    "length/format",
    "genre/world",
    "protagonists",
    "premise/conflict/ending",
    "themes",
    "style/POV/register",
    "constraints/audience",
]

BYPASS_PHRASE = "usa default"

def _is_bypass_value(value: object) -> bool:
    if isinstance(value, str) and BYPASS_PHRASE in value.lower():
        return True
    if isinstance(value, dict):
        for v in value.values():
            if isinstance(v, str) and BYPASS_PHRASE in v.lower():
                return True
            if isinstance(v, list):
                for item in v:
                    if isinstance(item, str) and BYPASS_PHRASE in item.lower():
                        return True
    return False

def validate_brief(answers: dict) -> list[str]:
    """Return list of missing question keys; empty means complete."""
    if not isinstance(answers, dict):
        return BRIEF_QUESTIONS[:]
    missing = []
    for q in BRIEF_QUESTIONS:
        v = answers.get(q)
        if not isinstance(v, str) or not v.strip():
            missing.append(q)
    return missing

def is_brief_complete(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    # Legacy autonomous brief from init/schedule is considered complete for backward compat
    if isinstance(data, dict) and data.get("mode") == "autonomous":
        return True
    # Legacy book brief (premise/characters/plot/tone) — pre-M2, considered complete
    if isinstance(data, dict) and any(k in data for k in ("premise", "characters", "plot", "tone", "length_notes")):
        return True
    answers = data.get("answers", data)
    if _is_bypass_value(answers) or _is_bypass_value(data):
        return True
    if not isinstance(answers, dict):
        return False
    return not validate_brief(answers)

def should_gate(project: Path, scope: str, book_id: str | None = None, skip_flag: bool = False) -> bool:
    """Return True if gate should block. Gate is default ON."""
    if skip_flag:
        return False
    # Check bypass phrase in existing brief file if present
    if scope == "universe":
        p = Path(project) / "universe" / "design-brief.json"
    else:
        if not book_id:
            return True
        p = Path(project) / "books" / book_id / "book-brief.json"
    if p.is_file():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if _is_bypass_value(data) or _is_bypass_value(data.get("answers", {})):
                return False
            # Legacy briefs are not gated (backward compat for tests)
            if isinstance(data, dict) and (data.get("mode") == "autonomous" or any(k in data for k in ("premise", "characters", "plot", "tone"))):
                return False
        except Exception:
            pass
        return not is_brief_complete(p)
    return True

def brief_status(project: Path, scope: str, book_id: str | None = None, skip_flag: bool = False) -> dict:
    gated = should_gate(project, scope, book_id, skip_flag)
    missing = []
    if gated:
        if scope == "universe":
            p = Path(project) / "universe" / "design-brief.json"
            try:
                data = json.loads(p.read_text()) if p.is_file() else {}
                answers = data.get("answers", data) if isinstance(data, dict) else {}
                missing = validate_brief(answers if isinstance(answers, dict) else {})
            except Exception:
                missing = BRIEF_QUESTIONS[:]
        else:
            p = Path(project) / "books" / book_id / "book-brief.json" if book_id else None
            try:
                data = json.loads(p.read_text()) if p and p.is_file() else {}
                answers = data.get("answers", data) if isinstance(data, dict) else {}
                missing = validate_brief(answers if isinstance(answers, dict) else {})
            except Exception:
                missing = BRIEF_QUESTIONS[:]
    return {"gated": gated, "missing": missing, "questions": BRIEF_QUESTIONS}
