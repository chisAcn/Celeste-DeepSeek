import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from agent.client import BridgeClient
from agent.codex_play import CodexPlanner, CodexPlayError
from agent.main import run
from agent.mock import MockBridge
from agent.protocol import ActionSequence, FrameAction, GameState, Request


def test_roundtrip():
    assert GameState.model_validate_json(GameState().model_dump_json()) == GameState()


@pytest.mark.parametrize("frames", [0, -1, 121, True])
def test_limits(frames):
    with pytest.raises(ValidationError):
        FrameAction(buttons=[], frames=frames)


def test_sequence_limit():
    with pytest.raises(ValidationError):
        ActionSequence(execution_id="x", actions=[FrameAction(buttons=[], frames=120)] * 6)


def test_duplicate_release():
    mock = MockBridge()
    req = Request(id="1", method="execute_frames", params={"execution_id": "a",
                  "actions": [{"buttons": ["right", "jump"], "frames": 10}]})
    result = mock.dispatch(req)
    assert result["executed_frames"] == 10
    assert not mock.held
    with pytest.raises(ValueError):
        mock.dispatch(req)


def test_e2e():
    async def scenario():
        server = await asyncio.start_server(MockBridge().handle, "127.0.0.1", 0)
        async with server, BridgeClient(server.sockets[0].getsockname()[1]) as client:
            assert await run(client, "mock") == "SUCCESS"
    asyncio.run(scenario())


def test_deepseek_requires_api_key(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    async def scenario():
        mock = MockBridge()
        server = await asyncio.start_server(mock.handle, "127.0.0.1", 0)
        async with server, BridgeClient(server.sockets[0].getsockname()[1]) as client:
            with pytest.raises(CodexPlayError, match="DEEPSEEK_API_KEY"):
                await run(client, "deepseek", steps=1)

    asyncio.run(scenario())


def test_deepseek_playtest(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fixture")
    captured = {}

    async def create(**kwargs):
        captured["request"] = kwargs
        content = json.dumps({
            "goal": "move right", "reason": "flat fixture",
            "actions": [{"buttons": ["right"], "frames": 30}],
            "expected_x_min": 1, "expected_x_max": 100,
        })
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=content))])

    async def close():
        pass

    def client_factory(**kwargs):
        captured["client"] = kwargs
        return SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
            close=close)

    monkeypatch.setitem(sys.modules, "openai",
                        SimpleNamespace(AsyncOpenAI=client_factory))

    async def scenario():
        mock = MockBridge()
        server = await asyncio.start_server(mock.handle, "127.0.0.1", 0)
        async with server, BridgeClient(server.sockets[0].getsockname()[1]) as client:
            assert await run(client, "deepseek", steps=1) == "STOPPED"
            assert not mock.held

    asyncio.run(scenario())
    assert captured["client"]["base_url"] == "https://api.deepseek.com"
    assert captured["client"]["api_key"] == "fixture"
    request = captured["request"]
    assert request["model"] == "deepseek-chat"
    assert request["response_format"] == {"type": "json_object"}
    content = request["messages"][1]["content"]
    assert '"mock-flat"' in content
    assert "movement_reference" in json.loads(content)
    reference = json.loads(content)["movement_reference"]
    assert "DASH. 240 px/s" in reference
    assert "27 px" in reference  # the jump apex that room 7 got wrong
    event = json.loads(Path("logs/decisions.jsonl").read_text(encoding="utf-8"))
    assert event["result"]["executed_frames"] == 30


def test_deepseek_pauses_while_planning(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fixture")
    order = []

    async def create(**kwargs):
        order.append("plan")
        content = json.dumps({
            "goal": "move right", "reason": "flat fixture",
            "actions": [{"buttons": ["right"], "frames": 30}],
            "expected_x_min": 1, "expected_x_max": 100,
        })
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=content))])

    async def close():
        pass

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(
        AsyncOpenAI=lambda **kwargs: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
            close=close)))

    class RecordingBridge(MockBridge):
        def dispatch(self, request):
            if request.method == "pause_game":
                order.append("pause")
            elif request.method == "resume_game":
                order.append("resume")
            return super().dispatch(request)

    async def scenario():
        mock = RecordingBridge()
        server = await asyncio.start_server(mock.handle, "127.0.0.1", 0)
        async with server, BridgeClient(server.sockets[0].getsockname()[1]) as client:
            assert await run(client, "deepseek", steps=1, pause_planning=True) == "STOPPED"
            assert mock.paused is False

    asyncio.run(scenario())
    assert order == ["pause", "plan", "resume"]


def test_deepseek_receives_skill_hints(monkeypatch, tmp_path):
    from agent.memory import Skill

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fixture")
    captured = {}

    async def create(**kwargs):
        captured["request"] = kwargs
        content = json.dumps({
            "goal": "replay skill", "reason": "verified route",
            "actions": [{"buttons": ["up", "right", "dash"], "frames": 12},
                        {"buttons": [], "frames": 45}],
            "expected_x_min": 2050, "expected_x_max": 2060,
        })
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=content))])

    async def close():
        pass

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(
        AsyncOpenAI=lambda **kwargs: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
            close=close)))

    skill = Skill(
        name="entrance-dash", game_version="fixture", room="mock-flat",
        sequence=ActionSequence(execution_id="skill-1", actions=[
            FrameAction(buttons=["up", "right", "dash"], frames=12),
            FrameAction(buttons=[], frames=45)]),
        expected_x_min=2055, expected_x_max=2055, successes=3,
        verified_start=GameState())

    async def scenario():
        mock = MockBridge()
        server = await asyncio.start_server(mock.handle, "127.0.0.1", 0)
        async with server, BridgeClient(server.sockets[0].getsockname()[1]) as client:
            await run(client, "deepseek", steps=1, skills=[skill])

    asyncio.run(scenario())
    content = captured["request"]["messages"][1]["content"]
    hints = json.loads(content)["verified_room_skills"]
    assert hints[0]["name"] == "entrance-dash"
    assert hints[0]["actions"][0] == {"buttons": ["up", "right", "dash"], "frames": 12}
    assert hints[0]["start_distance"] is not None


@pytest.mark.parametrize("frames", [30, 121])
def test_codex_playtest(monkeypatch, tmp_path, frames):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("agent.codex_play.shutil.which", lambda _: "codex")

    async def fake_call(self, args, **kwargs):
        if args == ["login", "status"]:
            return 0, b"Logged in using ChatGPT"
        assert '"mock-flat"' in kwargs["prompt"]
        output = Path(args[args.index("--output-last-message") + 1])
        output.write_text(json.dumps({
            "goal": "move right", "reason": "flat fixture",
            "actions": [{"buttons": ["right"], "frames": frames}],
            "expected_x_min": 1, "expected_x_max": 100,
        }), encoding="utf-8")
        return 0, b""

    monkeypatch.setattr(CodexPlanner, "_call", fake_call)

    async def scenario():
        mock = MockBridge()
        server = await asyncio.start_server(mock.handle, "127.0.0.1", 0)
        async with server, BridgeClient(server.sockets[0].getsockname()[1]) as client:
            if frames > 120:
                with pytest.raises(CodexPlayError, match="valid action plan"):
                    await run(client, "codex", steps=1)
                assert not Path("logs/decisions.jsonl").exists()
            else:
                assert await run(client, "codex", steps=1) == "STOPPED"
                event = json.loads(Path("logs/decisions.jsonl").read_text(encoding="utf-8"))
                assert event["result"]["executed_frames"] == frames
            assert not mock.held

    asyncio.run(scenario())
