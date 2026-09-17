"""
Shared safety rails for any script that runs a batch of games:
- a minimum wall-clock interval between games (--min-interval)
- a hard cap on how many games one invocation will launch
  (--max-games-per-run)
- stop early once cumulative token or estimated-cost spend crosses a
  budget (--budget-tokens / --budget-usd)

Nothing here runs games in parallel -- every runner/probe script in this
repo launches games from a single sequential loop already; this module
only adds pacing and spending caps to that loop.
"""

import argparse
import time

from experiments.run_logger import estimate_cost


class BudgetExceeded(Exception):
    pass


class RunThrottle:
    def __init__(
        self,
        min_interval=1.0,
        max_games_per_run=None,
        budget_usd=None,
        budget_tokens=None,
    ):
        self.min_interval = min_interval
        self.max_games_per_run = max_games_per_run
        self.budget_usd = budget_usd
        self.budget_tokens = budget_tokens

        self.games_launched = 0
        self.total_tokens = 0
        self.total_cost_usd = 0.0
        self._last_start = None

    def check_before_game(self):
        """Raise BudgetExceeded if a cap is already hit -- call this
        before starting the next game, so the caller can stop the batch
        instead of launching one more."""
        if (
            self.max_games_per_run is not None
            and self.games_launched >= self.max_games_per_run
        ):
            raise BudgetExceeded(
                f"max_games_per_run={self.max_games_per_run} reached "
                f"({self.games_launched} launched)"
            )
        if (
            self.budget_tokens is not None
            and self.total_tokens >= self.budget_tokens
        ):
            raise BudgetExceeded(
                f"budget_tokens={self.budget_tokens} reached "
                f"({self.total_tokens} used)"
            )
        if self.budget_usd is not None and self.total_cost_usd >= self.budget_usd:
            raise BudgetExceeded(
                f"budget_usd={self.budget_usd} reached "
                f"(${self.total_cost_usd:.4f} spent)"
            )

    def wait_for_interval(self):
        if self._last_start is not None:
            elapsed = time.monotonic() - self._last_start
            wait = self.min_interval - elapsed
            if wait > 0:
                time.sleep(wait)
        self._last_start = time.monotonic()

    def record_game(self, game, model):
        """Call after a game finishes (successfully or not) to update
        the running totals used by check_before_game()."""
        self.games_launched += 1
        meta = getattr(game, "run_metadata", {}) or {}
        prompt_tokens = meta.get("prompt_tokens", 0) or 0
        completion_tokens = meta.get("completion_tokens", 0) or 0
        self.total_tokens += prompt_tokens + completion_tokens

        cost = estimate_cost(model, prompt_tokens, completion_tokens)
        if cost is not None:
            self.total_cost_usd += cost


def add_throttle_args(parser: argparse.ArgumentParser):
    """Attach the standard throttle flags to an argparse parser."""
    parser.add_argument(
        "--min-interval",
        type=float,
        default=1.0,
        help="Minimum seconds between the start of consecutive games.",
    )
    parser.add_argument(
        "--max-games-per-run",
        type=int,
        default=None,
        help="Stop this invocation early after launching this many games.",
    )
    parser.add_argument(
        "--budget-usd",
        type=float,
        default=None,
        help="Stop this invocation early once estimated spend (from "
        "experiments/pricing.json) reaches this many USD. No effect if "
        "pricing.json has no rate for the model in use.",
    )
    parser.add_argument(
        "--budget-tokens",
        type=int,
        default=None,
        help="Stop this invocation early once cumulative prompt+completion "
        "tokens reach this amount.",
    )
    return parser


def throttle_from_args(args):
    return RunThrottle(
        min_interval=args.min_interval,
        max_games_per_run=args.max_games_per_run,
        budget_usd=args.budget_usd,
        budget_tokens=args.budget_tokens,
    )
