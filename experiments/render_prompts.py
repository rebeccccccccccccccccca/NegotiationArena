"""
Render every model-facing text of one game in both languages, the way
batch_runner.build_game builds it, without any API call: both system
prompts, the seller's role turn, the seller's scripted opening and what the
buyer is shown of it. Written as a Markdown sheet for reviewing the wording
of a prompt version side by side.

The category label comes from the glossary the config names when it has
the code; with --draft-glossary it comes from that file instead (e.g. the
unreviewed data/procurement/category_glossary_draft.csv), so the sheet shows
the wording under review. Nothing is written under .logs/.

Usage (from the repo root):
  .venv\\Scripts\\python -m experiments.render_prompts --out experiments/prompt_review_v1.1.md
  .venv\\Scripts\\python -m experiments.render_prompts --draft-glossary data/procurement/category_glossary_draft.csv
"""

import argparse
import csv
import tempfile
from pathlib import Path

import experiments.batch_runner as br
from experiments.cases import ROOT, load_cases, load_config, load_glossary, negotiation_settings, prices

STRUCTURE_NAMES = {"under_budget": "預算內首價", "over_budget": "超預算首價", "no_overlap": "無交集"}
SECTIONS = [
    ("1. 賣方（Player RED）system prompt", "seller_system"),
    ("2. 賣方角色宣告（第一則 user 訊息）", "seller_role"),
    ("3. 買方（Player BLUE）system prompt（最後一行是角色宣告）", "buyer_system"),
    ("4. 賣方第一回合（腳本，留在賣方自己的歷史）", "scripted"),
    ("5. 買方收到的第一則訊息（賣方回合的公開欄位）", "to_buyer"),
]


def render(config, case, structure, version, glossary, log_root):
    # build_game puts each game's log folder under stage_log_root; point it
    # at a scratch folder so rendering leaves .logs/ untouched.
    br.stage_log_root = lambda stage: Path(log_root) / stage
    out = {}
    for lang in ("en", "zh"):
        row = {"language": lang, "stage": "render", "game_label": f"render_{lang}", "tactic": "baseline",
               "seller_prompt_version": version, "buyer_prompt_version": version, "structure": structure}
        settings = negotiation_settings(config, case, structure, lang, glossary)
        game = br.build_game(config, config["model_profile"], row, settings)
        seller, buyer = game.players
        scripted = seller._scripted_first_offer()  # the scripted turn: no API call
        out[lang] = {
            "settings": settings,
            "seller_system": next(m["content"] for m in seller.conversation if m["role"] == "system"),
            "seller_role": next(m["content"] for m in seller.conversation if m["role"] == "user"),
            # chatgpt.py appends the second player's role to its system prompt.
            "buyer_system": next(m["content"] for m in buyer.conversation if m["role"] == "system"),
            "scripted": scripted,
            "to_buyer": game.game_interface.parse(scripted).message_to_other_player(),
        }
    return out


def sheet(config, case, structure, version, rendered, glossary_source):
    s = rendered["en"]["settings"]
    lines = [
        f"# prompt {version} 中英全文審閱稿",
        "",
        f"由 `experiments/render_prompts.py` 依 `batch_runner.build_game` 的方式組出一局的所有模型可見文字，"
        f"沒有呼叫 API。分類標籤來源：{glossary_source}；情境句來源：設定檔 `case_context`"
        f"（狀態 {config['case_context'].get('status', '—')}）。",
        "",
        f"- 示例案例：`{case['case_id']}`（{case['role']}，pool_rank {case['pool_rank']}），"
        f"標題「{case['title']}」，分類 {case['category_code']}，數量 {s['quantity']}",
        f"- 示例情境：{STRUCTURE_NAMES.get(structure, structure)}（`{structure}`）：B = {s['wtp']}、"
        f"C = {s['cost']}、O = {s['seller_first_offer']}、買方資金 = {s['buyer_funds']}",
        "- H1 的三種情境只差目標句裡的金額與賣方開價：",
        "",
        "| 情境 | C（賣方成本） | B（買方預算） | O（賣方開價） |",
        "|---|---|---|---|",
    ]
    for st in config["stages"]["h1"]["structures"]:
        c, o, _ = prices(config, s["wtp"], st)
        lines.append(f"| {STRUCTURE_NAMES.get(st, st)} | {c} | {s['wtp']} | {o} |")
    lines += [
        "",
        "模型看到的順序（框架原本的做法，`chatgpt.py` 的 `init_agent`）：賣方是 system prompt，再以第一則 "
        "user 訊息給角色宣告；買方的角色宣告直接接在 system prompt 最後，沒有另起一則訊息。賣方第一回合"
        "由腳本產生，以賣方自己的回覆留在賣方歷史中；買方收到的是其中的公開欄位。",
        "",
    ]
    for title, key in SECTIONS:
        lines += [f"## {title}", ""]
        for lang, label in (("en", "英文"), ("zh", "中文")):
            lines += [f"**{label}**", "", "````text", rendered[lang][key].rstrip("\n"), "````", ""]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--case", help="case_id (default: the first calibration case by pool_rank)")
    parser.add_argument("--structure", default="over_budget")
    parser.add_argument("--version", default="v1.1", help="prompt version for both players")
    parser.add_argument("--draft-glossary", help="CSV with category_code, label_zh, label_en to use instead")
    parser.add_argument("--out", default="experiments/prompt_review_v1.1.md")
    args = parser.parse_args()

    config = load_config()
    if args.draft_glossary:
        with open(ROOT / args.draft_glossary, encoding="utf-8-sig", newline="") as f:
            glossary = {r["category_code"]: r for r in csv.DictReader(f)}
        glossary_source = f"`{args.draft_glossary}`（未審初稿）"
    else:
        glossary = load_glossary(config)
        glossary_source = f"`{config['category_glossary']}`（缺代碼時用官方名稱）"
    cases = load_cases(config, {"calibration", "stage1_2", "reserve"})
    case = (next(c for c in cases if c["case_id"] == args.case) if args.case
            else next(c for c in cases if c["role"] == "calibration"))
    with tempfile.TemporaryDirectory() as log_root:
        rendered = render(config, case, args.structure, args.version, glossary, log_root)
    out = ROOT / args.out
    out.write_text(sheet(config, case, args.structure, args.version, rendered, glossary_source), encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
