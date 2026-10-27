"""
Condition allocator: write the run plan for one stage of the experiment.

Every case assigned to the stage's roles gets every combination of
language x price structure x tactic x seller prompt version x buyer
prompt version (x reps), so each case is paired with itself across
languages; `tactic_structures` can limit a tactic to some structures
(e.g. experiment B's scripted seller in one structure). Refused before
anything is written: a version pair experiments/goal_versions.py rejects,
a stage whose roles do not hold exactly `n_cases` cases, and any case
whose rounded prices break T1 (experiments/cases.py t1_problems).
Execution order is randomised with the stage's seed by pair: the pairs
run in random order, and the two languages of a pair run back to back,
in random order, so a pair's games are minutes apart and a model update
or API drift during collection hits both sides of a comparison alike.
With `order_blocks: case` the pairs of one case also run back to back
(cases in random order, pairs within a case in random order), so the
comparisons across structures and tactics within a case are close in
time too.
The plan is written once to experiments/plans/<stage>.csv and is
what batch_runner.py executes; it refuses to overwrite an existing plan
unless --force, so a frozen plan can't change by accident.

Usage (from the repo root):
  .venv\\Scripts\\python -m experiments.plan h1
"""

import argparse
import csv
import random
from collections import defaultdict

from experiments.cases import CONFIG_PATH, ROOT, file_sha256, load_cases, load_config, t1_problems
from experiments.goal_versions import check_combination

PLAN_DIR = ROOT / "experiments" / "plans"
PLAN_FIELDS = [
    "order",
    "game_label",
    "game_no",
    "run_id",
    "stage",
    "case_no",
    "case_id",
    "pool_rank",
    "role",
    "structure",
    "tactic",
    "seller_prompt_version",
    "buyer_prompt_version",
    "language",
    "rep",
    "pair_id",
]


def plan_path(stage):
    return PLAN_DIR / f"{stage}.csv"


def build_plan(config, stage):
    spec = config["stages"][stage]
    versions = [
        (seller, buyer)
        for seller in spec["seller_prompt_versions"]
        for buyer in spec["buyer_prompt_versions"]
    ]
    for seller, buyer in versions:
        check_combination(seller, buyer)
    cases = load_cases(config, spec["roles"], spec.get("max_cases"))
    if spec.get("n_cases") is not None and len(cases) != spec["n_cases"]:
        raise SystemExit(
            f"{stage}: roles {spec['roles']} hold {len(cases)} cases, the stage needs "
            f"exactly {spec['n_cases']} (has the case pool been rebuilt and frozen?)"
        )
    problems = [
        f"  {case['case_id']}: {p}"
        for case in cases
        for p in t1_problems(config, case, spec["structures"])
    ]
    if problems:
        raise SystemExit(f"{stage}: T1 fails for these cases:\n" + "\n".join(problems))
    rows = []
    for i, case in enumerate(cases):
        case_no = i + 1
        # "cycle": each case gets one structure, in turn, instead of all of
        # them -- for small pilots that should still cover every structure.
        structures = (
            [spec["structures"][i % len(spec["structures"])]]
            if spec.get("structure_assignment") == "cycle"
            else spec["structures"]
        )
        for structure in structures:
            for tactic in spec["tactics"]:
                if structure not in spec.get("tactic_structures", {}).get(tactic, structures):
                    continue
                for seller_version, buyer_version in versions:
                    for rep in range(1, spec["reps"] + 1):
                        pair_id = (
                            f"{case['case_id']}:{structure}:{tactic}:"
                            f"s{seller_version}-b{buyer_version}:r{rep}"
                        )
                        for language in spec["languages"]:
                            rows.append(
                                {
                                    "run_id": f"{stage}:{pair_id}:{language}",
                                    "stage": stage,
                                    "case_no": case_no,
                                    "case_id": case["case_id"],
                                    "pool_rank": case["pool_rank"],
                                    "role": case["role"],
                                    "structure": structure,
                                    "tactic": tactic,
                                    "seller_prompt_version": seller_version,
                                    "buyer_prompt_version": buyer_version,
                                    "language": language,
                                    "rep": rep,
                                    "pair_id": pair_id,
                                }
                            )
    # Game numbers follow the readable order the loops above build: case,
    # then structure, ..., then language, so a pair's two languages are
    # neighbours (h1_001 en, h1_002 zh). The order games are *run* in is
    # the shuffled one below, kept random on purpose.
    width = max(3, len(str(len(rows))))
    for i, row in enumerate(rows, 1):
        row["game_no"] = i
        row["game_label"] = f"{stage}_{i:0{width}d}"
    rng = random.Random(spec["seed"])
    by_pair = defaultdict(list)
    for row in rows:
        by_pair[row["pair_id"]].append(row)
    # Blocks of pairs that run back to back: one block per case with
    # order_blocks "case", else every pair is its own block.
    blocks = defaultdict(list)
    for pair_id, members in by_pair.items():
        key = members[0]["case_id"] if spec.get("order_blocks") == "case" else pair_id
        blocks[key].append(pair_id)
    block_keys = list(blocks)
    rng.shuffle(block_keys)
    ordered = []
    for key in block_keys:
        pair_ids = blocks[key]
        rng.shuffle(pair_ids)
        for pair_id in pair_ids:
            members = by_pair[pair_id]
            rng.shuffle(members)
            ordered += members
    for i, row in enumerate(ordered, 1):
        row["order"] = i
    return ordered


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
