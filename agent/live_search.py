"""Bounded beam search against a live Speedrun Tool save slot."""
import argparse
import asyncio
import json
import math
import random
import uuid
from pathlib import Path

from agent.client import BridgeClient
from agent.memory import Memory, assess_route, compose_skills, landing_skill
from agent.protocol import ExecutionResult, FrameAction, GameState
from agent.restore_probe import trace
from agent.tools import ToolRegistry

BUTTONS = ((), ("left",), ("right",), ("left", "jump"), ("right", "jump"),
           ("up", "left", "dash"), ("up", "right", "dash"))


async def search(client, dx, dy, radius, width, depth, budget, frames, *,
                 settle=0, grounded_frames=4, min_segments=1, strategy="beam",
                 seed=0, verification_runs=1, own_slot=True, absolute_target=None,
                 memory=None, game_version=None, use_skills=False):
    capabilities = await client.call("ping")
    if not capabilities.get("restore_and_execute") or capabilities.get("tas_active"):
        raise RuntimeError("bridge 0.2.2 with Speedrun Tool and inactive Studio playback required")
    if own_slot and not (await client.call("save_state"))["accepted"]:
        raise RuntimeError("could not save the current state")

    tools = ToolRegistry(client)
    fixed_direction = dx
    candidates = [FrameAction(buttons=list(buttons), frames=frames) for buttons in BUTTONS]
    frontier = [[]]
    baseline = target = best = None
    trials = []
    rng = random.Random(seed)
    settle_action = [FrameAction(buttons=[], frames=settle)] if settle else []

    async def run(actions):
        return await tools.restore_and_execute(
            execution_id=uuid.uuid4().hex, trace_frames=True, trace_platforms=True,
            actions=[action.model_dump() for action in actions])

    async def evaluate(actions, segments, skills=()):
        nonlocal baseline, target, best
        result = await run(actions)
        start = trace(result)[0]
        if baseline is None:
            baseline = start
            player = start["player"]
            if not player or player["dead"]:
                raise RuntimeError("restored start has no living player")
            target = absolute_target or (player["x"] + dx, player["y"] + dy)
        if start != baseline:
            raise RuntimeError("restored starting state changed across candidates")
        checkpoints = trace(result)
        for state in checkpoints:
            sample = state["platform_sample"]
            if sample is None or sample["total"] != len(sample["platforms"]):
                raise RuntimeError("missing or truncated platform samples")
        final = result["after"]
        player = final["player"]
        valid = (result["status"] == "completed" and player is not None
                 and not player["dead"] and final["room"]["name"] == baseline["room"]["name"]
                 and result["executed_frames"] == sum(a.frames for a in actions)
                 and len(result["checkpoints"]) == result["executed_frames"])
        distance = math.hypot(player["x"] - target[0], player["y"] - target[1]) if player else None
        landing = result["checkpoints"][-grounded_frames:]
        airborne = any(s["player"] and not s["player"]["on_ground"]
                       for s in checkpoints)
        stable = not settle or (airborne and len(landing) == grounded_frames and all(
            s["player"] and not s["player"]["dead"] and s["player"]["on_ground"]
            and s["room"]["name"] == baseline["room"]["name"]
            and math.hypot(s["player"]["x"]-target[0], s["player"]["y"]-target[1]) <= radius
            for s in landing))
        reached = valid and distance <= radius and stable and segments >= min_segments
        score = (not valid, not reached, distance if distance is not None else math.inf,
                 result["executed_frames"])
        trial = {"actions": [a.model_dump() for a in actions],
                 "segments": segments, "stable_landing": stable, "result": result,
                 "valid": valid, "reached": reached, "distance": distance}
        if skills:
            attempts = list(assess_route(skills, ExecutionResult.model_validate(result), game_version))
            trial["skills"] = [
                {"name": skill.name, "version": skill.version, "failure": reason}
                for skill, reason in attempts
            ]
            for skill, reason in attempts:
                memory.record_attempt(skill, reason)
            valid = valid and len(attempts) == len(skills) and all(
                reason is None for _, reason in attempts)
            trial["valid"] = valid
            trial["reached"] = reached = valid and reached
            score = (not valid, not reached, score[2], score[3])
        trials.append(trial)
        if not valid:
            return None
        entry = (score, len(trials) - 1, actions)
        if best is None or entry < best:
            best = entry
        return entry

    try:
        if strategy == "fixed" and absolute_target:
            player = (await client.call("get_state"))["player"]
            if not player:
                raise RuntimeError("fixed script requires a player observation")
            fixed_direction = absolute_target[0] - player["x"]
        for _ in range(depth):
            children = []
            for prefix in frontier:
                choices = candidates.copy()
                if strategy == "random":
                    rng.shuffle(choices)
                elif strategy == "fixed":
                    choices = [candidates[4 if fixed_direction >= 0 else 3]] if not prefix else [
                        candidates[2 if fixed_direction >= 0 else 1]]
                for action in choices:
                    if len(trials) >= budget:
                        break
                    actions = [*prefix, action]
                    entry = await evaluate([*actions, *settle_action], len(actions))
                    if entry:
                        children.append((*entry[:2], actions))
                    if use_skills and len(trials) == 1 and not trials[0]["reached"]:
                        state = GameState.model_validate(trials[0]["result"]["before"])
                        for route in compose_skills(memory, state, game_version, target):
                            if len(trials) >= budget:
                                break
                            skill_actions = [action for skill in route for action in skill.sequence.actions]
                            await evaluate(skill_actions, len(skill_actions), route)
                            if best and trials[best[1]]["reached"]:
                                break
                    if best and trials[best[1]]["reached"]:
                        break
                if len(trials) >= budget or (best and trials[best[1]]["reached"]):
                    break
            if not children or len(trials) >= budget or (best and trials[best[1]]["reached"]):
                break
            if strategy == "random":
                rng.shuffle(children)
            else:
                children.sort()
            frontier = [entry[2] for entry in children[:width]]
        verifications = [await run(best[2]) for _ in range(verification_runs)] if best else []
        verification = verifications[0] if verifications else None
        winner = trials[best[1]] if best else None
        verified = bool(verifications and all(
            run["status"] == "completed" and run["executed_frames"] == winner["result"]["executed_frames"]
            and trace(run) == trace(winner["result"]) for run in verifications))
        return {"target": target, "radius": radius, "evaluations": len(trials),
                "trials": trials, "winner": winner, "verification": verification,
                "verifications": verifications, "strategy": strategy, "settle": settle,
                "grounded_frames": grounded_frames, "verified": verified,
                "success": bool(verified and winner["reached"])}
    finally:
        if own_slot:
            await cleanup_slot()


async def cleanup_slot():
    try:
        async with BridgeClient() as cleanup:
            await cleanup.call("load_state")
    finally:
        async with BridgeClient() as cleanup:
            await cleanup.call("clear_state")


async def run(args, memory=None):
    async with BridgeClient() as client:
        async def evaluate(strategy, own_slot, use_skills=False):
            return await search(client, args.dx, args.dy, args.radius, args.width,
                                args.depth, args.budget, args.frames, settle=args.settle,
                                grounded_frames=args.grounded_frames, min_segments=args.min_segments,
                                strategy=strategy, seed=args.seed, verification_runs=args.repeats,
                                own_slot=own_slot, absolute_target=args.target, memory=memory,
                                game_version=args.game_version, use_skills=use_skills)

        if not (args.benchmark or args.compare_skills):
            return await evaluate(args.strategy, True, args.use_skills)
        if not (await client.call("save_state"))["accepted"]:
            raise RuntimeError("could not save the common benchmark start")
        try:
            if args.compare_skills:
                results = {
                    "without_skills": await evaluate("beam", False),
                    "with_skills": await evaluate("beam", False, True),
                }
                selected = "with_skills"
            else:
                results = {strategy: await evaluate(strategy, False)
                           for strategy in ("beam", "fixed", "random")}
                selected = "beam"
            starts = [trace(report["trials"][0]["result"])[0] for report in results.values()]
            if any(start != starts[0] for start in starts[1:]):
                raise RuntimeError("benchmark strategies did not share a common start")
            return {**results[selected], "benchmark": results}
        finally:
            await cleanup_slot()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    target_group = parser.add_mutually_exclusive_group(required=True)
    target_group.add_argument("--dx", type=float)
    target_group.add_argument("--target", type=float, nargs=2, metavar=("X", "Y"))
    parser.add_argument("--dy", type=float, default=0)
    parser.add_argument("--radius", type=float, default=4)
    parser.add_argument("--width", type=int, default=2, choices=range(1, 9))
    parser.add_argument("--depth", type=int, default=2, choices=range(1, 5))
    parser.add_argument("--budget", type=int, default=21, choices=range(1, 65))
    parser.add_argument("--frames", type=int, default=8, choices=range(1, 31))
    parser.add_argument("--settle", type=int, default=0, choices=range(121))
    parser.add_argument("--grounded-frames", type=int, default=4, choices=range(1, 121))
    parser.add_argument("--min-segments", type=int, default=1, choices=range(1, 5))
    parser.add_argument("--strategy", choices=["beam", "random", "fixed"], default="beam")
    parser.add_argument("--benchmark", action="store_true")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--repeats", type=int, default=1, choices=range(1, 4))
    parser.add_argument("--output", type=Path, default=Path("logs/live-search.json"))
    parser.add_argument("--skill-name")
    parser.add_argument("--game-version")
    parser.add_argument("--memory", type=Path, default=Path("logs/live-skills.sqlite3"))
    parser.add_argument("--use-skills", action="store_true")
    parser.add_argument("--compare-skills", action="store_true")
    parser.add_argument("--trajectory-jsonl", type=Path)
    parser.add_argument("--skill-revision", type=int, default=1)
    args = parser.parse_args()
    if args.dx is None:
        args.dx = 0
    if not all(map(math.isfinite, (args.dx, args.dy, args.radius, *(args.target or [])))) or args.radius < 0:
        parser.error("finite target offsets and a nonnegative radius required")
    if (args.frames * args.depth + args.settle > 120 or args.min_segments > args.depth
            or (args.settle and args.grounded_frames > args.settle)):
        parser.error("invalid segment or landing frame budget")
    if args.skill_name and (not args.game_version or args.repeats != 3 or not args.settle):
        parser.error("skill export requires --game-version, --repeats 3 and --settle")
    if sum((args.benchmark, args.compare_skills, args.use_skills)) > 1:
        parser.error("choose one of --benchmark, --compare-skills and --use-skills")
    if (args.compare_skills or args.use_skills) and (args.strategy != "beam" or args.budget < 2):
        parser.error("skill planning requires beam search and at least two evaluations")
    if (args.compare_skills or args.use_skills or args.trajectory_jsonl) and not args.game_version:
        parser.error("skill planning and trajectory storage require --game-version")
    if args.skill_revision < 1:
        parser.error("skill revision must be positive")
    memory = None
    if args.game_version:
        args.memory.parent.mkdir(parents=True, exist_ok=True)
        memory = Memory(args.memory)
    try:
        report = asyncio.run(run(args, memory))
        if memory:
            for strategy, recorded in report.get("benchmark", {args.strategy: report}).items():
                memory.store_report(recorded, args.game_version, strategy)
            memory.export_trajectories(args.trajectory_jsonl or args.memory.with_suffix(".jsonl"))
        if report["success"] and args.skill_name:
            skill = landing_skill(report, args.skill_name, args.game_version, args.skill_revision)
            memory.save_skill(skill)
            print({"skill": skill.name, "memory": str(args.memory)})
    finally:
        if memory:
            memory.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print({key: report[key] for key in ("target", "evaluations", "verified", "success")})
    if "benchmark" in report:
        print({name: {key: result[key] for key in ("evaluations", "success")}
               for name, result in report["benchmark"].items()})
    raise SystemExit(0 if report["success"] else 1)


if __name__ == "__main__":
    main()
