"""
Probe: with the seller's opening offer scripted to a fixed ZUP amount
(FixedFirstOfferSellerAgent), how does the buyer respond across three
cost/wtp regimes and two languages?

Does not touch runner/ or any prompt file. Reuses the existing
games/buy_sell_game(_zh) games and Buyer/SellerGoal classes unchanged;
only the seller's first move is scripted, every later move (including all
of the buyer's moves) is a normal API call.

Writes to .logs/probe_v2/<lang>_<condition>/<epoch_ms>/. Run
experiments/summarize.py afterwards to fold these runs into results.csv
along with everything else already under .logs/.
"""

import time
import traceback

from dotenv import load_dotenv

from negotiationarena.agents.chatgpt import ChatGPTAgent
from negotiationarena.agents.scripted_seller import FixedFirstOfferSellerAgent
from negotiationarena.game_objects.resource import Resources
from negotiationarena.game_objects.goal import (
    BuyerGoal,
    SellerGoal,
    BuyerGoalZH,
    SellerGoalZH,
)
from negotiationarena.game_objects.valuation import Valuation
from negotiationarena.constants import *
from games.buy_sell_game.game import BuySellGame as BuySellGameEN
from games.buy_sell_game_zh.game import BuySellGame as BuySellGameZH
from experiments.run_logger import append_run_log, infer_prompt_version
from experiments.backup import backup_logs

load_dotenv(".env")

INITIAL_RESOURCES = 100
MODEL = "gpt-4o-mini-2024-07-18"
TEMPERATURE = 0.7
REPS = 3
LOG_ROOT = ".logs/probe_v2"

# condition -> (cost, wtp, seller_first_offer)
CONDITIONS = {
    "wide": (40, 60, 50),  # normal range
    "narrow": (40, 45, 50),  # tight range
    "no_range": (60, 40, 65),  # cost > wtp, no valid deal exists
}


def run_one(lang, condition, cost, wtp, seller_first_offer):
    if lang == "en":
        game_cls = BuySellGameEN
        seller_goal_cls, buyer_goal_cls = SellerGoal, BuyerGoal
        red_role, blue_role = f"You are {AGENT_ONE}.", f"You are {AGENT_TWO}."
        max_tokens = 400
    else:
        game_cls = BuySellGameZH
        seller_goal_cls, buyer_goal_cls = SellerGoalZH, BuyerGoalZH
        red_role, blue_role = f"你是 {AGENT_ONE}。", f"你是 {AGENT_TWO}。"
        max_tokens = 600

    a1 = FixedFirstOfferSellerAgent(
        agent_name=AGENT_ONE,
        model=MODEL,
        temperature=TEMPERATURE,
        max_tokens=max_tokens,
        first_offer=seller_first_offer,
        language=lang,
    )
    a2 = ChatGPTAgent(
        agent_name=AGENT_TWO,
        model=MODEL,
        temperature=TEMPERATURE,
        max_tokens=max_tokens,
    )

    game = game_cls(
        players=[a1, a2],
        iterations=10,
        player_goals=[
            seller_goal_cls(cost_of_production=Valuation({"X": cost})),
            buyer_goal_cls(willingness_to_pay=Valuation({"X": wtp})),
        ],
        player_starting_resources=[
            Resources({"X": 1}),
            Resources({MONEY_TOKEN: INITIAL_RESOURCES}),
        ],
        player_conversation_roles=[red_role, blue_role],
        player_social_behaviour=["", ""],
        log_dir=f"{LOG_ROOT}/{lang}_{condition}",
    )
    try:
        game.run()
    except Exception:
        traceback.print_exc()
    return game


def main():
    for lang in ("en", "zh"):
        for condition, (cost, wtp, seller_first_offer) in CONDITIONS.items():
            games = []
            for rep in range(REPS):
                print(
                    f"=== {lang}/{condition} cost={cost} wtp={wtp} "
                    f"first_offer={seller_first_offer} rep {rep + 1}/{REPS} ==="
                )
                games.append(
                    run_one(lang, condition, cost, wtp, seller_first_offer)
                )
                time.sleep(1)

            prompt_version = infer_prompt_version(
                games[0].players[0].conversation[0]["content"]
            )
            append_run_log(
                games,
                model=MODEL,
                temperature=TEMPERATURE,
                language=lang,
                cost=cost,
                wtp=wtp,
                initial_resources=INITIAL_RESOURCES,
                seller_first_offer=seller_first_offer,
                prompt_version=prompt_version,
                output_dir=f"{LOG_ROOT}/{lang}_{condition}",
            )

    backup_logs()


if __name__ == "__main__":
    main()
