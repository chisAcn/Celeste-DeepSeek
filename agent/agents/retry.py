"""Recover from a failed step without spending a model call.

A miss does not always mean the plan was wrong about the room. It can mean the
step started a pixel off, or that a room transition cut it short, or that the
model's arc was fine but the body slid. Those have a cheaper answer than another
round trip: send a route that already worked from here, or send the same one
again when the world, not the route, is what failed.

This is deliberately not a planner. It can only pick a route out of the book,
so it can never invent an arc that has not already run on this machine. When
the book has nothing left to offer it returns ``None`` and the model is asked,
which keeps the cheap path from turning into a closed loop of the same failure.

The budget is per failure episode: consecutive misses without a landing. One
landing resets it, so a room that is being explored normally is not penalised
for the misses that exploration costs.
"""

from dataclasses import dataclass, field

from agent.agents.messages import (
    Abort,
    Anchor,
    PlannedStep,
    Precondition,
    StepContract,
    Success,
)
from agent.agents.skills import Replay, SkillBook, action_key


@dataclass
class LocalRetry:
    """Second attempts that cost frames instead of tokens."""

    book: SkillBook
    radius: float = 8.0
    limit: int = 2
    slack: int = 30
    tolerance: float = 1.5
    position_slack: float = 2.0
    budget: int = 2
    failures: int = 0
    retries: int = 0
    tried: set = field(default_factory=set)

    @property
    def recovering(self) -> bool:
        """Whether the last outcome was a miss, i.e. replay must be picky."""
        return self.failures > 0

    def reset(self) -> None:
        self.failures = 0
        self.budget = self.limit
        self.tried.clear()

    def note(self, outcome) -> None:
        """Fold the verdict in; a landing ends the episode."""
        if outcome.verdict == "LANDED":
            self.reset()
            return
        self.failures += 1
        # Whatever was just sent is not a candidate any more, whether it came
        # from the book or from the model. Keyed by actions because the report's
        # start can be a pixel away from the route's recorded one.
        if outcome.actions:
            self.tried.add(action_key(outcome.actions))

    def offer(self, anchor: Anchor) -> PlannedStep | None:
        """The next route to try from this anchor, or None to ask the model."""
        if not self.recovering or self.budget <= 0:
            return None
        state = anchor.state
        player = state.player
        if player is None or player.dead or not player.on_ground:
            return None
        candidates = []
        for entry in self.book.entries:
            if entry.room != state.room.name or entry.streak >= self.book.max_streak:
                continue
            if player.dashes < entry.dashes:
                continue
            if action_key(entry.actions) in self.tried:
                continue
            # An arc is what makes a wider start radius safe: the bridge stops
            # at the first frame that does not fit, so a route recorded two
            # ledges over costs a couple of frames rather than a death.
            reach = self.radius if entry.trace else self.book.match_px
            if entry.start_distance(state) > reach:
                continue
            candidates.append(entry)
        if not candidates:
            return None
        # Prefer the route that has worked most often, then the closest start.
        entry = max(candidates, key=lambda item: (item.hits, -item.start_distance(state)))
        self.tried.add(action_key(entry.actions))
        self.budget -= 1
        self.retries += 1
        return self.step(anchor, entry)

    def step(self, anchor: Anchor, entry: Replay) -> PlannedStep:
        ok = Success()
        if entry.end_x is not None:
            ok = Success(
                x=(entry.end_x - 6, entry.end_x + 6),
                y=None if entry.end_y is None else (entry.end_y - 6, entry.end_y + 6))
        contract = StepContract(
            pre=Precondition.from_state(anchor.state, self.position_slack),
            ok=ok, abort=Abort(timeout_frames=entry.frames + self.slack))
        return PlannedStep(anchor_id=anchor.id, actions=list(entry.actions),
                           contract=contract, goal=f"retry {entry.name}",
                           reason="the last step missed; this route starts within reach",
                           expect=entry.expected_from(anchor.state),
                           tolerance=self.tolerance)
