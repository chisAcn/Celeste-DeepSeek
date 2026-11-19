"""The dash aim frame.

The bridge applies one chunk per tick and freeze ticks tick nothing, so the
direction a dash travels on comes from the chunk that covers the first frame
after the freeze. A one-frame dash chunk leaves that frame to the chunk after
it, which is how ``[right+up+dash] x1`` followed by ``[right] x20`` became a
horizontal dash in room 8 and looked like a bridge bug for an afternoon.
"""
import asyncio

from agent.agents.messages import Anchor
from agent.agents.planner import PlannerAgent
from agent.aims import audit, repair
from agent.protocol import FrameAction, GameState


def frames(actions):
    return sum(action.frames for action in actions)


def shape(actions):
    return [(tuple(action.buttons), action.frames) for action in actions]


def state(**overrides):
    payload = {
        "frame": 1000,
        "player": {"x": 2719.0, "y": -1704.0, "vx": 0.0, "vy": 0.0,
                   "on_ground": True, "dashes": 1, "stamina": 110, "dead": False},
        "room": {"name": "8", "completed": False},
    }
    payload.update(overrides)
    return GameState.model_validate(payload)


class Plan:
    def __init__(self, actions):
        self.actions = actions
        self.goal = "improvised"
        self.reason = "no route matched"


def serve_once(planner, anchor_state, *, timeout=1.0):
    async def scenario():
        anchors, plans = asyncio.Queue(), asyncio.Queue()
        outcomes, stop = asyncio.Queue(), asyncio.Event()
        task = asyncio.create_task(planner.serve(anchors, plans, outcomes, stop))
        await anchors.put(Anchor(id=1, state=anchor_state, still_for=0.2))
        try:
            return await asyncio.wait_for(plans.get(), timeout)
        finally:
            stop.set()
            task.cancel()

    return asyncio.run(scenario())


# -- what counts as a lost aim ---------------------------------------------

def test_a_one_frame_dash_chunk_that_drops_the_aim_is_reported():
    actions = [FrameAction(buttons=["right", "up", "dash"], frames=1),
               FrameAction(buttons=["right"], frames=20)]

    problems = audit(actions)

    assert len(problems) == 1
    assert "chunk 2 drops up" in problems[0]


def test_aim_held_into_the_next_chunk_is_left_alone():
    actions = [FrameAction(buttons=["right", "up", "dash"], frames=1),
               FrameAction(buttons=["right", "up"], frames=20)]

    assert audit(actions) == []
    assert repair(actions) == (actions, [])


def test_a_dash_without_a_declared_aim_is_not_an_error():
    # Straight along facing is a legitimate dash; there is nothing to hold.
    actions = [FrameAction(buttons=["dash"], frames=1),
               FrameAction(buttons=["right"], frames=20)]

    assert audit(actions) == []


def test_a_multi_frame_dash_chunk_aims_for_itself():
    # The chunk is still being applied when the freeze ends, so it covers the
    # aim frame without help.
    actions = [FrameAction(buttons=["up", "dash"], frames=3),
               FrameAction(buttons=["right"], frames=20)]

    assert audit(actions) == []


def test_a_dash_on_the_last_chunk_has_no_aim_frame():
    problems = audit([FrameAction(buttons=["right", "up", "dash"], frames=1)])

    assert len(problems) == 1
    assert "last chunk" in problems[0]


# -- the repair ------------------------------------------------------------

def test_the_repair_holds_the_aim_for_exactly_one_frame():
    actions = [FrameAction(buttons=["right", "up", "dash"], frames=1),
               FrameAction(buttons=["right"], frames=20)]

    fixed, notes = repair(actions)

    assert shape(fixed) == [(("right", "up", "dash"), 1), (("right", "up"), 1),
                            (("right",), 19)]
    assert len(notes) == 1 and "up" in notes[0]
    assert frames(fixed) == frames(actions)


def test_a_partial_drop_holds_only_the_direction_that_was_lost():
    actions = [FrameAction(buttons=["right", "up", "dash"], frames=1),
               FrameAction(buttons=["right"], frames=6)]

    fixed, notes = repair(actions)

    assert shape(fixed) == [(("right", "up", "dash"), 1), (("right", "up"), 1),
                            (("right",), 5)]
    assert len(notes) == 1


def test_a_one_frame_follower_grows_no_empty_tail():
    actions = [FrameAction(buttons=["right", "up", "dash"], frames=1),
               FrameAction(buttons=["jump"], frames=1),
               FrameAction(buttons=["right"], frames=10)]

    fixed, notes = repair(actions)

    assert shape(fixed) == [(("right", "up", "dash"), 1),
                            (("jump", "right", "up"), 1),
                            (("right",), 10)]
    assert all(action.frames >= 1 for action in fixed)
    assert frames(fixed) == frames(actions)
    assert len(notes) == 1


def test_a_dash_on_the_last_chunk_is_reported_and_left_alone():
    actions = [FrameAction(buttons=["right"], frames=4),
               FrameAction(buttons=["right", "up", "dash"], frames=1)]

    fixed, notes = repair(actions)

    assert shape(fixed) == shape(actions)
    assert notes == []


# -- through the planner ---------------------------------------------------

def test_the_planner_sends_the_repaired_chunks_and_counts_them():
    actions = [FrameAction(buttons=["right", "up", "dash"], frames=1),
               FrameAction(buttons=["right"], frames=6)]

    async def plan(context):
        return Plan(actions)

    planner = PlannerAgent(plan)
    step = serve_once(planner, state())

    assert shape(step.actions) == [(("right", "up", "dash"), 1),
                                   (("right", "up"), 1), (("right",), 5)]
    assert planner.aim_repairs == 1
    assert planner.last_aim_note and "up" in planner.last_aim_note
    # The budget is the repaired frame count plus slack, not the model's count.
    assert step.contract.abort.timeout_frames == frames(step.actions) + planner.slack


def test_a_plan_that_already_holds_the_aim_is_untouched():
    actions = [FrameAction(buttons=["right", "up", "dash"], frames=1),
               FrameAction(buttons=["right", "up"], frames=6)]

    async def plan(context):
        return Plan(actions)

    planner = PlannerAgent(plan)
    step = serve_once(planner, state())

    assert shape(step.actions) == shape(actions)
    assert planner.aim_repairs == 0
