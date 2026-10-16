"""
Turn the fetched award notices (raw/award_details.jsonl, written by
fetch_awards.py) into the candidate case pool and the award/budget ratio
distribution the C and O price rules are calibrated from.

Settings live in data/procurement/pool_rules.json (seed, role split,
category whitelist, amount range), not on the command line, so the
version frozen before the formal experiment is the one on record.

Outputs in data/procurement/:
  awards_parsed.csv          every sampled notice, parsed, with the first
                             exclusion rule it failed and what triggered
                             it (blank = eligible)
  exclusion_counts.csv       how many notices each rule removed, in order
  category_summary.csv       per 標的分類 code (and per 2-digit group):
  category_group_summary.csv cases passing the base rules, cases left
                             after the scope rules, budget quantiles,
                             counts per 採購金額級距 -- for choosing the
                             whitelist and amount range
  candidates.csv             eligible notices in a fixed random order
                             (pool_rank) with the stage they are
                             assigned to
  ratio_summary.csv          distribution of award/budget (and reserve-
                             price ratios) over the eligible notices

Usage (from the repo root):
  .venv\\Scripts\\python -m experiments.procurement.build_pool

Roles are given out in pool_rank order, in the order `roles` lists them;
everything after the last role is "pool". Calibration comes first, so
resizing a later stage never moves a case into or out of calibration.

Reading the ratios: the budget (預算) and the reserve price (底價) are
both set by the procuring agency, so they sit on the buyer's side (close
to B). The award amount is the realised deal price. None of them is the
seller's cost: C has no empirical counterpart and is assumed through a
ratio rule; these distributions only keep that rule realistic.
"""

import argparse
import json
import math
import random
import re
import xml.etree.ElementTree as ET

import pandas as pd

from experiments.procurement.fetch_awards import (
    CATEGORY_XML_PATH,
    DETAILS_PATH,
    MANIFEST_PATH,
    OUT_DIR,
    POOL_RULES_PATH,
    SAMPLE_PATH,
    sha256,
)

PARSED_PATH = OUT_DIR / "awards_parsed.csv"

# Base exclusion rules, applied in this order; a notice is labelled with
# the first one it fails. Keyword lists are matched against the tender
# title and the awarded item name.
LEASE_MAINT_SOFTWARE_KEYWORDS = [
    "租賃", "租用", "承租", "租購", "標租",
    "維護", "維修", "保養", "修繕",
    "軟體", "授權", "訂閱",
]
FRAMEWORK_KEYWORDS = ["開口契約", "開口合約"]
PHARMA_CODE_PREFIXES = ["352"]  # 醫藥產品
DEFENSE_CODE_PREFIXES = ["447"]  # 武器, 彈藥及其零件
DEFENSE_UNIT_KEYWORDS = ["國防部", "陸軍", "海軍", "空軍", "憲兵", "軍備局"]
# "冷凍櫃等2項": several goods bundled under one awarded item.
BUNDLE_RE = re.compile(r"等\s*\d+\s*(項|式|品項)")

# Base rules first, then the scope rules set in pool_rules.json.
EXCLUSION_ORDER = [
    ("not_goods", "非財物類"),
    ("missing_amount", "預算或決標金額缺漏／未公開"),
    ("multiple_award", "複數決標"),
    ("framework", "共同供應契約／開口契約"),
    ("lease_maint_software", "租賃、維護、軟體類"),
    ("pharma_defense", "藥品、國防（含涉及國家安全）"),
    ("insufficient_item", "標的資訊不足（非單一品項、合併多項或缺數量）"),
    ("award_over_budget", "決標金額高於預算（資料異常）"),
    ("category_not_selected", "品項不在白名單（pool_rules.json）"),
    ("budget_out_of_range", "預算超出金額範圍或級距（pool_rules.json）"),
]
SCOPE_RULES = ["category_not_selected", "budget_out_of_range"]

AMOUNT_TIERS = ["未達公告金額", "公告金額以上未達查核金額", "查核金額以上未達巨額", "巨額"]

RATIO_COLUMNS = {
    "award_over_budget": (
        "決標金額 ÷ 預算金額",
        "成交價參考（決標為實際成交價）；不是賣方成本 C",
    ),
    "reserve_over_budget": (
        "底價 ÷ 預算金額",
        "底價是機關自訂的價格上限，屬買方側（接近 B）；不是賣方成本 C",
    ),
    "award_over_reserve": (
        "決標金額 ÷ 底價",
        "成交價相對機關底價",
    ),
}
QUANTILES = [0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95]

CATEGORY_RE = re.compile(r"<(?P<attr>[^>]+)>(?P<code>\d+)(?P<name>.*)")
MONEY_RE = re.compile(r"^(?P<amount>[\d,]+(?:\.\d+)?)元$")


def parse_money(value):
    m = MONEY_RE.match((value or "").strip())
    return float(m.group("amount").replace(",", "")) if m else None


def parse_roc_date(value):
    """'114/08/13' -> '2025-08-13'."""
    m = re.match(r"^(\d{2,3})/(\d{2})/(\d{2})", (value or "").strip())
    if not m:
        return None
    return f"{int(m.group(1)) + 1911}-{m.group(2)}-{m.group(3)}"


def parse_quantity(value):
    try:
        q = float((value or "").replace(",", "").strip())
    except ValueError:
        return None
    return q if q > 0 else None


def parse_roles(spec):
    roles = []
    for part in spec.split(","):
        name, n = part.split(":")
        roles.append((name.strip(), int(n)))
    return roles


def load_rules():
    rules = json.loads(POOL_RULES_PATH.read_text(encoding="utf-8"))
    rules["category_whitelist"] = [str(c) for c in rules["category_whitelist"]]
    if MANIFEST_PATH.exists():
        recorded = json.loads(MANIFEST_PATH.read_text(encoding="utf-8")).get("pool_rules")
        if recorded and recorded["frozen"] and recorded["sha256"] != sha256(POOL_RULES_PATH):
            raise SystemExit(
                f"{POOL_RULES_PATH.name} differs from the version frozen in "
                f"{MANIFEST_PATH.name} (sha256 {recorded['sha256'][:12]}...). Restore "
                "it, or unfreeze deliberately and re-run fetch_awards manifest."
            )
    return rules


def field(detail, suffix):
    """Value of the first key ending in `suffix` (section prefixes differ
    between notice formats, e.g. 已公告資料: vs 採購資料:)."""
    for key, value in detail.items():
        if key.endswith(suffix):
            return value
    return None


def load_category_names():
    """(標的分類, 代碼) -> (中文名, English name)."""
    root = ET.parse(CATEGORY_XML_PATH).getroot()
    return {
        (e.findtext("標的分類"), e.findtext("標的代碼")): (
            e.findtext("分類名稱中文"),
            e.findtext("分類名稱英文"),
        )
        for e in root
    }


def parse_notice(rec, category_names):
    d = rec["detail"]
    category = CATEGORY_RE.match(field(d, ":標的分類") or "")
    attr = category.group("attr") if category else None
    code = category.group("code") if category else None
    winners_on_item1 = [
        k for k in d if re.fullmatch(r"決標品項:第1品項:得標廠商\d+", k)
    ]
    n_items = field(d, "決標品項:決標品項數")
    return {
        "case_id": rec["filename"],
        "unit_name": field(d, "機關資料:機關名稱"),
        "title": field(d, ":標案名稱"),
        "procurement_attr": attr,
        "category_code": code,
        "category_zh": category.group("name").strip() if category else None,
        "category_en": category_names.get((attr, code), (None, None))[1],
        "item_name": d.get("決標品項:第1品項:品項名稱"),
        "quantity": parse_quantity(d.get("決標品項:第1品項:得標廠商1:預估需求數量")),
        "n_items": int(n_items) if (n_items or "").isdigit() else None,
        "n_winners_item1": len(winners_on_item1),
        "budget_public": field(d, ":預算金額是否公開"),
        "budget": parse_money(field(d, ":預算金額")),
        "reserve_price": parse_money(d.get("決標資料:底價金額")),
        "award_public": d.get("決標資料:總決標金額是否公開"),
        "award_amount": parse_money(d.get("決標資料:總決標金額")),
        "n_bidders": field(d, "投標廠商:投標廠商家數"),
        "procurement_method": field(d, ":招標方式"),
        "award_method": field(d, ":決標方式"),
        "amount_tier": field(d, ":採購金額級距"),
        "multiple_award": field(d, ":是否複數決標"),
        "joint_supply_contract": field(d, ":是否屬共同供應契約採購"),
        "national_security": field(d, "是否屬「涉及國家安全」採購"),
        "award_date": parse_roc_date(d.get("決標資料:決標日期")),
        "notice_date": parse_roc_date(d.get("決標資料:決標公告日期")),
        "source_url": d.get("url"),
    }


def first_keyword(text, keywords):
    return next((k for k in keywords if k in (text or "")), None)


def base_exclusion(row):
    """(rule, what triggered it) for the first base rule the notice
    fails, or ("", "") if it passes them all."""
    text = f"{row['title'] or ''} {row['item_name'] or ''}"
    code = row["category_code"] or ""
    if row["procurement_attr"] != "財物類":
        return "not_goods", row["procurement_attr"] or "unparsed"
    if row["budget_public"] != "是" or not row["budget"]:
        return "missing_amount", "budget"
    if row["award_public"] != "是" or not row["award_amount"]:
        return "missing_amount", "award"
    if row["multiple_award"] == "是":
        return "multiple_award", "multiple_award_field"
    if row["n_winners_item1"] > 1:
        return "multiple_award", f"winners={row['n_winners_item1']}"
    if row["joint_supply_contract"] == "是":
        return "framework", "joint_supply_contract_field"
    if kw := first_keyword(text, FRAMEWORK_KEYWORDS):
        return "framework", f"keyword:{kw}"
    if kw := first_keyword(text, LEASE_MAINT_SOFTWARE_KEYWORDS):
        return "lease_maint_software", f"keyword:{kw}"
    if code.startswith(tuple(PHARMA_CODE_PREFIXES)):
        return "pharma_defense", f"code:{code}"
    if code.startswith(tuple(DEFENSE_CODE_PREFIXES)):
        return "pharma_defense", f"code:{code}"
    if row["national_security"] == "是":
        return "pharma_defense", "national_security_field"
    if kw := first_keyword(row["unit_name"], DEFENSE_UNIT_KEYWORDS):
        return "pharma_defense", f"unit:{kw}"
    if row["n_items"] != 1:
        return "insufficient_item", f"n_items={row['n_items']}"
    if not row["item_name"]:
        return "insufficient_item", "no_item_name"
    if row["quantity"] is None:
        return "insufficient_item", "no_quantity"
    if m := BUNDLE_RE.search(text):
        return "insufficient_item", f"bundle:{m.group(0)}"
    if row["award_amount"] > row["budget"]:
        return "award_over_budget", ""
    return "", ""


def scope_exclusion(row, rules):
    """The pool_rules.json scope rules, for notices that passed the base
    rules: category whitelist first, then the amount range."""
    whitelist = rules["category_whitelist"]
    if whitelist and not (row["category_code"] or "").startswith(tuple(whitelist)):
        return "category_not_selected", f"code:{row['category_code']}"
    tiers = rules["amount_tiers"]
    if tiers and row["amount_tier"] not in tiers:
        return "budget_out_of_range", f"tier:{row['amount_tier']}"
    if rules["budget_min"] is not None and row["budget"] < rules["budget_min"]:
        return "budget_out_of_range", f"budget<{rules['budget_min']:.0f}"
    if rules["budget_max"] is not None and row["budget"] > rules["budget_max"]:
        return "budget_out_of_range", f"budget>{rules['budget_max']:.0f}"
    return "", ""


def exclusion(row, rules):
    reason = base_exclusion(row)
    return reason if reason[0] else scope_exclusion(row, rules)


def assign_roles(n, roles):
    out = []
    for name, size in roles:
        out += [name] * size
    out = out[:n]
    return out + ["pool"] * (n - len(out))


def budget_stats(budget):
    return {
        "budget_min": budget.min(),
        "budget_p25": budget.quantile(0.25),
        "budget_median": budget.median(),
        "budget_p75": budget.quantile(0.75),
        "budget_max": budget.max(),
    }


def category_summary(passed_base, key, names, whitelist):
    """Per category key: cases passing the base rules, cases left after
    the scope rules, budget quantiles and counts per amount tier. The
    first row (key "ALL") covers every case passing the base rules."""
    rows = []
    groups = [("ALL", passed_base)] + list(passed_base.groupby(key, sort=False))
    for code, g in groups:
        zh, en = names.get(code, (None, None)) if code != "ALL" else (None, None)
        row = {
            key: code,
            "name_zh": zh if zh else (g["category_zh"].iloc[0] if code != "ALL" else ""),
            "name_en": en,
            "in_whitelist": (
                None if code == "ALL" or not whitelist else str(code).startswith(tuple(whitelist))
            ),
            "n_passed_base": len(g),
            "n_eligible": int((g["exclude_reason"] == "").sum()),
            **budget_stats(g["budget"]),
        }
        for tier in AMOUNT_TIERS:
            row[f"n_{tier}"] = int((g["amount_tier"] == tier).sum())
        rows.append(row)
    out = pd.DataFrame(rows)
    return pd.concat([out.iloc[:1], out.iloc[1:].sort_values("n_passed_base", ascending=False)])


def ratio_summary(eligible):
    rows = []
    for col, (label, note) in RATIO_COLUMNS.items():
        s = eligible[col].dropna()
        row = {"ratio": col, "label": label, "interpretation": note, "n": len(s)}
        if len(s):
            row.update({"mean": s.mean(), "sd": s.std(), "min": s.min()})
            row.update({f"p{int(q * 100):02d}": s.quantile(q) for q in QUANTILES})
            row["max"] = s.max()
        rows.append(row)
    return pd.DataFrame(rows)


def load_sampled_records():
    """Details for the ids in sample_ids.csv only (award_details.jsonl can
    also hold notices from an earlier draw), plus the sample itself."""
    sample = pd.read_csv(SAMPLE_PATH, dtype={"filename": str, "month": str})
    sample_ids = set(sample["filename"])
    with open(DETAILS_PATH, encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]
    return [r for r in records if r["filename"] in sample_ids], sample


def warn_if_short(df, rules, needed, sample):
    """When the pool is too small, recommend enlarging the sample first:
    the scope is a design decision, the sample size is only data volume.
    What relaxing the scope would give (amount range first, then
    categories) is shown only as a fallback."""
    n_eligible = int((df["exclude_reason"] == "").sum())
    if n_eligible >= needed:
        return
    per_month = int(sample["month_rank"].max())
    n_months = sample["month"].nunique()
    print(f"\nWARNING: {n_eligible} eligible cases, the roles need {needed}.")
    if n_eligible:
        rate = n_eligible / len(df)
        need_total = math.ceil(needed / rate)
        print(
            f"  1) enlarge the sample, keeping the scope: at the current eligible rate "
            f"({n_eligible}/{len(df)}) about {need_total} notices are needed, "
            f"--per-month {math.ceil(need_total / n_months)} at minimum "
            f"({math.ceil(need_total * 1.25 / n_months)} with a 25% margin; now {per_month}).\n"
            "     fetch_awards sample --force --per-month N, then fetch_awards details "
            "(earlier ids are kept)"
        )
    else:
        print("  1) no eligible case at all: check the scope settings before enlarging the sample")

    passed_base = df["exclude_reason"].isin([""] + SCOPE_RULES)
    # Rows failing the whitelist are labelled with it, so dropping the
    # amount range frees exactly the budget_out_of_range rows.
    n_without_amount = int((passed_base & (df["exclude_reason"] != "category_not_selected")).sum())
    n_without_both = int(passed_base.sum())
    amount_set = bool(rules["amount_tiers"]) or rules["budget_min"] is not None or rules["budget_max"] is not None
    if amount_set or rules["category_whitelist"]:
        print("  Only if enlarging is not feasible, relaxing the scope would give, in this order:")
    if amount_set:
        print(f"     - without the amount range: {n_without_amount} eligible")
    if rules["category_whitelist"]:
        print(f"     - without the category whitelist as well: {n_without_both} eligible")


def check_amount_settings(eligible, rules):
    """Amount tiers and budget bounds are meant to be used together and
    must not contradict each other; tiers also follow different
    procurement procedures, so say when the pool mixes them."""
    for tier in rules["amount_tiers"]:
        if not (eligible["amount_tier"] == tier).any():
            print(
                f"WARNING: no eligible case in amount tier {tier} within budget "
                f"[{rules['budget_min']}, {rules['budget_max']}]: tier and budget range contradict"
            )
    tiers = eligible["amount_tier"].value_counts()
    if len(tiers) > 1:
        print(
            f"NOTE: eligible cases span {len(tiers)} amount tiers ("
            + ", ".join(f"{t} {n}" for t, n in tiers.items())
            + "), which follow different procurement procedures"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.parse_args()
    rules = load_rules()
    roles = parse_roles(rules["roles"])

    records, sample = load_sampled_records()
    names = load_category_names()
    df = pd.DataFrame([parse_notice(r, names) for r in records])
    df = df.drop_duplicates("case_id")
    df["award_over_budget"] = df["award_amount"] / df["budget"]
    df["reserve_over_budget"] = df["reserve_price"] / df["budget"]
    df["award_over_reserve"] = df["award_amount"] / df["reserve_price"]
    df[["exclude_reason", "exclude_detail"]] = df.apply(
        exclusion, axis=1, result_type="expand", rules=rules
    )
    df.to_csv(PARSED_PATH, index=False, encoding="utf-8-sig")

    remaining = len(df)
    counts = [
        {"step": "sampled", "label": "抽樣決標公告（已取得明細）", "removed": None, "remaining": remaining}
    ]
    for reason, label in EXCLUSION_ORDER:
        removed = int((df["exclude_reason"] == reason).sum())
        remaining -= removed
        counts.append({"step": reason, "label": label, "removed": removed, "remaining": remaining})
    counts = pd.DataFrame(counts)
    counts.to_csv(OUT_DIR / "exclusion_counts.csv", index=False, encoding="utf-8-sig")

    passed_base = df[df["exclude_reason"].isin([""] + SCOPE_RULES)].copy()
    goods_names = {code: v for (attr, code), v in names.items() if attr == "財物類"}
    by_code = category_summary(passed_base, "category_code", goods_names, rules["category_whitelist"])
    by_code.to_csv(OUT_DIR / "category_summary.csv", index=False, encoding="utf-8-sig")
    passed_base["category_group"] = passed_base["category_code"].str[:2]
    by_group = category_summary(passed_base, "category_group", goods_names, rules["category_whitelist"])
    by_group.to_csv(OUT_DIR / "category_group_summary.csv", index=False, encoding="utf-8-sig")

    eligible = df[df["exclude_reason"] == ""].sort_values("case_id")
    order = list(range(len(eligible)))
    random.Random(rules["seed"]).shuffle(order)
    eligible = eligible.iloc[order].reset_index(drop=True)
    eligible.insert(0, "pool_rank", range(1, len(eligible) + 1))
    eligible.insert(1, "role", assign_roles(len(eligible), roles))
    eligible.drop(columns=["exclude_reason", "exclude_detail"]).to_csv(
        OUT_DIR / "candidates.csv", index=False, encoding="utf-8-sig"
    )

    summary = ratio_summary(eligible)
    summary.to_csv(OUT_DIR / "ratio_summary.csv", index=False, encoding="utf-8-sig")

    if len(df) < len(sample):
        print(f"NOTE: details on disk for {len(df)} of {len(sample)} sampled ids\n")
    print(f"rules: whitelist={rules['category_whitelist'] or 'all'} "
          f"tiers={rules['amount_tiers'] or 'any'} "
          f"budget=[{rules['budget_min']}, {rules['budget_max']}] frozen={rules['frozen']}\n")
    print(counts.to_string(index=False))
    print()
    stat_cols = ["n_passed_base", "n_eligible", "budget_min", "budget_p25",
                 "budget_median", "budget_p75", "budget_max"]
    print(by_group[["category_group", "name_zh"] + stat_cols].to_string(index=False))
    print()
    role_counts = eligible["role"].value_counts().reindex([r for r, _ in roles] + ["pool"])
    print(role_counts.fillna(0).astype(int).to_string())
    if len(eligible):
        b = eligible["budget"]
        print(f"\neligible budget: max/min {b.max() / b.min():.1f}x, "
              f"p95/p05 {b.quantile(0.95) / b.quantile(0.05):.1f}x")
    print()
    print(summary.drop(columns=["interpretation"]).round(3).to_string(index=False))
    print()
    check_amount_settings(eligible, rules)
    warn_if_short(df, rules, sum(size for _, size in roles), sample)


if __name__ == "__main__":
    main()
