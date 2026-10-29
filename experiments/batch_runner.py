"""
Run the games of a stage plan (experiments/plans/<stage>.csv, written by
experiments/plan.py), one game per plan row, in plan order.

Resumable: a run counts as done once a game_state.json under
.logs/<stage>/ carries its run_id with status ok, max_rounds or rejected.
Runs that ended in api_error / parse_error are retried, up to --max-attempts in
total; every attempt keeps its own log and its number in
experiment.attempt, so the retry count per run is on record. A failed
attempt is retried right away, before the next run starts, so the two
languages of a pair stay minutes apart even when one of them fails; only
a run cut short by a spending cap (or a killed process) waits for the
next invocation.

A formal stage refuses to run while a case's category has no reviewed
label in the glossary, instead of falling back to the official name.

Each game's settings (case, price structure, C, O, buyer funds, context
sentence, model, and the SHA-256 of the config, plan and candidate pool
it came from) are stored in game_state.json under `experiment`, next to
the usual run_metadata.

Spending cap: --budget-tokens stops before the next game once the tokens
counted reach it (so it can overshoot by one game); with --budget-stages
the tokens already logged under those stages are counted first, so the
cap covers every invocation and retry.

Usage (from the repo root):
  .venv\\Scripts\\python -m experiments.batch_runner h1 --dry-run
  .venv\\Scripts\\python -m experiments.batch_runner h1 --max-games-per-run 20
  .venv\\Scripts\\python -m experiments.batch_runner h1 --budget-tokens 20000000 --budget-stages h1_trial,h1
"""

import argparse
import csv
import json
import subprocess
import traceback
from collections import defaultdict

from dotenv import load_dotenv

from experiments.backup import backup_logs
from experiments.cases import (
    CONFIG_PATH,
    ROOT,
    file_sha256,
    load_cases,
    load_config,
    load_glossary,
    negotiation_settings,
    t1_problems,
)
from experiments.goal_versions import (
    BUYER_GOALS,
    SELLER_GOALS,
    check_combination,
    combined_label,
)
from experiments.models import agent_kwargs
from experiments.plan import plan_path
from experiments.run_logger import append_run_log
from experiments.throttle import BudgetExceeded, add_throttle_args, throttle_from_args
from games.buy_sell_game.game import BuySellGame as BuySellGameEN
from games.buy_sell_game_zh.game import BuySellGame as BuySellGameZH
from games.player_roles import player_role_declaration
from negotiationarena.agents.chatgpt import ChatGPTAgent
from negotiationarena.agents.scripted_seller import FixedFirstOfferSellerAgent, ScriptedSellerAgent
from negotiationarena.constants import AGENT_ONE, AGENT_TWO, MONEY_TOKEN
from negotiationarena.game_objects.resource import Resources
from negotiationarena.game_objects.valuation import Valuation

load_dotenv(ROOT / ".env")

GAMES = {"en": BuySellGameEN, "zh": BuySellGameZH}
DONE_STATUSES = ("ok", "max_rounds", "rejected")
# Files a run itself appends to (or that only hold notes); a change to
# them doesn't change what a game runs, so they don't make the tree dirty.
RUN_OUTPUTS = {"experiments/runs.jsonl", "experiments/worklog.md"}


def uncommitted_changes():
    """Modified or untracked files, other than RUN_OUTPUTS. A game only
    records the HEAD commit, so with anything listed here that commit is
    not the code that actually ran."""
    out = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    paths = [line[3:].strip().strip('"') for line in out.splitlines() if line.strip()]
    return [p for p in paths if p not in RUN_OUTPUTS]


def row_versions(row):
    """(seller version, buyer version) of a plan row. Plans written before
    the two were split carry one prompt_version for both sides."""
    legacy = row.get("prompt_version")
    return (
        row.get("seller_prompt_version") or legacy,
        row.get("buyer_prompt_version") or legacy,
    )


def stage_log_root(stage):
    return ROOT / ".logs" / stage


def attempts_on_disk(stage, profile_name):
    """run_id -> status of every attempt logged with this model profile
    (None if it never got one, e.g. the process was killed mid-game). The
    same plan can be run once per profile, e.g. to compare models in a
    pilot."""
    attempts = defaultdict(list)
    for path in stage_log_root(stage).glob("**/game_state.json"):
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        experiment = d.get("experiment") or {}
        # Logs from before profiles existed were all gpt-4o-mini.
        if experiment.get("run_id") and experiment.get("profile", "gpt4omini") == profile_name:
            attempts[experiment["run_id"]].append((d.get("run_metadata") or {}).get("status"))
    return attempts


def logged_tokens(stages):
    """Prompt + completion tokens of every attempt already logged under
    these stages (failed ones included), so a spending cap counts what
    earlier invocations used instead of starting from zero."""
    total = 0
    for stage in stages:
        for path in stage_log_root(stage).glob("**/game_state.json"):
            try:
                meta = json.loads(path.read_text(encoding="utf-8")).get("run_metadata") or {}
            except (OSError, json.JSONDecodeError):
                continue
            total += (meta.get("prompt_tokens") or 0) + (meta.get("completion_tokens") or 0)
    return total


def read_plan(stage):
    path = plan_path(stage)
    if not path.exists():
        raise SystemExit(f"no plan at {path.relative_to(ROOT)}; run experiments.plan {stage} first")
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f)), path


def build_seller(config, row, settings, kwargs):
    """baseline: the model plays the seller after the scripted opening
    (H1). scripted_neutral: every seller turn follows the rules in
    config["scripted_seller"], no API call (experiment B)."""
    lang = row["language"]
    if row["tactic"] == "baseline":
        return FixedFirstOfferSellerAgent(
            agent_name=AGENT_ONE,
            first_offer=settings["seller_first_offer"],
            language=lang,
            prompt_version=row_versions(row)[0],
            **kwargs,
        )
    if row["tactic"] == "scripted_neutral":
        script = config["scripted_seller"]
        return ScriptedSellerAgent(
            agent_name=AGENT_ONE,
            first_offer=settings["seller_first_offer"],
            cost=settings["cost"],
            templates=script["templates"],
            language=lang,
            max_proposals=config["iterations"] // 2 - 1,
            concession_beta=script["concession_beta"],
            rounding=script["rounding"],
            buyer_funds=settings["buyer_funds"],
            script_version=script["version"],
            prompt_version=row_versions(row)[0],
        )
    raise NotImplementedError(f"tactic {row['tactic']} is not implemented yet")


def build_game(config, profile_name, row, settings):
    lang = row["language"]
    seller_version, buyer_version = row_versions(row)
    seller_goal_cls = SELLER_GOALS[(lang, seller_version)]
    buyer_goal_cls = BUYER_GOALS[(lang, buyer_version)]
    kwargs = agent_kwargs(lang, config, profile_name)
    seller = build_seller(config, row, settings, kwargs)
    buyer = ChatGPTAgent(agent_name=AGENT_TWO, **kwargs)
    # .logs/<stage>/<game_label>/<epoch_ms>/, e.g. .logs/h1/h1_001/...: a
    # retry lands next to the earlier attempt. Plans from before game
    # labels keep the older <lang>_<tactic>_<profile> folders.
    log_dir = stage_log_root(row["stage"]) / (
        row.get("game_label") or f"{lang}_{row['tactic']}_{profile_name}"
    )
    game = GAMES[lang](
        players=[seller, buyer],
        iterations=config["iterations"],
        player_goals=[
            seller_goal_cls(cost_of_production=Valuation({"X": settings["cost"]})),
            buyer_goal_cls(willingness_to_pay=Valuation({"X": settings["wtp"]})),
        ],
        player_starting_resources=[
            Resources({"X": 1}),
            Resources({MONEY_TOKEN: settings["buyer_funds"]}),
        ],
        player_conversation_roles=[
            player_role_declaration(AGENT_ONE, lang),
            player_role_declaration(AGENT_TWO, lang),
        ],
        # The game's free-text slot, appended to the end of both players'
        # rules: here the case's item and quantity (same for both).
        player_social_behaviour=[settings["case_context"], settings["case_context"]],
        log_dir=str(log_dir),
    )
    game.language = lang
    game.prompt_version = combined_label(seller_version, buyer_version)
    return game


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("stage")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the settings and both system prompts of the next run "
        "in each language, without calling the API",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=None,
        help="attempts per game, first run included (default: the stage's "
        "max_attempts in experiment_config.json, else 3)",
    )
    parser.add_argument(
        "--profile",
        help="model profile from experiment_config.json (default: its "
        "model_profile, the one formal runs use)",
    )
    parser.add_argument(
        "--budget-stages",
        help="comma-separated stages whose logged tokens (every attempt) "
        "count toward --budget-tokens before this run starts, e.g. "
        "h1_trial,h1: the cap is then cumulative and a resumed run does "
        "not start again from zero (h1_decision_record.md A19)",
    )
    add_throttle_args(parser)
    args = parser.parse_args()

    config = load_config()
    if args.max_attempts is None:
        args.max_attempts = config["stages"].get(args.stage, {}).get("max_attempts", 3)
    profile_name = args.profile or config["model_profile"]
    profile = config["model_profiles"][profile_name]
    glossary = load_glossary(config)
    plan, path = read_plan(args.stage)
    cases = {c["case_id"]: c for c in load_cases(config, {r["role"] for r in plan})}

    # T1 again, on the config as it is now: the plan may have been built
    # before a price ratio changed.
    structures_by_case = defaultdict(set)
    for row in plan:
        structures_by_case[row["case_id"]].add(row["structure"])
    t1 = [
        f"  {case_id}: {p}"
        for case_id, structures in sorted(structures_by_case.items())
        for p in t1_problems(config, cases[case_id], sorted(structures))
    ]
    if t1:
        raise SystemExit(f"{args.stage}: T1 fails for these cases:\n" + "\n".join(t1))
    hashes = {
        "config_sha256": file_sha256(CONFIG_PATH),
        "plan_sha256": file_sha256(path),
        "candidates_sha256": file_sha256(ROOT / config["candidates"]),
    }

    # Refuse a plan with a forbidden seller/buyer version pair before any
    # API call, even if the plan file was edited by hand.
    for row in plan:
        check_combination(*row_versions(row))

    # Formal stages only run from a clean tree, so the commit each game
    # records is the code that ran; pilots and smoke tests may run from a
    # dirty tree but record which files differed.
    formal = config["stages"].get(args.stage, {}).get("formal")
    changes = uncommitted_changes()
    if changes and formal and not args.dry_run:
        raise SystemExit(
            f"{args.stage} is a formal stage; commit these first, so the commit "
            "recorded with each game is the code that ran:\n  " + "\n  ".join(changes)
        )
    if changes:
        print(f"NOTE: {len(changes)} uncommitted file(s), recorded in each game's experiment.uncommitted_changes")

    attempts = attempts_on_disk(args.stage, profile_name)
    pending = [
        r for r in plan if not any(s in DONE_STATUSES for s in attempts[r["run_id"]])
    ]
    exhausted = [r for r in pending if len(attempts[r["run_id"]]) >= args.max_attempts]
    todo = [r for r in pending if len(attempts[r["run_id"]]) < args.max_attempts]
    print(
        f"{args.stage} [{profile_name}: {profile['model']}, "
        f"reasoning_effort={profile['reasoning_effort']}]: "
        f"{len(plan)} runs in plan, {len(plan) - len(pending)} done, "
        f"{len(todo)} to run, {len(exhausted)} gave up after {args.max_attempts} attempts"
    )
    official = sorted(
        {cases[r["case_id"]]["category_code"] for r in todo}
        - set(glossary)
    )
    if official:
        # The official names are unreviewed text; a formal stage must not
        # show them to the model. A dry run still prints them for review.
        if formal and not args.dry_run:
            raise SystemExit(
                f"{args.stage} is a formal stage; these category codes have no "
                f"reviewed label in {config['category_glossary']}: {official}"
            )
        print(f"NOTE: no glossary label for codes {official}; using official category names")

    if args.dry_run:
        for lang in sorted({r["language"] for r in todo}):
            row = next(r for r in todo if r["language"] == lang)
            settings = negotiation_settings(config, cases[row["case_id"]], row["structure"], lang, glossary,
                                            row_versions(row)[0])
            game = build_game(config, profile_name, row, settings)
            print(f"\n===== {row['run_id']}")
            print(json.dumps(settings, ensure_ascii=False, indent=2))
            for player in game.players:
                system = next(m["content"] for m in player.conversation if m["role"] == "system")
                print(f"\n--- {player.agent_name} system prompt ---\n{system}")
        return

    throttle = throttle_from_args(args)
    if args.budget_stages:
        budget_stages = [s.strip() for s in args.budget_stages.split(",") if s.strip()]
        throttle.total_tokens = logged_tokens(budget_stages)
        print(
            f"tokens already logged under {', '.join(budget_stages)}: {throttle.total_tokens}"
            + (f" of budget {args.budget_tokens}" if args.budget_tokens is not None else "")
        )
    games = []
    stopped = False
    for row in todo:
        label = row.get("game_label") or row["run_id"]
        settings = negotiation_settings(config, cases[row["case_id"]], row["structure"], row["language"], glossary,
                                        row_versions(row)[0])
        seller_version, buyer_version = row_versions(row)
        # Retry a failed attempt right away instead of at the next
        # invocation, so a pair's two games stay close in time.
        while True:
            try:
                throttle.check_before_game()
            except BudgetExceeded as e:
                print(f"Stopping early: {e}")
                stopped = True
                break
            throttle.wait_for_interval()

            game = build_game(config, profile_name, row, settings)
            # Serialized into game_state.json with the rest of the game.
            game.experiment = {
                "run_id": row["run_id"],
                "stage": row["stage"],
                "order": int(row["order"]),
                **(
                    {
                        "game_label": row["game_label"],
                        "game_no": int(row["game_no"]),
                        "case_no": int(row["case_no"]),
                    }
                    if row.get("game_label")
                    else {}
                ),
                "pair_id": row["pair_id"],
                "tactic": row["tactic"],
                "seller_prompt_version": seller_version,
                "buyer_prompt_version": buyer_version,
                "prompt_version": game.prompt_version,
                "language": row["language"],
                "rep": int(row["rep"]),
                "attempt": len(attempts[row["run_id"]]) + 1,
                "profile": profile_name,
                "model": profile["model"],
                "reasoning_effort": profile["reasoning_effort"],
                "temperature": profile["temperature"],
                "iterations": config["iterations"],
                "uncommitted_changes": changes,
                # The scripted seller's rules and wording, as run.
                **(
                    {"scripted_seller": config["scripted_seller"]}
                    if row["tactic"] == "scripted_neutral"
                    else {}
                ),
                **settings,
                **hashes,
            }
            print(
                f"=== [{row['order']}/{len(plan)}] {label} "
                f"B={settings['wtp']} C={settings['cost']} O={settings['seller_first_offer']} "
                f"attempt {game.experiment['attempt']} ==="
            )
            try:
                game.run()
            except Exception:
                # run() has already written game_state.json with the error status.
                traceback.print_exc()
            status = game.run_metadata.get("status")
            attempts[row["run_id"]].append(status)
            games.append(game)
            throttle.record_game(game, profile["model"])
            if status in DONE_STATUSES:
                break
            if len(attempts[row["run_id"]]) >= args.max_attempts:
                print(f"Giving up on {label}: {args.max_attempts} attempts ended in errors")
                break
            print(f"{label} ended in {status}; retrying it now")
        if stopped:
            break

    if games:
        append_run_log(
            games,
            model=profile["model"],
            temperature=profile["temperature"],
            language=",".join(sorted({g.language for g in games})),
            cost=None,
            wtp=None,
            initial_resources=None,
            seller_first_offer=None,
            prompt_version=",".join(sorted({g.prompt_version for g in games})),
            output_dir=str(stage_log_root(args.stage).relative_to(ROOT)),
        )
        backup_logs()


if __name__ == "__main__":
    main()
