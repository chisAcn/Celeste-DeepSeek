"""Per-frame expectations: the arc a step is allowed to stay on.

The bridge checks the expectation inside the tick that applied the frame, so the
only thing worth testing here is the contract: what is accepted on the wire,
what comes back, and how the executor reads it.
"""

import asyncio

import pytest
from pydantic import ValidationError

from agent.agents import ExecutorAgent, StepContract
from agent.agents.messages import PlannedStep
from agent.mock import MockBridge
from agent.protocol import ActionSequence, FrameAction, GameState


def state(x=0.0, y=-1128.0, *, dead=False, on_ground=True, room="6b"):
    return GameState.model_validate({
        "frame": 0,
        "player": {"x": x, "y": y, "vx": 0.0, "vy": 0.0, "on_ground": on_ground,
                   "dashes": 1, "stamina": 110, "dead": dead},
        "room": {"name": room, "completed": False},
    })


def sequence(frames=10, **kwargs):
    return ActionSequence(execution_id="probe",
                          actions=[FrameAction(buttons=["right"], frames=frames)],
                          **kwargs)


class Deviating:
    """Bridge stand-in that ends the job on the frame the arc stops fitting."""

    def __init__(self, frames=10, deviation_at=4):
        self.frames = frames
        self.deviation_at = deviation_at
        self.sent = None

    async def call(self, method, **params):
        if method == "get_state":
            return state(x=params.get("x", 0.0)).model_dump()
        if method == "execute_frames":
            self.sent = params
            return {"execution_id": params["execution_id"], "status": "running"}
        if method == "get_execution":
            done = state(x=float(self.deviation_at))
            return {"execution_id": params["execution_id"], "status": "deviated",
                    "executed_frames": self.deviation_at, "before": state().model_dump(),
                    "after": done.model_dump(),
                    "deviation": {"frame": self.deviation_at,
                                  "index": self.deviation_at,
                                  "expected": [float(self.deviation_at) + 2, -1128.0],
                                  "actual": [float(self.deviation_at), -1128.0],
                                  "offset": [2.0, 0.0], "tolerance": 1.5},
                    "positions": [[float(i), -1128.0]
                                  for i in range(1, self.deviation_at + 1)]}
        raise AssertionError(f"unexpected call {method}")


class Registry:
    def __init__(self):
        self.trajectory = []


def test_a_plan_may_leave_its_arc_unchecked_at_the_end():
    rows = [[0.0, 0.0], None, [2.0, 0.0]]

    seq = sequence(frames=5, expect=rows, tolerance=1.0)

    assert seq.expect == rows


def test_more_expectations_than_frames_is_refused():
    with pytest.raises(ValidationError):
        sequence(frames=2, expect=[[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]])


def test_an_expectation_row_needs_two_numbers():
    with pytest.raises(ValidationError):
        sequence(frames=2, expect=[[0.0]])


def test_a_negative_tolerance_is_refused():
    with pytest.raises(ValidationError):
        sequence(frames=2, tolerance=-1.0)


def test_a_step_carries_the_arc_it_may_not_leave():
    step = PlannedStep(anchor_id=1,
                       actions=[FrameAction(buttons=["right"], frames=3)],
                       expect=[[1.0, -1128.0], [2.0, -1128.0]], tolerance=1.5)

    assert step.expect == [[1.0, -1128.0], [2.0, -1128.0]] and step.tolerance == 1.5


def test_a_step_cannot_expect_more_frames_than_it_plans():
    with pytest.raises(ValidationError):
        PlannedStep(anchor_id=1, actions=[FrameAction(buttons=["right"], frames=2)],
                    expect=[[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]])


def test_the_executor_sends_the_arc_and_keeps_the_positions():
    bridge = Deviating()
    seq = sequence(frames=10, expect=[[1.0, -1128.0], [2.0, -1128.0]], tolerance=1.5,
                   capture_positions=True)

    report = asyncio.run(ExecutorAgent(bridge, Registry(), poll=0.0)
                         .run(seq, StepContract()))

    assert bridge.sent["expect"] == [[1.0, -1128.0], [2.0, -1128.0]]
    assert bridge.sent["tolerance"] == 1.5 and bridge.sent["capture_positions"] is True
    assert len(report.positions) == 4


def test_leaving_the_arc_is_an_abort_that_says_which_frame():
    report = asyncio.run(ExecutorAgent(Deviating(deviation_at=4), Registry(), poll=0.0)
                         .run(sequence(frames=10), StepContract()))

    assert report.status == "ABORTED" and report.reason == "deviated"
    assert report.at_frame == 4
    assert report.deviation is not None
    assert report.deviation.expected == [6.0, -1128.0]
    assert report.deviation.offset == [2.0, 0.0]


def test_a_deviated_step_is_not_judged_on_its_landing():
    report = asyncio.run(ExecutorAgent(Deviating(deviation_at=4), Registry(), poll=0.0)
                         .run(sequence(frames=10), StepContract()))

    # The success band is empty, so the landing check would have passed; the
    # deviation is what makes it a failure, and that is the point.
    assert report.reason != "x_out_of_band"


def test_the_mock_bridge_stops_on_the_frame_that_leaves_the_arc():
    mock = MockBridge()
    seq = sequence(frames=6, expect=[[1.0, 0.0], [2.0, 0.0], [9.0, 0.0]],
                   tolerance=1.0, capture_positions=True)

    result = mock.dispatch(type("Request", (), {
        "method": "execute_frames", "params": seq.model_dump()})())

    assert result["status"] == "deviated"
    assert result["executed_frames"] == 3
    assert result["deviation"]["expected"] == [9.0, 0.0]
    assert len(result["positions"]) == 3


def test_the_mock_bridge_runs_to_the_end_when_the_arc_holds():
    mock = MockBridge()
    seq = sequence(frames=4, expect=[[1.0, 0.0], [2.0, 0.0]], tolerance=1.0)

    result = mock.dispatch(type("Request", (), {
        "method": "execute_frames", "params": seq.model_dump()})())

    assert result["status"] == "completed" and result["executed_frames"] == 4
    assert "deviation" not in result
