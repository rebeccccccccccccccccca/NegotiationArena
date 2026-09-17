"""
post_fix pilot data collection: baseline_v2 (prompt v1, free seller
opening) and rephrase_check (prompt v2 -- task04's cost-sentence
paraphrase, free seller opening). Same model/temperature/
initial_resources as the seller-anchor probe (see
probe_seller_anchor.py): gpt-4o-mini-2024-07-18, temp 0.7,
initial_resources=100, Cost40/WTP60.

Writes to .logs/baseline_v2/ and .logs/rephrase_check/ (language-split by
game_id / prompt_version, not by subfolder -- there's only one condition
per batch here, unlike the probe's per-condition subfolders).
"""

import argparse
import traceback

from dotenv import load_dotenv

from negotiationarena.agents.chatgpt import ChatGPTAgent
from negotiationarena.game_objects.resource import Resources
from negotiationarena.game_objects.goal import (
    BuyerGoal,
    SellerGoal,
    SellerGoalV2,
    BuyerGoalZH,
    SellerGoalZH,
    SellerGoalZHV2,
)
from negotiationarena.game_objects.valuation import Valuation
from negotiationarena.constants import *
from games.buy_sell_game.game import BuySellGame as BuySellGameEN
from games.buy_sell_game_zh.game import BuySellGame as BuySellGameZH
from experiments.run_logger import append_run_log, infer_prompt_version
from experiments.backup import backup_logs
from experiments.throttle import add_throttle_args, throttle_from_args, BudgetExceeded

load_dotenv(".env")

MODEL = "gpt-4o-mini-2024-07-18"
TEMPERATURE = 0.7
INITIAL_RESOURCES = 100
COST, WTP = 40, 60
REPS = 6

# (batch name, prompt_version, log_dir)
BATCHES = [
    ("baseline_v2", "v1", ".logs/baseline_v2"),
    ("rephrase_check", "v2", ".logs/rephrase_check"),
]


def run_one(lang, prompt_version, log_dir):
    if lang == "en":
        game_cls = BuySellGameEN
        seller_goal_cls = SellerGoal if prompt_version == "v1" else SellerGoalV2
        buyer_goal_cls = BuyerGoal
        red_role, blue_role = f"You are {AGENT_ONE}.", f"You are {AGENT_TWO}."
        max_tokens = 400
    else:
        game_cls = BuySellGameZH
        seller_goal_cls = (
            SellerGoalZH if prompt_version == "v1" else SellerGoalZHV2
        )
        buyer_goal_cls = BuyerGoalZH
        red_role, blue_role = f"你是 {AGENT_ONE}。", f"你是 {AGENT_TWO}。"
        max_tokens = 600

    a1 = ChatGPTAgent(
        agent_name=AGENT_ONE, model=MODEL, temperature=TEMPERATURE, max_tokens=max_tokens
    )
    a2 = ChatGPTAgent(
        agent_name=AGENT_TWO, model=MODEL, temperature=TEMPERATURE, max_tokens=max_tokens
    )

    game = game_cls(
        players=[a1, a2],
        iterations=10,
        player_goals=[
            seller_goal_cls(cost_of_production=Valuation({"X": COST})),
            buyer_goal_cls(willingness_to_pay=Valuation({"X": WTP})),
        ],
        player_starting_resources=[
            Resources({"X": 1}),
            Resources({MONEY_TOKEN: INITIAL_RESOURCES}),
        ],
        player_conversation_roles=[red_role, blue_role],
        player_social_behaviour=["", ""],
        log_dir=log_dir,
    )
    game.language = lang
    try:
        game.run()
    except Exception:
        traceback.print_exc()
    return game


def log_batch(games, lang, log_dir):
    detected_version = infer_prompt_version(
        games[0].players[0].conversation[0]["content"]
    )
    append_run_log(
        games,
        model=MODEL,
        temperature=TEMPERATURE,
        language=lang,
        cost=COST,
        wtp=WTP,
        initial_resources=INITIAL_RESOURCES,
        seller_first_offer=None,
        prompt_version=detected_version,
        output_dir=log_dir,
    )


def parse_args():
    parser = argparse.ArgumentParser()
    add_throttle_args(parser)
    return parser.parse_args()


def main(throttle):
    for name, prompt_version, log_dir in BATCHES:
        for lang in ("en", "zh"):
            games = []
            for rep in range(REPS):
                try:
                    throttle.check_before_game()
                except BudgetExceeded as e:
                    print(f"Stopping early: {e}")
                    if games:
                        log_batch(games, lang, log_dir)
                    backup_logs()
                    return
                throttle.wait_for_interval()

                print(
                    f"=== {name}/{lang} prompt_version={prompt_version} "
                    f"rep {rep + 1}/{REPS} ==="
                )
                game = run_one(lang, prompt_version, log_dir)
                games.append(game)
                throttle.record_game(game, MODEL)

            log_batch(games, lang, log_dir)

    backup_logs()


if __name__ == "__main__":
    main(throttle_from_args(parse_args()))
