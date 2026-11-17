"""Recheck the recorded room 6b benchmarks without connecting to Celeste."""
import argparse
import json
import math
from pathlib import Path

from agent.memory import assess_route, complete_sample, landing_skill, same_observation
from agent.protocol import ExecutionResult
from agent.restore_probe import observed, trace

GAME_BUILD = "live-session-2026-11-16-bridge-0.2.3"
SCENARIOS = (
    ("single-skill", "phase6-live-comparison.json", (2057, -1128), 18, (True, True), 1),
    ("pair-tight-radius", "phase6-pair-comparison.json", (2141, -1152), 3, (False, False), 2),
    ("pair-moving-platform", "phase6-pair-comparison-radius10.json", (2141, -1152), 10,
     (False, True), 2),
)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def replay_difference(reference, actual):
    if (reference["status"], reference["executed_frames"]) != (
            actual["status"], actual["executed_frames"]):
        return "execution"
    expected, recorded = trace(reference), trace(actual)
    if len(expected) != len(recorded):
        return "trace length"
    for frame, (left, right) in enumerate(zip(expected, recorded)):
        if left != right:
            return frame
    if observed(reference["after"]) != observed(actual["after"]):
        return "endpoint"
    return None


def inspect_trial(trial, target, radius, skills):
    result = ExecutionResult.model_validate(trial["result"])
    checkpoints = result.checkpoints
    states = [result.before, *checkpoints]
    endpoint = result.after.player
    expected_frames = sum(action["frames"] for action in trial["actions"])
    valid = (checkpoints and result.status == "completed" and result.executed_frames == len(checkpoints)
             == expected_frames and endpoint and not endpoint.dead and all(
                 complete_sample(state) and state.player and not state.player.dead
                 and state.room.name == result.before.room.name for state in states)
             and result.after.room == checkpoints[-1].room
             and endpoint == checkpoints[-1].player)
    route = tuple(skills[(item["name"], item["version"])] for item in trial.get("skills", []))
    checks = list(assess_route(route, result, GAME_BUILD))
    handoffs = []
    offset = 0
    for skill, failure in checks:
        offset += skill.frames
        handoffs.append({"skill": skill.name, "frame": offset, "failure": failure})
    if route:
        valid = valid and len(checks) == len(route) and all(
            failure is None for _, failure in checks)
    distance = math.hypot(endpoint.x - target[0], endpoint.y - target[1]) if endpoint else None
    landing = checkpoints[-4:]
    stable = (len(landing) == 4 and any(s.player and not s.player.on_ground for s in states)
              and all(s.player and not s.player.dead and s.player.on_ground
                      and s.room.name == result.before.room.name
                      and math.hypot(s.player.x - target[0], s.player.y - target[1]) <= radius
                      for s in landing))
    return {"reached": bool(valid and stable and distance <= radius), "distance": distance,
            "skill_boundaries": handoffs}


def training_cost(report):
    runs = report.get("full_trials")
    if runs is None:
        runs = [*(trial["result"] for trial in report["trials"]), *report["verifications"]]
    return {"candidate_runs": len(report["trials"]), "verification_runs": len(report["verifications"]),
            "executed_frames": sum(run["executed_frames"] for run in runs)}


def summarize_arm(arm, target, radius, skills):
    trials, repeats = arm["trials"], arm["verifications"]
    winner = arm["winner"]
    outcomes = [inspect_trial(trial, target, radius, skills) for trial in trials]
    result = winner["result"]
    winner_outcome = outcomes[trials.index(winner)]
    differences = [replay_difference(result, repeat) for repeat in repeats]
    verified = len(differences) == 3 and all(diff is None for diff in differences)
    success = winner_outcome["reached"] and verified
    attempts = [trial["result"] for trial in trials]
    deaths = sum(any(state["player"] and state["player"]["dead"]
                     for state in [*run["checkpoints"], run["after"]]) for run in attempts)
    return {**winner_outcome, "success": success, "evaluations": len(trials),
            "reported_outcome_matches": (success == arm["success"]
                                         and len(trials) == arm["evaluations"]),
            "deaths_observed": deaths, "candidate_retries": max(0, len(trials) - 1),
            "candidate_frames": sum(run["executed_frames"] for run in attempts),
            "verification_frames": sum(run["executed_frames"] for run in repeats),
            "replays": [{"matches": diff is None, "first_difference": diff} for diff in differences],
            "actions": winner["actions"], "trajectory": [result["before"], *result["checkpoints"]],
            "final_state": result["after"], "screenshot": arm.get("screenshot"),
            "token_usage": arm.get("token_usage"), "api_cost": arm.get("api_cost")}


def evaluate(logs: Path):
    entrance = read_json(logs / "phase6-live-training.json")
    continuation = read_json(logs / "phase6-pair-training.json")
    definitions = [
        landing_skill(entrance, "phase6-entrance", GAME_BUILD),
        landing_skill(continuation, "phase6-entrance-continuation", GAME_BUILD),
    ]
    skills = {(skill.name, skill.version): skill for skill in definitions}
    with (logs / "phase6-live-acceptance.jsonl").open(encoding="utf-8") as source:
        archived = {row["result"]["execution_id"]: row for line in source if line.strip()
                    if (row := json.loads(line))}

    cases = []
    for name, filename, target, radius, expected, skill_count in SCENARIOS:
        report = read_json(logs / filename)
        raw = report["benchmark"]
        arms = {key: summarize_arm(raw[key], target, radius, skills)
                for key in ("without_skills", "with_skills")}
        runs = [ExecutionResult.model_validate(run) for arm in raw.values()
                for run in [*(trial["result"] for trial in arm["trials"]), *arm["verifications"]]]
        common_start = definitions[0].applicable(runs[0].before, GAME_BUILD) and all(
            same_observation(runs[0].before, run.before) for run in runs)
        archive_matches = all(
            (record := archived.get(run.execution_id)) and record["game_version"] == GAME_BUILD
            and ExecutionResult.model_validate(record["result"]) == run for run in runs)
        passed = (common_start and archive_matches and tuple(report["target"]) == target
                  and len(arms["with_skills"]["skill_boundaries"]) == skill_count
                  and all(boundary["failure"] is None
                          for boundary in arms["with_skills"]["skill_boundaries"])
                  and all(arm["reported_outcome_matches"] and arm["evaluations"] <= 21
                          and len(arm["replays"]) == 3 and all(r["matches"] for r in arm["replays"])
                          and arm["success"] == outcome
                          for arm, outcome in zip(arms.values(), expected)))
        cases.append({"id": name, "target": target, "radius": radius, "candidate_budget": 21,
                      "grounded_frames": 4, "common_start": common_start,
                      "archive_matches": archive_matches, "passed": passed, "arms": arms})
    return {"schema_version": 1, "game_build": GAME_BUILD, "passed": all(c["passed"] for c in cases),
            "training": {"entrance": training_cost(entrance),
                         "continuation": training_cost(continuation)}, "cases": cases}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--logs", type=Path, default=Path("logs"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = evaluate(args.logs)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(2, f"Cannot evaluate recordings: {error}\n")
    output = args.output or args.logs / "phase7-evaluation.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    for case in report["cases"]:
        print(f"{case['id']}: {'PASS' if case['passed'] else 'FAIL'}")
    print(output)
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
