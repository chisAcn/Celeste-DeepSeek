from copy import deepcopy

from agent.evaluate import inspect_trial, replay_difference
from agent.protocol import ExecutionResult, GameState, PlatformSample, PlayerState


def test_platform_landing_and_first_replay_difference():
    def state(x, grounded=True):
        return GameState(player=PlayerState(x=x, on_ground=grounded),
                         platform_sample=PlatformSample(total=0, platforms=[]))

    result = ExecutionResult(
        execution_id="test", before=state(0), after=state(20), status="completed",
        executed_frames=5, checkpoints=[state(5, False), *(state(x) for x in (11, 14, 17, 20))],
    ).model_dump()
    trial = {"actions": [{"buttons": ["jump"], "frames": 5}], "result": result}
    assert not inspect_trial(trial, (20, 0), 3, {})["reached"]
    assert inspect_trial(trial, (20, 0), 10, {})["reached"]

    repeat = deepcopy(result)
    repeat["before"]["frame"] += 200
    assert replay_difference(result, repeat) is None
    repeat["checkpoints"][1]["player"]["vx"] = 1
    assert replay_difference(result, repeat) == 2
