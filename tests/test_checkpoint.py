import pytest

from agent.checkpoint import (
    Checkpoint,
    deepest_safe,
    safe_index,
    sample_stance,
    truncate,
)
from agent.protocol import FrameAction


def sample(x=0.0, y=0.0, *, ground=False, state="StNormal", dead=False):
    return {
        "player": {"x": x, "y": y, "on_ground": ground, "state": state, "dead": dead}
    }


def trace(*samples):
    return list(samples)


def test_stance_reads_grip_and_air_separately():
    assert sample_stance(sample(ground=True)) == "ground"
    assert sample_stance(sample(state="StClimb")) == "climb"
    assert sample_stance(sample()) == "air"
    assert sample_stance(sample(dead=True)) == "dead"
    assert sample_stance({"player": None}) == "dead"


def test_safe_index_takes_the_deepest_standable_frame():
    rows = trace(sample(ground=True), sample(), sample(ground=True), sample())
    assert safe_index(rows) == 2


def test_safe_index_only_looks_deeper_than_the_current_root():
    rows = trace(sample(ground=True), sample(), sample(ground=True), sample())
    assert safe_index(rows, after=0) == 2
    # The root itself is not a rollback, and nothing below it is standable.
    assert safe_index(rows, after=2) is None


def test_safe_index_ignores_a_death_on_the_ground():
    """Landing and dying on the same frame is not a start."""
    assert safe_index(trace(sample(ground=True), sample(ground=True, dead=True))) == 0


def test_safe_index_reports_nothing_when_the_whole_trace_is_airborne():
    assert safe_index(trace(sample(), sample(), sample())) is None


def test_deepest_safe_carries_the_coordinates_it_was_taken_at():
    rows = trace(sample(), sample(12.5, -30.0, state="StClimb"))
    assert deepest_safe(rows) == Checkpoint(frame=1, x=12.5, y=-30.0, stance="climb")


def test_deepest_safe_is_none_without_a_landing():
    assert deepest_safe(trace(sample(), sample())) is None


def test_truncate_cuts_inside_a_chunk_without_changing_the_buttons():
    actions = [
        FrameAction(buttons=["right"], frames=4),
        FrameAction(buttons=["right", "jump"], frames=6),
    ]
    cut = truncate(actions, 6)
    assert [(a.buttons, a.frames) for a in cut] == [
        (["right"], 4),
        (["right", "jump"], 2),
    ]


def test_truncate_keeps_the_frame_count_it_promised():
    actions = [
        FrameAction(buttons=["right"], frames=4),
        FrameAction(buttons=["up", "dash"], frames=1),
        FrameAction(buttons=["up"], frames=9),
    ]
    assert sum(a.frames for a in truncate(actions, 8)) == 8
    assert sum(a.frames for a in truncate(actions, 14)) == 14


def test_truncate_does_not_mutate_the_input():
    actions = [FrameAction(buttons=["right"], frames=4)]
    truncate(actions, 2)
    assert actions[0].frames == 4


def test_truncate_refuses_a_frame_count_the_run_never_reached():
    actions = [FrameAction(buttons=["right"], frames=4)]
    with pytest.raises(ValueError):
        truncate(actions, 5)
    with pytest.raises(ValueError):
        truncate(actions, 0)
