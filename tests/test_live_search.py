"""The search must restart from where she stood, not from the room entrance.

A fake bridge keeps this deterministic: one dimension, one death line, and a
save slot that can be inspected. What is being checked is the rollback rule,
not the game.
"""

import asyncio

import pytest

from agent import live_search


class World:
    """One axis, a death line, and a frame counter that never rewinds."""

    def __init__(self, x=0.0, die_at=6.0):
        self.x = float(x)
        self.die_at = die_at
        self.frames = 0

    def copy(self):
        clone = World(self.x, self.die_at)
        clone.frames = self.frames
        return clone

    @property
    def dead(self):
        return self.x >= self.die_at


def sample(world):
    return {
        "player": {
            "x": world.x,
            "y": 0.0,
            "vx": 0.0,
            "vy": 0.0,
            "on_ground": not world.dead,
            "dashes": 1,
            "stamina": 110.0,
            "dead": world.dead,
            "state": "StNormal",
        },
        "room": {"name": "fake", "completed": False},
        "platform_sample": {"total": 0, "platforms": []},
        "frame": world.frames,
    }


class FakeSlot:
    def __init__(self):
        self.world = World()  # what save_state holds
        self.live = World()  # what the game is showing
        self.starts = []


class FakeClient:
    def __init__(self, slot):
        self.slot = slot

    async def call(self, method, **params):
        if method == "ping":
            return {"restore_and_execute": True, "tas_active": False}
        if method == "get_state":
            return sample(self.slot.live)
        if method == "save_state":
            self.slot.world = self.slot.live.copy()
            return {"accepted": True}
        if method == "load_state":
            return {"accepted": True}
        if method == "clear_state":
            return {"saved": False}
        raise RuntimeError(method)


class FakeTools:
    """Restores the slot, then applies the action list to a copy of it."""

    def __init__(self, slot):
        self.slot = slot

    async def restore_and_execute(
        self, execution_id, trace_frames, trace_platforms, actions
    ):
        world = self.slot.world.copy()
        self.slot.starts.append(world.x)
        before = sample(world)
        checkpoints = []
        for action in actions:
            for _ in range(action["frames"]):
                if not world.dead:
                    world.frames += 1
                    if "right" in action["buttons"]:
                        world.x += 1.0
                checkpoints.append(sample(world))
        self.slot.live = world
        return {
            "status": "completed",
            "executed_frames": len(checkpoints),
            "before": before,
            "after": sample(world),
            "checkpoints": checkpoints,
            "planned_frames": len(checkpoints),
        }


@pytest.fixture
def slot(monkeypatch):
    slot = FakeSlot()
    monkeypatch.setattr(live_search, "ToolRegistry", lambda client: FakeTools(slot))
    return slot


def run_search(slot, **overrides):
    options = dict(
        dx=10.0,
        dy=0.0,
        radius=1.0,
        width=1,
        depth=1,
        budget=5,
        frames=6,
        own_slot=False,
    )
    options.update(overrides)
    return asyncio.run(live_search.search(FakeClient(slot), **options))


def test_a_death_moves_the_start_to_the_last_frame_she_stood_on(slot):
    report = run_search(slot)
    assert report["rollbacks"] == 1
    assert report["root_frames"] == 5  # died on the 6th frame, at x=6
    assert slot.world.x == 5.0  # the slot now holds the checkpoint
    assert slot.starts[0] == 0.0  # the first attempts ran from the entrance
    assert 0.0 in slot.starts[1:]
    assert slot.starts[-1] == 5.0  # after the rollback, nobody did


def test_without_the_rule_every_attempt_restarts_from_the_entrance(slot):
    report = run_search(slot, checkpoint=False)
    assert report["rollbacks"] == 0
    assert set(slot.starts) == {0.0}


def test_the_rule_keeps_its_budget_and_stops_after_max_checkpoints(slot):
    report = run_search(slot, budget=6, max_checkpoints=1)
    assert report["rollbacks"] <= 1
    assert report["evaluations"] <= 6


def test_a_candidate_that_never_lands_is_not_a_checkpoint(slot):
    slot.world.die_at = 0.5  # dead before the first frame ends
    report = run_search(slot, budget=2)
    assert report["rollbacks"] == 0
    assert slot.world.x == 0.0
