"""The cumulative spending cap (h1_decision_record.md A19): tokens already
logged under the named stages, failed attempts included, count toward
--budget-tokens before a run starts. No model call."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "offline-test-not-used")

import experiments.batch_runner as br
from experiments.throttle import BudgetExceeded, RunThrottle


def write_game(root, stage, label, epoch, status, prompt, completion):
    folder = Path(root) / stage / label / epoch
    folder.mkdir(parents=True)
    state = {"run_metadata": {"status": status, "prompt_tokens": prompt, "completion_tokens": completion}}
    (folder / "game_state.json").write_text(json.dumps(state), encoding="utf-8")


class TestCumulativeBudget(unittest.TestCase):
    def test_counts_every_attempt_of_the_named_stages_only(self):
        with tempfile.TemporaryDirectory() as root:
            write_game(root, "h1_trial", "h1_trial_001", "1", "ok", 1000, 500)
            write_game(root, "h1_trial", "h1_trial_002", "2", "api_error", 300, 0)
            write_game(root, "h1", "h1_001", "3", "rejected", 2000, 700)
            write_game(root, "pilot_luna10", "x", "4", "ok", 99999, 99999)
            (Path(root) / "h1" / "h1_002" / "5").mkdir(parents=True)
            (Path(root) / "h1" / "h1_002" / "5" / "game_state.json").write_text("{not json", encoding="utf-8")
            with patch.object(br, "stage_log_root", side_effect=lambda stage: Path(root) / stage):
                self.assertEqual(br.logged_tokens(["h1_trial", "h1"]), 4500)
                self.assertEqual(br.logged_tokens(["h1"]), 2700)
                self.assertEqual(br.logged_tokens(["no_such_stage"]), 0)

    def test_throttle_stops_once_the_logged_total_reaches_the_cap(self):
        throttle = RunThrottle(budget_tokens=5000)
        throttle.total_tokens = 4999
        throttle.check_before_game()
        throttle.total_tokens = 5000
        with self.assertRaises(BudgetExceeded):
            throttle.check_before_game()


if __name__ == "__main__":
    unittest.main()
