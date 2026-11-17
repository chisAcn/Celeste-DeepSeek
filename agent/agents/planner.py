"""The planning agent, in its own task.

It never touches the bridge. Anchors arrive as plain data (state, room geometry,
platform sample), plans leave as plain data, and outcomes come back the same
way. That is what makes "one controller at a time" structural: the planner can
spend thirty seconds inside an HTTP request without blocking a frame, and the
executor can abort a step while the model is mid-sentence.

A plan is always bound to the anchor it was built on. If the anchor is gone by
the time the plan arrives, the plan is dropped -- not executed and judged
afterwards. Dropping is free; a wrong first frame is a death.
"""

import asyncio
import math
import time

from agent.agents.messages import (
    Anchor,
    PlanFailure,
    PlannedStep,
    StepContract,
    StepOutcome,
)
from agent.knowledge import MOVEMENT_REFERENCE
from agent.protocol import ActionSequence, GameState
from agent.tas_training import action_key

PLANNING_GOAL = (
    "Use grounded intermediate landings. Check recent settled outcomes "
    "before repeating a route. An airborne x coordinate does not "
    "establish a landing."
)


def skill_hint(skill, state):
    """Compact planner-facing view of a replay-verified room route."""
    start, end = skill.verified_start, skill.verified_end
    hint = {
        "name": skill.name,
        "frames": skill.frames,
        "successes": skill.successes,
        "failures": len(skill.failures),
        "actions": [action.model_dump() for action in skill.sequence.actions],
    }
    if start and start.player:
        hint["start"] = {"x": start.player.x, "y": start.player.y}
        if state.player:
            hint["start_distance"] = round(math.hypot(
                start.player.x - state.player.x, start.player.y - state.player.y), 1)
    if end and end.player:
        hint["end"] = {"x": end.player.x, "y": end.player.y,
                       "on_ground": end.player.on_ground}
    return hint


class PlannerAgent:
    """Plans from anchors; never blocks or reads the game."""

    def __init__(self, plan_fn, *, skills=None, exit_room=None, success_room=None,
                 action_prior=None, history: int = 3, timeout: float = 60.0,
                 slack: int = 30, position_slack: float = 2.0,
                 frozen_slack: float = 8.0):
        self.plan_fn = plan_fn
        self.skills = list(skills or [])
        self.exit_room = exit_room
        self.success_room = success_room
        self.action_prior = action_prior
        self.history_limit = history
        self.timeout = timeout
        self.slack = slack
        self.position_slack = position_slack
        self.frozen_slack = frozen_slack
        self.history: list[dict] = []
        self.previous_action: str | None = None
        self.plans = 0
        self.failures = 0
        self.last_error: str | None = None

    # -- context ---------------------------------------------------------

    def context(self, anchor: Anchor) -> dict:
        state = anchor.state
        context = {
            "state": state.model_dump(),
            "history": self.history[-self.history_limit:],
            "movement_reference": MOVEMENT_REFERENCE,
            "anchor": {
                "still_for": round(anchor.still_for, 2),
                "note": ("The world is holding still. This snapshot is what the "
                         "first frame of your plan will be applied to."),
            },
        }
        if anchor.frozen:
            context["anchor"]["note"] = (
                "The game is paused on this snapshot, so it is exact, but it resumes "
                "before your plan runs: anything moving in the room may drift by a few "
                "pixels. Plan a short step and land somewhere that absorbs that.")
        if self.exit_room:
            context["exit_room_goal"] = self.exit_room
            if self.success_room:
                context["success_room_goal"] = self.success_room
            context["planning_goal"] = PLANNING_GOAL
        room_skills = [skill for skill in self.skills if skill.room == state.room.name]
        if room_skills:
            context["verified_room_skills"] = [
                skill_hint(skill, state) for skill in room_skills]
            context["skill_guidance"] = (
                "verified_room_skills are replay-verified action sequences recorded in "
                "this room. When your grounded position matches a skill's start "
                "(small start_distance), prefer replaying its actions exactly instead "
                "of improvising. Chain skills through their endpoint positions.")
        if anchor.platforms:
            context["platforms"] = anchor.platforms
        geometry = anchor.geometry or {}
        if geometry.get("exits"):
            context["room_geometry"] = geometry
            context["room_geometry_guidance"] = (
                "room_geometry.bounds is the current room rectangle and "
                "room_geometry.exits lists boundary segments that open into a "
                "neighbouring room. Each segment gives the side, the target room "
                "and the axis range (from..to) of the doorway, measured in world "
                "coordinates. Route the player through one of those doorway "
                "ranges; a segment without a doorway on the target side does not "
                "lead out.")
        if self.action_prior is not None and state.player is not None:
            context["tas_action_hints"] = [
                hint.model_dump()
                for hint in self.action_prior.suggest(self.previous_action,
                                                      state.player.dashes)]
        return context

    # -- contract --------------------------------------------------------

    def contract(self, anchor: Anchor, plan) -> StepContract:
        """Bind the plan to the anchor, not to whatever the model wrote.

        The planner owns the success band and the frame budget; the precondition
        is always the anchor state, because that is the only thing the executor
        can actually promise.
        """
        low = getattr(plan, "expected_x_min", None)
        high = getattr(plan, "expected_x_max", None)
        expected = None if low is None or high is None else (low, high)
        return StepContract.for_plan(
            plan.actions, expected_x=expected, planned=anchor.state, slack=self.slack,
            position_slack=self.frozen_slack if anchor.frozen else self.position_slack)

    # -- bookkeeping -----------------------------------------------------

    def record(self, outcome: StepOutcome):
        """Keep a compact trace for the next prompt."""
        report = outcome.report
        row = {
            "actions": [action.model_dump() for action in outcome.actions],
            "verdict": outcome.verdict,
            "from": None if report is None else _point(report.start),
            "to": None if report is None else _point(report.end),
            "settled": _point(outcome.settled),
            "detail": outcome.detail,
        }
        self.history.append(row)
        del self.history[:-24]
        if outcome.actions:
            self.previous_action = action_key(outcome.actions[-1].buttons)

    def drain(self, outcomes: asyncio.Queue) -> None:
        while True:
            try:
                self.record(outcomes.get_nowait())
            except asyncio.QueueEmpty:
                return

    # -- the task --------------------------------------------------------

    async def serve(self, anchors: asyncio.Queue, plans: asyncio.Queue,
                    outcomes: asyncio.Queue, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                anchor = await asyncio.wait_for(anchors.get(), 0.2)
            except asyncio.TimeoutError:
                self.drain(outcomes)
                continue
            self.drain(outcomes)
            started = time.monotonic()
            try:
                plan = await asyncio.wait_for(self.plan_fn(self.context(anchor)),
                                              self.timeout + 15)
            except asyncio.TimeoutError:
                await _latest(plans, PlanFailure(anchor_id=anchor.id, kind="timeout",
                                                detail="model call exceeded the deadline"))
                continue
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - a bad plan is data, not a crash
                self.failures += 1
                self.last_error = str(error)[:200]
                await _latest(plans, PlanFailure(anchor_id=anchor.id,
                                                detail=self.last_error))
                continue
            latency = time.monotonic() - started
            try:
                step = PlannedStep(anchor_id=anchor.id, actions=plan.actions,
                                   goal=getattr(plan, "goal", ""),
                                   reason=getattr(plan, "reason", ""),
                                   latency=round(latency, 3),
                                   contract=self.contract(anchor, plan))
                ActionSequence(execution_id=f"validate-{anchor.id}",
                               actions=step.actions)
            except ValueError as error:
                self.failures += 1
                self.last_error = f"invalid plan: {error}"
                await _latest(plans, PlanFailure(anchor_id=anchor.id, kind="invalid",
                                                detail=self.last_error))
                continue
            self.plans += 1
            await _latest(plans, step)


def _point(state: GameState | None) -> list[float] | None:
    if state is None or state.player is None:
        return None
    return [round(state.player.x, 1), round(state.player.y, 1)]


async def _latest(queue: asyncio.Queue, item) -> None:
    """Put, dropping whatever was waiting: only the newest plan is worth running."""
    if queue.full():
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
    await queue.put(item)
