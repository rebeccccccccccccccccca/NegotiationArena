"""
Offline tests of experiment B's fully scripted seller
(negotiationarena/agents/scripted_seller.py): price path, reading the
buyer's offer, accept/reject rules, output format, and whole games
against a scripted fake buyer. No API call is made.

Run with: python -m unittest tests/test_scripted_seller.py
"""

import contextlib
import io
import json
import os
import tempfile
import unittest

os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")

from experiments.cases import load_config
from games.buy_sell_game.game import BuySellGame as BuySellGameEN
from games.buy_sell_game.game import BuySellGameDefaultParser
from games.buy_sell_game_zh.game import BuySellGame as BuySellGameZH
from games.player_roles import player_role_declaration
from negotiationarena.agents.agents import Agent
from negotiationarena.agents.scripted_seller import (
    FixedFirstOfferSellerAgent,
    ScriptedSellerAgent,
    buyer_offer,
    concession_path,
)
from negotiationarena.constants import AGENT_ONE, AGENT_TWO, MONEY_TOKEN
from negotiationarena.game_objects.goal import BuyerGoal, BuyerGoalZH, SellerGoal, SellerGoalZH
from negotiationarena.game_objects.resource import Resources
from negotiationarena.game_objects.valuation import Valuation

# A narrow-structure case: B = 1,000,000, C = 0.8889 B, O = 1.1111 B.
B, C, O, FUNDS = 1_000_000, 888_900, 1_111_100, 2_000_000
TEMPLATES = load_config()["scripted_seller"]["templates"]


def buyer_public(answer="PROPOSAL", price=None, trade=None, message="hi"):
    """The buyer's turn as the seller is shown it (message_to_other_player)."""
    if trade is None:
        trade = "NONE" if price is None else f"Player RED Gives X: 1 | Player BLUE Gives {MONEY_TOKEN}: {price}"
    return (
        f"<message> {message} </message>\n"
        f"<player answer> {answer} </player answer>\n"
        f"<newly proposed trade> {trade} </newly proposed trade>"
    )


def new_seller(language="en", **kw):
    seller = ScriptedSellerAgent(
        agent_name=AGENT_ONE, first_offer=O, cost=C, templates=TEMPLATES,
        language=language, buyer_funds=FUNDS, **kw,
    )
    seller.init_agent("<my goals> Sell resources. </my goals>", "You are Player RED.")
    return seller


class TestConcessionPath(unittest.TestCase):
    def test_linear_path(self):
        asks = concession_path(O, C, 9)
        self.assertEqual(asks[0], O)  # the opening, unrounded
        self.assertEqual(asks[4], B)  # 5th proposal reaches the budget
        self.assertEqual(asks[-1], 889_000)  # cost rounded up to 1,000
        self.assertEqual(len(asks), 9)
        self.assertTrue(all(a >= b for a, b in zip(asks, asks[1:])))
        self.assertTrue(all(a >= C for a in asks))
        self.assertTrue(all(a % 1000 == 0 for a in asks[1:]))

    def test_beta_shapes(self):
        boulware, linear, conceder = (concession_path(O, C, 9, beta) for beta in (0.5, 1.0, 2.0))
        self.assertGreater(boulware[2], linear[2])
        self.assertLess(conceder[2], linear[2])
        self.assertEqual(boulware[-1], linear[-1])


class TestBuyerOffer(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(buyer_offer(buyer_public(price=950_000), FUNDS), 950_000)

    def test_swapped_order_still_valid(self):
        trade = f"Player BLUE Gives {MONEY_TOKEN}: 950000 | Player RED Gives X: 1"
        self.assertEqual(buyer_offer(buyer_public(trade=trade), FUNDS), 950_000)

    def test_invalid(self):
        cases = {
            "no proposal": buyer_public(answer="NONE", price=950_000),
            "trade NONE": buyer_public(),
            "two X": buyer_public(trade=f"Player RED Gives X: 2 | Player BLUE Gives {MONEY_TOKEN}: 950000"),
            "buyer gives X": buyer_public(trade=f"Player RED Gives {MONEY_TOKEN}: 5 | Player BLUE Gives X: 1"),
            "above funds": buyer_public(price=FUNDS + 1),
            "zero": buyer_public(price=0),
            "garbled": buyer_public(trade="I offer nine hundred thousand"),
            "empty": "",
        }
        for name, message in cases.items():
            with self.subTest(name):
                self.assertIsNone(buyer_offer(message, FUNDS))


class TestDecisions(unittest.TestCase):
    def test_counters_then_accepts_at_own_ask(self):
        seller = new_seller()
        parse = BuySellGameDefaultParser().parse
        first = parse(seller.step(None))
        self.assertEqual(first.public["player answer"], "PROPOSAL")
        # Offer 950,000: below asks 2-6 (1,083,000 ... 972,000), at or
        # above ask 7 (944,000), so accepted on the seller's 7th turn.
        for turn in range(2, 8):
            response = parse(seller.step(buyer_public(price=950_000)))
            expected = "ACCEPT" if turn == 7 else "PROPOSAL"
            self.assertEqual(response.public["player answer"], expected, turn)
        self.assertEqual([d["action"] for d in seller.decisions][-1], "ACCEPT")

    def test_offer_above_current_ask_is_accepted_at_once(self):
        seller = new_seller()
        seller.step(None)
        response = BuySellGameDefaultParser().parse(seller.step(buyer_public(price=O + 1000)))
        self.assertEqual(response.public["player answer"], "ACCEPT")

    def test_invalid_move_gets_next_proposal(self):
        seller = new_seller()
        seller.step(None)
        response = BuySellGameDefaultParser().parse(seller.step(buyer_public()))
        self.assertEqual(response.public["player answer"], "PROPOSAL")
        self.assertEqual(response.public["newly proposed trade"].resources_from_second_agent.resource_dict,
                         {MONEY_TOKEN: 1_083_000})

    def test_last_turn(self):
        for offer, expected in ((C, "ACCEPT"), (C - 1, "REJECT"), (None, "REJECT")):
            with self.subTest(offer=offer):
                seller = new_seller()
                seller.step(None)
                for _ in range(2, 10):  # turns 2-9: always below the ask
                    seller.step(buyer_public(price=800_000))
                last = buyer_public(price=offer) if offer else buyer_public()
                response = BuySellGameDefaultParser().parse(seller.step(last))
                self.assertEqual(response.public["player answer"], expected)
                self.assertEqual(seller.proposals_made, 9)

    def test_messages_never_mention_cost_and_cycle_in_step(self):
        for lang in ("en", "zh"):
            seller = new_seller(lang)
            seller.step(None)
            messages = [
                BuySellGameDefaultParser().parse(seller.step(buyer_public(price=800_000))).public["message"]
                for _ in range(2, 8)
            ]
            variants = [v.format(price=a, money=MONEY_TOKEN)
                        for v, a in zip(TEMPLATES[lang]["counter"] * 2, concession_path(O, C, 9)[1:7])]
            self.assertEqual(messages, variants)
            self.assertFalse(any(str(C) in m for m in messages))


class TestOpeningMatchesH1(unittest.TestCase):
    def test_same_first_turn(self):
        for lang in ("en", "zh"):
            h1 = FixedFirstOfferSellerAgent(agent_name=AGENT_ONE, first_offer=O, language=lang)
            h1.init_agent("<my goals> Sell resources. </my goals>", "You are Player RED.")
            self.assertEqual(new_seller(lang).step(None), h1.chat(), lang)


class FakeBuyer(Agent):
    """Answers with a fixed list of moves: a price (PROPOSAL) or ACCEPT."""

    def __init__(self, moves):
        super().__init__(AGENT_TWO)
        self.moves, self.conversation, self.prompt_entity_initializer = list(moves), [], "system"
        self.run_epoch_time_ms = "0"

    def update_conversation_tracking(self, role, message):
        self.conversation.append({"role": role, "content": message})

    def chat(self):
        move = self.moves.pop(0)
        answer, trade = (
            ("ACCEPT", "NONE") if move == "ACCEPT"
            else ("PROPOSAL", f"Player RED Gives X: 1 | Player BLUE Gives {MONEY_TOKEN}: {move}")
        )
        return (
            "<proposal count> 1 </proposal count>\n"
            f"<my resources> {MONEY_TOKEN}: {FUNDS} </my resources>\n"
            "<my goals> buy </my goals>\n<reason> r </reason>\n"
            f"<player answer> {answer} </player answer>\n"
            f"<newly proposed trade> {trade} </newly proposed trade>\n"
            "<message> m </message>"
        )


def play(language, moves):
    game_cls, seller_goal, buyer_goal = (
        (BuySellGameEN, SellerGoal, BuyerGoal) if language == "en" else (BuySellGameZH, SellerGoalZH, BuyerGoalZH)
    )
    with tempfile.TemporaryDirectory() as log_dir, contextlib.redirect_stdout(io.StringIO()):
        game = game_cls(
            players=[new_seller(language), FakeBuyer(moves)],
            iterations=20,
            player_goals=[seller_goal(cost_of_production=Valuation({"X": C})),
                          buyer_goal(willingness_to_pay=Valuation({"X": B}))],
            player_starting_resources=[Resources({"X": 1}), Resources({MONEY_TOKEN: FUNDS})],
            player_conversation_roles=[player_role_declaration(AGENT_ONE, language),
                                       player_role_declaration(AGENT_TWO, language)],
            player_social_behaviour=["", ""],
            log_dir=log_dir,
        )
        game.run()
        with open(os.path.join(game.log_path, "game_state.json"), encoding="utf-8") as f:
            saved = json.load(f)
    return game, saved


class TestWholeGames(unittest.TestCase):
    def test_deal_when_ask_meets_offer(self):
        for lang in ("en", "zh"):
            game, saved = play(lang, [900_000] * 10)
            self.assertEqual(game.run_metadata["status"], "ok")
            summary = game.game_state[-1]["summary"]
            self.assertEqual(summary["proposed_trade"].resources_from_second_agent.resource_dict[MONEY_TOKEN], 900_000)
            # accepted on the seller's 9th turn = game iteration 17
            self.assertEqual(game.game_state[-2]["current_iteration"], 17)
            red = next(p for p in saved["players"] if p["agent_name"] == AGENT_ONE)
            self.assertEqual(red["decisions"][-1]["action"], "ACCEPT")

    def test_rejected_below_cost(self):
        game, _ = play("en", [800_000] * 10)
        self.assertEqual(game.run_metadata["status"], "rejected")
        self.assertEqual(game.game_state[-2]["current_iteration"], 19)

    def test_buyer_accepts_opening(self):
        game, _ = play("zh", ["ACCEPT"])
        self.assertEqual(game.run_metadata["status"], "ok")
        summary = game.game_state[-1]["summary"]
        self.assertEqual(summary["proposed_trade"].resources_from_second_agent.resource_dict[MONEY_TOKEN], O)


if __name__ == "__main__":
    unittest.main()
