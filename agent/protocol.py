from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlayerState(Schema):
    x: float = 0
    y: float = 0
    vx: float = 0
    vy: float = 0
    on_ground: bool = True
    dashes: int = 1
    stamina: float = 110
    dead: bool = False


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

    @model_validator(mode="after")
    def bounded(self):
        total = sum(a.frames for a in self.actions)
        if self.trace_platforms and not self.trace_frames:
            raise ValueError("platform traces require trace_frames")
        if self.trace_frames and total > 120:
            raise ValueError("trace exceeds 120 frames")
        if total > 600:
            raise ValueError("sequence exceeds 600 frames")
        return self


class ExecutionResult(Schema):
    execution_id: str
    status: Literal["completed", "interrupted"]
    executed_frames: int
    before: GameState
    after: GameState
    checkpoints: list[GameState] = Field(default_factory=list, max_length=120)


class Request(Schema):
    jsonrpc: Literal["2.0"] = "2.0"
    protocol_version: Literal["1.0"] = "1.0"
    id: str
    method: str
    params: dict = Field(default_factory=dict)
