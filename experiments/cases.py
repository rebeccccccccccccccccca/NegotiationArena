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


def case_context(config, case, language, glossary):
    label, source = category_label(case, language, glossary)
    text = config["case_context"][language].format(
        category=label, quantity=format_quantity(case["quantity"])
    )
    return text, label, source


def negotiation_settings(config, case, structure, language, glossary):
    """Everything a run needs from one case, as a flat dict that is also
    stored in game_state.json under `experiment`."""
    budget = round_half_up(case["budget"])
    cost, offer, funds = prices(config, budget, structure)
    context, label, source = case_context(config, case, language, glossary)
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
