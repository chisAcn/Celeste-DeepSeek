"""Second attempts that cost frames instead of tokens.

The retrier may only pick routes that already ran, so these tests are about the
two ways that can go wrong: offering the route that just failed (a loop), and
offering one from so far away that its arc is meaningless.
"""

from agent.agents.messages import Anchor, StepOutcome
from agent.agents.retry import LocalRetry
from agent.agents.skills import Replay, SkillBook
from agent.protocol import FrameAction, GameState


def state(x=100.0, y=-1000.0, *, room="7", dashes=1, on_ground=True, dead=False):
    return GameState.model_validate({
        "frame": 1000,
        "player": {"x": x, "y": y, "vx": 0.0, "vy": 0.0, "on_ground": on_ground,
                   "dashes": dashes, "stamina": 110, "dead": dead},
        "room": {"name": room, "completed": False},
    })


def anchor(x=100.0, **kwargs):
    return Anchor(id=1, state=state(x=x, **kwargs), still_for=0.2)


def route(name, x=100.0, *, y=-1000.0, hits=1, buttons=("right",), frames=12,
          trace=None):
    return Replay(name=name, room="7", x=x, y=y, dashes=1,
                  actions=[FrameAction(buttons=list(buttons), frames=frames)],
                  end_x=x + 20, end_y=y, hits=hits, trace=trace)


def outcome(verdict, buttons=("right",), frames=12):
    return StepOutcome(verdict=verdict,
                       actions=[FrameAction(buttons=list(buttons), frames=frames)])


def test_a_landing_ends_the_episode():
    retry = LocalRetry(SkillBook())
    retry.book.add(route("a"))
    retry.note(outcome("MISSED", buttons=("jump",)))

    assert retry.offer(anchor()) is not None
    retry.note(outcome("LANDED"))

    assert retry.offer(anchor()) is None and retry.failures == 0


def test_a_miss_offers_another_route_that_starts_here():
    retry = LocalRetry(SkillBook())
    retry.book.add(route("first", buttons=("right",)))
    retry.book.add(route("second", buttons=("left",)))
    retry.note(outcome("MISSED", buttons=("jump",)))

    step = retry.offer(anchor())

    assert step is not None and step.goal.startswith("retry ")
    assert step.actions[0].buttons in (["right"], ["left"])


def test_the_route_that_just_failed_is_not_offered_again():
    retry = LocalRetry(SkillBook())
    retry.book.add(route("only"))
    retry.note(outcome("MISSED", buttons=("right",), frames=12))

    assert retry.offer(anchor()) is None


def test_the_budget_limits_how_many_second_attempts_are_sent():
    retry = LocalRetry(SkillBook(), limit=2)
    for index in range(4):
        retry.book.add(route(f"r{index}", buttons=("right",) if index % 2 else ("left",),
                             frames=10 + index))
    retry.note(outcome("MISSED", buttons=("jump",)))

    offered = [retry.offer(anchor()) for _ in range(4)]

    assert sum(step is not None for step in offered) == 2
    assert retry.retries == 2


def test_the_route_with_the_most_landings_wins():
    retry = LocalRetry(SkillBook())
    retry.book.add(route("rare", hits=1, buttons=("left",)))
    retry.book.add(route("proven", hits=9, buttons=("right",)))
    retry.note(outcome("MISSED", buttons=("jump",)))

    step = retry.offer(anchor())

    assert step is not None and step.goal == "retry proven"


def test_an_arc_lets_a_route_be_reached_from_further_away():
    retry = LocalRetry(SkillBook(), radius=8.0)
    bare = route("bare", x=106.0, buttons=("right",))
    traced = route("traced", x=106.0, buttons=("left",),
                   trace=[(106.0 + i, -1000.0) for i in range(12)])
    retry.book.add(bare)
    retry.book.add(traced)
    retry.note(outcome("MISSED", buttons=("jump",)))

    step = retry.offer(anchor(x=100.0))

    # 6px away is outside the 2px replay window, so only the route with an arc
    # may be tried -- the arc is what stops it on the frame that does not fit.
    assert step is not None and step.goal == "retry traced"
    assert step.expect is not None and len(step.expect) == 12


def test_the_arc_moves_with_the_anchor():
    retry = LocalRetry(SkillBook())
    entry = route("traced", x=100.0,
                  trace=[(100.0, -1000.0), (102.0, -1004.0)])
    retry.book.add(entry)
    retry.note(outcome("MISSED", buttons=("jump",)))

    step = retry.offer(anchor(x=104.0))

    # The start is 4px off, so the whole recorded arc moves by 4px with it.
    assert step is not None and step.expect == [[104.0, -1000.0], [106.0, -1004.0]]


def test_nothing_is_offered_from_midair_or_after_death():
    retry = LocalRetry(SkillBook())
    retry.book.add(route("only"))
    retry.note(outcome("DIED", buttons=("jump",)))

    assert retry.offer(anchor(on_ground=False)) is None
    assert retry.offer(anchor(dead=True)) is None


def test_a_tired_anchor_does_not_get_a_route_that_needs_a_dash():
    book = SkillBook()
    book.add(route("dashy"))
    retry = LocalRetry(book)
    retry.note(outcome("MISSED", buttons=("jump",)))

    assert retry.offer(anchor(dashes=0)) is None


def test_the_retry_contract_pins_the_anchor_and_the_known_landing():
    retry = LocalRetry(SkillBook())
    retry.book.add(route("only"))

    step = retry.step(anchor(), retry.book.entries[0])

    assert step.contract.pre.x == (98.0, 102.0)
    assert step.contract.ok.x == (114.0, 126.0)
    assert step.contract.abort.timeout_frames == 12 + retry.slack
