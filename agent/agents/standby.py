"""What the executor does while the planner is thinking.

The old loop paused the game so its snapshot could not go stale. Pausing works,
but it freezes the whole room at every landing, and it hands the planner a
picture the game will not agree with the moment it resumes.

Standby is the cheaper answer. After a job finishes the mod hands input back, so
with nobody at the keyboard a resting Madeline just stands there: the room keeps
running, the clock keeps ticking, and the state does not move. A state that does
not move cannot go stale, which is exactly the promise the planner needs.

Three stances, and only the first one produces an anchor:

``ANCHORED``   on her feet or hanging on a wall, still for ``still_for`` seconds
``SETTLING``   airborne or sliding -- physics has not finished with her yet
``BLOCKED``    dead, or out of control -- the room has to sort itself out first

Standing still is verified by watching, not by assuming: two samples that differ
by less than ``drift_px`` while on a footing. That is what catches a moving
platform quietly carrying her away from under the plan.
"""

from typing import Literal

from agent.agents.messages import drift
from agent.protocol import GameState

Stance = Literal["ANCHORED", "SETTLING", "BLOCKED"]

REST_SPEED = 0.5  # px/s; below this she is not moving, only breathing


class Standby:
    """Tracks whether the world is holding still. Never touches the game."""

    def __init__(self, *, still_for: float = 0.15, drift_px: float = 1.5):
        self.still_for = still_for
        self.drift_px = drift_px
        self._previous: GameState | None = None
        self._still_since: float | None = None

    def reset(self):
        self._previous = None
        self._still_since = None

    @staticmethod
    def resting(state: GameState) -> bool:
        """Still, and on something -- the floor or a wall.

        A wall grab is a footing like the floor is: her hands hold her exactly
        where the last frame left her, and the next plan can start from there.
        The grip has to survive the job for this to be observable at all, which
        is what ``hold_after`` does on the bridge side. A bridge too old to name
        the state machine reports such a landing as airborne, so nothing anchors
        there and the old behaviour is preserved.
        """
        player = state.player
        return bool(player is not None and not player.dead
                    and player.stance() != "air"
                    and abs(player.vx) < REST_SPEED and abs(player.vy) < REST_SPEED)

    def observe(self, state: GameState, now: float) -> Stance:
        player = state.player
        if player is None or player.dead:
            self.reset()
            return "BLOCKED"
        if not self.resting(state):
            self._previous = state
            self._still_since = None
            return "SETTLING"
        if self._still_since is None:
            self._still_since = now
        elif self._previous is not None and drift(state, self._previous) > self.drift_px:
            # Grounded but moving: a lift is carrying her. Not an anchor.
            self._still_since = now
            self._previous = state
            return "SETTLING"
        self._previous = state
        return "ANCHORED" if now - self._still_since >= self.still_for else "SETTLING"

    def stable_for(self, now: float) -> float:
        return 0.0 if self._still_since is None else max(0.0, now - self._still_since)
