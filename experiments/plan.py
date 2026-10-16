"""
Condition allocator: write the run plan for one stage of the experiment.

Every case assigned to the stage's roles gets every combination of
language x price structure x tactic x prompt version (x reps), so each
case is paired with itself across languages. The whole list is then
shuffled with the stage's seed, so the execution order is random and
time-of-run effects (API drift, rate limits) fall on both languages
alike. The plan is written once to experiments/plans/<stage>.csv and is
what batch_runner.py executes; it refuses to overwrite an existing plan
unless --force, so a frozen plan can't change by accident.

Usage (from the repo root):
  .venv\\Scripts\\python -m experiments.plan h1
"""

import argparse
import csv
import random

from experiments.cases import CONFIG_PATH, ROOT, file_sha256, load_cases, load_config

PLAN_DIR = ROOT / "experiments" / "plans"
PLAN_FIELDS = [
    "order",
    "run_id",
    "stage",
    "case_id",
    "pool_rank",
    "role",
    "structure",
    "tactic",
    "prompt_version",
    "language",
    "rep",
    "pair_id",
]


def plan_path(stage):
    return PLAN_DIR / f"{stage}.csv"


def build_plan(config, stage):
    spec = config["stages"][stage]
    cases = load_cases(config, spec["roles"], spec.get("max_cases"))
    rows = []
    for case in cases:
        for structure in spec["structures"]:
            for tactic in spec["tactics"]:
                for prompt_version in spec["prompt_versions"]:
                    for rep in range(1, spec["reps"] + 1):
                        pair_id = f"{case['case_id']}:{structure}:{tactic}:{prompt_version}:r{rep}"
                        for language in spec["languages"]:
                            rows.append(
                                {
                                    "run_id": f"{stage}:{pair_id}:{language}",
                                    "stage": stage,
                                    "case_id": case["case_id"],
                                    "pool_rank": case["pool_rank"],
                                    "role": case["role"],
                                    "structure": structure,
                                    "tactic": tactic,
                                    "prompt_version": prompt_version,
                                    "language": language,
                                    "rep": rep,
                                    "pair_id": pair_id,
                                }
                            )
    random.Random(spec["seed"]).shuffle(rows)
    for i, row in enumerate(rows, 1):
        row["order"] = i
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("stage")
    parser.add_argument("--force", action="store_true", help="overwrite an existing plan")
    args = parser.parse_args()

    config = load_config()
    path = plan_path(args.stage)
    if path.exists() and not args.force:
        raise SystemExit(f"{path.relative_to(ROOT)} exists; --force to rebuild it")
    rows = build_plan(config, args.stage)
    PLAN_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PLAN_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    n_cases = len({r["case_id"] for r in rows})
    print(
        f"{args.stage}: {len(rows)} runs ({n_cases} cases) -> {path.relative_to(ROOT)}\n"
        f"config sha256 {file_sha256(CONFIG_PATH)[:12]}, "
        f"candidates sha256 {file_sha256(ROOT / config['candidates'])[:12]}"
    )


if __name__ == "__main__":
    main()
