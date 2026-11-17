"""The collaboration path: planner in its own task, executor on standby.

Two properties are contractual, so they are tested as contracts:

* standby does not touch the game -- no input, no pause -- which is what makes a
  landing stop freezing the room;
* a plan is judged against its anchor before a single frame is sent, which is
  what keeps ``STALE_PLAN`` at zero instead of merely making it harmless.
"""

import asyncio
from dataclasses import dataclass

import pytest

from agent.agents import (
    Anchor,
    PlannedStep,
    PlannerAgent,
    Standby,
    StepContract,
    TeamSession,
)
from agent.agents.messages import StepReport, Success
from agent.protocol import (
    ActionSequence,
    FrameAction,
    GameState,
    PlayerState,
    RoomState,
)

STILL = dict(on_ground=True, vx=0.0, vy=0.0)


def state(x=2000.0, y=-1128.0, *, dead=False, dashes=1, room="6b", **motion):
    return GameState(
        frame=0,
        player=PlayerState(x=x, y=y, dashes=dashes, stamina=110.0, dead=dead,
                           **{**STILL, **motion}),
        room=RoomState(name=room, completed=False),
    )


@dataclass
class FixturePlan:
    """What a model returns, minus the model."""

    actions: list
    goal: str = "fixture"
    reason: str = "fixture"
    expected_x_min: float = -10000.0
    expected_x_max: float = 10000.0


def right(frames=10, buttons=("right",)):
    return FrameAction(buttons=list(buttons), frames=frames)


class StubExecutor:
    """Executes nothing; reports whatever the test needs to see."""

    def __init__(self, current=None, *, status="SUCCEEDED", miss=None):
        self.state = current or state()
        self.status = status
        self.miss = miss
        self.calls: list[str] = []
        self.runs: list[tuple[ActionSequence, StepContract]] = []

    async def observe(self):
        return self.state

    async def call(self, method, **params):
        self.calls.append(method)
        if method == "ping":
            return {"backend": "stub", "pause_control": True, "platform_telemetry": True}
        if method == "get_playability":
            return {"playable": True}
        if method == "pause_game":
            return {"paused": True}
        if method == "resume_game":
            return {"paused": False}
        if method == "get_room_info":
            return {"room": self.state.room.name,
                    "bounds": {"x": 0, "y": 0, "width": 320, "height": 184},
                    "exits": [{"side": "right", "target": "6c", "axis": "y",
                               "from": -1200, "to": -1100}]}
        if method == "get_platforms":
            return {"platforms": [], "total": 0}
        raise AssertionError(f"unexpected call {method}")

    async def run(self, sequence, contract):
        self.runs.append((sequence, contract))
        frames = sum(action.frames for action in sequence.actions)
        return StepReport(status=self.status, execution_id=sequence.execution_id,
                          planned_frames=frames, executed_frames=frames,
                          contract=contract, start=self.state, end=self.state)

    def success_reason(self, contract, current):
        return self.miss


def build(plan_fn, executor=None, **options):
    executor = executor or StubExecutor()
    options.setdefault("still_for", 0.01)
    options.setdefault("poll", 0.01)
    options.setdefault("max_steps", 4)
    options.setdefault("settle_timeout", 0.4)
    options.setdefault("think_budget", 5.0)
    planner = PlannerAgent(plan_fn, exit_room=options.get("exit_room"))
    return TeamSession(executor, planner, **options), executor


# -- standby policy ------------------------------------------------------


def test_airborne_is_never_an_anchor():
    agent = Standby(still_for=0.01)
    air = state(on_ground=False, vy=-160.0)
    assert [agent.observe(air, t) for t in (0.0, 0.1, 0.2)] == ["SETTLING"] * 3


def test_a_resting_body_becomes_an_anchor_after_the_quiet_window():
    agent = Standby(still_for=0.1)
    still = state()
    assert agent.observe(still, 0.0) == "SETTLING"
    assert agent.observe(still, 0.05) == "SETTLING"
    assert agent.observe(still, 0.12) == "ANCHORED"


def test_a_lift_carrying_her_is_not_an_anchor():
    """Grounded and silent, but someone else is moving the floor."""
    agent = Standby(still_for=0.05, drift_px=1.5)
    for step in range(6):
        assert agent.observe(state(x=2000.0 + step * 6.0), step * 0.1) == "SETTLING"


def test_death_resets_the_quiet_window():
    agent = Standby(still_for=0.01)
    assert agent.observe(state(dead=True), 1.0) == "BLOCKED"
    assert agent.observe(state(), 1.1) == "SETTLING"


# -- the promise: plan against an anchor, not against hope ----------------


def test_the_precondition_comes_from_the_anchor_not_from_the_model():
    anchor = Anchor(id=7, state=state(x=2000.0, y=-1128.0))
    planner = PlannerAgent(lambda context: None)
    contract = planner.contract(anchor, FixturePlan(actions=[right(10)]))

    assert contract.pre.room == "6b"
    assert contract.pre.on_ground is True
    assert contract.pre.x == (1998.0, 2002.0)
    assert contract.pre.y == (-1130.0, -1126.0)


def test_a_frozen_anchor_widens_the_precondition_but_not_the_band():
    anchor = Anchor(id=8, state=state(x=2000.0), frozen=True)
    contract = PlannerAgent(lambda c: None).contract(
        anchor, FixturePlan(actions=[right(4)], expected_x_min=2005.0,
                            expected_x_max=2015.0))
    assert contract.pre.x == (1992.0, 2008.0)
    assert contract.ok.x == (2005.0, 2015.0)


def test_a_plan_bound_to_a_dead_anchor_is_dropped_before_any_input():
    session, executor = build(lambda c: FixturePlan(actions=[right()]))

    async def scenario():
        first = await session._publish(state())
        executor.state = state(x=2070.0, y=-1120.0)
        second = await session._publish(executor.state)
        await session.plans.put(PlannedStep(anchor_id=first.id, actions=[right()],
                                            contract=StepContract()))
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(session._await_plan(second, float("inf")), 0.2)

    asyncio.run(scenario())
    assert session.stats.superseded == 1
    assert executor.runs == []
    assert "execute_frames" not in executor.calls


def test_a_late_plan_for_the_current_anchor_is_accepted():
    session, executor = build(lambda c: FixturePlan(actions=[right()]))

    async def scenario():
        anchor = await session._publish(executor.state)
        await session.plans.put(PlannedStep(anchor_id=anchor.id, actions=[right()],
                                            contract=StepContract()))
        return await session._await_plan(anchor, float("inf"))

    accepted = asyncio.run(scenario())
    assert accepted.anchor_id == 1
    assert accepted.actions[0].frames == 10


def test_an_anchor_that_drifts_while_thinking_is_dropped():
    session, executor = build(lambda c: FixturePlan(actions=[right()]))

    async def scenario():
        anchor = await session._publish(state(x=2000.0))
        executor.state = state(x=2060.0)  # a lift, or a wandering thumb
        return await asyncio.wait_for(session._await_plan(anchor, float("inf")), 1.0)

    assert asyncio.run(scenario()) is None
    assert session.stats.superseded == 1


# -- the loop ------------------------------------------------------------


def test_standby_never_pauses_the_game():
    """Landing is not a reason to freeze the room."""

    async def slow_plan(context):
        await asyncio.sleep(0.12)  # a model thinking, in miniature
        return FixturePlan(actions=[right(10)])

    session, executor = build(slow_plan)
    result = asyncio.run(session.run())

    assert "pause_game" not in executor.calls
    assert "resume_game" not in executor.calls
    assert len(executor.runs) == 4  # the step limit, not a deadlock
    assert session.stats.rejected == 0
    assert result == "STOPPED"


def test_thinking_time_is_spent_standing_still():
    seen = []

    async def slow_plan(context):
        seen.append(context["anchor"])
        await asyncio.sleep(0.08)
        return FixturePlan(actions=[right(10)])

    session, executor = build(slow_plan, max_steps=1)
    asyncio.run(session.run())

    # One anchor per step: the world never had to be re-anchored while the
    # planner was thinking.
    assert len(seen) == 1
    assert seen[0]["still_for"] >= 0.0
    assert session.stats.superseded == 0


def test_an_unstable_world_ends_the_run_instead_of_freezing():
    session, executor = build(lambda c: FixturePlan(actions=[right()]),
                              StubExecutor(state(on_ground=False, vy=-160.0)),
                              anchor_timeout=0.05, max_steps=2)
    result = asyncio.run(session.run())

    assert result == "STOPPED"
    assert "pause_game" not in executor.calls
    assert executor.runs == []


def test_freeze_is_the_last_resort_and_still_runs_the_plan():
    async def plan(context):
        return FixturePlan(actions=[right(6)])

    session, executor = build(plan,
                              StubExecutor(state(on_ground=False, vy=-160.0)),
                              anchor_timeout=0.05, unstable="freeze", max_steps=1)
    result = asyncio.run(session.run())

    assert result == "STOPPED"
    assert "pause_game" in executor.calls
    assert "resume_game" in executor.calls
    assert executor.calls.index("pause_game") < executor.calls.index("resume_game")
    assert len(executor.runs) == 1
    assert session.stats.freezes == 1


def test_a_planner_failure_reanchors_instead_of_deadlocking():
    attempts = []

    async def flaky(context):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("model returned garbage")
        return FixturePlan(actions=[right(10)])

    session, executor = build(flaky, max_steps=1)
    assert asyncio.run(session.run()) == "STOPPED"
    assert len(executor.runs) == 1
    assert session.stats.plan_failures == 1
    assert session.stats.anchors == 2


def test_a_plan_that_cannot_be_a_sequence_is_refused_locally():
    """Too many frames is a planner bug, not something to send at the game."""
    oversized = FixturePlan(actions=[right(120)] * 6)
    session, executor = build(lambda c: oversized, max_steps=1, max_plan_failures=2)

    assert asyncio.run(session.run()) == "FAILED"
    assert executor.runs == []


def test_the_step_is_reported_back_to_the_planner():
    seen = []

    async def plan(context):
        seen.append(context["history"])
        return FixturePlan(actions=[right(10)])

    session, _ = build(plan, max_steps=2)
    asyncio.run(session.run())

    second = seen[1]
    assert second and second[0]["verdict"] == "LANDED"
    assert second[0]["actions"] == [{"buttons": ["right"], "frames": 10}]
    assert second[0]["settled"] == [2000.0, -1128.0]


def test_a_missed_landing_is_judged_on_the_settled_state():
    session, executor = build(lambda c: FixturePlan(actions=[right(10)]),
                              StubExecutor(miss="x_out_of_band"), max_steps=1)
    asyncio.run(session.run())

    assert session.stats.landed == 0
    assert session.stats.rejected == 0


@pytest.mark.parametrize("status", ["SUCCEEDED", "UNSATISFIED"])
def test_landing_verdict_follows_the_success_band(status):
    session, executor = build(lambda c: FixturePlan(actions=[right(10)]),
                              StubExecutor(status=status), max_steps=1)

    async def scenario():
        anchor = await session._publish(executor.state)
        step = PlannedStep(anchor_id=anchor.id, actions=[right(10)],
                           contract=StepContract(ok=Success(x=(0.0, 1.0))))
        return await session._execute(anchor, step)

    outcome = asyncio.run(scenario())
    assert outcome.verdict == "LANDED"
    assert session.stats.steps == 1
    assert session.stats.rejected == 0


def test_collab_runs_against_the_mock_bridge(tmp_path, monkeypatch):
    """End to end over a real socket: client, executor, planner task, standby."""
    from agent.agents import ExecutorAgent
    from agent.client import BridgeClient
    from agent.mock import MockBridge
    from agent.tools import ToolRegistry

    monkeypatch.chdir(tmp_path)

    async def plan(context):
        return FixturePlan(actions=[FrameAction(buttons=["right"], frames=30),
                                    FrameAction(buttons=[], frames=4)])

    async def scenario():
        server = await asyncio.start_server(MockBridge().handle, "127.0.0.1", 0)
        async with server, BridgeClient(server.sockets[0].getsockname()[1]) as client:
            session = TeamSession(ExecutorAgent(client, ToolRegistry(client)),
                                  PlannerAgent(plan, exit_room="mock-flat"),
                                  exit_room="mock-flat", max_steps=5, still_for=0.01,
                                  poll=0.01)
            return await session.run(), session.stats

    verdict, stats = asyncio.run(scenario())
    assert verdict == "SUCCESS"
    assert stats.rejected == 0
    assert stats.landed == stats.steps
    assert stats.superseded == 0
