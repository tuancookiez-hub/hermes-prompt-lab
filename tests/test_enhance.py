import importlib.util
import pathlib
import sys
from types import SimpleNamespace

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("pl_enhance", ROOT / "enhance.py")
E = importlib.util.module_from_spec(spec)
sys.modules["pl_enhance"] = E
spec.loader.exec_module(E)


class FakeLlm:
    def __init__(self, text):
        self.text, self.calls = text, []

    def complete(self, messages, **kw):
        self.calls.append((messages, kw))
        return SimpleNamespace(text=self.text, model="fake", usage=SimpleNamespace(input_tokens=5, output_tokens=7))


def test_rewrites_and_reports_usage():
    llm = FakeLlm("Goal: Fix it.")
    r = E.enhance(llm, "please fix the thing")
    assert r["prompt"] == "Goal: Fix it." and r["changed"] and r["usage"] == {"input_tokens": 5, "output_tokens": 7}


@pytest.mark.parametrize("text", ["hi", "Goal: x\nConstraints:\n- y"])
def test_short_or_structured_requests_skip_the_model(text):
    llm = FakeLlm("should not be used")
    assert E.enhance(llm, text)["changed"] is False and llm.calls == []


def test_empty_reply_raises_instead_of_passing_the_request_off_as_rewritten():
    with pytest.raises(E.EnhanceError):
        E.enhance(FakeLlm(""), "please fix the thing")


def test_clean_strips_thinking_and_fences():
    assert E.clean("<think>hm</think>\n```text\nGoal: x\n```") == "Goal: x"


def system_of(llm):
    return llm.calls[0][0][0]["content"]


def test_default_voice_is_structured():
    llm = FakeLlm("Goal: x")
    E.enhance(llm, "please fix the thing")
    assert "Goal: one sentence" in system_of(llm)


@pytest.mark.parametrize("voice", ["concise", "detailed", "clarify", "verify"])
def test_each_voice_changes_the_instructions(voice):
    llm = FakeLlm("ok then")
    E.enhance(llm, "please fix the thing", voice=voice)
    assert E.VOICES[voice] in system_of(llm) and E.VOICES["structured"] not in system_of(llm)


def test_custom_voice_uses_the_users_words():
    llm = FakeLlm("ok then")
    E.enhance(llm, "please fix the thing", voice="custom", custom="Sound like a pirate.")
    assert "Sound like a pirate." in system_of(llm)


@pytest.mark.parametrize("voice,custom", [("custom", "   "), ("nonsense", ""), (None, None)])
def test_empty_custom_or_unknown_voice_falls_back_to_structured(voice, custom):
    assert E.voice_text(voice, custom) == E.VOICES["structured"]


@pytest.mark.parametrize("voice", ["friendly", "expert"])
def test_a_voice_removed_in_0_5_falls_back_to_structured(voice):
    assert E.voice_text(voice) == E.VOICES["structured"]


def test_custom_voice_is_capped():
    assert len(E.voice_text("custom", "x" * 5000)) < E.MAX_CUSTOM_CHARS + 100


def test_other_voices_rewrite_an_already_structured_draft():
    llm = FakeLlm("Please fix it.")
    r = E.enhance(llm, "Goal: x\nConstraints:\n- y", voice="concise")
    assert r["changed"] and llm.calls


def test_only_the_request_is_sent():
    llm = FakeLlm("Goal: x")
    E.enhance(llm, "add a date parser")
    assert llm.calls[0][0][1]["content"] == "REQUEST:\nadd a date parser"


def test_desktop_button_uses_the_same_instructions():
    import json
    source = (ROOT / "desktop" / "plugin.js").read_text(encoding="utf-8")
    block = source.split("/* prompts:start */")[1].split("/* prompts:end */")[0]
    prompts = json.loads(block.strip().removeprefix("const PROMPTS =").strip().rstrip(";"))
    assert prompts == {"base": E.BASE, "voices": E.VOICES}
