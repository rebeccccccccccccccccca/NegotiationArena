"""
Streamlit viewer for .logs/ game data. Does NOT import or depend on
Game.from_dict / Agent.from_dict (see experiments/worklog.md 2026-09-17 for
why: the original webapp/ can't load a single BuySellGame log, in ways
unrelated to language or any field added by this project). Every game is
read with a plain json.load() straight off game_state.json, following the
same pattern as webapp/pages/1_user_view.py's (working) chat_message
rendering, just without the broken discovery/deserialization layer in
front of it.

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
import time
from datetime import datetime

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from experiments import summarize
from experiments.summarize import summarize_game, trade_price

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
]

METRIC_LABELS = [
    ("deal", "成交率", "rate"),
    ("breach_A", "breach_A 比例", "rate"),
    ("buyer_no_counter", "buyer_no_counter 比例", "rate"),
    ("buyer_surplus_share", "buyer_surplus_share 平均", "avg"),
    ("buyer_surplus_uncond", "buyer_surplus_uncond 平均", "avg"),
    ("seller_below_cost", "seller_below_cost 比例", "rate"),
    ("_max_rounds", "max_rounds 比例", "rate"),
    ("_failure", "失敗率", "rate"),
]


def derive_grouping(game_id):
    """(output_dir, condition) from a game_id like
    'probe_v2/en_wide/12345' -> ('probe_v2', 'wide'), or
    'baseline_v2/12345' -> ('baseline_v2', 'baseline_v2')."""
    parts = game_id.split("/")
    output_dir = parts[0]
    if len(parts) == 3:
        lang_condition = parts[1]
        if lang_condition.startswith(("en_", "zh_")):
            condition = lang_condition.split("_", 1)[1]
        else:
            condition = lang_condition
    else:
        condition = output_dir
    return output_dir, condition


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


@st.cache_data
def load_results_df(_cache_key):
    df = _read_results_csv()
    df = df.replace("", pd.NA)
    for col in BOOL_COLS:
        if col in df.columns:
            df[col] = df[col].map({"True": True, "False": False}).astype("boolean")
    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    grouping = df["game_id"].map(derive_grouping)
    df["output_dir"] = [g[0] for g in grouping]
    df["condition"] = [g[1] for g in grouping]
    return df


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


def series_mean(series):
    series = series.dropna()
    if series.empty:
        return None
    return float(series.mean())


def render_metric_cards(df):
    for key, label, kind in METRIC_LABELS:
        cols = st.columns(2)
        for col, lang in zip(cols, ("en", "zh")):
            sub = df[df["language"] == lang]
            if key == "_max_rounds":
                value = (sub["status"] == "max_rounds").mean() if len(sub) else None
            elif key == "_failure":
                value = (
                    (~sub["status"].isin(["ok", "max_rounds"])).mean()
                    if len(sub)
                    else None
                )
            else:
                value = series_mean(sub[key]) if key in sub.columns else None

            if value is None:
                display = "—"
            elif kind == "rate":
                display = f"{value:.1%}"
            else:
                display = f"{value:.3f}"
            col.metric(f"{label} ({lang})", display)


def plot_seller_first_offer_dist(df):
    fig, ax = plt.subplots()
    plotted = False
    for lang, color in (("en", "tab:blue"), ("zh", "tab:orange")):
        vals = df[df["language"] == lang]["seller_first_offer"].dropna()
        if not vals.empty:
            plotted = True
            ax.hist(
                vals,
                bins=range(int(vals.min()), int(vals.max()) + 2),
                alpha=0.6,
                label=lang,
                color=color,
            )
    ax.set_xlabel("Seller first offer (ZUP)")
    ax.set_ylabel("Count")
    if plotted:
        ax.legend()
    return fig


def style_results_table(df):
    def style_breach(val):
        return "background-color: #ffb3b3" if val is True else ""

    def style_status(val):
        return "background-color: #fff3b0" if val not in ("ok", "max_rounds") else ""

    styler = df.style
    if "breach_A" in df.columns:
        styler = styler.map(style_breach, subset=["breach_A"])
    if "status" in df.columns:
        styler = styler.map(style_status, subset=["status"])
    return styler


def render_results_table_tab():
    st.subheader("交易表格")

    df = load_results_df(RESULTS_CSV.stat().st_mtime if RESULTS_CSV.exists() else 0)

    st.sidebar.header("交易表格篩選")

    def multiselect(label, col):
        options = sorted(x for x in df[col].dropna().unique())
        default = options
        if col == "data_version" and "post_fix" in options:
            default = ["post_fix"]
        return st.sidebar.multiselect(label, options, default=default)

    lang_sel = multiselect("language", "language")
    cond_sel = multiselect("條件 (condition)", "condition")
    pv_sel = multiselect("prompt_version", "prompt_version")
    status_sel = multiselect("status", "status")
    out_sel = multiselect("output_dir", "output_dir")
    dv_sel = multiselect("data_version", "data_version")

    filtered = df[
        df["language"].isin(lang_sel)
        & df["condition"].isin(cond_sel)
        & df["prompt_version"].isin(pv_sel)
        & df["status"].isin(status_sel)
        & df["output_dir"].isin(out_sel)
        & df["data_version"].isin(dv_sel)
    ]

    st.caption(f"{len(filtered)} / {len(df)} 局符合篩選條件")

    render_metric_cards(filtered)

    st.markdown("#### 賣方第一口價分布")
    st.pyplot(plot_seller_first_offer_dist(filtered))

    st.markdown("#### 局列表")
    st.dataframe(style_results_table(filtered), width="stretch")


def render_negotiation_tab():
    st.subheader("議價過程")

    df = load_results_df(RESULTS_CSV.stat().st_mtime if RESULTS_CSV.exists() else 0)
    game_id = st.selectbox("選擇 game_id", sorted(df["game_id"].tolist()))
    if not game_id:
        return

    path = LOGS_DIR / game_id / "game_state.json"
    row = summarize_game(game_id, path)

    cols = st.columns(4)
    cols[0].metric("語言", row["language"])
    cols[1].metric("狀態 (status)", row["status"])
    cols[2].metric("Cost / WTP", f"{row['cost']} / {row['wtp']}")
    cols[3].metric("成交價", row["final_price"] if row["final_price"] is not None else "—")

    with st.expander("失守判定 / 其他欄位"):
        st.json(
            {
                k: row[k]
                for k in (
                    "model",
                    "model_version",
                    "prompt_version",
                    "data_version",
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

    game = load_game_state(game_id)

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
                st.markdown(f"**{speaker}** · {answer}" + (f" · {price} ZUP" if price is not None else ""))
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
        if row["cost"] is not None:
            ax.axhline(row["cost"], color="green", linestyle="--", label=f"Cost={row['cost']}")
        if row["wtp"] is not None:
            ax.axhline(row["wtp"], color="red", linestyle="--", label=f"WTP={row['wtp']}")
        ax.set_xlabel("Iteration")
        ax.set_ylabel("ZUP")
        ax.legend()
        st.pyplot(fig)


def condition_label(row):
    offer = row["seller_first_offer"]
    offer_str = "free" if pd.isna(offer) else str(int(offer))
    return f"{row['language']} · cost={row['cost']} wtp={row['wtp']} offer={offer_str}"


def render_prompt_versions_tab():
    st.subheader("Prompt 版本")

    versions = load_prompt_versions()
    by_id = {v["version_id"]: v for v in versions}

    st.markdown("#### 目前使用中的版本")
    baseline = by_id.get("v1")
    active = versions[-1] if versions else None

    cols = st.columns(2)
    with cols[0]:
        st.markdown("**Baseline（v1）**")
        if baseline:
            st.caption(f"code_ref: {baseline['code_ref']}")
            st.write(f"**動機**：{baseline['rationale']}")
            st.write(f"**假設**：{baseline['hypothesis']}")
        else:
            st.info("prompt_versions.json 裡沒有 v1 的紀錄。")
    with cols[1]:
        label = active["version_id"] if active else "—"
        st.markdown(f"**目前作用中版本（{label}，prompt_versions.json 最後一筆）**")
        if active:
            st.caption(f"code_ref: {active['code_ref']}")
            st.write(f"**動機**：{active['rationale']}")
            st.write(f"**假設**：{active['hypothesis']}")
        else:
            st.info("experiments/prompt_versions.json 還沒有任何版本紀錄。")

    with st.expander("所有版本紀錄（experiments/prompt_versions.json）"):
        if versions:
            st.dataframe(pd.DataFrame(versions), width="stretch")
        else:
            st.info("還沒有任何版本紀錄。")

    st.markdown("---")
    st.markdown("#### 版本效果比較表")
    st.caption(
        "同條件（語言 × cost/wtp/賣方開價）下，各 prompt_version 的表現，"
        "並附上跟 baseline（v1）的差異。欄位不足以算效應量（例如樣本數太小、"
        "標準差沒存）時只呈現原始差異。"
    )

    df = load_results_df(RESULTS_CSV.stat().st_mtime if RESULTS_CSV.exists() else 0)
    comparable = df.dropna(subset=["language", "cost", "wtp", "prompt_version"])

    if comparable.empty:
        st.info("目前沒有可比較的資料。")
    else:
        comparable = comparable.copy()
        comparable["condition"] = comparable.apply(condition_label, axis=1)

        rows = []
        for (condition, pv), sub in comparable.groupby(["condition", "prompt_version"]):
            rows.append(
                {
                    "condition": condition,
                    "prompt_version": pv,
                    "n": len(sub),
                    "breach_A_rate": series_mean(sub["breach_A"]),
                    "buyer_no_counter_rate": series_mean(sub["buyer_no_counter"]),
                    "buyer_surplus_share_avg": series_mean(sub["buyer_surplus_share"]),
                    "avg_rounds": series_mean(sub["rounds"]),
                }
            )
        comp_df = pd.DataFrame(rows)

        diff_cols = [
            "breach_A_rate",
            "buyer_no_counter_rate",
            "buyer_surplus_share_avg",
            "avg_rounds",
        ]

        # Diff vs baseline (v1) within each condition, via merge rather than
        # groupby().apply() -- pandas 3.x can drop the grouping column when
        # the applied function returns a DataFrame with the same index.
        baseline_df = comp_df[comp_df["prompt_version"] == "v1"][
            ["condition"] + diff_cols
        ].rename(columns={c: f"__baseline_{c}" for c in diff_cols})
        comp_df = comp_df.merge(baseline_df, on="condition", how="left")
        for c in diff_cols:
            comp_df[f"{c}_vs_baseline"] = comp_df[c] - comp_df[f"__baseline_{c}"]
            comp_df = comp_df.drop(columns=[f"__baseline_{c}"])

        st.dataframe(
            comp_df.sort_values(["condition", "prompt_version"]), width="stretch"
        )

    st.markdown("---")
    st.markdown("#### 單局完整 Prompt 檢視")

    pv_options = sorted(df["prompt_version"].dropna().unique())
    if not pv_options:
        st.info("目前沒有任何局有 prompt_version。")
        return

    sel_pv = st.selectbox("prompt_version", pv_options, key="pv_tab_version")
    sub = df[df["prompt_version"] == sel_pv]
    sel_game_id = st.selectbox(
        "選擇局", sorted(sub["game_id"].tolist()), key="pv_tab_game"
    )
    sel_role = st.radio(
        "查看哪一方的 system prompt",
        ["Player RED（賣方）", "Player BLUE（買方）"],
        horizontal=True,
        key="pv_tab_role",
    )

    if sel_game_id:
        game = load_game_state(sel_game_id)
        idx = 0 if "RED" in sel_role else 1
        system_prompt = game["players"][idx]["conversation"][0]["content"]
        st.text_area(
            f"{sel_game_id} — {sel_role} — system prompt 原文",
            system_prompt,
            height=400,
        )


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
            summarize.main()
        st.session_state["results_regenerated"] = True

    tab1, tab2, tab3, tab4 = st.tabs(
        ["交易表格", "議價過程", "工作日誌", "Prompt 版本"]
    )
    with tab1:
        render_results_table_tab()
    with tab2:
        render_negotiation_tab()
    with tab3:
        render_worklog_tab()
    with tab4:
        render_prompt_versions_tab()


if __name__ == "__main__":
    main()
