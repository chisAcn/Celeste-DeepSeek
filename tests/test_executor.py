import asyncio

import pytest

from agent.agents import ExecutorAgent, StepContract
from agent.agents.messages import Abort, Precondition, Success
from agent.protocol import ActionSequence, FrameAction, GameState


def state(x=0.0, y=-1128.0, *, dead=False, on_ground=True, dashes=1, room="6b",
          vx=0.0, vy=0.0):
    return GameState.model_validate({
        "frame": 0,
        "player": {"x": x, "y": y, "vx": vx, "vy": vy, "on_ground": on_ground,
                   "dashes": dashes, "stamina": 110, "dead": dead},
        "room": {"name": room, "completed": False},
    })


class Scripted:
    """Bridge stand-in: one scripted state per observation, frames advance by poll."""

    def __init__(self, states, *, finish_at=None, interrupted=False):
        self.states = states
        self.index = 0
        self.frames = 0
        self.finish_at = len(states) if finish_at is None else finish_at
        self.interrupted = interrupted
        self.calls = []

    @property
    def methods(self):
        return [name for name, _ in self.calls]

    def current(self):
        return self.states[min(self.index, len(self.states) - 1)]

    async def call(self, method, **params):
        self.calls.append((method, params))
        if method == "get_state":
            current = self.current()
            self.index += 1
            return current.model_dump()
        if method == "execute_frames":
            self.frames = 0
            return {"execution_id": params["execution_id"], "status": "running"}
        if method == "get_execution":
            self.frames += 1
            if self.frames >= self.finish_at or self.interrupted:
                return {"execution_id": params["execution_id"],
                        "status": "interrupted" if self.interrupted else "completed",
                        "executed_frames": self.frames,
                        "before": self.states[0].model_dump(),
                        "after": self.current().model_dump()}
            return {"execution_id": params["execution_id"], "status": "running",
                    "executed_frames": self.frames}
        if method == "stop":
            self.interrupted = True
            return {"stopped": True}
        raise AssertionError(f"unexpected call {method}")


class Registry:
    def __init__(self):
        self.trajectory = []


def sequence(*actions, identifier="probe"):
    return ActionSequence(
        execution_id=identifier,
        actions=[FrameAction(buttons=buttons, frames=frames) for buttons, frames in actions])


def run(bridge, contract, seq):
    return asyncio.run(ExecutorAgent(bridge, Registry(), poll=0.0).run(seq, contract))


def test_rejects_stale_plan_without_sending_input():
    bridge = Scripted([state(x=0.0)])
    contract = StepContract(pre=Precondition(room="6b", x=(10.0, 20.0)))
    report = run(bridge, contract, sequence((["right"], 10)))

    assert report.status == "REJECTED"
    assert report.reason == "position_changed"
    assert report.executed_frames == 0
    assert "execute_frames" not in bridge.methods
    assert bridge.methods == ["get_state"]


def test_precondition_reproduces_the_old_drift_guard():
    planned = state(x=2016.0, y=-1128.0)
    contract = StepContract.for_plan([FrameAction(buttons=["right"], frames=10)],
                                     expected_x=(2020.0, 2050.0), planned=planned)

    assert contract.pre.room == "6b"
    assert contract.pre.on_ground is True
    assert contract.pre.min_dashes == 1
    assert contract.pre.x == (2012.0, 2020.0)
    assert contract.ok.x == (2020.0, 2050.0)
    assert contract.abort.timeout_frames == 40


def test_completed_landing_inside_the_band_succeeds():
    bridge = Scripted([state(x=30.0), state(x=50.0)], finish_at=2)
    contract = StepContract(ok=Success(on_ground=True, x=(40.0, 60.0)))
    report = run(bridge, contract, sequence((["right"], 2)))

    assert report.status == "SUCCEEDED"
    assert report.executed_frames == 2
    assert report.trace
    assert "stop" not in bridge.methods


def test_completed_landing_outside_the_band_is_unsatisfied():
    bridge = Scripted([state(x=30.0), state(x=35.0)], finish_at=2)
    contract = StepContract(ok=Success(x=(40.0, 60.0)))
    report = run(bridge, contract, sequence((["right"], 2)))

    assert report.status == "UNSATISFIED"
    assert report.reason == "x_out_of_band"
    assert report.executed_frames == 2


def test_stall_aborts_a_step_that_stops_moving():
    bridge = Scripted([state(x=30.0)], finish_at=99)
    contract = StepContract(ok=Success(x=(0.0, 400.0)), abort=Abort(stall_frames=3))
    report = run(bridge, contract, sequence((["right"], 30)))

    assert report.status == "ABORTED"
    assert report.reason == "stalled"
    assert report.at_frame == 3
    assert "stop" in bridge.methods


def test_crouching_in_place_is_not_a_stall():
    bridge = Scripted([state(x=30.0)], finish_at=99)
    contract = StepContract(ok=Success(x=(0.0, 400.0)),
                            abort=Abort(stall_frames=3, timeout_frames=5))
    report = run(bridge, contract, sequence((["down"], 30)))

    assert report.reason == "timeout"


def test_timeout_bounds_an_execution_that_never_ends():
    bridge = Scripted([state(x=30.0, vx=60.0)], finish_at=99)
    contract = StepContract(ok=Success(x=(0.0, 400.0)), abort=Abort(timeout_frames=2))
    report = run(bridge, contract, sequence((["right"], 30)))

    assert report.status == "ABORTED"
    assert report.reason == "timeout"
    assert report.at_frame == 2
    assert bridge.methods.count("stop") == 1


def test_divergence_is_opt_in():
    wide = StepContract(ok=Success(x=(0.0, 100.0)), abort=Abort(timeout_frames=4))
    assert run(Scripted([state(x=200.0)], finish_at=99), wide,
               sequence((["right"], 30))).reason == "timeout"

    tight = StepContract(ok=Success(x=(0.0, 100.0)),
                         abort=Abort(diverged_px=10.0, timeout_frames=4))
    report = run(Scripted([state(x=200.0)], finish_at=99), tight,
                 sequence((["right"], 30)))
    assert report.reason == "diverged"


def test_death_stops_the_step_and_is_reported_as_died():
    bridge = Scripted([state(x=30.0), state(x=40.0, dead=True)], finish_at=99)
    contract = StepContract(ok=Success(x=(100.0, 200.0)))
    report = run(bridge, contract, sequence((["right"], 30)))

    assert report.status == "DIED"
    assert report.reason == "dead"
    assert "stop" in bridge.methods


def test_bridge_interruption_without_death():
    bridge = Scripted([state(x=30.0), state(x=60.0)], finish_at=1, interrupted=True)
    report = run(bridge, StepContract(), sequence((["right"], 5)))

    assert report.status == "INTERRUPTED"
    assert report.reason == "bridge_interrupted"


def test_executor_never_resets_the_room():
    bridge = Scripted([state(x=30.0), state(x=40.0, dead=True)], finish_at=99)
    run(bridge, StepContract(ok=Success(x=(100.0, 200.0))), sequence((["right"], 10)))

    assert "reset_room" not in bridge.methods


@pytest.mark.parametrize("band", [(5.0, 1.0)])
def test_inverted_bands_are_rejected(band):
    with pytest.raises(ValueError):
        Precondition(x=band)


class FrameOnly(Scripted):
    """Bridge 0.3.2 as observed live: a running record carries no frame count.

    ``get_execution`` only fills ``executed_frames`` when the job finishes, so a
    watchdog that trusts that field is blind for the whole step. The room frame
    counter is the clock that does advance.
    """

    def __init__(self, states):
        super().__init__(states, finish_at=10 ** 6)
        self.clock = 0

    async def call(self, method, **params):
        if method == "get_state":
            self.calls.append((method, params))
            self.clock += 1
            data = self.states[0].model_dump()
            data["frame"] = self.clock
            return data
        if method == "get_execution":
            self.calls.append((method, params))
            return {"execution_id": params["execution_id"], "status": "running"}
        return await super().call(method, **params)


def test_a_blind_frame_counter_still_times_out():
    bridge = FrameOnly([state(x=30.0, vx=60.0)])
    contract = StepContract(ok=Success(x=(0.0, 400.0)), abort=Abort(timeout_frames=3))
    report = run(bridge, contract, sequence((["right"], 30)))

    assert report.status == "ABORTED"
    assert report.reason == "timeout"
    assert report.at_frame is not None and report.at_frame >= 3
    assert bridge.methods.count("stop") == 1


def test_a_blind_frame_counter_still_notices_a_stall():
    bridge = FrameOnly([state(x=30.0)])
    contract = StepContract(ok=Success(x=(0.0, 400.0)), abort=Abort(stall_frames=3))
    report = run(bridge, contract, sequence((["right"], 30)))

    assert report.status == "ABORTED"
    assert report.reason == "stalled"
