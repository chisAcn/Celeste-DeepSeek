"""The component that actually touches the game.

Only the executor holds the bridge client. The planner receives snapshots and
reports as plain data, so "one controller at a time" is guaranteed by the
object graph rather than by discipline.

Execution is real time: the mod applies one input set per Level.Update while
the client polls. That makes frame-level abort possible without splitting the
sequence, which matters because releasing input between chunks would ruin a
jump arc.
"""

import asyncio
import time

from agent.agents.messages import (
    StepContract,
    StepReport,
    TraceRow,
    first_action,
    within,
)
from agent.protocol import ActionSequence, ExecutionResult, GameState

MOVING = frozenset({"left", "right", "up", "jump", "dash"})


def _point(state: GameState) -> tuple[float, float] | None:
    player = state.player
    return None if player is None else (player.x, player.y)


class ExecutorAgent:
    """Runs one step at a time and reports why it ended."""

    def __init__(self, client, registry, *, poll: float = 0.012, trace_every: int = 3):
        self.client = client
        self.registry = registry
        self.poll = poll
        self.trace_every = trace_every

    async def observe(self) -> GameState:
        return GameState.model_validate(await self.client.call("get_state"))

    async def call(self, method: str, **params):
        """Control-plane passthrough: pause, playability, geometry.

        Input stays inside this class -- ``run`` is the only thing that sends
        frames, which is what makes "one controller at a time" true.
        """
        return await self.client.call(method, **params)

    def precondition_reason(self, contract: StepContract, state: GameState) -> str | None:
        pre = contract.pre
        player = state.player
        if pre.room is not None and state.room.name != pre.room:
            return "room_changed"
        if player is None:
            return "player_unavailable"
        if player.dead:
            return "player_dead"
        if pre.on_ground is not None and player.on_ground != pre.on_ground:
            return "ground_state_changed"
        if pre.min_dashes is not None and player.dashes < pre.min_dashes:
            return "dash_count_changed"
        if not within(player.x, pre.x) or not within(player.y, pre.y):
            return "position_changed"
        return None

    def success_reason(self, contract: StepContract, state: GameState) -> str | None:
        ok = contract.ok
        player = state.player
        if player is None:
            return "player_unavailable"
        if player.dead:
            return "player_dead"
        if ok.on_ground is not None and player.on_ground != ok.on_ground:
            return "not_grounded"
        if ok.min_dashes is not None and player.dashes < ok.min_dashes:
            return "no_dash"
        if not within(player.x, ok.x):
            return "x_out_of_band"
        if not within(player.y, ok.y):
            return "y_out_of_band"
        return None

    def _watch(self, contract: StepContract, state: GameState, frames: int, stall: int) -> str | None:
        abort = contract.abort
        player = state.player
        if abort.dead and player is not None and player.dead:
            return "dead"
        if abort.timeout_frames is not None and frames >= abort.timeout_frames:
            return "timeout"
        if (player is not None and contract.ok.x is not None
                and abort.diverged_px is not None):
            low, high = contract.ok.x
            if player.x < low - abort.diverged_px or player.x > high + abort.diverged_px:
                return "diverged"
        if stall >= abort.stall_frames:
            return "stalled"
        return None

    @staticmethod
    def _row(frames: int, state: GameState) -> TraceRow:
        player = state.player
        return TraceRow(frame=frames, x=player.x, y=player.y, vx=player.vx,
                        vy=player.vy, on_ground=player.on_ground, dashes=player.dashes)

    def _sample(self, sequence: ActionSequence, trace: list[TraceRow], state: GameState,
                frames: int, still_since: int,
                last: tuple[float, float] | None) -> tuple[int, int, tuple[float, float] | None]:
        """Track stillness in frames, and only while the input intends motion.

        Crouching or grabbing on the spot is not a stall, so any action whose
        buttons are all non-movement resets the clock.
        """
        player = state.player
        if player is None:
            return 0, frames, last
        idle = not (set(first_action(sequence, frames)) & MOVING)
        moved = last is not None and max(
            abs(player.x - last[0]), abs(player.y - last[1])) >= 0.5
        if idle or moved:
            still_since = frames
        if frames % self.trace_every == 0 and len(trace) < 240:
            trace.append(self._row(frames, state))
        return frames - still_since, still_since, (player.x, player.y)

    async def _final(self, execution_id: str) -> ExecutionResult | None:
        for _ in range(25):
            try:
                payload = await self.client.call("get_execution", execution_id=execution_id)
            except RuntimeError:
                return None
            if payload.get("status") != "running":
                return ExecutionResult.model_validate(payload)
            await asyncio.sleep(0.02)
        return None

    async def run(self, sequence: ActionSequence, contract: StepContract) -> StepReport:
        planned = sum(action.frames for action in sequence.actions)
        start = await self.observe()
        rejection = self.precondition_reason(contract, start)
        if rejection is not None:
            return StepReport(status="REJECTED", reason=rejection,
                              execution_id=sequence.execution_id,
                              planned_frames=planned, executed_frames=0,
                              contract=contract, start=start)

        last = _point(start)
        still_since = 0
        trace: list[TraceRow] = []
        result: ExecutionResult | None = None
        stopped: str | None = None
        stopped_at: int | None = None

        first = await self.client.call("execute_frames", **sequence.model_dump())
        if first.get("status") == "running":
            deadline = time.monotonic() + max(5.0, planned / 20.0)
            while True:
                state = await self.observe()
                status = await self.client.call(
                    "get_execution", execution_id=sequence.execution_id)
                frames = int(status.get("executed_frames") or 0)
                stall, still_since, last = self._sample(
                    sequence, trace, state, frames, still_since, last)
                if status.get("status") != "running":
                    result = ExecutionResult.model_validate(status)
                    break
                verdict = self._watch(contract, state, frames, stall)
                if verdict is not None:
                    stopped = verdict
                    stopped_at = frames
                elif time.monotonic() > deadline:
                    stopped = "deadline"
                    stopped_at = frames
                if stopped is not None:
                    await self.client.call("stop")
                    result = await self._final(sequence.execution_id)
                    break
                await asyncio.sleep(self.poll)
        else:
            result = ExecutionResult.model_validate(first)

        if result is not None:
            self.registry.trajectory.append(result.model_dump())
        end = result.after if result is not None else await self.observe()
        executed = result.executed_frames if result is not None else 0

        if stopped is not None:
            reason = stopped
            status = "DIED" if end.player is not None and end.player.dead else "ABORTED"
        elif result is not None and result.status == "interrupted":
            died = end.player is not None and end.player.dead
            reason = "dead" if died else "bridge_interrupted"
            status = "DIED" if died else "INTERRUPTED"
        else:
            failure = self.success_reason(contract, end)
            reason = failure
            status = "SUCCEEDED" if failure is None else "UNSATISFIED"

        # The landing frame is the one a route is judged on, and it arrives
        # between polls, so it is appended rather than sampled.
        if end.player is not None and (not trace or trace[-1].frame != executed):
            trace.append(self._row(executed, end))
            del trace[240:]

        return StepReport(status=status, reason=reason,
                          execution_id=sequence.execution_id,
                          planned_frames=planned, executed_frames=executed,
                          at_frame=stopped_at if status in {"ABORTED", "DIED"} else None,
                          contract=contract, start=start, end=end, trace=trace)
