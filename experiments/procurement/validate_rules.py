"""
Manual check of the rule-based exclusions in build_pool.py that rely on
keywords or agency names (framework, lease/maintenance/software,
pharma/defense), so their accuracy can be reported in the methods chapter.

  draw   stratified random sample from the notices those rules were
         applied to (goods, amounts public, single award): half that the
         rules excluded, half they kept -> rule_validation.csv
  score  after a person fills in `human_reason`, agreement per stratum
         plus overall accuracy weighted back to the population
         -> rule_validation_summary.csv

Usage (from the repo root, after build_pool):
  .venv\\Scripts\\python -m experiments.procurement.validate_rules draw
  (fill in human_reason / human_note in rule_validation.csv)
  .venv\\Scripts\\python -m experiments.procurement.validate_rules score

human_reason takes one of: framework, lease_maint_software,
pharma_defense, keep. The sample is fixed once drawn; `draw` refuses to
overwrite a file that exists unless --force.
"""

import argparse

import pandas as pd

from experiments.procurement.build_pool import PARSED_PATH
from experiments.procurement.fetch_awards import OUT_DIR

VALIDATION_PATH = OUT_DIR / "rule_validation.csv"
SUMMARY_PATH = OUT_DIR / "rule_validation_summary.csv"

CHECKED_RULES = ["framework", "lease_maint_software", "pharma_defense"]
# Rules that run before the checked ones; notices they removed never
# reached the keyword rules, so they are outside the population.
EARLIER_RULES = ["not_goods", "missing_amount", "multiple_award"]
LABELS = CHECKED_RULES + ["keep"]

SHOWN_COLUMNS = [
    "case_id",
    "stratum",
    "auto_reason",
    "exclude_detail",
    "title",
    "item_name",
    "unit_name",
    "category_code",
    "category_zh",
    "source_url",
]


def population():
    df = pd.read_csv(PARSED_PATH, dtype={"category_code": str}, keep_default_na=False)
    df = df[~df["exclude_reason"].isin(EARLIER_RULES)].copy()
    df["auto_reason"] = df["exclude_reason"].where(
        df["exclude_reason"].isin(CHECKED_RULES), "keep"
    )
    df["stratum"] = df["auto_reason"].map(lambda r: "keep" if r == "keep" else "excluded")
    return df


def draw(n, seed, force):
    if VALIDATION_PATH.exists() and not force:
        print(f"{VALIDATION_PATH.name} exists, keeping it (--force to redraw)")
        return
    df = population()
    parts = []
    for stratum, size in [("excluded", n // 2), ("keep", n - n // 2)]:
        pool = df[df["stratum"] == stratum].sort_values("case_id")
        parts.append(pool.sample(min(size, len(pool)), random_state=seed))
        print(f"{stratum}: {len(pool)} in population, {min(size, len(pool))} drawn")
    # Shuffle so whoever labels can't tell the stratum from the row order;
    # the stratum/auto columns can be hidden while labelling.
    sample = pd.concat(parts).sample(frac=1, random_state=seed)[SHOWN_COLUMNS]
    sample["human_reason"] = ""
    sample["human_note"] = ""
    sample.to_csv(VALIDATION_PATH, index=False, encoding="utf-8-sig")
    print(f"{len(sample)} rows -> {VALIDATION_PATH.name}")


def score():
    sample = pd.read_csv(VALIDATION_PATH, keep_default_na=False)
    unlabelled = sample["human_reason"].str.strip() == ""
    bad = ~sample["human_reason"].isin(LABELS) & ~unlabelled
    if bad.any():
        raise SystemExit(
            f"human_reason must be one of {LABELS}; fix rows: "
            + ", ".join(sample.loc[bad, "case_id"])
        )
    if unlabelled.any():
        print(f"NOTE: {int(unlabelled.sum())} rows not labelled yet, scored without them")
    sample = sample[~unlabelled]

    pop_sizes = population()["stratum"].value_counts()
    rows = []
    for stratum, g in sample.groupby("stratum"):
        human_excl = g["human_reason"] != "keep"
        auto_excl = stratum == "excluded"
        rows.append(
            {
                "stratum": stratum,
                "population": int(pop_sizes.get(stratum, 0)),
                "labelled": len(g),
                # Same keep/exclude decision as the person.
                "decision_agreement": (human_excl == auto_excl).mean(),
                # Same decision and, when excluded, the same rule.
                "reason_agreement": (g["human_reason"] == g["auto_reason"]).mean(),
            }
        )
    summary = pd.DataFrame(rows).set_index("stratum")
    if {"excluded", "keep"} <= set(summary.index):
        n_ex, n_keep = summary.loc["excluded", "population"], summary.loc["keep", "population"]
        precision = summary.loc["excluded", "decision_agreement"]
        npv = summary.loc["keep", "decision_agreement"]
        accuracy = (n_ex * precision + n_keep * npv) / (n_ex + n_keep)
        # Share of notices that should be excluded which the rules caught.
        should_exclude = n_ex * precision + n_keep * (1 - npv)
        recall = n_ex * precision / should_exclude if should_exclude else float("nan")
        summary.loc["overall (weighted)", "decision_agreement"] = accuracy
        summary.loc["overall (weighted)", "population"] = n_ex + n_keep
        summary.loc["overall (weighted)", "labelled"] = len(sample)
        print(f"precision {precision:.3f}  NPV {npv:.3f}  "
              f"weighted accuracy {accuracy:.3f}  estimated recall {recall:.3f}")
    summary.to_csv(SUMMARY_PATH, encoding="utf-8-sig")
    print(summary.round(3).to_string())


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("step", choices=["draw", "score"])
    parser.add_argument("--n", type=int, default=50)
    parser.add_argument("--seed", type=int, default=20261016)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.step == "draw":
        draw(args.n, args.seed, args.force)
    else:
        score()


if __name__ == "__main__":
    main()
