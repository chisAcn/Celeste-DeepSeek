import asyncio
import json
import sys
from types import SimpleNamespace

import pytest

from agent.main import Plan, run
from agent.mock import MockBridge
from agent.protocol import FrameAction, Request
from agent.tas_training import examples, parse_route, train


def test_tas_parser_preserves_boundaries(tmp_path):
    path = tmp_path / "demo.tas"
    path.write_text("1\n#lvl_a\n3,R\nRepeat,2\n2,R,J\nEndRepeat\n5,L,Z\n4,L\n#lvl_b\n3,R\n")
    rows, skipped = parse_route(path)
    records = list(examples(path, rows, "train"))
    assert skipped == 1
    assert [row["previous"] for row in records] == [None, "right", "jump,right", None, None]
    path.write_text("#lvl_a\nRead,other.tas\n")
    with pytest.raises(ValueError, match="flatten read"):
        parse_route(path)


def test_gpt_receives_trained_action_hints(monkeypatch, tmp_path):
    model = train([{"action": "right", "frames": 20, "previous": None}] * 4
                  + [{"action": "dash,right", "frames": 5, "previous": "right"}] * 3)
    assert all("dash" not in hint.buttons for hint in model.suggest("right", 0))
    captured = []
    bridge = MockBridge()

    async def call(method, **params):
        return bridge.dispatch(Request(id="test", method=method, params=params))

    async def parse(**kwargs):
        captured.append(json.loads(kwargs["input"]))
        return SimpleNamespace(output_parsed=Plan(
            goal="right", reason="fixture", actions=[FrameAction(buttons=["right"], frames=20)],
            expected_x_min=0, expected_x_max=100))

    async def close():
        pass

    sdk = SimpleNamespace(AsyncOpenAI=lambda **kwargs: SimpleNamespace(
        responses=SimpleNamespace(parse=parse), close=close))
    monkeypatch.setitem(sys.modules, "openai", sdk)
    monkeypatch.setenv("OPENAI_MODEL", "fixture")
    monkeypatch.chdir(tmp_path)
    asyncio.run(run(SimpleNamespace(call=call), "gpt", steps=2, action_prior=model))
    assert captured[0]["tas_action_hints"][0]["buttons"] == ["right"]
    assert captured[1]["tas_action_hints"][0]["buttons"] == ["dash", "right"]
