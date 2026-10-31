"""Chapter-contract fixtures that meet the engagement gate.

A contract that cannot say what the POV character wants, what stands in the way
and how the chapter turns is refused before a run starts. Tests that build a
contract for some other purpose get those three fields from here, so the gate
does not turn every fixture into a test of the gate."""

DEFAULT_WANT = "Mara wants the harbour log before the tide turns."
DEFAULT_OBSTACLE = "The warden will not open the door."
DEFAULT_TURN = {"kind": "decision", "text": "She breaks the lock herself."}


def with_engagement_fields(
    row: dict,
    *,
    want=DEFAULT_WANT,
    obstacle=DEFAULT_OBSTACLE,
    turn=None,
    chapter_kind=None,
    exempt_reason=None,
    omit=(),
) -> dict:
    """Return a copy of a chapter row carrying the three fields.

    `omit` lets a test build the invalid row it is about; `chapter_kind` and
    `exempt_reason` describe an exempt chapter instead."""
    result = dict(row)
    values = {
        "want": want,
        "obstacle": obstacle,
        "turn": dict(DEFAULT_TURN) if turn is None else turn,
    }
    for field_name, value in values.items():
        result.pop(field_name, None)
        if field_name not in omit:
            result[field_name] = value
    if chapter_kind is not None:
        result["chapter_kind"] = chapter_kind
    if exempt_reason is not None:
        result["exempt_reason"] = exempt_reason
    return result
