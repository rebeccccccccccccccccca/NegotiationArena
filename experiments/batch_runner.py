"""
Run the games of a stage plan (experiments/plans/<stage>.csv, written by
experiments/plan.py), one game per plan row, in plan order.

Resumable: a run counts as done once a game_state.json under
.logs/<stage>/ carries its run_id with status ok, max_rounds or rejected.
Runs that ended in api_error / parse_error are retried, up to --max-attempts in
total; every attempt keeps its own log and its number in
experiment.attempt, so the retry count per run is on record.

Each game's settings (case, price structure, C, O, buyer funds, context
sentence, model, and the SHA-256 of the config, plan and candidate pool
it came from) are stored in game_state.json under `experiment`, next to
the usual run_metadata.

Usage (from the repo root):
  .venv\\Scripts\\python -m experiments.batch_runner h1 --dry-run
  .venv\\Scripts\\python -m experiments.batch_runner h1 --max-games-per-run 20
"""

import argparse
import csv
import json
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
)
from experiments.plan import plan_path
from experiments.run_logger import append_run_log
from experiments.throttle import BudgetExceeded, add_throttle_args, throttle_from_args
from games.buy_sell_game.game import BuySellGame as BuySellGameEN
from games.buy_sell_game_zh.game import BuySellGame as BuySellGameZH
from games.player_roles import player_role_declaration
from negotiationarena.agents.chatgpt import ChatGPTAgent
from negotiationarena.agents.scripted_seller import FixedFirstOfferSellerAgent
from negotiationarena.constants import AGENT_ONE, AGENT_TWO, MONEY_TOKEN
from negotiationarena.game_objects.goal import (
    BuyerGoal,
    BuyerGoalZH,
    SellerGoal,
    SellerGoalZH,
)
from negotiationarena.game_objects.resource import Resources
from negotiationarena.game_objects.valuation import Valuation

load_dotenv(ROOT / ".env")

GAMES = {"en": BuySellGameEN, "zh": BuySellGameZH}
# (language, prompt_version) -> (seller goal, buyer goal)
GOALS = {
    ("en", "v1"): (SellerGoal, BuyerGoal),
    ("zh", "v1"): (SellerGoalZH, BuyerGoalZH),
}
DONE_STATUSES = ("ok", "max_rounds", "rejected")


def stage_log_root(stage):
    return ROOT / ".logs" / stage


def attempts_on_disk(stage):
    """run_id -> status of every logged attempt (None if it never got one,
    e.g. the process was killed mid-game)."""
    attempts = defaultdict(list)
    for path in stage_log_root(stage).glob("**/game_state.json"):
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        run_id = (d.get("experiment") or {}).get("run_id")
        if run_id:
            attempts[run_id].append((d.get("run_metadata") or {}).get("status"))
    return attempts


def read_plan(stage):
    path = plan_path(stage)
    if not path.exists():
        raise SystemExit(f"no plan at {path.relative_to(ROOT)}; run experiments.plan {stage} first")
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f)), path


def build_game(config, row, settings):
    lang = row["language"]
    if row["tactic"] != "baseline":
        raise NotImplementedError(f"tactic {row['tactic']} is not implemented yet")
    seller_goal_cls, buyer_goal_cls = GOALS[(lang, row["prompt_version"])]
    agent_kwargs = dict(
        model=config["model"],
        temperature=config["temperature"],
        max_tokens=config["max_tokens"][lang],
    )
    seller = FixedFirstOfferSellerAgent(
        agent_name=AGENT_ONE,
        first_offer=settings["seller_first_offer"],
        language=lang,
        **agent_kwargs,
    )
    buyer = ChatGPTAgent(agent_name=AGENT_TWO, **agent_kwargs)
    log_dir = stage_log_root(row["stage"]) / f"{lang}_{row['tactic']}_{config['model_short']}"
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
    game.prompt_version = row["prompt_version"]
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
    parser.add_argument("--max-attempts", type=int, default=3)
    add_throttle_args(parser)
    args = parser.parse_args()

    config = load_config()
    glossary = load_glossary(config)
    plan, path = read_plan(args.stage)
    cases = {c["case_id"]: c for c in load_cases(config, {r["role"] for r in plan})}
    hashes = {
        "config_sha256": file_sha256(CONFIG_PATH),
        "plan_sha256": file_sha256(path),
        "candidates_sha256": file_sha256(ROOT / config["candidates"]),
    }

    attempts = attempts_on_disk(args.stage)
    pending = [
        r for r in plan if not any(s in DONE_STATUSES for s in attempts[r["run_id"]])
    ]
    exhausted = [r for r in pending if len(attempts[r["run_id"]]) >= args.max_attempts]
    todo = [r for r in pending if len(attempts[r["run_id"]]) < args.max_attempts]
    print(
        f"{args.stage}: {len(plan)} runs in plan, {len(plan) - len(pending)} done, "
        f"{len(todo)} to run, {len(exhausted)} gave up after {args.max_attempts} attempts"
    )
    official = sorted(
        {cases[r["case_id"]]["category_code"] for r in todo}
        - set(glossary)
    )
    if official:
        print(f"NOTE: no glossary label for codes {official}; using official category names")

    if args.dry_run:
        for lang in sorted({r["language"] for r in todo}):
            row = next(r for r in todo if r["language"] == lang)
            settings = negotiation_settings(config, cases[row["case_id"]], row["structure"], lang, glossary)
            game = build_game(config, row, settings)
            print(f"\n===== {row['run_id']}")
            print(json.dumps(settings, ensure_ascii=False, indent=2))
            for player in game.players:
                system = next(m["content"] for m in player.conversation if m["role"] == "system")
                print(f"\n--- {player.agent_name} system prompt ---\n{system}")
        return

    throttle = throttle_from_args(args)
    games = []
    for row in todo:
        try:
            throttle.check_before_game()
        except BudgetExceeded as e:
            print(f"Stopping early: {e}")
            break
        throttle.wait_for_interval()

        settings = negotiation_settings(config, cases[row["case_id"]], row["structure"], row["language"], glossary)
        game = build_game(config, row, settings)
        # Serialized into game_state.json with the rest of the game.
        game.experiment = {
            "run_id": row["run_id"],
            "stage": row["stage"],
            "order": int(row["order"]),
            "pair_id": row["pair_id"],
            "tactic": row["tactic"],
            "prompt_version": row["prompt_version"],
            "language": row["language"],
            "rep": int(row["rep"]),
            "attempt": len(attempts[row["run_id"]]) + 1,
            "model": config["model"],
            "iterations": config["iterations"],
            **settings,
            **hashes,
        }
        print(
            f"=== [{row['order']}/{len(plan)}] {row['run_id']} "
            f"B={settings['wtp']} C={settings['cost']} O={settings['seller_first_offer']} "
            f"attempt {game.experiment['attempt']} ==="
        )
        try:
            game.run()
        except Exception:
            # run() has already written game_state.json with the error status.
            traceback.print_exc()
        attempts[row["run_id"]].append(game.run_metadata.get("status"))
        games.append(game)
        throttle.record_game(game, config["model"])

    if games:
        append_run_log(
            games,
            model=config["model"],
            temperature=config["temperature"],
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
