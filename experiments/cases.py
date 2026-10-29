"""
Procurement cases -> negotiation settings.

Reads the candidate pool (data/procurement/candidates.csv, built by
experiments/procurement/build_pool.py) and turns one case plus one price
structure into the numbers a BuySellGame needs, using the ratios in
experiments/experiment_config.json:

  B (buyer willingness to pay) = the case's budget, in TWD (MONEY_TOKEN)
  C (seller cost)              = round(B * cost_ratio)
  O (scripted opening offer)   = round(B * offer_ratio)
  buyer funds                  = round(B * buyer_funds_multiple)

Both languages get exactly the same numbers; only the wording differs.
The category label comes from the hand-made glossary when it has the
code, otherwise from the official classification name (recorded as
label_source so a run can't silently use the fallback).
"""

import csv
import hashlib
import json
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "experiments" / "experiment_config.json"


class PriceRuleError(ValueError):
    pass


def load_config(path=CONFIG_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def round_half_up(x):
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def format_quantity(q):
    q = float(q)
    return str(int(q)) if q.is_integer() else f"{q:g}"


def load_glossary(config):
    path = ROOT / config["category_glossary"]
    if not path.exists():
        return {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        return {row["category_code"]: row for row in csv.DictReader(f)}


def load_cases(config, roles, max_cases=None):
    """Candidate cases with one of `roles`, in pool_rank order."""
    with open(ROOT / config["candidates"], encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["role"] in roles]
    rows.sort(key=lambda r: int(r["pool_rank"]))
    return rows[:max_cases] if max_cases else rows


def category_label(case, language, glossary):
    entry = glossary.get(case["category_code"])
    if entry:
        return entry[f"label_{language}"], "glossary"
    return case[f"category_{language}"], "official"


def prices(config, budget, structure):
    """(C, O, buyer funds) for a budget under a price structure, after
    checking the opening offer stays under the agreed ceiling."""
    rule = config["price_structures"][structure]
    if rule["offer_ratio"] > config["offer_ceiling_ratio"]:
        raise PriceRuleError(
            f"{structure}: offer_ratio {rule['offer_ratio']} exceeds "
            f"offer_ceiling_ratio {config['offer_ceiling_ratio']} (buyer funds are "
            f"{config['buyer_funds_multiple']} x B)"
        )
    if rule["offer_ratio"] > config["offer_warning_ratio"]:
        print(
            f"WARNING: {structure}: offer_ratio {rule['offer_ratio']} is above "
            f"{config['offer_warning_ratio']} x B, close to the buyer's funds"
        )
    b = round_half_up(budget)
    return (
        round_half_up(b * rule["cost_ratio"]),
        round_half_up(b * rule["offer_ratio"]),
        round_half_up(b * config["buyer_funds_multiple"]),
    )


# T1 (h1_decision_record.md section 5), per kind of price structure.
T1_RULES = {
    "under_budget": ("C < O < B", lambda b, c, o: c < o < b),
    "over_budget": ("C < B < O", lambda b, c, o: c < b < o),
    "no_overlap": ("B < C < O", lambda b, c, o: b < c < o),
}


def t1_problems(config, case, structures):
    """T1 for one case, on the rounded prices it would play: each
    structure with a `kind` keeps its order of B, C and O, every opening
    offer stays at or under offer_ceiling_ratio x B, and the structures a
    deal is possible in (under/over budget) share one C. Structures
    without a kind (the pilot ones) are not checked. Returns the problems,
    empty when the case passes."""
    b = round_half_up(case["budget"])
    problems, tradable_costs = [], {}
    for structure in structures:
        kind = config["price_structures"][structure].get("kind")
        if kind is None:
            continue
        if kind not in T1_RULES:
            raise PriceRuleError(f"{structure}: unknown kind {kind!r}")
        c, o, _ = prices(config, b, structure)
        rule, holds = T1_RULES[kind]
        if not holds(b, c, o):
            problems.append(f"{structure}: B={b} C={c} O={o} breaks {rule}")
        if o > b * config["offer_ceiling_ratio"]:
            problems.append(f"{structure}: O={o} is over {config['offer_ceiling_ratio']} x B={b}")
        if kind != "no_overlap":
            tradable_costs[structure] = c
    if len(set(tradable_costs.values())) > 1:
        problems.append(f"under/over-budget structures must share C, got {tradable_costs}")
    return problems


def case_context(config, case, language, glossary, prompt_version=None):
    """The context sentence: the template for the seller's prompt version
    in case_context_versions, else the default case_context (v1's)."""
    label, source = category_label(case, language, glossary)
    template = config.get("case_context_versions", {}).get(prompt_version, config["case_context"])
    text = template[language].format(
        category=label, quantity=format_quantity(case["quantity"])
    )
    return text, label, source


def negotiation_settings(config, case, structure, language, glossary, prompt_version=None):
    """Everything a run needs from one case, as a flat dict that is also
    stored in game_state.json under `experiment`."""
    budget = round_half_up(case["budget"])
    cost, offer, funds = prices(config, budget, structure)
    context, label, source = case_context(config, case, language, glossary, prompt_version)
    return {
        "case_id": case["case_id"],
        "pool_rank": int(case["pool_rank"]),
        "role": case["role"],
        "category_code": case["category_code"],
        "category_label": label,
        "label_source": source,
        "quantity": format_quantity(case["quantity"]),
        "structure": structure,
        "wtp": budget,
        "cost": cost,
        "seller_first_offer": offer,
        "buyer_funds": funds,
        "case_context": context,
    }
