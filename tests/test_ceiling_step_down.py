"""M59: a call that spends its ceiling and writes nothing is asked again one rung lower."""
import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_step_down", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bf = load_module()
EMPTY = {"text": "", "tokens": {"reasoning": 39000, "output": 0}, "session_id": "s", "variant": "high"}
ENVELOPE = {"bytes": b"{}", "hash": "h"}


def stepping_runner(answers_at):
    """Answers with text only at the efforts named in `answers_at`; None is the agent's own."""
    seen = []

    def runner(role, envelope, attempt_dir, variant=None):
        seen.append(variant)
        text = answers_at.get(variant, "")
        if not text:
            return dict(EMPTY)
        return {"text": text, "tokens": {"reasoning": 900, "output": 40}, "session_id": "s", "variant": "high"}

    return runner, seen


def test_an_empty_answer_at_high_lands_at_medium(tmp_path):
    runner, seen = stepping_runner({"medium": '{"ok": true}'})
    result = bf._ask_past_empty(runner, "technical-editor", ENVELOPE, tmp_path, "high", ["low", "medium", "high", "max"])
    assert seen == [None, "medium"]
    assert result["variant"] == "medium"
    assert result["stepped_from"] == "high"


def test_each_further_ask_steps_down_again(tmp_path):
    runner, seen = stepping_runner({"low": '{"ok": true}'})
    result = bf._ask_past_empty(runner, "technical-editor", ENVELOPE, tmp_path, "high", ["low", "medium", "high"])
    assert seen == [None, "medium", "low"]
    assert result["variant"] == "low"


def test_a_model_with_one_rung_is_asked_again_as_before(tmp_path):
    runner, seen = stepping_runner({})
    with pytest.raises(bf.ReasoningCeilingSpent):
        bf._ask_past_empty(runner, "technical-editor", ENVELOPE, tmp_path, "high", ["high"])
    assert seen == [None] * bf.REVIEW_CEILING_REASKS


def test_a_role_that_was_never_re_asked_stops_when_no_rung_is_left(tmp_path):
    runner, seen = stepping_runner({})
    with pytest.raises(bf.ReasoningCeilingSpent):
        bf._ask_past_empty(runner, "locale-reader", ENVELOPE, tmp_path, "low", ["low", "medium"], asks=2, only_lower=True)
    assert seen == [None]


def test_a_runner_that_takes_no_effort_is_never_handed_one(tmp_path):
    calls = []

    def runner(role, envelope, attempt_dir):
        calls.append(role)
        return dict(EMPTY)

    with pytest.raises(bf.ReasoningCeilingSpent):
        bf._ask_past_empty(runner, "technical-editor", ENVELOPE, tmp_path, "high", ["low", "medium", "high"])
    assert len(calls) == bf.REVIEW_CEILING_REASKS


@pytest.mark.parametrize("variant, ladder, lower", [
    ("high", ["low", "medium", "high", "max"], "medium"),
    ("xhigh", ["low", "medium", "high", "xhigh"], "high"),
    ("max", ["low", "medium", "high", "max"], "high"),
    ("high", ["high"], None),
    ("low", None, None),
    (None, None, None),
])
def test_one_rung_lower_follows_the_models_ladder(variant, ladder, lower):
    assert bf._one_rung_lower(variant, ladder) == lower


def test_the_role_ladder_reads_the_pin_and_the_models_steps(tmp_path):
    project = tmp_path / "world"
    bf.init_project(project, "World", chorus_models=[])
    variant, ladder = bf._role_ladder(bf._project_root(project), "technical-editor")
    model, pinned = bf._role_pin(bf._project_config(bf._project_root(project)), "technical-editor")
    assert variant == pinned
    assert ladder == list(bf.CHORUS_MODEL_CONFIGS[model]["variants"])
