"""
Regression test for the upstream (vinid/NegotiationArena) bug where
from_name_and_tag_to_message()'s two parameters were used with swapped
semantics, causing a player's public info to render with its content and
XML tag reversed (e.g. the whole message text used as the tag, wrapping
the literal word "message").

Run with: python -m unittest tests/test_message_format.py
(or pytest, if installed).
"""

import unittest

from negotiationarena.agent_message import AgentMessage
from negotiationarena.game_objects.trade import Trade
from negotiationarena.utils import from_name_and_tag_to_message
from negotiationarena.constants import (
    MESSAGE_TAG,
    PLAYER_ANSWER_TAG,
    PROPOSED_TRADE_TAG,
)


class TestFromNameAndTagToMessage(unittest.TestCase):
    def test_tag_wraps_content(self):
        self.assertEqual(
            from_name_and_tag_to_message("message", "hello"),
            "<message> hello </message>",
        )


class TestAgentMessagePublicFormat(unittest.TestCase):
    def test_message_to_other_player_uses_tag_as_delimiter(self):
        trade = Trade({"RED": {"X": 1}, "BLUE": {"ZUP": 40}})

        ms = AgentMessage()
        ms.add_public(MESSAGE_TAG, "hello there")
        ms.add_public(PLAYER_ANSWER_TAG, "PROPOSAL")
        ms.add_public(PROPOSED_TRADE_TAG, trade)

        rendered = ms.message_to_other_player()
        lines = rendered.split("\n")

        self.assertEqual(lines[0], f"<{MESSAGE_TAG}> hello there </{MESSAGE_TAG}>")
        self.assertEqual(
            lines[1], f"<{PLAYER_ANSWER_TAG}> PROPOSAL </{PLAYER_ANSWER_TAG}>"
        )
        self.assertEqual(
            lines[2],
            f"<{PROPOSED_TRADE_TAG}> {trade} </{PROPOSED_TRADE_TAG}>",
        )


if __name__ == "__main__":
    unittest.main()
