import argparse
import sys
from dotenv import load_dotenv

from negotiationarena.agents.chatgpt import ChatGPTAgent
from negotiationarena.agents.scripted_seller import FixedFirstOfferSellerAgent
from negotiationarena.game_objects.resource import Resources
from negotiationarena.game_objects.goal import (
    BuyerGoalZH,
    BuyerGoalZHV11,
    SellerGoalZH,
    SellerGoalZHV2,
    SellerGoalZHV11,
)
from negotiationarena.game_objects.valuation import Valuation
from negotiationarena.constants import *
import traceback
from games.buy_sell_game_zh.game import BuySellGame
from games.player_roles import player_role_declaration
from experiments.run_logger import append_run_log
from experiments.backup import backup_logs
from experiments.throttle import add_throttle_args, throttle_from_args, BudgetExceeded
from experiments.models import agent_kwargs, profile_settings


load_dotenv(".env")

# Model settings come from experiment_config.json's default profile
# (gpt-6-luna), like every other script; see experiments/models.py.
PROFILE_NAME, PROFILE = profile_settings()
MODEL = PROFILE["model"]
TEMPERATURE = PROFILE["temperature"]
AGENT_KWARGS = agent_kwargs("zh")
COST, WTP = 40, 60
LOG_DIR = ".logs/zh_baseline_test"


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--initial-resources",
        type=int,
        default=100,
        help="Player BLUE's (buyer) starting money budget (MONEY_TOKEN).",
    )
    parser.add_argument(
        "--seller-first-offer",
        type=int,
        default=None,
        help="If set, Player RED's (seller) opening offer is fixed to this "
        "money amount by script instead of the model; the model plays "
        "from its second move onward.",
    )
    parser.add_argument(
        "--prompt-version",
        choices=["v1", "v1.1", "v2"],
        default="v1",
        help="v1 is the standard SellerGoalZH cost sentence; v1.1 is v1 "
        "with the prompt template's typo fixed, for both sides (the "
        "version H1 runs); v2 is the task04 paraphrase (same meaning, "
        "different wording), used to check if the seller's opening-price "
        "behaviour is wording-sensitive. Never overwrites v1.",
    )
    add_throttle_args(parser)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    throttle = throttle_from_args(args)

    games = []
    for i in range(1):
        c = None
        try:
            throttle.check_before_game()
        except BudgetExceeded as e:
            print(f"Stopping before next game: {e}")
            break
        throttle.wait_for_interval()
        try:
            if args.seller_first_offer is not None:
                a1 = FixedFirstOfferSellerAgent(
                    agent_name=AGENT_ONE,
                    **AGENT_KWARGS,
                    first_offer=args.seller_first_offer,
                    language="zh",
                )
            else:
                a1 = ChatGPTAgent(agent_name=AGENT_ONE, **AGENT_KWARGS)
            a2 = ChatGPTAgent(agent_name=AGENT_TWO, **AGENT_KWARGS)

            seller_goal_cls = {
                "v1": SellerGoalZH, "v1.1": SellerGoalZHV11, "v2": SellerGoalZHV2,
            }[args.prompt_version]
            buyer_goal_cls = BuyerGoalZHV11 if args.prompt_version == "v1.1" else BuyerGoalZH
            c = BuySellGame(
                players=[a1, a2],
                iterations=10,
                player_goals=[
                    seller_goal_cls(cost_of_production=Valuation({"X": COST})),
                    buyer_goal_cls(willingness_to_pay=Valuation({"X": WTP})),
                ],
                player_starting_resources=[
                    Resources({"X": 1}),
                    Resources({MONEY_TOKEN: args.initial_resources}),
                ],
                player_conversation_roles=[
                    player_role_declaration(AGENT_ONE, "zh"),
                    player_role_declaration(AGENT_TWO, "zh"),
                ],
                player_social_behaviour=[
                    "",
                    "",
                ],
                log_dir=LOG_DIR,
            )
            c.language = "zh"
            c.prompt_version = args.prompt_version

            c.run()
        except Exception as e:
            exception_type = type(e).__name__
            exception_message = str(e)
            stack_trace = traceback.format_exc()

            # Print or use the information as needed
            print(f"Exception Type: {exception_type}")
            print(f"Exception Message: {exception_message}")
            print(f"Stack Trace:\n{stack_trace}")
        finally:
            if c is not None:
                games.append(c)
                throttle.record_game(c, MODEL)

    append_run_log(
        games,
        model=MODEL,
        temperature=TEMPERATURE,
        language="zh",
        cost=COST,
        wtp=WTP,
        initial_resources=args.initial_resources,
        seller_first_offer=args.seller_first_offer,
        prompt_version=args.prompt_version,
        output_dir=LOG_DIR,
    )
    backup_logs()
