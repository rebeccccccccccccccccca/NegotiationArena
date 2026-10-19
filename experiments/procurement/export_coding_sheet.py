"""
Export the manual coding sheet for the case pool: every candidate whose
budget lies in the planned range, with keyword flags and a suggested
exclusion code as hints for the coder (nothing is excluded here). The
codes are defined in data/procurement/coding_manual.md.

The coder fills `include` (Y/N), `reason_code` (E1-E10 when N) and
`coder_note`. The sheet is never overwritten without --force, so manual
coding can't be lost by re-running this.

Usage (from the repo root):
  .venv\\Scripts\\python -m experiments.procurement.export_coding_sheet
  .venv\\Scripts\\python -m experiments.procurement.export_coding_sheet --budget-min 150001 --budget-max 1499999
"""

import argparse
import csv

from experiments.cases import ROOT

CANDIDATES_PATH = ROOT / "data" / "procurement" / "candidates.csv"
SHEET_PATH = ROOT / "data" / "procurement" / "case_coding.csv"

# Suggested code -> (category code prefixes, title/item keywords), checked
# in this order; the first match is the suggestion. Hints only: the coder
# decides, and a flag can be a false alarm (e.g. 暨 in an event name).
SUGGESTIONS = [
    ("E7", ("21", "22", "23", "24", "352"), ("菌苗", "疫苗", "藥品", "食材", "餐盒", "點心")),
    ("E8", ("15", "17", "18", "531", "532"), ()),
    ("E4", (), ("後續擴充", "變更設計", "契約變更", "增購", "共約額外項")),
    ("E6", (), ("禮券", "商品券", "禮品卡")),
    ("E1", (), ("工程", "修繕", "整修", "拆除", "建置", "統包", "安裝")),
    ("E3", (), ("系統", "平台", "平臺", "軟體", "授權", "雲端")),
    ("E2", (), ("印製", "服務", "維護", "租賃", "照相", "美編", "檢驗", "委託")),
]
FLAG_WORDS = sorted({w for _, _, words in SUGGESTIONS for w in words} | {"暨", "一式", "1式", "含"})
FIELDS = [
    "case_id", "pool_rank", "category_code", "category_zh", "budget",
    "at_boundary", "quantity", "unit_name", "title", "item_name",
    "flags", "suggested_code", "include", "reason_code", "coder_note",
]


def suggest(row):
    text = f"{row['title']} {row['item_name']}"
    for code, prefixes, words in SUGGESTIONS:
        if prefixes and row["category_code"].startswith(prefixes):
            return code
        if any(w in text for w in words):
            return code
    return ""


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--budget-min", type=float, default=150_000, help="inclusive")
    parser.add_argument("--budget-max", type=float, default=1_500_000, help="inclusive")
    parser.add_argument("--force", action="store_true", help="overwrite an existing sheet")
    args = parser.parse_args()

    if SHEET_PATH.exists() and not args.force:
        raise SystemExit(f"{SHEET_PATH.relative_to(ROOT)} exists (it may hold manual coding); --force to overwrite")
    with open(CANDIDATES_PATH, encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f) if args.budget_min <= float(r["budget"]) <= args.budget_max]
    rows.sort(key=lambda r: (r["category_code"], float(r["budget"])))

    out = []
    for r in rows:
        text = f"{r['title']} {r['item_name']}"
        budget = float(r["budget"])
        out.append(
            {
                **{k: r[k] for k in ("case_id", "pool_rank", "category_code", "category_zh",
                                     "quantity", "unit_name", "title", "item_name")},
                "budget": f"{budget:.0f}",
                # 150,000 is the small-purchase ceiling and 1,500,000 the
                # announcement threshold; a case exactly on one of them
                # stays or goes with the boundary decision.
                "at_boundary": "Y" if budget in (args.budget_min, args.budget_max) else "",
                "flags": " ".join(w for w in FLAG_WORDS if w in text),
                "suggested_code": suggest(r),
                "include": "",
                "reason_code": "",
                "coder_note": "",
            }
        )
    # utf-8-sig so Excel opens the Chinese text correctly.
    with open(SHEET_PATH, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(out)
    n_suggested = sum(1 for r in out if r["suggested_code"])
    print(
        f"wrote {len(out)} cases in [{args.budget_min:.0f}, {args.budget_max:.0f}] to "
        f"{SHEET_PATH.relative_to(ROOT)}; {n_suggested} carry a suggested exclusion code"
    )


if __name__ == "__main__":
    main()
