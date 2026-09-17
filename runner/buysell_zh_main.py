import sys
from dotenv import load_dotenv

from negotiationarena.agents.chatgpt import ChatGPTAgent
from negotiationarena.game_objects.resource import Resources
from negotiationarena.game_objects.goal import BuyerGoalZH, SellerGoalZH
from negotiationarena.game_objects.valuation import Valuation
from negotiationarena.constants import *
import traceback
from games.buy_sell_game_zh.game import BuySellGame


load_dotenv(".env")


if __name__ == "__main__":
    for i in range(1):
        try:
            a1 = ChatGPTAgent(
                agent_name=AGENT_ONE, model="gpt-4o-mini", max_tokens=600
            )
            a2 = ChatGPTAgent(
                agent_name=AGENT_TWO, model="gpt-4o-mini", max_tokens=600
            )

            c = BuySellGame(
                players=[a1, a2],
                iterations=10,
                player_goals=[
                    SellerGoalZH(cost_of_production=Valuation({"X": 40})),
                    BuyerGoalZH(willingness_to_pay=Valuation({"X": 60})),
                ],
                player_starting_resources=[
                    Resources({"X": 1}),
                    Resources({MONEY_TOKEN: 1000}),
                ],
                player_conversation_roles=[
                    f"你是 {AGENT_ONE}。",
                    f"你是 {AGENT_TWO}。",
                ],
                player_social_behaviour=[
                    "",
                    "",
                ],
                log_dir=".logs/zh_baseline_test",
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
