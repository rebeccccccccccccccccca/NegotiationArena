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

import json
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from experiments import summarize
from experiments.summarize import summarize_game, trade_price

LOGS_DIR = Path(".logs")
RESULTS_CSV = Path("experiments") / "results.csv"
RUNS_JSONL = Path("experiments") / "runs.jsonl"
WORKLOG_PATH = Path("experiments") / "worklog.md"

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


@st.cache_data
def load_results_df(_cache_key):
    df = pd.read_csv(RESULTS_CSV, dtype=str, keep_default_na=False)
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

    tab1, tab2, tab3 = st.tabs(["交易表格", "議價過程", "工作日誌"])
    with tab1:
        render_results_table_tab()
    with tab2:
        render_negotiation_tab()
    with tab3:
        render_worklog_tab()


if __name__ == "__main__":
    main()
