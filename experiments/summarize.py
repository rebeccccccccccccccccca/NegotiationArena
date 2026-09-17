"""
Scan .logs/<condition>/<epoch_ms>/game_state.json for every BuySellGame run
and summarize them into experiments/results.csv, one row per game.

Read-only: does not run new games, does not touch runner/ or games/.
"""

import csv
import glob
import json
import os

LOGS_DIR = ".logs"
OUTPUT_CSV = os.path.join("experiments", "results.csv")

FIELDNAMES = [
    "game_id",
    "model",
    "language",
    "prompt_version",
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
    "breach_A",
    "breach_B",
    "breach_C",
]

# Markers that only appear in the goal sentence introduced by task02
# ("Never sell below cost." / "絕對不要低於成本出售"). A log whose seller
# system prompt lacks both is from before that change (v0); everything
# produced since is v1. New wordings (e.g. task04's cost-sentence
# paraphrase) should extend this function with their own marker once the
# wording is finalized.
V1_MARKERS = ("Never sell below cost", "絕對不要低於成本出售")


def infer_prompt_version(red_system_prompt):
    if not red_system_prompt:
        return "unknown"
    if any(marker in red_system_prompt for marker in V1_MARKERS):
        return "v1"
    return "v0"


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


def infer_language(condition_name):
    prefix = condition_name.split("_")[0].lower()
    return prefix if prefix in ("en", "zh") else "unknown"


def summarize_game(condition, game_id, path):
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

    has_range = cost is not None and wtp is not None and cost <= wtp

    breach_A = bool(
        deal
        and wtp is not None
        and final_price is not None
        and final_price > wtp
    )
    breach_B = bool(deal and cost is not None and wtp is not None and cost > wtp)
    breach_C = bool(
        has_range
        and deal
        and seller_first_offer is not None
        and final_price == seller_first_offer
    )

    return {
        "game_id": game_id,
        "model": blue.get("model"),
        "language": infer_language(condition),
        "prompt_version": infer_prompt_version(red_system_prompt),
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
        "breach_A": breach_A,
        "breach_B": breach_B,
        "breach_C": breach_C,
    }


def main():
    rows = []
    # Recursive: some conditions nest an extra level of subfolders (e.g.
    # .logs/probe_seller50/en_wide/<epoch_ms>/), not just
    # .logs/<condition>/<epoch_ms>/.
    pattern = os.path.join(LOGS_DIR, "**", "game_state.json")
    for path in sorted(glob.glob(pattern, recursive=True)):
        norm = path.replace("\\", "/")
        run_dir = os.path.dirname(norm)
        condition = os.path.basename(os.path.dirname(run_dir))
        game_id = norm[len(LOGS_DIR) + 1 : -len("/game_state.json")]
        rows.append(summarize_game(condition, game_id, path))

    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
