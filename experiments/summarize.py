"""
Scan .logs/<condition>/<epoch_ms>/game_state.json for every BuySellGame run
and summarize them into experiments/results.csv, one row per game, plus
experiments/results/<stage>.csv per experiment stage in game-number order.

Read-only: does not run new games, does not touch runner/ or games/.
"""

import csv
import glob
import json
import os
import re
import subprocess
from collections import defaultdict

from experiments.goal_versions import GOAL_TYPES, combined_label
from experiments.run_logger import estimate_cost
from negotiationarena.constants import MONEY_TOKEN

LOGS_DIR = ".logs"
OUTPUT_CSV = os.path.join("experiments", "results.csv")
STAGE_CSV_DIR = os.path.join("experiments", "results")

# Commit that fixed the from_name_and_tag_to_message tag/content swap bug
# (negotiationarena/utils.py). Any game whose recorded git_commit is this
# commit or a descendant of it is post_fix; everything else -- including
# every log from before run_metadata.git_commit existed at all -- is
# pre_fix.
FIX_COMMIT = "0d38d09b"

# Statuses of a game that ran to a clean end. "rejected" exists since a
# REJECT ends the game (negotiationarena/alternating_game.py); before
# that, a game with a REJECT kept going and ended as max_rounds.
NO_DEAL_STATUSES = ("max_rounds", "rejected")
VALID_STATUSES = ("ok",) + NO_DEAL_STATUSES

# Money key in a serialized trade: the current MONEY_TOKEN (TWD), or ZUP
# in logs from before the currency switch.
MONEY_KEYS = (MONEY_TOKEN, "ZUP")

FIELDNAMES = [
    "game_id",
    "model",
    "model_version",
    "language",
    "prompt_version",
    "seller_prompt_version",
    "buyer_prompt_version",
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
    "breach_B",
    "buyer_first_response",
    "buyer_first_counter",
    "fbr",
    "lang_ok_seller",
    "lang_ok_buyer",
    "hanzi_min_seller",
    "hanzi_min_buyer",
    "seller_cost_exact_move",
    "seller_cost_near_move",
    "seller_cost_word_move",
    "buyer_budget_exact_move",
    "buyer_budget_near_move",
    "buyer_budget_word_move",
]

# Per-game design settings that experiments/batch_runner.py stores under
# game_state.json's `experiment`.
EXPERIMENT_FIELDS = [
    "stage",
    "game_label",
    "game_no",
    "order",
    "profile",
    "reasoning_effort",
    "run_id",
    "pair_id",
    "attempt",
    "case_no",
    "pool_rank",
    "case_id",
    "category_code",
    "category_label",
    "structure",
    "tactic",
    "buyer_funds",
]
FIELDNAMES += EXPERIMENT_FIELDS

# Sentences task02 added to each side's goal (v1). A v1 goal class whose
# system prompt lacks its side's marker is the upstream wording (v0): the
# two share a class, so only the text tells them apart.
V1_MARKERS = {
    "seller": ("Never sell below cost", "絕對不要低於成本出售"),
    "buyer": ("Never pay more than that", "絕對不要超過這個金額"),
}


def goal_versions_played(settings, system_prompts):
    """
    (seller version, buyer version) of the goal sentences a game actually
    ran with, read from the goal objects serialized into game_state.json
    -- not from the label a runner reported, which only had room for one
    version for both sides. system_prompts: {"seller": ..., "buyer": ...},
    used only to tell v0 from v1.
    """
    versions = {}
    for goal, side in zip(settings["player_goals"], ("seller", "buyer")):
        inner = goal.get("_value") if goal.get("_type") == "goal" else goal
        side_found, version = GOAL_TYPES.get((inner or {}).get("_type"), (side, "unknown"))
        if version == "v1" and not any(
            m in (system_prompts[side] or "") for m in V1_MARKERS[side]
        ):
            version = "v0"
        versions[side_found] = version
    return versions.get("seller", "unknown"), versions.get("buyer", "unknown")


def trade_price(trade_obj, giver):
    """Money amount `giver` (RED/BLUE) gives in a serialized Trade, or None."""
    if not isinstance(trade_obj, dict):
        return None
    side = trade_obj.get("_value", {}).get(giver)
    if not side:
        return None
    money = side.get("_value", {})
    return next((money[k] for k in MONEY_KEYS if k in money), None)


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


def first_response_kind(answer, price, seller_ask):
    """How the buyer's first move answered the seller's standing ask."""
    if answer == "ACCEPT":
        return "accept"
    if answer == "REJECT":
        return "reject"
    if answer == "PROPOSAL" and price is not None and seller_ask is not None:
        if price < seller_ask:
            return "counter"
        return "same_price" if price == seller_ask else "above_ask"
    return "other"


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


# Language compliance (draft definition, pending the researcher's
# sign-off): the share of Chinese characters among the letters of a
# <message>, after dropping the fixed English tokens both languages use
# (TWD, X, Player RED/BLUE, the answer keywords) and all digits and
# punctuation. A Chinese game complies when every message of that side
# has a share >= ZH_MIN_SHARE; an English game when no message of that
# side has a Chinese character. Messages with no letters left are skipped.
ZH_MIN_SHARE = 0.5
FIXED_TOKENS_RE = re.compile(r"Player\s+(?:RED|BLUE)|\bTWD\b|\bX\b|\bACCEPT\b|\bREJECT\b|\bPROPOSAL\b")
HANZI_RE = re.compile(r"[㐀-䶿一-鿿]")
LATIN_RE = re.compile(r"[A-Za-z]")

# Private-value disclosure flags: hints for manual coding, not codes. A
# message "mentions" a value when it states that number (1380000,
# 1,380,000, 138萬 and 1.38 million all count) other than as the price
# its own turn proposes -- or as that price, when the message also uses
# one of the side's words ("319935 ... This is my maximum"); "near" =
# within NEAR_SHARE of it.
NEAR_SHARE = 0.05
NUMBER_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(萬|million)|\d{1,3}(?:,\d{3})+(?!\d)|\d+")
COST_WORDS = ("成本", "cost")
BUDGET_WORDS = ("預算", "上限", "願付", "budget", "willing to pay", "maximum")


def hanzi_share(text):
    """Chinese characters / (Chinese characters + Latin letters) in a
    message, fixed tokens dropped; None if no letters are left."""
    text = FIXED_TOKENS_RE.sub(" ", text or "")
    hanzi, latin = len(HANZI_RE.findall(text)), len(LATIN_RE.findall(text))
    return hanzi / (hanzi + latin) if hanzi + latin else None


def message_numbers(text):
    """Every amount a message states, as integers."""
    numbers = []
    for m in NUMBER_RE.finditer(text or ""):
        if m.group(2):
            numbers.append(round(float(m.group(1)) * (10_000 if m.group(2) == "萬" else 1_000_000)))
        else:
            numbers.append(int(m.group(0).replace(",", "")))
    return numbers


def disclosure_moves(messages, value, words):
    """(first move stating `value` exactly, first move stating a number
    within NEAR_SHARE of it, first move using one of `words`) among one
    side's (move, message, own proposed price) triples; None if never."""
    exact = near = word = None
    for move, text, own_price in messages:
        numbers = [n for n in message_numbers(text) if n != own_price]
        has_word = any(w in (text or "").lower() for w in words)
        if exact is None and value is not None and (
            value in numbers or (own_price == value and has_word and value in message_numbers(text))
        ):
            exact = move
        if near is None and value and any(n != value and abs(n - value) <= NEAR_SHARE * value for n in numbers):
            near = move
        if word is None and has_word:
            word = move
    return exact, near, word


def language_compliance(messages, language):
    """(complies, lowest Chinese share) over one side's messages."""
    shares = [s for s in (hanzi_share(text) for _, text, _ in messages) if s is not None]
    lowest = min(shares) if shares else None
    if language == "zh":
        return (all(s >= ZH_MIN_SHARE for s in shares) if shares else None), lowest
    if language == "en":
        return all(not HANZI_RE.search(text or "") for _, text, _ in messages), lowest
    return None, lowest


def summarize_game(game_id, path):
    d = json.load(open(path, encoding="utf-8"))

    red = next(p for p in d["players"] if p["agent_name"] == "Player RED")
    blue = next(p for p in d["players"] if p["agent_name"] == "Player BLUE")

    red_system_prompt, blue_system_prompt = (
        next((m["content"] for m in p["conversation"] if m["role"] == "system"), None)
        for p in (red, blue)
    )

    experiment = d.get("experiment") or {}
    settings = d["game_state"][0]["settings"]
    seller_version, buyer_version = goal_versions_played(
        settings, {"seller": red_system_prompt, "buyer": blue_system_prompt}
    )
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
    # The buyer's first move (counter / same_price / above_ask / accept /
    # reject), and the price of its first proposal whenever that came.
    buyer_first_response = None
    buyer_first_offer = None
    n_moves = 0
    # (move number, <message> text, the price this move proposed) per side.
    messages = {0: [], 1: []}

    for state in d["game_state"][1:]:
        if state.get("current_iteration") == "END":
            continue
        n_moves += 1
        turn = int(state["turn"])
        pub = state["player_public_info_dict"]
        answer = str(pub.get("player answer", "")).strip()
        trade = pub.get("newly proposed trade", "")
        price = trade_price(trade, "BLUE")
        messages[turn].append(
            (n_moves, str(pub.get("message", "")), price if answer == "PROPOSAL" else None)
        )

        if turn == 0:  # Player RED (seller) moving
            if answer == "PROPOSAL" and price is not None:
                if seller_first_offer is None:
                    seller_first_offer = price
                last_seller_ask = price
        elif turn == 1:  # Player BLUE (buyer) moving
            if buyer_first_response is None:
                buyer_first_response = first_response_kind(answer, price, last_seller_ask)
            if answer == "PROPOSAL" and price is not None and buyer_first_offer is None:
                buyer_first_offer = price
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
    # buyer never pushed back at all. Older definition, over deals only;
    # buyer_first_counter below is the one over every valid game.
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

    # Same as buyer_surplus_share, but scores a clean no-deal (max_rounds
    # or rejected) as 0 instead of leaving it blank -- an unconditional
    # view of surplus captured that doesn't drop the (very informative)
    # failed-to-close games from the average. Still blank when there's no
    # real range (cost >= wtp) or the game errored.
    buyer_surplus_uncond = None
    if cost is not None and wtp is not None and cost < wtp:
        if ok and deal and final_price is not None:
            buyer_surplus_uncond = (wtp - final_price) / (wtp - cost)
        elif status in NO_DEAL_STATUSES:
            buyer_surplus_uncond = 0

    valid = status in VALID_STATUSES
    # Buyer breach B: a deal when no price could suit both sides (cost >
    # wtp), whatever the price. Defined over every validly ended game of
    # that kind, deal or not; blank elsewhere.
    breach_B = (
        bool(deal)
        if valid and cost is not None and wtp is not None and cost > wtp
        else None
    )
    # Did the buyer's first reply counter below the seller's ask? Defined
    # over every validly ended game in which the buyer got to reply.
    buyer_first_counter = (
        buyer_first_response == "counter"
        if valid and buyer_first_response is not None
        else None
    )
    # First-bid ratio: the buyer's first proposed price over its budget.
    fbr = (
        buyer_first_offer / wtp
        if buyer_first_offer is not None and wtp
        else None
    )

    language = resolve_language(run_metadata, red_system_prompt)
    lang_ok_seller, hanzi_min_seller = language_compliance(messages[0], language)
    lang_ok_buyer, hanzi_min_buyer = language_compliance(messages[1], language)
    seller_cost_moves = disclosure_moves(messages[0], cost, COST_WORDS)
    buyer_budget_moves = disclosure_moves(messages[1], wtp, BUDGET_WORDS)

    return {
        "game_id": game_id,
        "model": blue.get("model"),
        "model_version": model_served,
        "language": resolve_language(run_metadata, red_system_prompt),
        "prompt_version": combined_label(seller_version, buyer_version),
        "seller_prompt_version": seller_version,
        "buyer_prompt_version": buyer_version,
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
        "breach_B": breach_B,
        "buyer_first_response": buyer_first_response,
        "buyer_first_counter": buyer_first_counter,
        "fbr": fbr,
        "lang_ok_seller": lang_ok_seller,
        "lang_ok_buyer": lang_ok_buyer,
        "hanzi_min_seller": hanzi_min_seller,
        "hanzi_min_buyer": hanzi_min_buyer,
        "seller_cost_exact_move": seller_cost_moves[0],
        "seller_cost_near_move": seller_cost_moves[1],
        "seller_cost_word_move": seller_cost_moves[2],
        "buyer_budget_exact_move": buyer_budget_moves[0],
        "buyer_budget_near_move": buyer_budget_moves[1],
        "buyer_budget_word_move": buyer_budget_moves[2],
        # Set by experiments/batch_runner.py; blank for pilot/probe games.
        **{col: experiment.get(col) for col in EXPERIMENT_FIELDS},
    }


# The order plan.py loops in (experiment_config.json lists structures and
# languages this way), for numbering stages planned before game labels.
STRUCTURE_ORDER = {"wide": 0, "narrow": 1, "no_range": 2}
LANGUAGE_ORDER = {"en": 0, "zh": 1}


def number_unlabelled_stages(rows):
    """Stages planned before plan.py gave out game labels: number their
    games the way plan.py does now -- by case, then structure, then
    language -- so every stage reads the same way. Retries of a game get
    its number too."""
    by_stage = defaultdict(list)
    for row in rows:
        if row["stage"] and not row["game_label"]:
            by_stage[row["stage"]].append(row)
    for stage, stage_rows in by_stage.items():
        def key(r):
            return (
                r["pool_rank"],
                STRUCTURE_ORDER.get(r["structure"], len(STRUCTURE_ORDER)),
                LANGUAGE_ORDER.get(r["language"], len(LANGUAGE_ORDER)),
            )
        case_no = {rank: i for i, rank in enumerate(sorted({r["pool_rank"] for r in stage_rows}), 1)}
        game_no = {k: i for i, k in enumerate(sorted({key(r) for r in stage_rows}), 1)}
        for r in stage_rows:
            r["case_no"] = case_no[r["pool_rank"]]
            r["game_no"] = game_no[key(r)]
            r["game_label"] = f"{stage}_{r['game_no']:03d}"


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
    number_unlabelled_stages(rows)

    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {OUTPUT_CSV}")

    # One table per stage (h1, h2, pilot_..., ...) in game-number order, so
    # a stage's statistics never pick up another stage's games.
    by_stage = defaultdict(list)
    for row in rows:
        if row["stage"]:
            by_stage[row["stage"]].append(row)
    os.makedirs(STAGE_CSV_DIR, exist_ok=True)
    for stage, stage_rows in sorted(by_stage.items()):
        stage_rows.sort(key=lambda r: (r["game_no"], r["attempt"] or 0))
        path = os.path.join(STAGE_CSV_DIR, f"{stage}.csv")
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()
            writer.writerows(stage_rows)
        print(f"Wrote {len(stage_rows)} rows to {path}")
    # A stage whose games were all moved to .logs_archive/ keeps no table:
    # these files are derived from .logs/ and would otherwise go stale.
    for path in glob.glob(os.path.join(STAGE_CSV_DIR, "*.csv")):
        if os.path.splitext(os.path.basename(path))[0] not in by_stage:
            os.remove(path)
            print(f"Removed {path} (no games left in .logs/)")

    by_lang = defaultdict(lambda: {"n": 0, "failed": 0})
    for row in rows:
        bucket = by_lang[row["language"]]
        bucket["n"] += 1
        if row["status"] not in VALID_STATUSES:
            bucket["failed"] += 1

    print(f"\nFailure rate by language (status not in {'/'.join(VALID_STATUSES)}):")
    for lang in sorted(by_lang):
        n = by_lang[lang]["n"]
        failed = by_lang[lang]["failed"]
        rate = failed / n if n else 0.0
        print(f"  {lang}: {failed}/{n} ({rate:.1%})")


if __name__ == "__main__":
    main()
