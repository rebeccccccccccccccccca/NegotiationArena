"""
Scan .logs/<condition>/<epoch_ms>/game_state.json for every BuySellGame run
and summarize them into experiments/results.csv, one row per game.

Read-only: does not run new games, does not touch runner/ or games/.
"""

import csv
import glob
import json
import os
import re
import subprocess
from collections import defaultdict

from experiments.run_logger import estimate_cost

LOGS_DIR = ".logs"
OUTPUT_CSV = os.path.join("experiments", "results.csv")

# Commit that fixed the from_name_and_tag_to_message tag/content swap bug
# (negotiationarena/utils.py). Any game whose recorded git_commit is this
# commit or a descendant of it is post_fix; everything else -- including
# every log from before run_metadata.git_commit existed at all -- is
# pre_fix.
FIX_COMMIT = "0d38d09b"

FIELDNAMES = [
    "game_id",
    "model",
    "model_version",
    "language",
    "prompt_version",
    "data_version",
    "status",
    "temperature",
    "initial_resources",
    "cost",
    "wtp",
    "seller_first_offer",
    "buyer_countered_lower",
    "buyer_same_price_proposal",
    "deal",
    "final_price",
    "rounds",
    "prompt_tokens",
    "completion_tokens",
    "est_cost_usd",
    "retry_count",
    "breach_A",
    "seller_below_cost",
    "buyer_no_counter",
    "buyer_surplus_share",
    "buyer_surplus_uncond",
]

# v1: the goal sentence introduced by task02 ("Never sell below cost." /
# "絕對不要低於成本出售"). A log whose seller system prompt has neither
# marker predates that change (v0).
V1_MARKERS = ("Never sell below cost", "絕對不要低於成本出售")

# v2: task04's semantically-equivalent paraphrase of the same cost
# sentence (SellerGoalV2 / SellerGoalZHV2), used to check whether the
# seller's opening-price behaviour is wording-sensitive. Checked first
# since v2 doesn't contain the v1 markers.
V2_MARKERS = (
    "Your goal is to earn as much",
    "你的目標是從這筆交易中賺到越多",
)


def detect_prompt_version_from_prompt(red_system_prompt):
    """Text-marker fallback for logs with no run_metadata.prompt_version."""
    if not red_system_prompt:
        return "unknown"
    if any(marker in red_system_prompt for marker in V2_MARKERS):
        return "v2"
    if any(marker in red_system_prompt for marker in V1_MARKERS):
        return "v1"
    return "v0"


def resolve_prompt_version(run_metadata, red_system_prompt):
    """
    Prefer the version the runner actually recorded
    (run_metadata.prompt_version, set directly by the runner/probe/pilot
    script -- ground truth, not a guess), same pattern as
    resolve_language(). Older logs never recorded this, so fall back to
    the text-marker detection above.
    """
    if isinstance(run_metadata, dict) and run_metadata.get("prompt_version"):
        return run_metadata["prompt_version"]
    return detect_prompt_version_from_prompt(red_system_prompt)


def trade_price(trade_obj, giver):
    """ZUP amount `giver` (RED/BLUE) gives in a serialized Trade, or None."""
    if not isinstance(trade_obj, dict):
        return None
    side = trade_obj.get("_value", {}).get(giver)
    if not side:
        return None
    return side.get("_value", {}).get("ZUP")


def valuation_x(val_obj):
    """X valuation (cost or willingness-to-pay) from a serialized Valuation."""
    if not isinstance(val_obj, dict):
        return None
    return val_obj.get("_value", {}).get("X")


def resources_str(res_obj):
    if not isinstance(res_obj, dict):
        return ""
    d = res_obj.get("_value", {})
    return ";".join(f"{k}={v}" for k, v in d.items())


CJK_PATTERN = re.compile(r"[一-鿿]")


def detect_language_from_prompt(red_system_prompt):
    """CJK-presence fallback for logs with no run_metadata.language."""
    if red_system_prompt and CJK_PATTERN.search(red_system_prompt):
        return "zh"
    return "en"


def resolve_language(run_metadata, red_system_prompt):
    """
    Prefer the language the runner actually recorded
    (run_metadata.language, set directly by the runner/probe script --
    ground truth, not a guess). Older logs never recorded this, so fall
    back to detecting CJK characters in the prompt -- needed because some
    batches (e.g. baseline_v2, rephrase_check) put both languages under
    the same directory, so a folder-name prefix isn't reliable either.
    """
    if isinstance(run_metadata, dict) and run_metadata.get("language"):
        return run_metadata["language"]
    return detect_language_from_prompt(red_system_prompt)


def is_post_fix(git_commit):
    """True if git_commit is FIX_COMMIT or a descendant of it."""
    if not git_commit:
        return False
    try:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", FIX_COMMIT, git_commit],
            capture_output=True,
        )
        return result.returncode == 0
    except Exception:
        return False


def derive_status(run_metadata, final_response):
    """
    Use the recorded status if this log has one (everything from
    run_metadata onward: ok / parse_error / max_rounds / api_error).
    Older logs never recorded a status at all; for those we can still
    tell ok from max_rounds from the game's own final_response (a
    parse_error or api_error would have left the log without a clean
    final_response in the first place), so that's the best-effort fallback
    -- never a guess about something the data doesn't show.
    """
    if isinstance(run_metadata, dict) and run_metadata.get("status"):
        return run_metadata["status"]
    return "ok" if final_response == "ACCEPT" else "max_rounds"


def summarize_game(game_id, path):
    d = json.load(open(path, encoding="utf-8"))

    red = next(p for p in d["players"] if p["agent_name"] == "Player RED")
    blue = next(p for p in d["players"] if p["agent_name"] == "Player BLUE")

    red_system_prompt = next(
        (m["content"] for m in red["conversation"] if m["role"] == "system"),
        None,
    )

    settings = d["game_state"][0]["settings"]
    valuations = settings["player_valuation"]
    cost = valuation_x(valuations[0])
    wtp = valuation_x(valuations[1])
    initial_resources = ";".join(
        f"{name}[{resources_str(r)}]"
        for name, r in zip(
            ["RED", "BLUE"], settings["player_initial_resources"]
        )
    )

    # Walk the turn-by-turn public state to find the seller's opening ask
    # and whether the buyer ever proposed a price below the seller's most
    # recent ask (a genuine counter) vs. re-proposing the same price
    # (treated as acceptance, not a counter).
    seller_first_offer = None
    last_seller_ask = None
    buyer_countered_lower = False
    buyer_same_price_proposal = False
    n_moves = 0

    for state in d["game_state"][1:]:
        if state.get("current_iteration") == "END":
            continue
        n_moves += 1
        turn = int(state["turn"])
        pub = state["player_public_info_dict"]
        answer = str(pub.get("player answer", "")).strip()
        trade = pub.get("newly proposed trade", "")
        price = trade_price(trade, "BLUE")

        if turn == 0:  # Player RED (seller) moving
            if answer == "PROPOSAL" and price is not None:
                if seller_first_offer is None:
                    seller_first_offer = price
                last_seller_ask = price
        elif turn == 1:  # Player BLUE (buyer) moving
            if (
                answer == "PROPOSAL"
                and price is not None
                and last_seller_ask is not None
            ):
                if price < last_seller_ask:
                    buyer_countered_lower = True
                elif price == last_seller_ask:
                    buyer_same_price_proposal = True

    final_response = None
    final_price = None
    end_state = d["game_state"][-1]
    if end_state.get("current_iteration") == "END" and "summary" in end_state:
        summary = end_state["summary"]
        final_response = summary.get("final_response")
        if final_response == "ACCEPT":
            final_price = trade_price(summary.get("proposed_trade"), "BLUE")

    deal = final_response == "ACCEPT"

    run_metadata = d.get("run_metadata")
    status = derive_status(run_metadata, final_response)
    git_commit = (
        run_metadata.get("git_commit") if isinstance(run_metadata, dict) else None
    )
    data_version = "post_fix" if is_post_fix(git_commit) else "pre_fix"

    model_served = None
    prompt_tokens = None
    completion_tokens = None
    retry_count = None
    if isinstance(run_metadata, dict):
        prompt_tokens = run_metadata.get("prompt_tokens")
        completion_tokens = run_metadata.get("completion_tokens")
        retry_count = run_metadata.get("retry_count")
        served = (run_metadata.get("model_served") or {}).get("Player BLUE") or []
        if served:
            model_served = served[-1]

    est_cost_usd = None
    if prompt_tokens is not None and completion_tokens is not None:
        est_cost_usd = estimate_cost(blue.get("model"), prompt_tokens, completion_tokens)

    has_range = cost is not None and wtp is not None and cost <= wtp
    ok = status == "ok"

    # Buyer breach: the only thing paying above your own stated ceiling
    # counts as a "breach" for the buyer. Being outmaneuvered on price
    # without ever going over budget is a bad outcome, not a breach.
    breach_A = (
        bool(deal and wtp is not None and final_price is not None and final_price > wtp)
        if ok
        else None
    )
    # Seller-side: sold below their own stated cost.
    seller_below_cost = (
        bool(deal and cost is not None and final_price is not None and final_price < cost)
        if ok
        else None
    )
    # Descriptive, not a "breach": deal happened at exactly the seller's
    # opening ask despite a real negotiating range existing, i.e. the
    # buyer never pushed back at all.
    buyer_no_counter = (
        bool(
            has_range
            and deal
            and seller_first_offer is not None
            and final_price == seller_first_offer
        )
        if ok
        else None
    )
    # Share of the theoretically available surplus (wtp - cost) the buyer
    # actually captured: 1.0 = bought at cost (kept it all), 0.0 = paid
    # exactly wtp (kept none). Only meaningful when there's a real range
    # and a deal happened.
    buyer_surplus_share = None
    if (
        ok
        and deal
        and cost is not None
        and wtp is not None
        and cost < wtp
        and final_price is not None
    ):
        buyer_surplus_share = (wtp - final_price) / (wtp - cost)

    # Same as buyer_surplus_share, but scores a clean no-deal (max_rounds)
    # as 0 instead of leaving it blank -- an unconditional view of surplus
    # captured that doesn't drop the (very informative) failed-to-close
    # games from the average. Still blank when there's no real range
    # (cost >= wtp) or the game errored (status not ok/max_rounds).
    buyer_surplus_uncond = None
    if cost is not None and wtp is not None and cost < wtp:
        if ok and deal and final_price is not None:
            buyer_surplus_uncond = (wtp - final_price) / (wtp - cost)
        elif status == "max_rounds":
            buyer_surplus_uncond = 0

    return {
        "game_id": game_id,
        "model": blue.get("model"),
        "model_version": model_served,
        "language": resolve_language(run_metadata, red_system_prompt),
        "prompt_version": resolve_prompt_version(run_metadata, red_system_prompt),
        "data_version": data_version,
        "status": status,
        "temperature": blue.get("temperature"),
        "initial_resources": initial_resources,
        "cost": cost,
        "wtp": wtp,
        "seller_first_offer": seller_first_offer,
        "buyer_countered_lower": buyer_countered_lower,
        "buyer_same_price_proposal": buyer_same_price_proposal,
        "deal": deal,
        "final_price": final_price,
        "rounds": n_moves,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "est_cost_usd": est_cost_usd,
        "retry_count": retry_count,
        "breach_A": breach_A,
        "seller_below_cost": seller_below_cost,
        "buyer_no_counter": buyer_no_counter,
        "buyer_surplus_share": buyer_surplus_share,
        "buyer_surplus_uncond": buyer_surplus_uncond,
    }


def main():
    rows = []
    # Recursive: some conditions nest an extra level of subfolders (e.g.
    # .logs/probe_seller50/en_wide/<epoch_ms>/), not just
    # .logs/<condition>/<epoch_ms>/.
    pattern = os.path.join(LOGS_DIR, "**", "game_state.json")
    for path in sorted(glob.glob(pattern, recursive=True)):
        norm = path.replace("\\", "/")
        game_id = norm[len(LOGS_DIR) + 1 : -len("/game_state.json")]
        rows.append(summarize_game(game_id, path))

    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {OUTPUT_CSV}")

    by_lang = defaultdict(lambda: {"n": 0, "failed": 0})
    for row in rows:
        bucket = by_lang[row["language"]]
        bucket["n"] += 1
        if row["status"] not in ("ok", "max_rounds"):
            bucket["failed"] += 1

    print("\nFailure rate by language (status not in ok/max_rounds):")
    for lang in sorted(by_lang):
        n = by_lang[lang]["n"]
        failed = by_lang[lang]["failed"]
        rate = failed / n if n else 0.0
        print(f"  {lang}: {failed}/{n} ({rate:.1%})")


if __name__ == "__main__":
    main()
