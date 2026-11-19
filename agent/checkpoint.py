"""Roll a failed attempt back to the last frame she could stand on.

A search that restarts every branch from the room entrance pays for the same
opening twice: once to learn it, and again for every candidate that dies after
it. A branch that lands, walks, and then falls into spikes has already proved a
deeper start -- the landing -- and throwing that away is what makes a room feel
unsearchable.

These helpers answer the two questions such a rollback needs, and nothing else:
*which frame in this trace was she standing on something* (the ground, or a
wall she had a grip on), and *how do I cut an action list exactly there*.
Neither touches the bridge. Restoring the slot, spending the budget and
deciding how many rollbacks are worth it stay with the caller.
"""

from dataclasses import dataclass

from agent.protocol import FrameAction

# A wall grip is a landing: she can start from it, and the bridge can hold it.
SAFE_STANCES = ("ground", "climb")


@dataclass(frozen=True)
class Checkpoint:
    """A frame that is safe to plan from, in the coordinates it was taken at."""

    frame: int
    x: float
    y: float
    stance: str

    def key(self) -> tuple:
        return (self.frame, round(self.x), round(self.y), self.stance)


def sample_stance(sample: dict) -> str:
    """Stance of one bridge sample, treating a death as its own answer."""
    player = sample.get("player")
    if player is None or player.get("dead"):
        return "dead"
    if player.get("state") == "StClimb":
        return "climb"
    return "ground" if player.get("on_ground") else "air"


def safe_index(trace: list[dict], *, after: int = -1) -> int | None:
    """Deepest index in ``trace`` she could stand on, or None.

    ``trace`` is ``[before, *checkpoints]``, so an index equals the number of
    frames executed to reach it. ``after`` excludes frames at or above it --
    the current root, which is not a rollback.
    """
    for index in range(len(trace) - 1, after, -1):
        if sample_stance(trace[index]) in SAFE_STANCES:
            return index
    return None


def deepest_safe(trace: list[dict], *, after: int = -1) -> Checkpoint | None:
    index = safe_index(trace, after=after)
    if index is None:
        return None
    player = trace[index]["player"]
    return Checkpoint(
        frame=index,
        x=float(player["x"]),
        y=float(player["y"]),
        stance=sample_stance(trace[index]),
    )


def truncate(actions: list[FrameAction], frames: int) -> list[FrameAction]:
    """Cut ``actions`` so it lasts exactly ``frames`` frames.

    A cut inside a chunk keeps the buttons and shortens the count: the prefix
    has to be the same inputs, or the frame it replays to is not the frame the
    checkpoint was taken at.
    """
    if frames < 1:
        raise ValueError("a checkpoint needs at least one frame")
    cut: list[FrameAction] = []
    used = 0
    for action in actions:
        if used >= frames:
            break
        take = min(action.frames, frames - used)
        cut.append(
            action
            if take == action.frames
            else action.model_copy(update={"frames": take})
        )
        used += take
    if used != frames:
        raise ValueError(f"{frames} frames requested, {used} available")
    return cut
