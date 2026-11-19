"""Contract fixture only: not a Celeste physics simulation."""
import json

from agent.protocol import (
    ActionSequence,
    Deviation,
    ExecutionResult,
    GameState,
    PlatformSample,
    Request,
)


class MockBridge:
    def __init__(self):
        self.state = GameState()
        self.results = {}
        self.held = set()
        self.paused = False

    def dispatch(self, request):
        method, params = request.method, request.params
        if method == "ping":
            return {"backend": "mock", "tas": False, "pause_control": True}
        if method == "pause_game":
            self.paused = True
            return {"paused": True, "frame": self.state.frame}
        if method == "resume_game":
            self.paused = False
            return {"paused": False, "frame": self.state.frame}
        if method == "get_playability":
            return {"playable": not self.paused, "frame": self.state.frame}
        if method == "get_state":
            return self.state.model_dump()
        if method == "get_room_info":
            return {
                "room": self.state.room.name, "frame": self.state.frame,
                "bounds": {"x": 0, "y": 0, "width": 320, "height": 184},
                "exits": [{"side": "right", "target": "mock-next",
                           "axis": "y", "from": 0, "to": 184}],
            }
        if method == "reset_room":
            self.state = GameState(frame=self.state.frame)
            self.held.clear()
            return self.state.model_dump()
        if method == "stop":
            self.held.clear()
            return {"stopped": True}
        if method == "get_execution":
            return self.results[params["execution_id"]]
        if method != "execute_frames":
            raise LookupError("unknown method")
        seq = ActionSequence.model_validate(params)
        if seq.execution_id in self.results:
            raise ValueError("duplicate execution ID")
        before = self.state.model_copy(deep=True)
        count = 0
        checkpoints = []
        positions = []
        deviation = None
        status = "completed"
        try:
            for action in seq.actions:
                self.held = set(action.buttons)
                for _ in range(action.frames):
                    self.state.frame += 1
                    count += 1
                    self.state.player.vx = 60 * (("right" in self.held) - ("left" in self.held))
                    self.state.player.x += self.state.player.vx / 60
                    if self.state.player.x >= 100:
                        self.state.room.completed = True
                    if seq.capture_positions:
                        positions.append([round(self.state.player.x, 1),
                                          round(self.state.player.y, 1)])
                    if seq.trace_frames:
                        sample = self.state.model_copy(deep=True)
                        if seq.trace_platforms:
                            sample.platform_sample = PlatformSample(platforms=[], total=0)
                        checkpoints.append(sample)
                    # Same contract as the real bridge: the frame that leaves
                    # the arc ends the job, and the frames after it never run.
                    if (seq.expect is not None and count <= len(seq.expect)
                            and seq.expect[count - 1] is not None):
                        want = seq.expect[count - 1]
                        offset_x = abs(self.state.player.x - want[0])
                        offset_y = abs(self.state.player.y - want[1])
                        if offset_x > seq.tolerance or offset_y > seq.tolerance:
                            deviation = Deviation(
                                frame=count, index=count, expected=list(want),
                                actual=[round(self.state.player.x, 1),
                                        round(self.state.player.y, 1)],
                                offset=[round(offset_x, 1), round(offset_y, 1)],
                                tolerance=seq.tolerance)
                            status = "deviated"
                            break
                    if self.state.room.completed:
                        break
                if status != "completed" or self.state.room.completed:
                    break
        finally:
            self.held.clear()
        excluded = set() if seq.trace_frames else {"checkpoints"}
        if deviation is None:
            excluded.add("deviation")
        result = ExecutionResult(execution_id=seq.execution_id, status=status,
                                 executed_frames=count, before=before,
                                 after=self.state.model_copy(deep=True),
                                 checkpoints=checkpoints, deviation=deviation,
                                 positions=positions).model_dump(exclude=excluded)
        self.results[seq.execution_id] = result
        return result

    async def handle(self, reader, writer):
        try:
            while raw := await reader.readline():
                response = {"jsonrpc": "2.0", "protocol_version": "1.0", "id": None}
                try:
                    req = Request.model_validate_json(raw)
                    response["id"] = req.id
                    response["result"] = self.dispatch(req)
                except Exception as exc:
                    response["error"] = {"code": -32602, "message": str(exc)}
                writer.write((json.dumps(response) + "\n").encode())
                await writer.drain()
        finally:
            self.held.clear()
            writer.close()
            await writer.wait_closed()
