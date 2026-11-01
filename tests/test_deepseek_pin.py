import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import book_forge as bf  # noqa: E402

MODEL = "openrouter/deepseek/deepseek-v4.1-flash-1017"


def test_deepseek_pin_has_fallback_endpoints():
    provider = bf.CHORUS_MODEL_CONFIGS[MODEL]["provider"]
    assert provider["allow_fallbacks"] is True
    assert provider["order"] == provider["only"]
    assert len(provider["order"]) >= 3
    assert provider["order"][-1] == "deepseek"
