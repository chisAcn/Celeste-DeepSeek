import asyncio

import pytest

from agent.agents import ExecutorAgent, StepContract
from agent.agents.messages import Abort, Precondition, Success
from agent.mock import MockBridge
from agent.protocol import ActionSequence, FrameAction, GameState, PlayerState, Request


def state(x=0.0, y=-1128.0, *, dead=False, on_ground=True, dashes=1, room="6b",
          vx=0.0, vy=0.0, state_name=""):
    return GameState.model_validate({
        "frame": 0,
        "player": {"x": x, "y": y, "vx": vx, "vy": vy, "on_ground": on_ground,
                   "dashes": dashes, "stamina": 110, "dead": dead,
                   "state": state_name},
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


class ClockAhead(Scripted):
    """Bridge 0.3.3: the running record carries the count, but the room clock
    may have raced ahead of the job (other scenes, skipped frames)."""

    def __init__(self, states):
        super().__init__(states, finish_at=10 ** 6)
        self.clock = 0

    async def call(self, method, **params):
        if method == "get_state":
            self.calls.append((method, params))
            self.clock += 10
            data = self.states[0].model_dump()
            data["frame"] = self.clock
            return data
        return await super().call(method, **params)


def test_a_reported_count_wins_over_the_room_clock():
    bridge = ClockAhead([state(x=30.0, vx=60.0)])
    contract = StepContract(ok=Success(x=(0.0, 400.0)), abort=Abort(timeout_frames=5))
    report = run(bridge, contract, sequence((["right"], 30)))

    assert report.status == "ABORTED"
    assert report.at_frame == 5


def test_a_wall_grab_counts_as_its_own_landing():
    # Room 8's TAS arc ends holding a wall. At the same coordinates, the floor
    # and the wall face are different places to plan the next step from.
    executor = ExecutorAgent(None, None)
    ok = Success(x=(100.0, 100.0), y=(-1128.0, -1128.0), stance="climb")

    assert executor.success_reason(StepContract(ok=ok),
                                  state(100.0, on_ground=False, state_name="StClimb")) is None
    assert executor.success_reason(StepContract(ok=ok),
                                  state(100.0, on_ground=False, state_name="StNormal")) == "not_climbing"
    assert executor.success_reason(StepContract(ok=ok), state(100.0, state_name="StNormal")) == "not_climbing"


def test_the_same_spot_reads_differently_by_stance():
    executor = ExecutorAgent(None, None)
    ok = Success(x=(100.0, 100.0), y=(-1128.0, -1128.0), stance="ground")
    contract = StepContract(ok=ok)

    assert executor.success_reason(contract, state(100.0)) is None
    assert executor.success_reason(
        contract, state(100.0, on_ground=False, state_name="StClimb")) == "not_grounded"
    airborne = Success(x=(100.0, 100.0), y=(-1128.0, -1128.0), stance="air")
    assert executor.success_reason(StepContract(ok=airborne),
                                  state(100.0, on_ground=False, vy=-90.0)) is None


def test_a_blind_snapshot_says_so_instead_of_guessing():
    # A 0.3.4 bridge reports on_ground but not the state machine, so it cannot
    # tell a wall from a fall. Saying "not climbing" there would be a guess.
    executor = ExecutorAgent(None, None)
    contract = StepContract(ok=Success(stance="climb"))
    assert executor.success_reason(contract, state(on_ground=False)) == "stance_unknown"


def test_a_contract_without_a_stance_keeps_the_old_behaviour():
    executor = ExecutorAgent(None, None)
    ok = Success(x=(100.0, 100.0))

    assert ok.stance is None
    assert executor.success_reason(StepContract(ok=ok),
                                  state(100.0, on_ground=False, state_name="StClimb")) is None


def test_a_stance_that_contradicts_on_ground_is_refused():
    assert Success(on_ground=False, stance="climb").stance == "climb"
    assert Success(on_ground=True, stance="ground").stance == "ground"
    with pytest.raises(ValueError):
        Success(on_ground=False, stance="ground")
    with pytest.raises(ValueError):
        Success(on_ground=True, stance="air")
    # ``climb`` is not a contradiction with either one: grabbing a wall while
    # standing on the floor under it is real, and the live bridge reports
    # StClimb with on_ground true when she does it.
    assert Success(on_ground=True, stance="climb").stance == "climb"
    assert Success(on_ground=False, stance="climb").stance == "climb"


def test_an_old_snapshot_without_a_state_name_still_parses():
    player = PlayerState.model_validate({
        "x": 0, "y": 0, "vx": 0, "vy": 0, "on_ground": False,
        "dashes": 1, "stamina": 110, "dead": False})
    assert player.state == ""
    assert player.stance() == "air"
    assert PlayerState(on_ground=True).stance() == "ground"


def test_holding_a_wall_is_not_a_stall():
    # Live: left+grab from the floor of room 8 goes StClimb and then does not
    # move -- 0.03 px a frame at best -- so the still clock used to fire at
    # twelve frames and abort the step mid-grip, before its landing.
    executor = ExecutorAgent(None, None)
    seq = ActionSequence(execution_id="grip", actions=[
        FrameAction(buttons=["left", "grab"], frames=40)])
    stall = still_since = 0
    last = (100.0, -1128.0)
    climbing = state(100.0, on_ground=False, state_name="StClimb")

    for frames in range(1, 41):
        stall, still_since, last = executor._sample(
            seq, [], climbing, frames, still_since, last)
        assert stall < 12, f"aborted mid-grip at frame {frames}"


def test_walking_into_a_wall_still_stalls():
    # The exemption is the button, not the wall: running into one with no grab
    # held is still a plan that stopped making progress.
    executor = ExecutorAgent(None, None)
    seq = ActionSequence(execution_id="push", actions=[
        FrameAction(buttons=["right"], frames=40)])
    stall = still_since = 0
    last = (100.0, -1128.0)

    for frames in range(1, 20):
        stall, still_since, last = executor._sample(
            seq, [], state(100.0), frames, still_since, last)
    assert stall >= 12


def test_a_climb_landing_asks_the_bridge_to_keep_the_grip():
    # The mod releases input when a job ends, so a landing on a wall only
    # survives if the job says to keep holding grab.
    seq = ActionSequence(execution_id="grip", actions=[
        FrameAction(buttons=["left", "grab"], frames=6)])
    climb = StepContract(ok=Success(stance="climb"))

    assert ExecutorAgent._payload(seq, climb)["hold_after"] == ["grab"]
    assert ExecutorAgent._payload(seq, StepContract(ok=Success()))["hold_after"] == []
    grounded = StepContract(ok=Success(stance="ground"))
    assert ExecutorAgent._payload(seq, grounded)["hold_after"] == []


def test_the_mock_bridge_keeps_what_the_job_asked_it_to_hold():
    bridge = MockBridge()
    seq = ActionSequence(execution_id="hold", actions=[
        FrameAction(buttons=["left", "grab"], frames=4)], hold_after=["grab"])
    bridge.dispatch(Request(id="hold-1", method="execute_frames", params=seq.model_dump()))

    assert bridge.held == {"grab"}
