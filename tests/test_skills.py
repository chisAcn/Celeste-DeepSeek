import asyncio
import math

from agent.agents.messages import Anchor, StepOutcome, StepReport
from agent.agents.planner import PlannerAgent
from agent.agents.skills import Replay, SkillBook
from agent.protocol import ActionSequence, FrameAction, GameState


def state(x=100.0, y=-1000.0, *, room="7", on_ground=True, dashes=1, dead=False):
    return GameState.model_validate({
        "frame": 1000,
        "player": {"x": x, "y": y, "vx": 0.0, "vy": 0.0, "on_ground": on_ground,
                   "dashes": dashes, "stamina": 110, "dead": dead},
        "room": {"name": room, "completed": False},
    })


def route(x=100.0, y=-1000.0, *, end=180.0, room="7", dashes=1, frames=12):
    return Replay(name="hop", room=room, x=x, y=y, dashes=dashes,
                  actions=[FrameAction(buttons=["right"], frames=frames)],
                  end_x=end, end_y=y)


def outcome(verdict, start=None, end=None, actions=None, **report_fields):
    from agent.agents.messages import TraceRow

    start = start or state()
    report = StepReport(
        status=report_fields.pop("status", "SUCCEEDED"),
        reason=report_fields.pop("reason", None),
        execution_id="probe",
        actions=actions or [FrameAction(buttons=["right"], frames=12)],
        planned_frames=12, executed_frames=report_fields.pop("executed", 12),
        at_frame=report_fields.pop("at_frame", None),
        start=start, end=end or state(x=180.0),
        trace=[TraceRow(frame=i, x=100.0 + i, y=-1000.0) for i in range(4)],
        **report_fields)
    return StepOutcome(verdict=verdict, report=report, actions=actions or list(report.actions),
                       settled=report.end)


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
            await asyncio.gather(task, return_exceptions=True)
    return asyncio.run(scenario())


def test_a_route_matches_only_inside_the_tolerance():
    book = SkillBook(match_px=2.0)
    book.add(route())

    assert book.match(state(x=101.0, y=-999.5)) is not None
    assert book.match(state(x=102.0)) is not None
    assert book.match(state(x=103.0)) is None


def test_airborne_or_wrong_room_or_tired_anchors_never_match():
    book = SkillBook()
    book.add(route())

    assert book.match(state(on_ground=False)) is None
    assert book.match(state(room="7a")) is None
    assert book.match(state(dashes=0)) is None
    assert book.match(state(dead=True)) is None


def test_a_landed_step_becomes_a_route_and_can_be_replayed():
    book = SkillBook()
    assert book.note(outcome("LANDED")) == "learned-1"
    assert len(book) == 1

    matched = book.match(state(x=100.5))
    assert matched is not None and matched.end_x == 180.0
    assert matched.origin == "session"


def test_a_missed_step_is_not_promoted():
    book = SkillBook()
    assert book.note(outcome("MISSED", status="UNSATISFIED")) is None
    assert len(book) == 0


def test_two_consecutive_misses_take_a_route_out_of_rotation():
    book = SkillBook(max_streak=2)
    book.add(route())
    book.note(outcome("MISSED", status="ABORTED", reason="timeout"))

    assert book.match(state()) is not None
    book.note(outcome("MISSED", status="ABORTED", reason="timeout"))
    assert book.match(state()) is None

    assert book.describe("7") == []


def test_a_landing_restores_a_route_that_was_missing():
    book = SkillBook(max_streak=2)
    book.add(route())
    book.note(outcome("MISSED", status="ABORTED"))
    book.note(outcome("LANDED"))

    assert book.match(state()) is not None
    assert book.entries[0].streak == 0


def test_a_landed_step_keeps_the_frames_it_actually_flew():
    book = SkillBook()
    positions = [[100.0 + index, -1000.0] for index in range(12)]

    assert book.note(outcome("LANDED", positions=positions)) == "learned-1"

    assert book.entries[0].trace == [[round(x, 1), y] for x, y in positions]
    assert book.entries[0].expected_from(state()) is not None


def test_a_partial_capture_is_not_kept_as_an_arc():
    book = SkillBook()

    # Four positions for twelve frames means the step stopped early; replaying
    # that arc would stop the next attempt where this one stopped.
    book.note(outcome("LANDED", positions=[[100.0, -1000.0]] * 4))

    assert book.entries[0].trace is None


def test_the_recorded_arc_moves_to_where_the_anchor_stands():
    entry = route(x=100.0, frames=3)
    entry.trace = [[100.0, -1000.0], [102.0, -1002.0], [104.0, -1004.0]]

    assert entry.expected_from(state(x=102.0)) == [[102.0, -1000.0],
                                                   [104.0, -1002.0],
                                                   [106.0, -1004.0]]


def test_a_route_without_an_arc_has_nothing_to_check():
    assert route().expected_from(state()) is None


def test_the_planner_tries_the_book_before_asking_the_model():
    calls = []

    async def plan(context):
        calls.append(context)
        return Plan([FrameAction(buttons=["jump"], frames=6)])

    planner = PlannerAgent(plan)
    planner.book.add(route())
    planner.record(outcome("MISSED", actions=[FrameAction(buttons=["jump"], frames=4)]))

    step = serve_once(planner, state(x=100.5))

    assert step.goal == "retry hop"
    assert not calls
    assert planner.plans == 0 and planner.retry.retries == 1


def test_when_the_book_has_nothing_left_the_model_is_asked():
    calls = []

    async def plan(context):
        calls.append(context)
        return Plan([FrameAction(buttons=["jump"], frames=6)])

    planner = PlannerAgent(plan)
    planner.book.add(route())
    planner.record(outcome("MISSED", actions=[FrameAction(buttons=["right"], frames=12)]))

    step = serve_once(planner, state(x=100.5))

    # The only route here is the one that just missed; replaying it again is
    # how a failure becomes a loop, so the model gets the question instead.
    assert step.goal == "improvised" and len(calls) == 1


def test_a_landing_puts_the_book_back_in_charge():
    planner = PlannerAgent(lambda context: None)
    planner.book.add(route())
    planner.record(outcome("MISSED", actions=[FrameAction(buttons=["jump"], frames=4)]))
    planner.record(outcome("LANDED"))

    step = serve_once(planner, state(x=100.5))

    assert step.goal == "replay hop"


def test_the_planner_replays_without_asking_the_model():
    def refuse(context):
        raise AssertionError("a matched anchor must not reach the model")

    planner = PlannerAgent(refuse)
    planner.book.add(route())

    step = serve_once(planner, state(x=100.5))

    assert step.goal == "replay hop"
    assert planner.replays == 1
    assert planner.plans == 0
    assert [a.buttons for a in step.actions] == [["right"]]


def test_the_planner_asks_when_no_route_starts_here():
    calls = []

    async def plan(context):
        calls.append(context)
        return Plan([FrameAction(buttons=["left"], frames=6)])

    planner = PlannerAgent(plan)
    planner.book.add(route())

    step = serve_once(planner, state(x=140.0))

    assert step.goal == "improvised"
    assert len(calls) == 1
    assert planner.replays == 0


def test_no_replay_flag_always_asks_the_model():
    calls = []

    async def plan(context):
        calls.append(context)
        return Plan([FrameAction(buttons=["left"], frames=6)])

    planner = PlannerAgent(plan, replay=False)
    planner.book.add(route())

    step = serve_once(planner, state(x=100.5))

    assert step.goal == "improvised"
    assert len(calls) == 1


def test_a_replay_contract_pins_the_anchor_and_the_known_landing():
    planner = PlannerAgent(lambda context: None)
    planner.book.add(route(frames=12))

    step = planner._replay_step(Anchor(id=3, state=state()), planner.book.entries[0])

    assert step.anchor_id == 3
    assert step.contract.pre.x == (98.0, 102.0)
    assert step.contract.pre.on_ground is True
    assert step.contract.ok.x == (174.0, 186.0)
    assert step.contract.abort.timeout_frames == 12 + planner.slack


def test_history_says_why_a_step_stopped_not_just_that_it_did():
    planner = PlannerAgent(lambda context: None)
    planner.record(outcome("ABORTED", status="ABORTED", reason="timeout",
                           at_frame=8, executed=9))

    row = planner.history[-1]
    assert row["status"] == "ABORTED"
    assert row["reason"] == "timeout"
    assert row["at_frame"] == 8
    assert row["executed"] == 9
    assert row["trace"]


def test_the_thinned_trace_keeps_both_ends():
    from agent.agents.messages import TraceRow

    planner = PlannerAgent(lambda context: None)
    rows = [TraceRow(frame=i, x=100.0 + i, y=-1000.0) for i in range(40)]
    report = StepReport(status="SUCCEEDED", execution_id="probe", start=state(),
                        end=state(), trace=rows)
    planner.record(StepOutcome(verdict="LANDED", report=report,
                               actions=[FrameAction(buttons=["right"], frames=40)]))
    trace = planner.history[-1]["trace"]

    assert len(trace) == 6
    assert trace[0][0] == 0 and trace[-1][0] == 39
    assert all(math.isfinite(value) for row in trace for value in row[1:4])


def test_routes_loaded_from_memory_come_from_verified_replays():
    from agent.memory import Skill

    skill = Skill(name="6b-entry", game_version="1.4.0.0", room="6b",
                  sequence=ActionSequence(execution_id="skill-6b",
                                          actions=[FrameAction(buttons=["right"], frames=24)]),
                  expected_x_min=2100.0, expected_x_max=2120.0,
                  verified_start=state(x=2072.0, y=-1128.0, room="6b"),
                  verified_end=state(x=2111.0, y=-1152.0, room="6b"),
                  successes=3)

    entry = Replay.from_skill(skill)
    assert entry is not None
    assert (entry.x, entry.y) == (2072.0, -1128.0)
    assert entry.hits == 3 and entry.origin == "memory"

    planner = PlannerAgent(lambda context: None, skills=[skill])
    assert planner.book.match(state(x=2072.0, y=-1128.0, room="6b")) is not None


# -- a wall is a footing too --------------------------------------------


def hanging(x=100.0, y=-1000.0, *, room="7", on_ground=True):
    return GameState.model_validate({
        "frame": 1000,
        "player": {"x": x, "y": y, "vx": 0.0, "vy": 0.0, "on_ground": on_ground,
                   "dashes": 1, "stamina": 90, "dead": False, "state": "StClimb"},
        "room": {"name": room, "completed": False},
    })


def test_a_route_can_start_on_a_wall():
    # A wall is a place to plan the next step from. Leaving match() grounded-
    # only meant such a route was booked as a hit and then never used.
    book = SkillBook()
    book.add(route())

    assert book.match(hanging()) is not None
    # A slow fall is not a footing: no state name, nothing holding her.
    falling = hanging(on_ground=False).model_copy(deep=True)
    falling.player = falling.player.model_copy(update={"state": ""})
    assert falling.player.stance() == "air"
    assert book.match(falling) is None


def test_a_wall_landing_is_a_route_worth_keeping():
    book = SkillBook()
    end = hanging(x=180.0, y=-1000.0, on_ground=False)

    assert book.note(outcome("LANDED", end=end)) == "learned-1"
    assert book.entries[0].end_stance == "climb"


def test_a_step_that_ended_mid_fall_is_not_a_route():
    book = SkillBook()
    air = state(x=180.0, on_ground=False)
    assert air.player.stance() == "air"
    assert book.note(outcome("LANDED", end=air)) is None


def test_a_landing_updates_the_recorded_stance():
    book = SkillBook()
    book.add(route())
    book.note(outcome("LANDED", end=hanging(x=180.0, on_ground=False)))
    assert book.entries[0].end_stance == "climb"
    book.note(outcome("LANDED", end=state(x=180.0)))
    assert book.entries[0].end_stance == "ground"


def test_the_landing_stance_survives_the_disk():
    entry = route()
    entry.end_stance = "climb"

    assert Replay.from_dict(entry.to_dict()).end_stance == "climb"
    row = entry.to_dict()
    row.pop("end_stance")
    # Rows written before the field existed still load, judged by the bands.
    assert Replay.from_dict(row).end_stance is None
