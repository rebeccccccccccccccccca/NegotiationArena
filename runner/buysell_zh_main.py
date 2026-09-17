import argparse
import sys
from dotenv import load_dotenv

from negotiationarena.agents.chatgpt import ChatGPTAgent
from negotiationarena.agents.scripted_seller import FixedFirstOfferSellerAgent
from negotiationarena.game_objects.resource import Resources
from negotiationarena.game_objects.goal import BuyerGoalZH, SellerGoalZH
from negotiationarena.game_objects.valuation import Valuation
from negotiationarena.constants import *
import traceback
from games.buy_sell_game_zh.game import BuySellGame
from experiments.run_logger import append_run_log, infer_prompt_version
from experiments.backup import backup_logs


load_dotenv(".env")

MODEL = "gpt-4o-mini-2024-07-18"
TEMPERATURE = 0.7
COST, WTP = 40, 60
LOG_DIR = ".logs/zh_baseline_test"


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--initial-resources",
        type=int,
        default=100,
        help="Player BLUE's (buyer) starting ZUP budget.",
    )
    parser.add_argument(
        "--seller-first-offer",
        type=int,
        default=None,
        help="If set, Player RED's (seller) opening offer is fixed to this "
        "ZUP amount by script instead of the model; the model plays "
        "from its second move onward.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    games = []
    for i in range(1):
        c = None
        try:
            if args.seller_first_offer is not None:
                a1 = FixedFirstOfferSellerAgent(
                    agent_name=AGENT_ONE,
                    model=MODEL,
                    temperature=TEMPERATURE,
                    max_tokens=600,
                    first_offer=args.seller_first_offer,
                )
            else:
                a1 = ChatGPTAgent(
                    agent_name=AGENT_ONE,
                    model=MODEL,
                    temperature=TEMPERATURE,
                    max_tokens=600,
                )
            a2 = ChatGPTAgent(
                agent_name=AGENT_TWO,
                model=MODEL,
                temperature=TEMPERATURE,
                max_tokens=600,
            )

            c = BuySellGame(
                players=[a1, a2],
                iterations=10,
                player_goals=[
                    SellerGoalZH(cost_of_production=Valuation({"X": COST})),
                    BuyerGoalZH(willingness_to_pay=Valuation({"X": WTP})),
                ],
                player_starting_resources=[
                    Resources({"X": 1}),
                    Resources({MONEY_TOKEN: args.initial_resources}),
                ],
                player_conversation_roles=[
                    f"你是 {AGENT_ONE}。",
                    f"你是 {AGENT_TWO}。",
                ],
                player_social_behaviour=[
                    "",
                    "",
                ],
                log_dir=LOG_DIR,
            )

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

    prompt_version = (
        infer_prompt_version(games[0].players[0].conversation[0]["content"])
        if games
        else None
    )
    append_run_log(
        games,
        model=MODEL,
        temperature=TEMPERATURE,
        language="zh",
        cost=COST,
        wtp=WTP,
        initial_resources=args.initial_resources,
        seller_first_offer=args.seller_first_offer,
        prompt_version=prompt_version,
        output_dir=LOG_DIR,
    )
    backup_logs()
