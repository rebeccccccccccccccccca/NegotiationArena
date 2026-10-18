"""
Streamlit viewer for .logs/ game data. Does NOT import or depend on
Game.from_dict / Agent.from_dict (see experiments/worklog.md 2026-09-17 for
why: the original webapp/ can't load a single BuySellGame log, in ways
unrelated to language or any field added by this project). Every game is
read with a plain json.load() straight off game_state.json, following the
same pattern as webapp/pages/1_user_view.py's (working) chat_message
rendering, just without the broken discovery/deserialization layer in
front of it.

Everything is shown one data set at a time: pick a stage (H1, a pilot, a
smoke test) in the sidebar and every tab only sees that stage's games,
listed by game label (h1_001, h1_002, ...).

Run with: python -m streamlit run experiments/viewer.py
"""

import os
import sys
from pathlib import Path

# Make the project importable (`experiments.*`) and every path below
# resolve correctly regardless of the working directory the process was
# launched from -- e.g. double-clicking run_viewer.bat, or `streamlit run`
# from some other directory, both leave cwd pointed somewhere other than
# the repo root.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import json
import subprocess
import time
from datetime import datetime

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from experiments.summarize import trade_price

LOGS_DIR = ROOT / ".logs"
RESULTS_CSV = ROOT / "experiments" / "results.csv"
RUNS_JSONL = ROOT / "experiments" / "runs.jsonl"
WORKLOG_PATH = ROOT / "experiments" / "worklog.md"
PROMPT_VERSIONS_PATH = ROOT / "experiments" / "prompt_versions.json"

BOOL_COLS = [
    "buyer_countered_lower",
    "buyer_same_price_proposal",
    "deal",
    "breach_A",
    "seller_below_cost",
    "buyer_no_counter",
]
NUMERIC_COLS = [
    "temperature",
    "cost",
    "wtp",
    "seller_first_offer",
    "final_price",
    "rounds",
    "prompt_tokens",
    "completion_tokens",
    "est_cost_usd",
    "retry_count",
    "buyer_surplus_share",
    "buyer_surplus_uncond",
    "game_no",
    "order",
    "case_no",
    "attempt",
    "buyer_funds",
]

FORMAL_STAGES = {
    "h1": "H1 正式實驗",
    "h2": "H2 正式實驗",
    "h3": "H3 正式實驗",
    "wording": "措辭穩健性",
}
# Games with no stage: everything run before the batch runner (the
# gpt-4o-mini pilots). They only show up if moved back from .logs_archive/.
LEGACY_DATASET = "（Luna 之前的舊資料）"

STATUS_LABELS = {"ok": "成交", "rejected": "拒絕", "max_rounds": "回合用盡"}
ERROR_LABEL = "錯誤"
STRUCTURE_LABELS = {"wide": "寬鬆", "narrow": "緊縮", "no_range": "無交集"}
LANGUAGE_LABELS = {"en": "英文", "zh": "中文"}

# (column, header) of the game list, in display order.
TABLE_COLUMNS = [
    ("display_label", "局編號"),
    ("case_no", "案例"),
    ("category_label", "品項"),
    ("structure_label", "價格結構"),
    ("language_label", "語言"),
    ("result", "結果"),
    ("wtp", "預算 B"),
    ("cost", "成本 C"),
    ("seller_first_offer", "賣方開價 O"),
    ("final_price", "成交價"),
    ("rounds", "發言次數"),
    ("buyer_surplus_share", "買方剩餘份額"),
    ("breach_A", "失守 A（超預算成交）"),
    ("buyer_no_counter", "成交且未還價"),
    ("seller_prompt_version", "賣方版本"),
    ("buyer_prompt_version", "買方版本"),
    ("attempt", "第幾次嘗試"),
    ("order", "執行順序"),
]

# Columns this viewer relies on that older summarize.py versions didn't
# write; filled with blanks if missing so the page still loads.
EXPECTED_COLUMNS = [
    "stage",
    "game_label",
    "game_no",
    "order",
    "attempt",
    "case_no",
    "category_label",
    "structure",
    "seller_prompt_version",
    "buyer_prompt_version",
]


def dataset_label(stage):
    if stage is None:
        return LEGACY_DATASET
    if stage in FORMAL_STAGES:
        return FORMAL_STAGES[stage]
    if stage.startswith("smoke"):
        return f"測試：{stage}"
    return f"前導：{stage}"


def dataset_sort_key(stage):
    if stage in FORMAL_STAGES:
        return (0, list(FORMAL_STAGES).index(stage), stage)
    if stage.startswith("smoke"):
        return (2, 0, stage)
    return (1, 0, stage)


def _read_results_csv():
    # RESULTS_CSV lives under a OneDrive-synced folder; OneDrive's on-access
    # sync hook can make a file we *just* finished writing look briefly
    # empty/locked to the next reader. Retry a few times before giving up.
    last_exc = None
    for attempt in range(5):
        try:
            return pd.read_csv(RESULTS_CSV, dtype=str, keep_default_na=False)
        except pd.errors.EmptyDataError as e:
            last_exc = e
            time.sleep(0.2 * (attempt + 1))
    raise last_exc


def regenerate_results():
    """Rebuild results.csv in a separate process, so it is always the
    summarize.py on disk that runs: a long-lived Streamlit server keeps the
    modules it imported at start-up even after their files change."""
    return subprocess.run(
        [sys.executable, "-m", "experiments.summarize"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )


@st.cache_data
def load_results_df(_cache_key):
    df = _read_results_csv()
    missing = [c for c in EXPECTED_COLUMNS if c not in df.columns]
    for col in missing:
        df[col] = ""
    df = df.replace("", pd.NA)
    for col in BOOL_COLS:
        if col in df.columns:
            df[col] = df[col].map({"True": True, "False": False}).astype("boolean")
    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["result"] = df["status"].map(STATUS_LABELS).fillna(ERROR_LABEL)
    df["structure_label"] = df["structure"].map(STRUCTURE_LABELS)
    df["language_label"] = df["language"].map(LANGUAGE_LABELS).fillna(df["language"])
    df["display_label"] = df["game_label"].fillna(df["game_id"])
    return df, missing


def select_dataset(df):
    """Sidebar picker for one stage; returns (its games in game-number
    order, the stage or None for the pre-batch-runner games)."""
    options = sorted(df["stage"].dropna().unique(), key=dataset_sort_key)
    if df["stage"].isna().any():
        options.append(None)
    if not options:
        return df, None
    stage = st.sidebar.selectbox(
        "資料集", options, format_func=dataset_label, key="dataset"
    )
    if stage is None:
        return df[df["stage"].isna()].sort_values("game_id"), None
    sub = df[df["stage"] == stage]
    return sub.sort_values(["game_no", "attempt"], na_position="last"), stage


def load_runs_df():
    if not RUNS_JSONL.exists():
        return pd.DataFrame()
    rows = []
    with RUNS_JSONL.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    df = pd.DataFrame(rows)
    if "timestamp" in df.columns:
        df = df.sort_values("timestamp", ascending=False)
    return df


def load_prompt_versions():
    if not PROMPT_VERSIONS_PATH.exists():
        return []
    with PROMPT_VERSIONS_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def load_game_state(game_id):
    path = LOGS_DIR / game_id / "game_state.json"
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def money_token(game):
    """Currency the game was played in: TWD, or ZUP in older logs."""
    buyer_start = game["game_state"][0]["settings"]["player_initial_resources"][1]
    return next(iter(buyer_start.get("_value", {})), "")


def series_mean(series):
    series = series.dropna()
    if series.empty:
        return None
    return float(series.mean())


def game_option_label(row):
    """'h1_001 · 案例 1 · 寬鬆 · 英文' for game pickers."""
    parts = [row["display_label"]]
    if pd.notna(row.get("case_no")):
        parts.append(f"案例 {int(row['case_no'])}")
    if pd.notna(row.get("structure_label")):
        parts.append(row["structure_label"])
    parts.append(row["language_label"])
    if pd.notna(row.get("attempt")) and row["attempt"] > 1:
        parts.append(f"第 {int(row['attempt'])} 次嘗試")
    return " · ".join(parts)


def select_game(df, key):
    if df.empty:
        st.info("這個資料集沒有任何局。")
        return None
    labels = {row["game_id"]: game_option_label(row) for _, row in df.iterrows()}
    return st.selectbox(
        "選擇局", list(labels), format_func=labels.get, key=key
    )


def metrics_table(df):
    """Rows = metrics, columns = languages."""
    def rate(sub, mask):
        return mask.mean() if len(sub) else None

    metrics = [
        ("局數", lambda s: len(s), "count"),
        ("成交率", lambda s: rate(s, s["result"] == "成交"), "rate"),
        ("拒絕比例", lambda s: rate(s, s["result"] == "拒絕"), "rate"),
        ("回合用盡比例", lambda s: rate(s, s["result"] == "回合用盡"), "rate"),
        ("錯誤比例", lambda s: rate(s, s["result"] == ERROR_LABEL), "rate"),
        ("失守 A（超預算成交）比例", lambda s: series_mean(s["breach_A"]), "rate"),
        ("成交且未還價比例", lambda s: series_mean(s["buyer_no_counter"]), "rate"),
        ("買方剩餘份額平均（成交局）", lambda s: series_mean(s["buyer_surplus_share"]), "avg"),
        ("買方剩餘份額平均（未成交計 0）", lambda s: series_mean(s["buyer_surplus_uncond"]), "avg"),
        ("賣方低於成本成交比例", lambda s: series_mean(s["seller_below_cost"]), "rate"),
    ]
    langs = [lang for lang in ("en", "zh") if (df["language"] == lang).any()]
    rows = []
    for name, fn, kind in metrics:
        row = {"指標": name}
        for lang in langs:
            value = fn(df[df["language"] == lang])
            if value is None:
                row[LANGUAGE_LABELS[lang]] = "—"
            elif kind == "count":
                row[LANGUAGE_LABELS[lang]] = f"{value}"
            elif kind == "rate":
                row[LANGUAGE_LABELS[lang]] = f"{value:.1%}"
            else:
                row[LANGUAGE_LABELS[lang]] = f"{value:.3f}"
        rows.append(row)
    return pd.DataFrame(rows).set_index("指標")


def plot_surplus_dist(df):
    fig, ax = plt.subplots(figsize=(6, 3))
    plotted = False
    for lang, color in (("en", "tab:blue"), ("zh", "tab:orange")):
        vals = df[df["language"] == lang]["buyer_surplus_share"].dropna()
        if not vals.empty:
            plotted = True
            ax.hist(vals, bins=[i / 10 for i in range(11)], alpha=0.6,
                    label=LANGUAGE_LABELS[lang], color=color)
    ax.set_xlabel("Buyer surplus share (deals only)")
    ax.set_ylabel("Games")
    if plotted:
        ax.legend()
    return fig


def style_results_table(table):
    def style_breach(val):
        return "background-color: #ffb3b3" if val is True else ""

    def style_result(val):
        return "background-color: #fff3b0" if val == ERROR_LABEL else ""

    return (
        table.style
        .map(style_breach, subset=["失守 A（超預算成交）"])
        .map(style_result, subset=["結果"])
    )


def sidebar_filter(df, label, col):
    options = [x for x in df[col].dropna().unique()]
    if len(options) <= 1:
        return df
    chosen = st.sidebar.multiselect(label, sorted(options), default=sorted(options))
    return df[df[col].isin(chosen)]


def render_results_table_tab(df, stage):
    st.subheader(f"交易表格 — {dataset_label(stage)}")

    st.sidebar.header("篩選")
    filtered = df
    filtered = sidebar_filter(filtered, "語言", "language_label")
    filtered = sidebar_filter(filtered, "價格結構", "structure_label")
    filtered = sidebar_filter(filtered, "結果", "result")
    filtered = sidebar_filter(filtered, "賣方版本", "seller_prompt_version")
    filtered = sidebar_filter(filtered, "買方版本", "buyer_prompt_version")

    st.caption(f"{len(filtered)} / {len(df)} 局符合篩選條件")

    left, right = st.columns([3, 2])
    with left:
        st.markdown("#### 主要指標")
        st.table(metrics_table(filtered))
    with right:
        st.markdown("#### 買方剩餘份額分布")
        st.pyplot(plot_surplus_dist(filtered))

    st.markdown("#### 局列表（依局編號排序）")
    columns = [(c, h) for c, h in TABLE_COLUMNS if c in filtered.columns]
    table = filtered[[c for c, _ in columns]].rename(columns=dict(columns))
    st.dataframe(style_results_table(table), width="stretch", hide_index=True)
    with st.expander("顯示全部欄位"):
        st.dataframe(filtered, width="stretch", hide_index=True)


def render_negotiation_tab(df):
    st.subheader("議價過程")

    game_id = select_game(df, key="negotiation_game")
    if not game_id:
        return

    # The game's row from results.csv (rebuilt by the current summarize.py
    # at start-up), rather than re-summarizing it in this process.
    row = df[df["game_id"] == game_id].iloc[0]
    game = load_game_state(game_id)
    money = money_token(game)
    experiment = game.get("experiment") or {}

    def amount(value):
        return "—" if pd.isna(value) else f"{int(value):,}"

    cols = st.columns(5)
    cols[0].metric("語言", row["language_label"])
    cols[1].metric("結果", row["result"])
    cols[2].metric("預算 B", amount(row["wtp"]))
    cols[3].metric("成本 C", amount(row["cost"]))
    cols[4].metric("成交價", amount(row["final_price"]))
    if experiment.get("case_context"):
        st.caption(experiment["case_context"])

    with st.expander("其他欄位"):
        st.json(
            {
                k: None if pd.isna(row.get(k)) else str(row.get(k))
                for k in (
                    "game_id",
                    "model",
                    "model_version",
                    "seller_prompt_version",
                    "buyer_prompt_version",
                    "seller_first_offer",
                    "breach_A",
                    "seller_below_cost",
                    "buyer_no_counter",
                    "buyer_surplus_share",
                    "buyer_surplus_uncond",
                    "prompt_tokens",
                    "completion_tokens",
                    "est_cost_usd",
                )
            }
        )

    left, right = st.columns([2, 1])

    with left:
        for state in game["game_state"][1:]:
            if state.get("current_iteration") == "END":
                continue
            turn = int(state["turn"])
            speaker = "Player RED（賣方）" if turn == 0 else "Player BLUE（買方）"
            pub = state.get("player_public_info_dict", {})
            priv = state.get("player_private_info_dict", {})
            message = pub.get("message", "")
            answer = pub.get("player answer", "")
            trade = pub.get("newly proposed trade", "")
            price = trade_price(trade, "BLUE")

            with st.chat_message("assistant" if turn == 0 else "user"):
                st.markdown(f"**{speaker}** · {answer}" + (f" · {price:,} {money}" if price is not None else ""))
                if message:
                    st.write(message)
                reason = priv.get("reason") if isinstance(priv, dict) else None
                if reason:
                    with st.expander("推理 (reason)"):
                        st.write(reason)

    with right:
        iterations, prices = [], []
        for state in game["game_state"][1:]:
            if state.get("current_iteration") == "END":
                continue
            pub = state.get("player_public_info_dict", {})
            price = trade_price(pub.get("newly proposed trade", ""), "BLUE")
            if price is not None:
                iterations.append(state["current_iteration"])
                prices.append(price)

        fig, ax = plt.subplots()
        if iterations:
            ax.plot(iterations, prices, marker="o")
        if pd.notna(row["cost"]):
            ax.axhline(row["cost"], color="green", linestyle="--", label="Cost C")
        if pd.notna(row["wtp"]):
            ax.axhline(row["wtp"], color="red", linestyle="--", label="Budget B")
        ax.set_xlabel("Iteration")
        ax.set_ylabel(money)
        ax.legend()
        st.pyplot(fig)


def version_counts(series):
    """'v1×10, v3×2' for a column of per-game versions."""
    counts = series.fillna("—").value_counts()
    return ", ".join(f"{v}×{n}" for v, n in counts.items())


def render_prompt_versions_tab(df, stage):
    st.subheader("Prompt 版本")

    st.markdown("#### 版本登記（設計用途）")
    st.caption(
        "experiments/prompt_versions.json 記錄每個版本的用途、適用方（買方／賣方）與狀態。"
        "登記不代表這個版本有進入正式實驗；實際用了哪個版本，請看下一張表。"
    )
    versions = load_prompt_versions()
    if versions:
        st.dataframe(pd.DataFrame(versions), width="stretch", hide_index=True)
    else:
        st.info("experiments/prompt_versions.json 還沒有任何版本紀錄。")

    st.markdown(f"#### 這個資料集實際使用的版本 — {dataset_label(stage)}")
    st.caption(
        "依每局 game_state.json 裡實際建構的目標句類別判定（summarize.py），"
        "不看執行時自報的標籤；買方、賣方分開計數。"
    )
    if df.empty:
        st.info("這個資料集沒有任何局。")
        return
    st.table(
        pd.DataFrame(
            [
                {
                    "局數": len(df),
                    "賣方版本": version_counts(df["seller_prompt_version"]),
                    "買方版本": version_counts(df["buyer_prompt_version"]),
                }
            ]
        )
    )

    st.markdown("#### 版本效果比較表")
    st.caption(
        "同一語言、同一價格結構下，各版本組合的表現（prompt_version：雙方相同時寫一個版本，"
        "不同時寫「賣方/買方」，例如 v1/v3）。樣本數小時只供參考。"
    )
    keys = ["language_label", "structure_label", "prompt_version"]
    comparable = df.dropna(subset=["prompt_version"])
    rows = [
        {
            "語言": lang,
            "價格結構": structure if pd.notna(structure) else "—",
            "版本": pv,
            "局數": len(sub),
            "失守 A 比例": series_mean(sub["breach_A"]),
            "成交且未還價比例": series_mean(sub["buyer_no_counter"]),
            "買方剩餘份額平均": series_mean(sub["buyer_surplus_share"]),
            "平均發言次數": series_mean(sub["rounds"]),
        }
        for (lang, structure, pv), sub in comparable.groupby(keys, dropna=False)
    ]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    st.markdown("---")
    st.markdown("#### 單局完整 Prompt 檢視")
    game_id = select_game(df, key="prompt_game")
    sel_role = st.radio(
        "查看哪一方的 system prompt",
        ["Player RED（賣方）", "Player BLUE（買方）"],
        horizontal=True,
        key="pv_tab_role",
    )
    if game_id:
        game = load_game_state(game_id)
        idx = 0 if "RED" in sel_role else 1
        system_prompt = game["players"][idx]["conversation"][0]["content"]
        st.text_area(f"{sel_role} — system prompt 原文", system_prompt, height=400)


def append_worklog_note(note_text):
    today_header = f"## {datetime.now().strftime('%Y-%m-%d')}"
    content = WORKLOG_PATH.read_text(encoding="utf-8") if WORKLOG_PATH.exists() else ""
    lines = content.splitlines()
    bullet = f"- {note_text.strip()}"

    if today_header in lines:
        idx = lines.index(today_header)
        insert_at = idx + 1
        while insert_at < len(lines) and not lines[insert_at].startswith("## "):
            insert_at += 1
        lines.insert(insert_at, bullet)
    else:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(today_header)
        lines.append("")
        lines.append(bullet)

    WORKLOG_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def render_worklog_tab():
    st.subheader("工作日誌")

    runs_df = load_runs_df()

    if not runs_df.empty:
        total_tokens = pd.to_numeric(runs_df.get("total_tokens"), errors="coerce").fillna(0).sum()
        cost_col = pd.to_numeric(runs_df.get("est_cost_usd"), errors="coerce")
        cost_known = cost_col.notna().any()

        cols = st.columns(2) if cost_known else st.columns(1)
        cols[0].metric("累計 tokens", f"{total_tokens:,.0f}")
        if cost_known:
            cols[1].metric("累計花費 (USD)", f"${cost_col.fillna(0).sum():,.4f}")

        st.markdown("#### 執行紀錄 (runs.jsonl，新到舊)")
        st.dataframe(runs_df, width="stretch")
    else:
        st.info("experiments/runs.jsonl 還沒有任何紀錄。")

    st.markdown("---")
    st.markdown("#### worklog.md")
    if WORKLOG_PATH.exists():
        st.markdown(WORKLOG_PATH.read_text(encoding="utf-8"))
    else:
        st.info("experiments/worklog.md 還不存在。")

    with st.form("worklog_note_form", clear_on_submit=True):
        note = st.text_area("新增筆記（會自動加上今天的日期）")
        submitted = st.form_submit_button("加入 worklog")
        if submitted and note.strip():
            append_worklog_note(note)
            st.success("已加入 worklog.md")
            st.rerun()


def main():
    st.set_page_config(page_title="NegotiationArena Viewer", layout="wide")
    st.title("NegotiationArena Viewer")

    if "results_regenerated" not in st.session_state:
        with st.spinner("重新產生 experiments/results.csv..."):
            result = regenerate_results()
        if result.returncode != 0:
            st.error("重新產生 results.csv 失敗，下面是目前檔案裡的資料。")
            st.code(result.stderr[-2000:])
        st.session_state["results_regenerated"] = True

    df, missing = load_results_df(RESULTS_CSV.stat().st_mtime if RESULTS_CSV.exists() else 0)
    if missing:
        st.warning(
            f"results.csv 缺少欄位 {missing}，可能是舊版程式產生的。"
            "請關掉 Viewer 再重新開啟（run_viewer.bat）。"
        )
    dataset, stage = select_dataset(df)

    tab1, tab2, tab3, tab4 = st.tabs(
        ["交易表格", "議價過程", "工作日誌", "Prompt 版本"]
    )
    with tab1:
        render_results_table_tab(dataset, stage)
    with tab2:
        render_negotiation_tab(dataset)
    with tab3:
        render_worklog_tab()
    with tab4:
        render_prompt_versions_tab(dataset, stage)


if __name__ == "__main__":
    main()
