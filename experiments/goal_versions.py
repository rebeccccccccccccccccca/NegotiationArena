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
    BuyerGoalV11,
    BuyerGoalZH,
    BuyerGoalZHV3,
    BuyerGoalZHV11,
    SellerGoal,
    SellerGoalV2,
    SellerGoalV11,
    SellerGoalZH,
    SellerGoalZHV2,
    SellerGoalZHV11,
)

# Baselines: v1 (upstream text) and v1.1 (v1 with its typos fixed, the
# version H1 runs). A variant changes one side's sentence on top of one
# baseline; v2 and v3 were written on v1.
BASELINES = ("v1", "v1.1")
VARIANT_BASE = {"v2": "v1", "v3": "v1"}

# (language, version) -> goal class
SELLER_GOALS = {
    ("en", "v1"): SellerGoal,
    ("zh", "v1"): SellerGoalZH,
    ("en", "v1.1"): SellerGoalV11,
    ("zh", "v1.1"): SellerGoalZHV11,
    ("en", "v2"): SellerGoalV2,
    ("zh", "v2"): SellerGoalZHV2,
}
BUYER_GOALS = {
    ("en", "v1"): BuyerGoal,
    ("zh", "v1"): BuyerGoalZH,
    ("en", "v1.1"): BuyerGoalV11,
    ("zh", "v1.1"): BuyerGoalZHV11,
    ("en", "v3"): BuyerGoalV3,
    ("zh", "v3"): BuyerGoalZHV3,
}

# The goal's _type in game_state.json -> (side, version). v0, the upstream
# wording, was these same v1 classes with different text, so a v1 _type
# can still be v0 in an old log; summarize.py tells them apart by text.
GOAL_TYPES = {
    "seller_goal": ("seller", "v1"),
    "seller_goal_zh": ("seller", "v1"),
    "seller_goal_v1_1": ("seller", "v1.1"),
    "seller_goal_zh_v1_1": ("seller", "v1.1"),
    "seller_goal_v2": ("seller", "v2"),
    "seller_goal_zh_v2": ("seller", "v2"),
    "buyer_goal": ("buyer", "v1"),
    "buyer_goal_zh": ("buyer", "v1"),
    "buyer_goal_v1_1": ("buyer", "v1.1"),
    "buyer_goal_zh_v1_1": ("buyer", "v1.1"),
    "buyer_goal_v3": ("buyer", "v3"),
    "buyer_goal_zh_v3": ("buyer", "v3"),
}


class VersionComboError(ValueError):
    pass


def check_combination(seller_version, buyer_version):
    """Both sides play the same baseline, or one side plays a variant of
    the baseline the other side plays: a wording check varies the seller
    (v2) with the buyer at v1, H3 varies the buyer (v3) with the seller at
    v1. Both sides off the baseline at once would confound the two, and
    v1 and v1.1 in one game would mix two prompt templates."""
    for side, version, table in (
        ("seller", seller_version, SELLER_GOALS),
        ("buyer", buyer_version, BUYER_GOALS),
    ):
        if not any(v == version for _, v in table):
            raise VersionComboError(f"no {side} goal class for version {version}")
    if seller_version == buyer_version and seller_version in BASELINES:
        return
    for variant, other in ((seller_version, buyer_version), (buyer_version, seller_version)):
        if VARIANT_BASE.get(variant) == other:
            return
    raise VersionComboError(
        f"seller {seller_version} + buyer {buyer_version}: both sides must play the "
        f"same baseline ({', '.join(BASELINES)}), or one side a variant written on "
        f"the baseline the other plays ({', '.join(f'{v} on {b}' for v, b in VARIANT_BASE.items())})"
    )


def combined_label(seller_version, buyer_version):
    """One label for both sides: "v1" when they agree, else "seller/buyer"."""
    if seller_version == buyer_version:
        return seller_version
    return f"{seller_version}/{buyer_version}"
