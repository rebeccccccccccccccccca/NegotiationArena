import argparse
import sys
from dotenv import load_dotenv

from negotiationarena.agents.chatgpt import ChatGPTAgent
from negotiationarena.agents.scripted_seller import FixedFirstOfferSellerAgent
from negotiationarena.game_objects.resource import Resources
from negotiationarena.game_objects.goal import BuyerGoal, SellerGoal, SellerGoalV2
from negotiationarena.game_objects.valuation import Valuation
from negotiationarena.constants import *
import traceback
from games.buy_sell_game.game import BuySellGame
from experiments.run_logger import append_run_log, infer_prompt_version
from experiments.backup import backup_logs
from experiments.throttle import add_throttle_args, throttle_from_args, BudgetExceeded


load_dotenv(".env")

MODEL = "gpt-4o-mini-2024-07-18"
TEMPERATURE = 0.7
COST, WTP = 40, 60
LOG_DIR = ".logs/en_baseline_test"


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
    parser.add_argument(
        "--prompt-version",
        choices=["v1", "v2"],
        default="v1",
        help="v1 is the standard SellerGoal cost sentence; v2 is the "
        "task04 paraphrase (same meaning, different wording), used to "
        "check if the seller's opening-price behaviour is wording-"
        "sensitive. Never overwrites v1.",
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
                    model=MODEL,
                    temperature=TEMPERATURE,
                    first_offer=args.seller_first_offer,
                    language="en",
                )
            else:
                a1 = ChatGPTAgent(
                    agent_name=AGENT_ONE, model=MODEL, temperature=TEMPERATURE
                )
            a2 = ChatGPTAgent(
                agent_name=AGENT_TWO, model=MODEL, temperature=TEMPERATURE
            )

            seller_goal_cls = SellerGoal if args.prompt_version == "v1" else SellerGoalV2
            c = BuySellGame(
                players=[a1, a2],
                iterations=10,
                player_goals=[
                    seller_goal_cls(cost_of_production=Valuation({"X": COST})),
                    BuyerGoal(willingness_to_pay=Valuation({"X": WTP})),
                ],
                player_starting_resources=[
                    Resources({"X": 1}),
                    Resources({MONEY_TOKEN: args.initial_resources}),
                ],
                player_conversation_roles=[
                    f"You are {AGENT_ONE}.",
                    f"You are {AGENT_TWO}.",
                ],
                player_social_behaviour=[
                    "",
                    "",
                ],
                log_dir=LOG_DIR,
            )
            c.language = "en"

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

    prompt_version = (
        infer_prompt_version(games[0].players[0].conversation[0]["content"])
        if games
        else None
    )
    append_run_log(
        games,
        model=MODEL,
        temperature=TEMPERATURE,
        language="en",
        cost=COST,
        wtp=WTP,
        initial_resources=args.initial_resources,
        seller_first_offer=args.seller_first_offer,
        prompt_version=prompt_version,
        output_dir=LOG_DIR,
    )
    backup_logs()
