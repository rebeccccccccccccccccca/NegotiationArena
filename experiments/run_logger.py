"""
Shared helper for runner scripts / experiments: append one summary row per
batch of games to experiments/runs.jsonl, and estimate USD cost from
experiments/pricing.json (which you maintain by hand -- rates are never
hardcoded here).
"""

import json
import os
from datetime import datetime, timezone

PRICING_PATH = os.path.join("experiments", "pricing.json")
RUNS_PATH = os.path.join("experiments", "runs.jsonl")

# Keep in sync with experiments/summarize.py's V1_MARKERS / infer_prompt_version.
V1_MARKERS = ("Never sell below cost", "絕對不要低於成本出售")


def infer_prompt_version(red_system_prompt):
    if not red_system_prompt:
        return "unknown"
    if any(marker in red_system_prompt for marker in V1_MARKERS):
        return "v1"
    return "v0"


def load_pricing():
    if not os.path.exists(PRICING_PATH):
        return {}
    with open(PRICING_PATH, encoding="utf-8") as f:
        return json.load(f)


def estimate_cost(model, prompt_tokens, completion_tokens):
    rates = load_pricing().get(model)
    if not rates:
        return None
    prompt_rate = rates.get("prompt_per_1k")
    completion_rate = rates.get("completion_per_1k")
    if prompt_rate is None or completion_rate is None:
        return None
    return (prompt_tokens / 1000) * prompt_rate + (
        completion_tokens / 1000
    ) * completion_rate


def append_run_log(
    games,
    *,
    model,
    temperature,
    language,
    cost,
    wtp,
    initial_resources,
    seller_first_offer,
    prompt_version,
    output_dir,
    runs_path=RUNS_PATH,
):
    """
    games: list of BuySellGame instances that already finished .run()
    (successfully or not -- run_metadata is set either way). Appends one
    row summarizing this batch to runs.jsonl.
    """
    metadatas = [getattr(g, "run_metadata", {}) for g in games]
    n_games = len(games)
    n_failed = sum(
        1 for m in metadatas if m.get("status") not in ("ok", "max_rounds")
    )
    total_prompt_tokens = sum(m.get("prompt_tokens", 0) for m in metadatas)
    total_completion_tokens = sum(
        m.get("completion_tokens", 0) for m in metadatas
    )
    total_tokens = total_prompt_tokens + total_completion_tokens
    git_commit = metadatas[0].get("git_commit") if metadatas else None

    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit,
        "model": model,
        "temperature": temperature,
        "language": language,
        "cost": cost,
        "wtp": wtp,
        "initial_resources": initial_resources,
        "seller_first_offer": seller_first_offer,
        "prompt_version": prompt_version,
        "n_games": n_games,
        "n_failed": n_failed,
        "total_tokens": total_tokens,
        "est_cost_usd": estimate_cost(
            model, total_prompt_tokens, total_completion_tokens
        ),
        "output_dir": output_dir,
        "backfilled": False,
    }

    os.makedirs(os.path.dirname(runs_path), exist_ok=True)
    with open(runs_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

    return row
