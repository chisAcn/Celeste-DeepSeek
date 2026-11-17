import asyncio
import json

import pytest

from agent.live_search import search
from agent.memory import Memory, assess_route, compose_skills, landing_skill
from agent.protocol import ExecutionResult, GameState, PlatformSample


def state(x, grounded=True):
    observation = GameState(platform_sample=PlatformSample(platforms=[], total=0))
    observation.player.x = x
    observation.player.on_ground = grounded
    return observation


def recording(start, end, identifier="reference"):
    result = ExecutionResult(
        execution_id=identifier, status="completed", executed_frames=2,
        before=state(start), after=state(end),
        checkpoints=[state(start, False), state(end)],
    ).model_dump()
    winner = {"stable_landing": True, "result": result,
              "actions": [{"buttons": ["right", "jump"], "frames": 2}]}
    return {"success": True, "settle": 1, "grounded_frames": 1, "winner": winner,
            "trials": [winner], "verifications": [
                {**result, "execution_id": f"{identifier}-{i}"} for i in range(3)]}


def test_import_retrieval_composition_and_outcomes(tmp_path):
    report = recording(0, 4)
    first = landing_skill(report, "jump", "fixture")
    second = landing_skill(recording(4, 8, "next"), "next", "fixture")
    memory = Memory(tmp_path / "skills.sqlite3")
    try:
        memory.save_skill(first)
        memory.save_skill(second)
        assert memory.retrieve(state(0), "other") == []
        assert memory.retrieve(state(1), "fixture") == []
        changed = state(0)
        changed.platform_sample = None
        assert memory.retrieve(changed, "fixture") == []
        route = compose_skills(memory, state(0), "fixture", (8, 0))[0]
        assert route == (first, second)
        result = ExecutionResult(
            execution_id="attempt", status="completed", executed_frames=4,
            before=state(0), after=state(7),
            checkpoints=[state(0, False), state(4), state(4, False), state(7)],
        )
        attempts = list(assess_route(route, result, "fixture"))
        assert attempts == [(first, None), (second, "outcome_mismatch")]
        for skill, failure in attempts:
            memory.record_attempt(skill, failure)
        memory.save_skill(second)
        assert memory.retrieve(state(4), "fixture")[0].success_rate == 0.75
        memory.store_report(report, "fixture", "beam")
        jsonl = tmp_path / "trajectories.jsonl"
        memory.export_trajectories(jsonl)
        assert [json.loads(line) for line in jsonl.read_text().splitlines()] == memory.list("trajectory")
    finally:
        memory.close()

    report["verifications"][0]["executed_frames"] = 1
    with pytest.raises(ValueError, match="traces differ"):
        landing_skill(report, "invalid", "fixture")


def test_skill_search_beats_primitive_budget(tmp_path):
    class SavedBridge:
        async def call(self, method, **params):
            if method == "ping":
                return {"restore_and_execute": True}
            assert method == "restore_and_execute"
            action = params["actions"][0]
            if action["buttons"] == ["right", "jump"]:
                return {**recording(0, 4)["winner"]["result"],
                        "execution_id": params["execution_id"]}
            return ExecutionResult(
                execution_id=params["execution_id"], status="completed", executed_frames=2,
                before=state(0), after=state(0), checkpoints=[state(0), state(0)],
            ).model_dump()

    memory = Memory(tmp_path / "skills.sqlite3")
    try:
        memory.save_skill(landing_skill(recording(0, 4), "jump", "fixture"))
        options = dict(dx=4, dy=0, radius=0, width=1, depth=1, budget=2, frames=2,
                       own_slot=False, memory=memory, game_version="fixture")
        baseline = asyncio.run(search(SavedBridge(), **options))
        assisted = asyncio.run(search(SavedBridge(), use_skills=True, **options))
        assert not baseline["success"]
        assert assisted["success"]
        assert baseline["evaluations"] == assisted["evaluations"] == 2
        assert memory.retrieve(state(0), "fixture")[0].successes == 4
    finally:
        memory.close()
