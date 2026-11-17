"""Replayable routes: what a verified macro becomes when the anchor lines up.

The planner is expensive and improvisation is what kills runs -- the model sees
a room it has never walked and guesses. A route that already worked from a
specific grounded spot is a stronger prior than any prompt, so every step that
lands is kept as start position + actions + landing. When a later anchor sits on
that same spot, the route is replayed instead of asking the model: no latency,
no drift, and no chance of a different answer to an identical question.

Two sources feed the book. Routes loaded from skill memory were verified by
replay before they were recorded. Routes promoted in-session have landed once,
which is weaker evidence, so a route that misses twice in a row leaves rotation
instead of being replayed a third time.

Matching is deliberately tight. A route is a promise about physics, and 2px is
already generous for a grounded body; a wider tolerance would replay an arc
that no longer fits the ledge it was recorded on.
"""

import math
from dataclasses import dataclass, field

from agent.protocol import FrameAction, GameState


def action_key(actions) -> tuple:
    """Identity of an action list, for matching a report back to its route."""
    return tuple((tuple(action.buttons), action.frames) for action in actions)


def _key(room: str, x: float, y: float, actions) -> tuple:
    return (room, round(x, 1), round(y, 1), action_key(actions))


@dataclass
class Replay:
    """One route that is worth sending again from the same spot."""

    name: str
    room: str
    x: float
    y: float
    dashes: int
    actions: list[FrameAction]
    end_x: float | None = None
    end_y: float | None = None
    hits: int = 0
    misses: int = 0
    streak: int = 0
    origin: str = "session"

    @property
    def frames(self) -> int:
        return sum(action.frames for action in self.actions)

    @property
    def key(self) -> tuple:
        return _key(self.room, self.x, self.y, self.actions)

    def start_distance(self, state: GameState) -> float:
        player = state.player
        return math.inf if player is None else max(abs(player.x - self.x),
                                                   abs(player.y - self.y))

    def hint(self) -> dict:
        row = {
            "name": self.name,
            "start": [round(self.x, 1), round(self.y, 1)],
            "frames": self.frames,
            "hits": self.hits,
            "misses": self.misses,
            "origin": self.origin,
            "actions": [action.model_dump() for action in self.actions],
        }
        if self.end_x is not None:
            row["end"] = [round(self.end_x, 1),
                          None if self.end_y is None else round(self.end_y, 1)]
        return row

    @classmethod
    def from_skill(cls, skill) -> "Replay | None":
        """Adapt a skill-memory row; verified routes are the only ones loaded."""
        start = skill.verified_start
        if start is None or start.player is None:
            return None
        end = skill.verified_end
        return cls(name=skill.name, room=skill.room,
                   x=start.player.x, y=start.player.y,
                   dashes=skill.min_dashes,
                   actions=list(skill.sequence.actions),
                   end_x=None if end is None or end.player is None else end.player.x,
                   end_y=None if end is None or end.player is None else end.player.y,
                   hits=skill.successes, misses=len(skill.failures),
                   origin="memory")


@dataclass
class SkillBook:
    """The routes this session is allowed to replay, keyed by where they start."""

    match_px: float = 2.0
    max_streak: int = 2
    limit: int = 200
    entries: list[Replay] = field(default_factory=list)
    _index: dict = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.entries)

    def add(self, entry: Replay) -> Replay | None:
        if entry.key in self._index:
            return None
        if not entry.actions:
            return None
        self.entries.append(entry)
        self._index[entry.key] = entry
        if len(self.entries) > self.limit:
            dropped = self.entries.pop(0)
            self._index.pop(dropped.key, None)
        return entry

    def match(self, state: GameState) -> Replay | None:
        """The closest route whose start this anchor still stands on."""
        player = state.player
        if player is None or player.dead or not player.on_ground:
            return None
        best: tuple[float, Replay] | None = None
        for entry in self.entries:
            if entry.streak >= self.max_streak or entry.room != state.room.name:
                continue
            if player.dashes < entry.dashes:
                continue
            gap = entry.start_distance(state)
            if gap <= self.match_px and (best is None or gap < best[0]):
                best = (gap, entry)
        return None if best is None else best[1]

    def note(self, outcome) -> str | None:
        """Fold a finished step back in; returns the route that changed."""
        report = outcome.report
        start = None if report is None else report.start
        if start is None or start.player is None:
            return None
        actions = list(outcome.actions or (report.actions if report else []))
        entry = self._index.get(_key(start.room.name, start.player.x, start.player.y, actions))
        landed = outcome.verdict == "LANDED"

        if entry is not None:
            if landed:
                entry.hits += 1
                entry.streak = 0
                settled = outcome.settled or report.end
                if settled is not None and settled.player is not None:
                    entry.end_x = settled.player.x
                    entry.end_y = settled.player.y
            else:
                entry.misses += 1
                entry.streak += 1
            return entry.name

        if not landed or not actions:
            return None
        settled = outcome.settled or report.end
        if settled is None or settled.player is None or not settled.player.on_ground:
            return None
        promoted = self.add(Replay(name=f"learned-{len(self.entries) + 1}",
                                   room=start.room.name,
                                   x=start.player.x, y=start.player.y,
                                   dashes=start.player.dashes,
                                   actions=actions,
                                   end_x=settled.player.x, end_y=settled.player.y))
        return None if promoted is None else promoted.name

    def describe(self, room: str, limit: int = 6) -> list[dict]:
        rows = [entry for entry in self.entries
                if entry.room == room and entry.streak < self.max_streak]
        rows.sort(key=lambda entry: (-entry.hits, entry.name))
        return [entry.hint() for entry in rows[:limit]]


def landed_here(entry: Replay, state: GameState, slack: float = 6.0) -> bool:
    """Whether a settled state is close enough to the route's recorded landing."""
    if entry.end_x is None or state.player is None:
        return True
    return abs(state.player.x - entry.end_x) <= slack
