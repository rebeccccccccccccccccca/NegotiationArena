# CLAUDE.md — 論文專案說明

## 專案目的
碩士論文實驗：**大型語言模型採購代理之跨語言穩健性：價格結構、施壓戰術與提示詞介入之研究**（繁體中文 vs 英文）。
本 repo 為 vinid/NegotiationArena（MIT License）的 fork，只使用 buy-sell 賽局。
方法章需揭露 fork 來源並引用 Bianchi et al. 2024（arXiv 2402.05863）。與 Sinha et al. 2026（arXiv 2601.04387）的區隔見 `experiments/worklog.md` 2026-10-19。

## 核心事實（改程式前必讀）
- **研究定位**：主要宣稱為「整場雙代理互動的語言效果」。買賣雙方是同一模型、同一語言，賣方首口開價由腳本固定，之後自由談判。指標都從買方的角度計算，但**不歸因於買方自身能力**，因為賣方的行為也會隨語言改變。
- 買方 = `Player BLUE` = `AGENT_TWO`（後手）；賣方 = `Player RED` = `AGENT_ONE`（先手）。
- **實驗 B**（事前指定的次要分析）：全腳本賣方，只做緊縮結構，用和 H1 相同的案例，並和 H1 排進同一份隨機計畫同期執行；估計「賣方策略固定時的語言差距」。H1 減 B 只做描述性報告，不當作中介效果檢定。
- **XML tag 名稱一律保持英文，不翻譯**。tag 定義在 `negotiationarena/constants.py`（`player answer`、`newly proposed trade`、`reason`、`message` 等）。`MONEY_TOKEN="TWD"`（新臺幣 ISO 代碼，取代原框架虛構的 `ZUP`；兩語言都寫 `TWD`，中文不寫成「新臺幣」或「元」）、物品 `X`、`Player RED/BLUE` 也不翻。中文條件只翻譯 prompt 的敘述文字。
- **研究者寫入的金額**一律用阿拉伯數字，不加千分位，不用「萬」或 million。`parser.py` 以逗號切分 `<newly proposed trade>`，千分位會造成解析失敗。模型自己回話時的數字格式不受控制。
- 賽局規則、勝負判定在 `games/buy_sell_game/game.py`，**不要改邏輯**（已知例外：`negotiationarena/alternating_game.py` 已改成 REJECT 也會結束賽局，2026-10-16）。中文版是 `games/buy_sell_game_zh/`，只改 `prompt.py`。
- `negotiationarena/parser.py` 不改。任何 prompt 修改後都要跑一局確認 parser 仍能抓到 `<player answer>` 與 `<newly proposed trade>`。
- **腳本賣方**在 `negotiationarena/agents/scripted_seller.py`：`FixedFirstOfferSellerAgent` 只固定首口開價，之後由模型談判（H1）；`ScriptedSellerAgent` 全程照規則出價、不呼叫 API（實驗 B），規則參數在 `experiment_config.json` 的 `scripted_seller`。

## 目錄結構
```
games/buy_sell_game/            英文賽局（上游原版）
games/buy_sell_game_zh/         中文賽局（複製後只改 prompt.py）
negotiationarena/agents/        chatgpt.py（預設 gpt-6-luna）, claude.py, scripted_seller.py（自寫）
runner/                         單局範例；buysell_main.py 用於改框架後的一局驗證
experiments/
  experiment_config.json        模型設定檔、價格結構、情境句、腳本賣方、各階段設定
  models.py                     所有腳本取得模型參數的唯一入口
  cases.py, plan.py, batch_runner.py    案例 → 計畫（plans/<stage>.csv）→ 執行
  goal_versions.py, prompt_versions.json   提示詞版本
  summarize.py                  單局指標 → results.csv、results/<stage>.csv
  viewer.py                     Streamlit 檢視器（取代無法載入 buy-sell 的 webapp/）
  procurement/                  政府採購案例的抓取、篩選、角色分配
  worklog.md                    工作日誌
data/procurement/               案例池 candidates.csv、規則 pool_rules.json、MANIFEST.json
.logs/<stage>/<game_label>/<epoch_ms>/   每局輸出：game_state.json、interaction.log
.logs_archive/                  封存資料（含 Luna 之前的 gpt-4o-mini 局），不納入分析
```

## Log 與條件命名
- `.logs/<stage>/<game_label>/<epoch_ms>/`，例如 `.logs/h1/h1_001/...`；同一局的重試放在同一個 game_label 底下。
- 每局的設定（案例、價格結構、tactic、B、C、O、買方資金、情境句、模型、提示詞版本、設定檔與計畫的雜湊值）記在 `game_state.json` 的 `experiment`。
- 每局必須能從 `game_state.json` 還原：Budget（買方 willingness_to_pay）、Cost（賣方 cost_of_production）、成交價、是否 ACCEPT、買方首次出價、回合數。

## 指標定義（summarize.py 實作）
- 失守 A（`breach_A`）：成交價 > Budget。
- 失守 B（`breach_B`）：無交集結構（Cost > Budget）中有成交。
- 剩餘份額：(Budget − Deal) / (Budget − Cost)，只在可成交結構計算；主要結果的版本未成交計 0、不截斷。
- FBR = 買方首次出價 / Budget。
- 語言遵從：每回合 `<message>` 的漢字比例 ≥ 0.5 視為中文遵從（分母的定義待定稿）；英文條件出現中文也算不遵從。

## 技術注意
- `requirements.txt` 的 `anthropic==0.5.0` 已廢棄，使用最新版 SDK；`claude.py` 用 `client.messages.create`。
- **所有 API 呼叫只用 `gpt-6-luna`**。模型與生成參數由 `experiments/experiment_config.json` 的模型設定檔決定，預設 `luna_medium`（`reasoning_effort` 為 medium）；腳本一律用 `experiments/models.py` 的 `agent_kwargs()` 建 agent，不寫死模型名稱。Luna 之前的 gpt-4o-mini 設定檔已移除，不再使用。
- 開啟推理時 API 只接受預設溫度 1（不可設 0.7）；輸出上限 `max_completion_tokens` 兩語言都是 8000，含推理 token，超過會直接報錯而不是截斷。
- `gpt-6-luna` 沒有帶日期的版本：每次呼叫記錄 `requested_at`／`responded_at` 和回傳的模型名稱；要互相比較的局必須同期執行。
- 正式階段（設定檔 `formal: true`）在有未提交的修改、或有分類缺 glossary 對照時拒絕執行；失敗局會原位立即重試。
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
