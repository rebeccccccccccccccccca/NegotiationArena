# CLAUDE.md — 論文專案說明

## 專案目的
碩士論文實驗：**跨語言 LLM 買方議價之穩健性（中文 vs 英文）**。
本 repo 為 vinid/NegotiationArena（MIT License）的 fork，只使用 buy-sell 賽局。
方法章需揭露 fork 來源並引用 Bianchi et al. 2024（arXiv 2402.05863）。

## 核心事實（改程式前必讀）
- **受測對象是買方 = `Player BLUE` = `AGENT_TWO`**（後手）。賣方 = `Player RED` = `AGENT_ONE`（先手）。所有「失守率」指標都算在 BLUE 身上。
- **XML tag 名稱一律保持英文，不翻譯**。tag 定義在 `negotiationarena/constants.py`（`player answer`、`newly proposed trade`、`reason`、`message` 等）。`MONEY_TOKEN="ZUP"`、物品 `X`、`Player RED/BLUE` 也不翻。中文條件只翻譯 prompt 的敘述文字。
- 賽局規則、勝負判定在 `games/buy_sell_game/game.py`，**不要改邏輯**；中文版是複製整個資料夾成 `games/buy_sell_game_zh/`，只改 `prompt.py`。
- `negotiationarena/parser.py` 不改。任何 prompt 修改後都要跑一局確認 parser 仍能抓到 `<player answer>` 與 `<newly proposed trade>`。
- 賣方施壓戰術之一是**確定性腳本賣方**（不呼叫 API），實作為 `negotiationarena/agents/scripted_seller.py`，繼承 `Agent`，`step()` 回傳符合 prompt 格式的 XML 字串。

## 目錄結構
```
games/buy_sell_game/        原版英文賽局（不動）
games/buy_sell_game_zh/     中文賽局（複製後只改 prompt.py）
negotiationarena/agents/    chatgpt.py, claude.py（已升級新版 SDK）, scripted_seller.py（自寫）
runner/                     原版單局範例（參考用）
experiments/                自寫：batch_runner.py, metrics.py, lang_check.py
.logs/<condition>/<epoch_ms>/   每局輸出：game_state.json（序列化狀態）、interaction.log（對話）
analysis/                   CSV、統計腳本、圖表
```

## Log 與條件命名
- `.logs/{lang}_{tactic}_{buyer_model}/{epoch_ms}/`
  - lang ∈ {en, zh}
  - tactic ∈ {baseline, scripted}（可選 emotional）
  - buyer_model 用簡短代號（如 haiku45, gpt4omini, opus）
- 每局必須能從 `game_state.json` 還原：Budget（買方 willingness_to_pay）、Cost（賣方 cost_of_production）、成交價、是否 ACCEPT、買方首次出價、回合數。

## 指標定義（metrics.py 必須實作）
- 失守 A：成交價 > Budget（違規成交率）
- 失守 B：CI 場景（Cost > Budget）有成交（CI deal rate）
- 失守 C：MI 場景 normalized profit = (Budget − Deal) / (Budget − Cost)
- FBR = 買方首次出價 / Budget
- 語言遵從：中文條件每回合 `<message>` 內漢字比例 ≥ 0.5 視為遵從

## 技術注意
- `requirements.txt` 的 `anthropic==0.5.0` 已廢棄，使用最新版 SDK；`claude.py` 用 `client.messages.create`。
- temperature 0.7（沿用原論文）；中文條件 `max_tokens` 用 600（英文 400）。
- API key 在 `.env`，不 commit。
- 每個模組完成即 commit；pilot 與正式資料收集前打 git tag（`pilot-v1`、`data-v1`）。

## 與我協作的方式
- 改框架檔案（`game.py`、`parser.py`、`agents.py`）前先說明會動到什麼，並在改完後跑 `runner/buysell_main.py` 一局驗證。
- 中文 prompt 由我人工校對；你可以出翻譯初稿，但不要自行決定用詞。
- 統計模型（mixed-effects 的固定／隨機效應）由我決定，你負責實作。

## Git 規則
- 不可執行 git commit、git push、git rebase、git reset,
  也不可改寫任何歷史。
- 改動完成後只回報:改了哪些檔案、每個檔案改了什麼、
  建議的 commit 訊息。由使用者自己提交。
- git status、git diff、git log 等唯讀指令可以使用。