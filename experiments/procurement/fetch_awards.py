"""
Collect award notices (決標公告) from 政府電子採購網 through the g0v pcc
API (https://pcc-api.openfun.app, crawled from web.pcc.gov.tw). These
are the source of the procurement cases (item, quantity, budget, award
price) the negotiation scenarios are built from.

Steps, each resumable (re-running skips whatever is already on disk):

  categories  official 標的分類 code list with English names (data.gov.tw
              dataset 6576) -> raw/CpcOpenData.xml
  frame       every 決標公告 announced on each day in [--start, --end]
              -> raw/award_frame.jsonl  (the sampling frame)
  sample      first --per-month notices of each announcement month after
              a fixed random shuffle (--seed) -> sample_ids.csv; a larger
              --per-month later (with --force) only appends ids
  details     full notice for every sampled id -> raw/award_details.jsonl
  all         the four steps above in order
  manifest    zip raw/ + sample_ids.csv into backups/ and record sizes,
              SHA-256 hashes, fetch dates and pool_rules.json (content
              and hash) -> MANIFEST.json. Run it once the data is final
              and again after freezing pool_rules.json: the API may
              change or go offline, and the hashes show the backup and
              rules are the ones analysed.

Usage (from the repo root):
  .venv\\Scripts\\python -m experiments.procurement.fetch_awards all

Requests are sequential and paced by --min-interval: the API is run by
volunteers, so don't lower it much.
"""

import argparse
import csv
import datetime as dt
import hashlib
import json
import random
import ssl
import time
import zipfile
from collections import defaultdict
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter

API_BASE = "https://pcc-api.openfun.app/api"
CATEGORY_XML_URL = (
    "https://web.pcc.gov.tw/osm/public/proctrg/download/CpcOpenData.xml"
)

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "procurement"
RAW_DIR = OUT_DIR / "raw"
CATEGORY_XML_PATH = RAW_DIR / "CpcOpenData.xml"
FRAME_PATH = RAW_DIR / "award_frame.jsonl"
FRAME_DONE_PATH = RAW_DIR / "frame_dates_done.txt"
SAMPLE_PATH = OUT_DIR / "sample_ids.csv"
DETAILS_PATH = RAW_DIR / "award_details.jsonl"
FAILED_PATH = RAW_DIR / "details_failed.jsonl"
MANIFEST_PATH = OUT_DIR / "MANIFEST.json"
POOL_RULES_PATH = OUT_DIR / "pool_rules.json"
BACKUP_DIR = ROOT / "backups"

AWARD_TYPE = "決標公告"
# On a day with no notices at all (weekends, holidays) the API answers
# 200 with this PHP warning instead of JSON.
NO_DATA_MARKER = "count(): Parameter must be an array"

SAMPLE_FIELDS = [
    "month",
    "month_rank",
    "date",
    "filename",
    "unit_id",
    "job_number",
    "unit_name",
    "title",
]


class Pacer:
    """Keeps at least `min_interval` seconds between consecutive requests."""

    def __init__(self, min_interval):
        self.min_interval = min_interval
        self.last = 0.0

    def wait(self):
        remaining = self.min_interval - (time.monotonic() - self.last)
        if remaining > 0:
            time.sleep(remaining)
        self.last = time.monotonic()


class LenientX509Adapter(HTTPAdapter):
    # web.pcc.gov.tw's certificate has no Subject Key Identifier, which
    # Python 3.13+ rejects under its default strict X.509 checks. Chain and
    # hostname are still verified; only the strict-mode extras are off.
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


session = requests.Session()
session.headers["User-Agent"] = "NegotiationArena-thesis-research (python-requests)"
session.mount("https://web.pcc.gov.tw/", LenientX509Adapter())


def http_get(url, pacer, params=None, retries=6):
    # Backoff doubles from 2s, so the last retry comes ~2 minutes after
    # the first failure: enough to ride out a short network drop.
    for attempt in range(retries + 1):
        pacer.wait()
        try:
            resp = session.get(url, params=params, timeout=120)
            if resp.status_code < 500:
                resp.raise_for_status()
                return resp
            error = f"HTTP {resp.status_code}"
        except requests.RequestException as e:
            error = repr(e)
        if attempt == retries:
            raise RuntimeError(f"GET {url} {params} failed: {error}")
        backoff = 2 ** (attempt + 1)
        print(f"  retry in {backoff}s ({error})")
        time.sleep(backoff)


def api_get(endpoint, pacer, params):
    """JSON from the pcc API, or None when the API reports no data."""
    resp = http_get(f"{API_BASE}/{endpoint}", pacer, params=params)
    if NO_DATA_MARKER in resp.text:
        return None
    return resp.json()


def append_text(path, text, retries=5):
    # OneDrive sometimes holds a file for a moment while syncing it.
    for attempt in range(retries + 1):
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(text)
            return
        except PermissionError:
            if attempt == retries:
                raise
            time.sleep(1)


def append_jsonl(path, objs):
    if objs:
        append_text(
            path, "".join(json.dumps(o, ensure_ascii=False) + "\n" for o in objs)
        )


def read_jsonl(path):
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def step_categories(pacer):
    if CATEGORY_XML_PATH.exists():
        print(f"categories: {CATEGORY_XML_PATH.name} already on disk")
        return
    resp = http_get(CATEGORY_XML_URL, pacer)
    CATEGORY_XML_PATH.write_bytes(resp.content)
    print(f"categories: saved {len(resp.content):,} bytes")


def step_frame(start, end, pacer):
    done = set()
    if FRAME_DONE_PATH.exists():
        done = set(FRAME_DONE_PATH.read_text(encoding="utf-8").split())
    day = start
    while day <= end:
        key = day.strftime("%Y%m%d")
        if key not in done:
            data = api_get("listbydate", pacer, {"date": key})
            records = [] if data is None else data["records"]
            awards = [
                {
                    "date": r["date"],
                    "filename": r["filename"],
                    "unit_id": r["unit_id"],
                    "job_number": r["job_number"],
                    "unit_name": r["unit_name"],
                    "title": r["brief"]["title"],
                }
                for r in records
                if r["brief"]["type"] == AWARD_TYPE
            ]
            # One write per day, then mark the day done; a crash in
            # between only duplicates lines, which load_frame() drops.
            append_jsonl(FRAME_PATH, awards)
            append_text(FRAME_DONE_PATH, key + "\n")
            print(f"frame: {key} {len(records):>5} notices, {len(awards):>4} awards")
        day += dt.timedelta(days=1)


def load_frame():
    by_filename = {}
    for r in read_jsonl(FRAME_PATH):
        by_filename.setdefault(r["filename"], r)
    return list(by_filename.values())


def step_sample(per_month, seed, force):
    if SAMPLE_PATH.exists() and not force:
        print(f"sample: {SAMPLE_PATH.name} exists, keeping it (--force to redraw)")
        return
    by_month = defaultdict(list)
    for r in load_frame():
        by_month[str(r["date"])[:6]].append(r)
    rng = random.Random(seed)
    rows = []
    for month in sorted(by_month):
        # Shuffle the whole month (fixed order first, so the same seed gives
        # the same permutation) and keep the first `per_month`. The
        # permutation doesn't depend on `per_month`, so redrawing with a
        # larger value keeps every id drawn before and only appends.
        pool = sorted(by_month[month], key=lambda r: r["filename"])
        rng.shuffle(pool)
        for rank, r in enumerate(pool[:per_month], 1):
            rows.append(
                {
                    "month": month,
                    "month_rank": rank,
                    **{k: r[k] for k in SAMPLE_FIELDS[2:]},
                }
            )
        print(f"sample: {month} {len(pool):>6} awards in frame")
    with open(SAMPLE_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SAMPLE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"sample: {len(rows)} ids -> {SAMPLE_PATH.name}")


def step_details(pacer):
    with open(SAMPLE_PATH, encoding="utf-8", newline="") as f:
        sample = list(csv.DictReader(f))
    done = {r["filename"] for r in read_jsonl(DETAILS_PATH)}
    todo = [row for row in sample if row["filename"] not in done]
    print(f"details: {len(done)} on disk, {len(todo)} to fetch")
    for i, row in enumerate(todo, 1):
        data = api_get(
            "tender",
            pacer,
            {"unit_id": row["unit_id"], "job_number": row["job_number"]},
        )
        # A job number's history holds every notice of the case; keep only
        # the award notice that was sampled.
        match = next(
            (
                r
                for r in (data or {}).get("records", [])
                if r.get("filename") == row["filename"]
            ),
            None,
        )
        if match is None:
            append_jsonl(FAILED_PATH, [{**row, "reason": "notice_not_found"}])
            print(f"details: [{i}/{len(todo)}] {row['filename']} not found")
            continue
        append_jsonl(
            DETAILS_PATH,
            [
                {
                    "filename": row["filename"],
                    "date": match["date"],
                    "unit_id": row["unit_id"],
                    "job_number": row["job_number"],
                    "fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
                    "detail": match["detail"],
                }
            ],
        )
        if i % 50 == 0 or i == len(todo):
            print(f"details: [{i}/{len(todo)}]")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def file_entry(path):
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def step_manifest(start, end, seed):
    files = [
        p
        for p in [
            CATEGORY_XML_PATH,
            FRAME_DONE_PATH,
            FRAME_PATH,
            SAMPLE_PATH,
            DETAILS_PATH,
            FAILED_PATH,
        ]
        if p.exists()
    ]
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M")
    zip_path = BACKUP_DIR / f"procurement_raw_{stamp}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            zf.write(p, p.relative_to(ROOT).as_posix())

    frame = load_frame()
    dates_with_awards = {str(r["date"]) for r in frame}
    queried = FRAME_DONE_PATH.read_text(encoding="utf-8").split()
    with open(SAMPLE_PATH, encoding="utf-8", newline="") as f:
        sample = list(csv.DictReader(f))
    sample_ids = {r["filename"] for r in sample}
    fetched_at = [
        r["fetched_at"] for r in read_jsonl(DETAILS_PATH) if r["filename"] in sample_ids
    ]
    manifest = {
        "source": "政府電子採購網 https://web.pcc.gov.tw, award notices "
        "(決標公告) retrieved through the g0v pcc API",
        "api_base": API_BASE,
        "category_list_url": CATEGORY_XML_URL,
        "frame": {
            "notice_type": AWARD_TYPE,
            "date_field": "決標公告日期 (announcement date, not award date)",
            "from": start.isoformat(),
            "to": end.isoformat(),
            "n_notices": len(frame),
            # Weekdays the API returned nothing for: public holidays, or
            # gaps in the API's crawl.
            "weekdays_without_notices": sorted(
                d
                for d in queried
                if d not in dates_with_awards
                and dt.datetime.strptime(d, "%Y%m%d").weekday() < 5
            ),
            "fetched_on": dt.date.fromtimestamp(FRAME_PATH.stat().st_mtime).isoformat(),
        },
        "sample": {
            "seed": seed,
            "per_month": max(int(r["month_rank"]) for r in sample),
            "n_ids": len(sample),
        },
        "details": {
            "n_fetched": len(fetched_at),
            "n_failed": len(read_jsonl(FAILED_PATH)),
            "fetched_from": min(fetched_at, default=None),
            "fetched_to": max(fetched_at, default=None),
        },
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "files": [file_entry(p) for p in files],
        "backup": file_entry(zip_path),
    }
    if POOL_RULES_PATH.exists():
        rules = json.loads(POOL_RULES_PATH.read_text(encoding="utf-8"))
        # build_pool checks this hash once `frozen` is recorded here.
        manifest["pool_rules"] = {
            **file_entry(POOL_RULES_PATH),
            "frozen": bool(rules.get("frozen")),
            "rules": {k: v for k, v in rules.items() if not k.startswith("_")},
        }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"manifest: backup {zip_path.name}, {len(files)} files -> {MANIFEST_PATH.name}")


def parse_date(s):
    return dt.datetime.strptime(s, "%Y-%m-%d").date()


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "step",
        choices=["categories", "frame", "sample", "details", "all", "manifest"],
    )
    parser.add_argument("--start", type=parse_date, default=dt.date(2025, 10, 1))
    parser.add_argument("--end", type=parse_date, default=dt.date(2026, 9, 30))
    parser.add_argument("--per-month", type=int, default=250)
    parser.add_argument("--seed", type=int, default=20261016)
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite sample_ids.csv; with the same --seed a larger "
        "--per-month keeps every earlier id",
    )
    # At 1.0 the API answered 429 to about one request in three.
    parser.add_argument("--min-interval", type=float, default=2.0)
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    pacer = Pacer(args.min_interval)
    if args.step in ("categories", "all"):
        step_categories(pacer)
    if args.step in ("frame", "all"):
        step_frame(args.start, args.end, pacer)
    if args.step in ("sample", "all"):
        step_sample(args.per_month, args.seed, args.force)
    if args.step in ("details", "all"):
        step_details(pacer)
    if args.step == "manifest":
        step_manifest(args.start, args.end, args.seed)


if __name__ == "__main__":
    main()
