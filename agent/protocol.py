from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid")


Stance = Literal["ground", "climb", "air"]


class PlayerState(Schema):
    x: float = 0
    y: float = 0
    vx: float = 0
    vy: float = 0
    on_ground: bool = True
    dashes: int = 1
    stamina: float = 110
    dead: bool = False
    # StateMachine name, e.g. "StClimb". Empty on bridges older than 0.3.5;
    # stance then falls back to on_ground, which cannot see a wall.
    state: str = ""

    def stance(self) -> Stance:
        """Posture as a contract sees it: holding a wall, grounded, or falling.

        Grabbing a wall is a landing. Without this, a step that ends with her
        hanging on a wall reads as airborne and can be booked as landed only
        because the x/y bands happened to hold.
        """
        if self.state == "StClimb":
            return "climb"
        return "ground" if self.on_ground else "air"


class RoomState(Schema):
    name: str = "mock-flat"
    completed: bool = False


class PlatformPosition(Schema):
    type: str
    ordinal: int = Field(ge=0)
    x: float
    y: float
    collidable: bool


class PlatformSample(Schema):
    platforms: list[PlatformPosition] = Field(max_length=16)
    total: int = Field(ge=0)


class PlatformObservation(PlatformSample):
    frame: int
    room: str


class GameState(Schema):
    protocol_version: Literal["1.0"] = "1.0"
    frame: int = 0
    player: PlayerState | None = Field(default_factory=PlayerState)
    room: RoomState = Field(default_factory=RoomState)
    platform_sample: PlatformSample | None = None


class FrameAction(Schema):
    buttons: list[Literal["left", "right", "up", "down", "jump", "dash", "grab"]]
    frames: int = Field(ge=1, le=120, strict=True)


class ActionSequence(Schema):
    execution_id: str = Field(min_length=1, max_length=128)
    actions: list[FrameAction] = Field(min_length=1, max_length=64)
    trace_frames: bool = False
    trace_platforms: bool = False
    # Per-frame expected position, checked inside the tick that applied the
    # frame. ``None`` skips a frame, so a recorded arc can be shorter than the
    # plan that uses it. This is what lets a long macro stop on the exact frame
    # it leaves its route instead of running into whatever is at the end.
    expect: list[list[float] | None] | None = None
    tolerance: float = Field(default=1.0, ge=0, le=64)
    capture_positions: bool = False

    @model_validator(mode="after")
    def bounded(self):
        total = sum(a.frames for a in self.actions)
        if self.trace_platforms and not self.trace_frames:
            raise ValueError("platform traces require trace_frames")
        if self.trace_frames and total > 120:
            raise ValueError("trace exceeds 120 frames")
        if total > 600:
            raise ValueError("sequence exceeds 600 frames")
        if self.expect is not None:
            if len(self.expect) > total:
                raise ValueError("expect rows exceed frames")
            for row in self.expect:
                if row is not None and (len(row) != 2
                                        or not all(isinstance(v, (int, float)) for v in row)):
                    raise ValueError("expect rows are null or [x, y]")
        return self


class Deviation(Schema):
    """Where a step left its expected arc, as the bridge measured it.

    ``frame`` is 1-based: it is the frame of the step that first went off, so
    it lines up with ``executed_frames`` and with the trace.
    """

    frame: int
    index: int = 0
    expected: list[float]
    actual: list[float] | None = None
    offset: list[float] | None = None
    tolerance: float = 1.0


class ExecutionResult(Schema):
    execution_id: str
    status: Literal["completed", "interrupted", "deviated"]
    executed_frames: int
    before: GameState
    after: GameState
    checkpoints: list[GameState] = Field(default_factory=list, max_length=120)
    deviation: Deviation | None = None
    positions: list[list[float]] = Field(default_factory=list, max_length=600)


class Request(Schema):
    jsonrpc: Literal["2.0"] = "2.0"
    protocol_version: Literal["1.0"] = "1.0"
    id: str
    method: str
    params: dict = Field(default_factory=dict)
