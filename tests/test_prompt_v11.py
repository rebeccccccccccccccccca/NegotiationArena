"""Offline checks of prompt v1.1 (h1_decision_record.md A13, A16): the
aligned bilingual wording, the scripted opening and context sentence per
version, and a whole game that parses in both languages. No model call."""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "offline-test-not-used")

import experiments.batch_runner as br
from experiments.cases import load_cases, load_config, negotiation_settings
from experiments.goal_versions import BUYER_GOALS, SELLER_GOALS
from experiments.render_prompts import render
from experiments.summarize import prompt_template_check
from games.buy_sell_game.prompt import buy_sell_prompt as prompt_en
from games.buy_sell_game_zh.prompt import buy_sell_prompt as prompt_zh
from negotiationarena.agents.chatgpt import ChatGPTAgent
from negotiationarena.agents.scripted_seller import scripted_opening_message
from negotiationarena.game_objects.resource import Resources
from negotiationarena.game_objects.valuation import Valuation
from tests.test_scripted_seller import FakeBuyer

TAGS = ("proposal count", "my resources", "my goals", "reason",
        "player answer", "newly proposed trade", "message")


class TestPromptV11(unittest.TestCase):
    def setUp(self):
        self.config = load_config()
        self.case = load_cases(self.config, {"calibration"})[0]
        self.glossary = {self.case["category_code"]: {"label_zh": "家具", "label_en": "furniture"}}

    def test_goals_show_plain_integer_amounts(self):
        for lang in ("en", "zh"):
            for table, amount in ((SELLER_GOALS, 440000), (BUYER_GOALS, 550000)):
                goal = table[(lang, "v1.1")](Valuation({"X": amount}))
                self.assertIn(f"{amount} TWD", str(goal))
                self.assertNotIn("X:", str(goal))
                self.assertEqual(goal.json()["_value"]["_value"], {"X": amount})
                self.assertTrue(goal.json()["_type"].endswith("v1_1"))

    def test_v1_goals_keep_valuation_format(self):
        for lang in ("en", "zh"):
            goal = SELLER_GOALS[(lang, "v1")](Valuation({"X": 440000}))
            self.assertIn("X: 440000 TWD", str(goal))

    def test_opening_message_per_version(self):
        self.assertEqual(scripted_opening_message("en", 632500), "I am offering the object for 632500 TWD.")
        self.assertEqual(scripted_opening_message("zh", 632500, "v1"), "我以 632500 TWD 出售這件物品。")
        self.assertEqual(scripted_opening_message("en", 632500, "v1.1"), "My asking price for the object is 632500 TWD.")
        self.assertEqual(scripted_opening_message("zh", 632500, "v1.1"), "我對這件物品的開價是 632500 TWD。")

    def test_context_sentence_per_version(self):
        context = {}
        for lang in ("en", "zh"):
            for version in (None, "v1", "v1.1"):
                context[lang, version] = negotiation_settings(
                    self.config, self.case, "over_budget", lang, self.glossary, version)["case_context"]
            self.assertEqual(context[lang, None], context[lang, "v1"])
            self.assertNotEqual(context[lang, "v1"], context[lang, "v1.1"])
        self.assertIn("「家具」", context["zh", "v1"])
        self.assertIn("一批家具，數量 1", context["zh", "v1.1"])
        self.assertIn("one lot of furniture, quantity 1", context["en", "v1.1"])

    def test_template_wording_and_trailing_blank_line(self):
        for lang, factory in (("en", prompt_en), ("zh", prompt_zh)):
            goal = SELLER_GOALS[(lang, "v1.1")](Valuation({"X": 440000}))
            text = factory("X", Resources({"X": 1}), goal, 9, "context")
            self.assertTrue(text.endswith("context\n\n"))
            self.assertNotIn("</my goals>,", text)
            self.assertNotIn("DO NOT", text)
            if lang == "en":
                self.assertIn("A) proposing, B) accepting, or C) rejecting", text)
                self.assertNotIn("buy resources", text)
                self.assertNotIn("purcahse", text)
            else:
                self.assertIn("A) 提出、B) 接受，或 C) 拒絕", text)
                self.assertNotIn("市場上", text)
            for tag in TAGS:
                self.assertIn(f"</{tag}>", text)

    def test_render_and_public_message(self):
        original = br.stage_log_root
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
            with patch.object(ChatGPTAgent, "chat", side_effect=AssertionError("API call forbidden")):
                actual = render(self.config, self.case, "over_budget", "v1.1", self.glossary, temp)
        br.stage_log_root = original
        for lang, data in actual.items():
            prompts = {"seller": data["seller_system"], "buyer": data["buyer_system"]}
            self.assertEqual(prompt_template_check({"seller": "v1.1", "buyer": "v1.1"}, prompts), "ok")
            self.assertEqual(prompt_template_check({"seller": "v1", "buyer": "v1"}, prompts), "mismatch")
            self.assertIn(str(data["settings"]["seller_first_offer"]), data["to_buyer"])
            self.assertNotIn(str(data["settings"]["cost"]), data["to_buyer"])
            self.assertNotIn("<my goals>", data["to_buyer"])
            self.assertNotIn("<reason>", data["to_buyer"])
            role = "You are Player BLUE." if lang == "en" else "你是 Player BLUE。"
            self.assertTrue(data["buyer_system"].endswith("\n\n" + role))

    def test_whole_game_parses_in_both_languages(self):
        for lang in ("en", "zh"):
            row = {"language": lang, "stage": "offline_v11", "game_label": lang, "tactic": "baseline",
                   "seller_prompt_version": "v1.1", "buyer_prompt_version": "v1.1"}
            settings = negotiation_settings(self.config, self.case, "under_budget", lang, self.glossary, "v1.1")
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
                with patch.object(br, "stage_log_root", return_value=Path(temp)):
                    with patch.object(br, "ChatGPTAgent", side_effect=lambda **kw: FakeBuyer(["ACCEPT"])):
                        game = br.build_game(self.config, self.config["model_profile"], row, settings)
                with patch.object(ChatGPTAgent, "chat", side_effect=AssertionError("API call forbidden")):
                    with contextlib.redirect_stdout(io.StringIO()):
                        game.run()
                self.assertEqual(game.run_metadata["status"], "ok")
                summary = game.game_state[-1]["summary"]
                deal = summary["proposed_trade"].resources_from_second_agent.resource_dict["TWD"]
                self.assertEqual(deal, settings["seller_first_offer"])


if __name__ == "__main__":
    unittest.main()
