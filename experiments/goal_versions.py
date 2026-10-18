"""
Prompt (goal-sentence) versions: which goal class plays each version, per
side and language, and the rule for pairing a seller version with a
buyer version. Shared by plan.py and batch_runner.py, which build games
from it, and summarize.py, which reads back the versions a logged game
actually used. What each version is for is documented in
experiments/prompt_versions.json.
"""

from negotiationarena.game_objects.goal import (
    BuyerGoal,
    BuyerGoalV3,
    BuyerGoalZH,
    BuyerGoalZHV3,
    SellerGoal,
    SellerGoalV2,
    SellerGoalZH,
    SellerGoalZHV2,
)

BASELINE = "v1"

# (language, version) -> goal class
SELLER_GOALS = {
    ("en", "v1"): SellerGoal,
    ("zh", "v1"): SellerGoalZH,
    ("en", "v2"): SellerGoalV2,
    ("zh", "v2"): SellerGoalZHV2,
}
BUYER_GOALS = {
    ("en", "v1"): BuyerGoal,
    ("zh", "v1"): BuyerGoalZH,
    ("en", "v3"): BuyerGoalV3,
    ("zh", "v3"): BuyerGoalZHV3,
}

# The goal's _type in game_state.json -> (side, version). v0, the upstream
# wording, was these same v1 classes with different text, so a v1 _type
# can still be v0 in an old log; summarize.py tells them apart by text.
GOAL_TYPES = {
    "seller_goal": ("seller", "v1"),
    "seller_goal_zh": ("seller", "v1"),
    "seller_goal_v2": ("seller", "v2"),
    "seller_goal_zh_v2": ("seller", "v2"),
    "buyer_goal": ("buyer", "v1"),
    "buyer_goal_zh": ("buyer", "v1"),
    "buyer_goal_v3": ("buyer", "v3"),
    "buyer_goal_zh_v3": ("buyer", "v3"),
}


class VersionComboError(ValueError):
    pass


def check_combination(seller_version, buyer_version):
    """Only one side may differ from the baseline in a game: a wording
    check varies the seller (v2) with the buyer at v1, H3 varies the
    buyer (v3) with the seller at v1. Both off the baseline at once would
    confound the two."""
    for side, version, table in (
        ("seller", seller_version, SELLER_GOALS),
        ("buyer", buyer_version, BUYER_GOALS),
    ):
        if not any(v == version for _, v in table):
            raise VersionComboError(f"no {side} goal class for version {version}")
    if seller_version != BASELINE and buyer_version != BASELINE:
        raise VersionComboError(
            f"seller {seller_version} + buyer {buyer_version}: only one side may "
            f"leave the baseline ({BASELINE}) in a game, otherwise the seller and "
            f"buyer wording effects are confounded"
        )


def combined_label(seller_version, buyer_version):
    """One label for both sides: "v1" when they agree, else "seller/buyer"."""
    if seller_version == buyer_version:
        return seller_version
    return f"{seller_version}/{buyer_version}"
