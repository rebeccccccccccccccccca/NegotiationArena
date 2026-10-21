"""
Second-round review of the manual case coding (coding_manual.md, 判讀流程
step 2).

  export  writes data/procurement/coding_round2.csv: every case the first
          round left open, grouped by kind of doubt, with what the award
          notice adds beyond the coding sheet (notice URL, every awarded
          item, country of origin, winning vendor and its trade, contract
          period, unit-price award, additional notes). The reviewer fills
          the protocol and source-audit fields as well as include_r2,
          reason_code_r2 and r2_evidence there.
  append  adds to an existing coding_round2.csv the cases a fresh export
          would list but the sheet lacks (e.g. a group added later), at the
          end; rows already there, and their review input, are kept as they
          are, and a column the sheet lacks is added last.
  merge   copies the reviewed rows back into case_coding.csv (dry run unless
          --write): include and reason_code take the round-2 values and
          "｜二輪：<evidence>" is appended to coder_note. Rows not reviewed
          yet are left alone, so it can run after each sitting.

Groups (a case is in the first that applies):
  A_E10        N / E10, data too thin to decide
  B_E9         N / E9, item known not to fit the category
  C_Y_二輪     Y, but the note asks for a second-round check
  D_N_二輪     N with another code, note asks for a second-round check
  E_備註無標記 a note without the second-round marker (Y or N): listed
               so nothing with a stated doubt is skipped
  F_級距高於預算 Y with no note, but the notice's 採購金額級距 is above
               what its budget implies (budget under 1500000, tier at or
               over the announcement threshold): the procurement amount
               may include options or follow-on purchases, so B may not be
               the whole price (inclusion condition 3)
  G_單價或長履約 Y with no note, awarded on unit price times estimated
               quantity, or with a contract period over LONG_DAYS days: the
               purchase may be an open-ended or staged supply (E4 / E5)
               rather than one lot whose whole price is B

Usage (from the repo root):
  .venv\\Scripts\\python -m experiments.procurement.coding_round2 export
  .venv\\Scripts\\python -m experiments.procurement.coding_round2 append
  .venv\\Scripts\\python -m experiments.procurement.coding_round2 merge
  .venv\\Scripts\\python -m experiments.procurement.coding_round2 merge --write
"""

import argparse
import csv
import io
import json
import re
from collections import Counter
from datetime import date

from experiments.cases import ROOT

CODING_PATH = ROOT / "data" / "procurement" / "case_coding.csv"
SHEET_PATH = ROOT / "data" / "procurement" / "coding_round2.csv"
DETAILS_PATH = ROOT / "data" / "procurement" / "raw" / "award_details.jsonl"
POOL_RULES_PATH = ROOT / "data" / "procurement" / "pool_rules.json"

MARKER = "二輪"
CODES = {f"E{i}" for i in range(1, 11)}
GROUPS = ["A_E10", "B_E9", "C_Y_二輪", "D_N_二輪", "E_備註無標記", "F_級距高於預算", "G_單價或長履約"]
SMALL_TIER = "未達公告金額"
LONG_DAYS = 180
CODING_COLUMNS = [
    "case_id", "pool_rank", "category_code", "category_zh", "budget", "quantity",
    "unit_name", "title", "item_name", "include", "reason_code", "coder_note",
]
DETAIL_COLUMNS = [
    "notice_url", "amount_tier", "n_items", "item_names", "unit_price_award", "origin",
    "winner", "winner_trade", "contract_period", "additional_note",
]
REVIEW_COLUMNS = ["include_r2", "reason_code_r2", "r2_evidence"]
CURRENT_PROTOCOL = "R2-20261021"
# The corresponding manual is a draft. Enable only after researcher approval.
PROTOCOL_FROZEN = False
AUDIT_COLUMNS = [
    "r2_protocol", "r2_sources_checked", "r2_award_method",
    "r2_quantity_binding", "r2_calloff", "r2_settlement",
    "r2_budget_scope", "r2_item_scope", "r2_unresolved",
]
# pilot_excluded = Y: already played in a pilot, so build_pool never gives
# it a role whatever its code; reviewing it changes nothing. contract_days
# was added after the first sheet went out, so it comes last and existing
# sheets keep their column order.
FIELDS = ["review_group", "pilot_excluded"] + CODING_COLUMNS + DETAIL_COLUMNS + REVIEW_COLUMNS + ["contract_days"] + AUDIT_COLUMNS


def group_of(row, details):
    note = row["coder_note"].strip()
    if row["include"] == "N" and row["reason_code"] == "E10":
        return "A_E10"
    if row["include"] == "N" and row["reason_code"] == "E9":
        return "B_E9"
    if MARKER in note:
        return "C_Y_二輪" if row["include"] == "Y" else "D_N_二輪"
    if note:
        return "E_備註無標記"
    if row["include"] != "Y":
        return None
    if details["amount_tier"] and details["amount_tier"] != SMALL_TIER:
        return "F_級距高於預算"
    days = details["contract_days"]
    if details["unit_price_award"] == "是" or (days != "" and days > LONG_DAYS):
        return "G_單價或長履約"
    return None


def contract_days(period):
    """Length in days of the longest contract period in text such as
    "115/01/01－115/12/31(預估)" (ROC years; several winners are joined by
    、); "" when no period can be read."""
    spans = []
    for part in period.split("、"):
        dates = re.findall(r"(\d{2,3})/(\d{1,2})/(\d{1,2})", part)
        if len(dates) >= 2:
            start, end = (date(int(y) + 1911, int(m), int(d)) for y, m, d in dates[:2])
            spans.append((end - start).days)
    return max(spans) if spans else ""


def amount_tier(detail):
    """採購金額級距; the section prefix differs between notice formats."""
    return next((v for k, v in detail.get("detail", {}).items() if k.endswith("採購金額級距")), "")


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, fields, rows):
    """utf-8 with BOM and CRLF, the format Excel saves case_coding.csv in."""
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=fields, lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)
    path.write_bytes(b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8"))


def unique(values):
    return list(dict.fromkeys(v for v in values if v))


def notice_details(detail):
    """The award-notice fields a reviewer needs, flattened to text."""
    d = detail.get("detail", {})
    items = sorted(
        {int(m.group(1)) for k in d if (m := re.match(r"決標品項:第(\d+)品項:", k))}
    )
    names, unit_price, origin = [], [], []
    for i in items:
        prefix = f"決標品項:第{i}品項:"
        names.append(d.get(prefix + "品項名稱", ""))
        unit_price.append(d.get(prefix + "是否以單價及預估需求數量之乘積決定最低標", ""))
        origin += [v for k, v in d.items() if k.startswith(prefix) and k.endswith("原產地國別:原產地國別")]
    bidders = sorted(
        {int(m.group(1)) for k in d if (m := re.match(r"投標廠商:投標廠商(\d+):", k))}
    )
    winners = [b for b in bidders if d.get(f"投標廠商:投標廠商{b}:是否得標") == "是"]
    field = lambda name: unique(d.get(f"投標廠商:投標廠商{b}:{name}", "") for b in winners)
    period = "、".join(field("履約起迄日期"))
    return {
        "notice_url": d.get("url", ""),
        "amount_tier": amount_tier(detail),
        "n_items": d.get("決標品項:決標品項數", ""),
        "item_names": " | ".join(names),
        "unit_price_award": "是" if "是" in unit_price else ("否" if unit_price else ""),
        "origin": "、".join(unique(origin)),
        "winner": "、".join(field("廠商名稱")),
        "winner_trade": "、".join(field("廠商業別")),
        "contract_period": period,
        "additional_note": d.get("決標資料:附加說明", "").strip(),
        "contract_days": contract_days(period),
    }


def sheet_rows():
    """The rows a fresh export lists, in sheet order."""
    coding = read_csv(CODING_PATH)
    ids = {r["case_id"] for r in coding}
    details = {}
    with open(DETAILS_PATH, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rec = json.loads(line)
                if rec["filename"] in ids:
                    details[rec["filename"]] = rec
    missing = sorted(ids - set(details))
    if missing:
        raise SystemExit(f"no award notice on disk for {len(missing)} case(s): {missing[:5]}")
    notices = {cid: notice_details(rec) for cid, rec in details.items()}
    picked = [(group_of(r, notices[r["case_id"]]), r) for r in coding]
    picked = [(g, r) for g, r in picked if g]

    excluded = set(json.loads(POOL_RULES_PATH.read_text(encoding="utf-8"))["exclude_case_ids"])
    picked.sort(key=lambda gr: (GROUPS.index(gr[0]), gr[1]["category_code"], float(gr[1]["budget"])))
    return [
        {
            "review_group": g,
            "pilot_excluded": "Y" if r["case_id"] in excluded else "",
            **{k: r[k] for k in CODING_COLUMNS},
            **notices[r["case_id"]],
            **{k: "" for k in REVIEW_COLUMNS + AUDIT_COLUMNS},
        }
        for g, r in picked
    ]


def print_counts(label, rows):
    counts = Counter(r["review_group"] for r in rows)
    print(f"{label} {len(rows)} cases")
    for g in GROUPS:
        if counts.get(g):
            print(f"  {g}: {counts[g]}")


def export(args):
    if SHEET_PATH.exists() and not args.force:
        raise SystemExit(f"{SHEET_PATH.relative_to(ROOT)} exists (it may hold review input); --force to overwrite")
    rows = sheet_rows()
    write_csv(SHEET_PATH, FIELDS, rows)
    print_counts(f"wrote {SHEET_PATH.name}:", rows)


def append(args):
    with open(SHEET_PATH, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields, existing = list(reader.fieldnames), list(reader)
    have = {r["case_id"] for r in existing}
    new = [r for r in sheet_rows() if r["case_id"] not in have]
    fields += [k for k in FIELDS if k not in fields]
    print_counts(f"{len(existing)} cases kept as they are; adding", new)
    if new:
        write_csv(SHEET_PATH, fields, existing + new)


def check_review(row):
    """Problems with one reviewed row, as text; empty when it is valid."""
    inc, code, evidence = (row[k].strip() for k in REVIEW_COLUMNS)
    problems = []
    if inc not in ("Y", "N"):
        problems.append(f"include_r2 must be Y or N, not {inc!r}")
    elif inc == "N" and code not in CODES:
        problems.append(f"reason_code_r2 must be E1-E10 when N, not {code!r}")
    elif inc == "Y" and code:
        problems.append("reason_code_r2 must be empty when Y")
    if not evidence:
        problems.append("r2_evidence is empty (record what was checked)")
    if row.get("r2_protocol", "").strip() != CURRENT_PROTOCOL:
        problems.append(f"r2_protocol must be {CURRENT_PROTOCOL} after re-review")
    if not row.get("r2_sources_checked", "").strip():
        problems.append("r2_sources_checked is empty")
    if inc == "N" and code == "E10" and not row.get("r2_unresolved", "").strip():
        problems.append("N/E10 requires r2_unresolved (which necessary evidence is missing)")
    return problems


def merge(args):
    if args.write and not PROTOCOL_FROZEN:
        raise SystemExit("round-2 protocol is still a draft; researcher approval and manual freeze required before --write")
    sheet = read_csv(SHEET_PATH)
    coding = read_csv(CODING_PATH)
    fields = list(coding[0].keys())
    by_id = {r["case_id"]: r for r in coding}

    applied, already, pending, errors = [], 0, 0, []
    for row in sheet:
        cid = row["case_id"]
        if not row["include_r2"].strip():
            pending += 1
            continue
        target = by_id.get(cid)
        if target is None:
            errors.append(f"{cid}: not in {CODING_PATH.name}")
            continue
        problems = check_review(row)
        if problems:
            errors.append(f"{cid}: " + "; ".join(problems))
            continue
        inc, code, evidence = (row[k].strip() for k in REVIEW_COLUMNS)
        tag = f"｜{MARKER}：{evidence}"
        if target["include"] == inc and target["reason_code"] == code and target["coder_note"].endswith(tag):
            already += 1
            continue
        # The first-round values the sheet was exported with must still be
        # the ones on file, so a later edit to case_coding.csv is not
        # silently overwritten.
        if (target["include"], target["reason_code"]) != (row["include"], row["reason_code"]):
            errors.append(
                f"{cid}: case_coding.csv now has {target['include']}/{target['reason_code'] or '-'}, "
                f"the sheet was exported with {row['include']}/{row['reason_code'] or '-'}"
            )
            continue
        applied.append((row["review_group"], f"{row['include']}/{row['reason_code'] or '-'}", f"{inc}/{code or '-'}"))
        target["include"], target["reason_code"] = inc, code
        target["coder_note"] = target["coder_note"] + tag

    print(f"{len(sheet)} cases in the sheet: {len(applied)} to apply, {already} already applied, "
          f"{pending} not reviewed yet, {len(errors)} with problems")
    for (group, before, after), n in sorted(Counter(applied).items()):
        print(f"  {group}: {before} -> {after}  x{n}")
    for e in errors:
        print(f"  PROBLEM {e}")
    if errors:
        raise SystemExit("fix the problems above first; nothing was written")
    if not args.write:
        print("dry run: nothing written (--write to apply)")
        return
    if applied:
        write_csv(CODING_PATH, fields, coding)
        print(f"updated {CODING_PATH.name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("export", help="write the review sheet")
    p.add_argument("--force", action="store_true", help="overwrite an existing sheet")
    p.set_defaults(func=export)
    p = sub.add_parser("append", help="add the cases the sheet lacks, keeping every existing row")
    p.set_defaults(func=append)
    p = sub.add_parser("merge", help="copy reviewed rows back into case_coding.csv")
    p.add_argument("--write", action="store_true", help="apply instead of a dry run")
    p.set_defaults(func=merge)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
