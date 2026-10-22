"""
Lean route to freezing the case pool (h1_decision_record.md v0.6, section 6):
the researcher confirms, case by case, the first-round Y cases that carry no
doubt flag; every flagged case not verified under the round-2 protocol is
excluded conservatively.

  export  writes data/procurement/pool_confirm.csv: the Y cases outside
          coding_round2.csv (and outside the pilot exclusion list), with the
          award-notice facts the five checks need. Facts read straight from
          the notice are prefilled (chk_total_price, chk_budget_match); the
          researcher fills chk_item_specific, chk_one_lot, chk_no_contrary,
          confirm (Y/N), reason_code (E1-E10 when N) and confirm_note.
  apply   checks the sheet and, with --write, updates case_coding.csv:
          confirm = N takes the given code; every Y case in coding_round2.csv
          becomes N / E10 (excluded conservatively, not verified); confirmed
          cases get the confirmation recorded in coder_note. Refuses to
          write while any row is unconfirmed, a confirmed Y fails a check,
          or fewer than NEEDED cases are confirmed.

Usage (from the repo root):
  .venv\\Scripts\\python -m experiments.procurement.pool_confirm export
  .venv\\Scripts\\python -m experiments.procurement.pool_confirm apply
  .venv\\Scripts\\python -m experiments.procurement.pool_confirm apply --write
"""

import argparse
import json
import re
from collections import Counter

from experiments.cases import ROOT
from experiments.procurement.coding_round2 import (
    CODES, CODING_PATH, DETAILS_PATH, POOL_RULES_PATH, SHEET_PATH, SMALL_TIER,
    notice_details, read_csv, write_csv,
)

CONFIRM_PATH = ROOT / "data" / "procurement" / "pool_confirm.csv"
NEEDED = 110  # calibration 20 + H1 80 + reserve 10
LONG_DAYS = 180
CONTRARY_RE = re.compile("後續擴充|增購|開口|叫貨|依實際|契約變更|共同供應")
GENERIC_RE = re.compile("計畫|活動|專案")
CHECKS = ["chk_item_specific", "chk_one_lot", "chk_total_price", "chk_budget_match", "chk_no_contrary"]
FIELDS = [
    "case_id", "pool_rank", "category_code", "category_zh", "budget", "quantity",
    "unit_name", "title", "item_name", "notice_url", "amount_tier", "award_method",
    "award_unit_price", "est_quantity", "contract_period", "contract_days",
    "additional_note", "auto_flags",
] + CHECKS + ["confirm", "reason_code", "confirm_note"]
LEAN_EXCLUSION = "｜精簡路線保守排除（有疑義旗標，未依第二輪程序查證）"


def first_value(detail, suffix):
    return next((v for k, v in detail.get("detail", {}).items() if k.endswith(suffix)), "")


def auto_flags(row, notice):
    """Contrary signals the notice shows, as text for the researcher."""
    flags = []
    text = f"{row['title']} {row['item_name']} {notice['additional_note']}"
    if m := CONTRARY_RE.search(text):
        flags.append(f"字樣「{m.group()}」")
    if m := GENERIC_RE.search(row["title"]):
        flags.append(f"標題含「{m.group()}」")
    if notice["unit_price_award"] == "是":
        flags.append("單價決標")
    days = notice["contract_days"]
    if days == "":
        flags.append("履約期間缺值")
    elif days > LONG_DAYS:
        flags.append(f"履約 {days} 天")
    if notice["amount_tier"] != SMALL_TIER:
        flags.append("級距高於預算")
    return "；".join(flags)


def export(args):
    if CONFIRM_PATH.exists() and not args.force:
        raise SystemExit(f"{CONFIRM_PATH.name} exists (it may hold confirmations); --force to overwrite")
    coding = read_csv(CODING_PATH)
    in_sheet = {r["case_id"] for r in read_csv(SHEET_PATH)}
    excluded = set(json.loads(POOL_RULES_PATH.read_text(encoding="utf-8"))["exclude_case_ids"])
    cands = [r for r in coding if r["include"] == "Y" and r["case_id"] not in in_sheet | excluded]
    ids = {r["case_id"] for r in cands}
    details = {}
    with open(DETAILS_PATH, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rec = json.loads(line)
                if rec["filename"] in ids:
                    details[rec["filename"]] = rec
    cands.sort(key=lambda r: (r["category_code"], float(r["budget"])))
    rows = []
    for r in cands:
        rec = details[r["case_id"]]
        notice = notice_details(rec)
        rows.append({
            **{k: r[k] for k in ("case_id", "pool_rank", "category_code", "category_zh", "budget",
                                 "quantity", "unit_name", "title", "item_name")},
            **{k: notice[k] for k in ("notice_url", "amount_tier", "contract_period",
                                      "contract_days", "additional_note")},
            "award_method": "單價" if notice["unit_price_award"] == "是" else "總價",
            "award_unit_price": first_value(rec, "得標廠商1:決標單價"),
            "est_quantity": first_value(rec, "得標廠商1:預估需求數量"),
            "auto_flags": auto_flags(r, notice),
            # Facts read straight from the notice; the researcher may change them.
            "chk_total_price": "Y" if notice["unit_price_award"] != "是" else "N",
            "chk_budget_match": "Y" if notice["amount_tier"] == SMALL_TIER else "N",
            **{k: "" for k in ("chk_item_specific", "chk_one_lot", "chk_no_contrary",
                               "confirm", "reason_code", "confirm_note")},
        })
    write_csv(CONFIRM_PATH, FIELDS, rows)
    print(f"wrote {len(rows)} candidates to {CONFIRM_PATH.name}; "
          f"{sum(1 for r in rows if r['auto_flags'])} carry an automatic flag")


def check_row(row):
    confirm, code = row["confirm"].strip(), row["reason_code"].strip()
    if confirm not in ("Y", "N"):
        return "confirm is empty (Y or N)" if not confirm else f"confirm must be Y or N, not {confirm!r}"
    if confirm == "N":
        return "" if code in CODES else f"reason_code must be E1-E10 when N, not {code!r}"
    if code:
        return "reason_code must be empty when Y"
    failed = [k for k in CHECKS if row[k].strip() != "Y"]
    return f"confirmed Y but not Y on {', '.join(failed)}" if failed else ""


def apply(args):
    sheet = read_csv(CONFIRM_PATH)
    coding = read_csv(CODING_PATH)
    fields = list(coding[0].keys())
    by_id = {r["case_id"]: r for r in coding}
    problems, unconfirmed = [], 0
    for row in sheet:
        target = by_id.get(row["case_id"])
        if target is None or target["include"] != "Y":
            problems.append(f"{row['case_id']}: no longer Y in {CODING_PATH.name}")
        elif not row["confirm"].strip():
            unconfirmed += 1
        elif msg := check_row(row):
            problems.append(f"{row['case_id']}: {msg}")
    if unconfirmed:
        problems.append(f"{unconfirmed} row(s) not confirmed yet (confirm is empty)")
    confirmed = [r for r in sheet if r["confirm"].strip() == "Y"]
    rejected = [r for r in sheet if r["confirm"].strip() == "N"]
    in_sheet_y = [by_id[r["case_id"]] for r in read_csv(SHEET_PATH)
                  if by_id.get(r["case_id"], {}).get("include") == "Y"]

    print(f"{len(sheet)} candidates: {len(confirmed)} confirmed Y, {len(rejected)} N "
          f"({dict(Counter(r['reason_code'].strip() for r in rejected))}), "
          f"{len(sheet) - len(confirmed) - len(rejected)} not confirmed yet")
    print(f"{len(in_sheet_y)} Y cases in {SHEET_PATH.name} would become N/E10 (conservative exclusion)")
    print(f"confirmed {len(confirmed)} / needed {NEEDED}")
    for p in problems:
        print(f"  PROBLEM {p}")
    if problems:
        raise SystemExit("fix the problems above first; nothing was written")
    if len(confirmed) < NEEDED:
        raise SystemExit(f"fewer than {NEEDED} confirmed: top up per h1_decision_record.md section 6 first; "
                         "nothing was written")
    if not args.write:
        print("dry run: nothing written (--write to apply)")
        return
    for row in rejected:
        t = by_id[row["case_id"]]
        t["include"], t["reason_code"] = "N", row["reason_code"].strip()
        t["coder_note"] += f"｜精簡確認排除：{row['confirm_note'].strip()}"
    for row in confirmed:
        t = by_id[row["case_id"]]
        note = row["confirm_note"].strip()
        t["coder_note"] += "｜研究者確認納入" + (f"：{note}" if note else "")
    for t in in_sheet_y:
        t["include"], t["reason_code"] = "N", "E10"
        t["coder_note"] += LEAN_EXCLUSION
    write_csv(CODING_PATH, fields, coding)
    print(f"updated {CODING_PATH.name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("export", help="write the confirmation sheet")
    p.add_argument("--force", action="store_true", help="overwrite an existing sheet")
    p.set_defaults(func=export)
    p = sub.add_parser("apply", help="check the sheet and update case_coding.csv")
    p.add_argument("--write", action="store_true", help="apply instead of a dry run")
    p.set_defaults(func=apply)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
