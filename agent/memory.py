"""Version-scoped skills and durable JSON recordings."""
import argparse
import json
import math
import sqlite3
from pathlib import Path
from tempfile import NamedTemporaryFile

from pydantic import Field, model_validator

from agent.protocol import ActionSequence, ExecutionResult, GameState, Schema
from agent.restore_probe import observed, trace


def same_observation(left: GameState, right: GameState) -> bool:
    return observed(left.model_dump()) == observed(right.model_dump())


def complete_sample(state: GameState) -> bool:
    sample = state.platform_sample
    return sample is not None and sample.total == len(sample.platforms)


class Skill(Schema):
    name: str
    version: int = Field(default=1, ge=1)
    game_version: str = Field(min_length=1)
    room: str
    grounded: bool = True
    min_dashes: int = Field(default=0, ge=0)
    sequence: ActionSequence
    expected_x_min: float
    expected_x_max: float
    expected_y: float | None = None
    verified_start: GameState | None = None
    verified_end: GameState | None = None
    successes: int = Field(default=0, ge=0)
    failures: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_outcome(self):
        if self.expected_x_min > self.expected_x_max:
            raise ValueError("invalid expected horizontal range")
        return self

    @property
    def frames(self) -> int:
        return sum(action.frames for action in self.sequence.actions)

    def applicable(self, state: GameState, game_version: str) -> bool:
        p = state.player
        start = self.verified_start
        return bool(start and complete_sample(state) and same_observation(start, state)
                    and p and not p.dead and self.game_version == game_version
                    and state.room.name == self.room and p.on_ground == self.grounded
                    and p.dashes >= self.min_dashes)

    def outcome_matches(self, state: GameState) -> bool:
        p = state.player
        return bool(p and not p.dead and p.on_ground and state.room.name == self.room
                    and self.expected_x_min <= p.x <= self.expected_x_max
                    and (self.expected_y is None or p.y == self.expected_y)
                    and (self.verified_end is None or same_observation(self.verified_end, state)))

    @property
    def success_rate(self):
        total = self.successes + len(self.failures)
        return self.successes / total if total else None


class Memory:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS records (kind TEXT, name TEXT, body TEXT, PRIMARY KEY(kind,name))")

    def put(self, kind, name, value):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO records VALUES (?,?,?)",
                            (kind, name, value.model_dump_json()))

    def list(self, kind):
        return [json.loads(row[0]) for row in self.db.execute(
            "SELECT body FROM records WHERE kind=? ORDER BY name", (kind,))]

    def retrieve(self, state, game_version):
        return [s for row in self.list("skill") if
                (s := Skill.model_validate(row)).applicable(state, game_version)]

    def save_skill(self, skill: Skill):
        # Preserve history on repeated imports. A changed definition needs a new revision.
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            stored = next((Skill.model_validate(row) for row in self.list("skill")
                           if (row["name"], row["game_version"], row.get("version", 1))
                           == (skill.name, skill.game_version, skill.version)), None)
            if stored:
                counters = {"successes", "failures"}
                if stored.model_dump(exclude=counters) != skill.model_dump(exclude=counters):
                    raise ValueError("skill already exists with a different definition; use a new revision")
                return
            key = json.dumps([skill.name, skill.game_version, skill.version])
            self.db.execute("INSERT INTO records VALUES (?,?,?)",
                            ("skill", key, skill.model_dump_json()))

    def record_attempt(self, skill: Skill, reason: str | None):
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            for key, body in self.db.execute("SELECT name, body FROM records WHERE kind='skill'"):
                current = Skill.model_validate_json(body)
                if (current.name, current.game_version, current.version) != (
                        skill.name, skill.game_version, skill.version):
                    continue
                if reason is None:
                    current.successes += 1
                else:
                    current.failures.append(reason)
                self.db.execute("UPDATE records SET body=? WHERE kind='skill' AND name=?",
                                (current.model_dump_json(), key))
                return
            raise LookupError(f"skill not stored: {skill.name}")

    def store_trajectory(self, trajectory: ExecutionResult, game_version: str, strategy: str):
        record = Trajectory(game_version=game_version, strategy=strategy, result=trajectory)
        self.put("trajectory", trajectory.execution_id, record)

    def store_report(self, report: dict, game_version: str, strategy: str):
        for result in [*(trial["result"] for trial in report["trials"]), *report["verifications"]]:
            self.store_trajectory(ExecutionResult.model_validate(result), game_version, strategy)

    def export_trajectories(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False)
        try:
            with temporary as output:
                for row in self.list("trajectory"):
                    output.write(json.dumps(row) + "\n")
            Path(temporary.name).replace(path)
        finally:
            Path(temporary.name).unlink(missing_ok=True)

    def close(self):
        self.db.close()


class Trajectory(Schema):
    schema_version: int = 1
    game_version: str
    strategy: str
    result: ExecutionResult


def landing_skill(report: dict, name: str, game_version: str, version: int = 1) -> Skill:
    winner = report.get("winner")
    repeats = report.get("verifications", [])
    if (not report.get("success") or not winner or not winner["stable_landing"]
            or not report.get("settle") or len(repeats) < 3):
        raise ValueError("a stable landing and three verified live repeats are required")
    result = ExecutionResult.model_validate(winner["result"])
    sequence = ActionSequence(execution_id=result.execution_id, actions=winner["actions"],
                              trace_frames=True, trace_platforms=True)
    frames = sum(action.frames for action in sequence.actions)
    checks = [result, *(ExecutionResult.model_validate(run) for run in repeats)]
    if any(run.status != "completed" or run.executed_frames != frames
           or len(run.checkpoints) != frames
           or trace(run.model_dump()) != trace(result.model_dump())
           or run.after.player != result.after.player or run.after.room != result.after.room
           for run in checks):
        raise ValueError("recorded verification traces differ")
    initial, final = result.before, result.checkpoints[-1]
    if not all(complete_sample(state) and state.player and not state.player.dead
               and state.room.name == initial.room.name for state in [initial, *result.checkpoints]):
        raise ValueError("route lacks complete living player and platform observations")
    grounded_frames = report["grounded_frames"]
    if (not 1 <= grounded_frames <= frames
            or not all(state.player.on_ground for state in result.checkpoints[-grounded_frames:])
            or not any(not state.player.on_ground for state in [initial, *result.checkpoints])
            or result.after.player != final.player or result.after.room != final.room):
        raise ValueError("route lacks a valid start or grounded endpoint")
    return Skill(
        name=name, version=version, game_version=game_version, room=initial.room.name,
        grounded=initial.player.on_ground, min_dashes=initial.player.dashes,
        sequence=sequence,
        expected_x_min=final.player.x, expected_x_max=final.player.x,
        expected_y=final.player.y, verified_start=initial, verified_end=final, successes=len(repeats),
    )


def compose_skills(memory: Memory, start: GameState, game_version: str, target):
    """Rank single skills and compatible pairs by predicted target distance."""
    routes = []
    for first in memory.retrieve(start, game_version):
        if first.frames > 120:
            continue
        routes.append((first,))
        if first.verified_end is None:
            continue
        for second in memory.retrieve(first.verified_end, game_version):
            if (first.frames + second.frames <= 120
                    and len(first.sequence.actions) + len(second.sequence.actions) <= 64):
                routes.append((first, second))

    def rank(route):
        last = route[-1]
        x = min(last.expected_x_max, max(last.expected_x_min, target[0]))
        y = last.expected_y if last.expected_y is not None else target[1]
        return math.hypot(x - target[0], y - target[1]), sum(skill.frames for skill in route)

    return sorted(routes, key=rank)


def assess_route(skills: tuple[Skill, ...], result: ExecutionResult, game_version: str):
    """Attribute at most the first failure using observations at skill boundaries."""
    start = result.before
    offset = 0
    for skill in skills:
        offset += skill.frames
        if not skill.applicable(start, game_version):
            return
        if result.executed_frames < offset or len(result.checkpoints) < offset:
            yield skill, "interrupted" if result.status == "interrupted" else "incomplete_trace"
            return
        end = result.checkpoints[offset - 1]
        if (result.status == "interrupted" and offset == result.executed_frames
                or not skill.outcome_matches(end)):
            yield skill, "interrupted" if result.status == "interrupted" else "outcome_mismatch"
            return
        yield skill, None
        start = end


def main():
    parser = argparse.ArgumentParser(description="Import a verified live-search recording as a skill.")
    parser.add_argument("report", type=Path)
    parser.add_argument("--name", required=True)
    parser.add_argument("--game-version", required=True)
    parser.add_argument("--revision", type=int, default=1)
    parser.add_argument("--memory", type=Path, default=Path("logs/live-skills.sqlite3"))
    parser.add_argument("--trajectory-jsonl", type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    skill = landing_skill(report, args.name, args.game_version, args.revision)
    args.memory.parent.mkdir(parents=True, exist_ok=True)
    memory = Memory(args.memory)
    try:
        memory.save_skill(skill)
        memory.store_report(report, args.game_version, report["strategy"])
        memory.export_trajectories(args.trajectory_jsonl or args.memory.with_suffix(".jsonl"))
    finally:
        memory.close()
    print(f"Imported {skill.name} revision {skill.version} into {args.memory}")


if __name__ == "__main__":
    main()
