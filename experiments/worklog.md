## 2026-09-17

- 找到上游 NegotiationArena 既有的訊息組裝 bug：`negotiationarena/utils.py` 的
  `from_name_and_tag_to_message(name, tag)` 參數語意跟呼叫端
  （`agent_message.py:33`）相反，導致 `AgentMessage.message_to_other_player()`
  組出來的公開資訊是「整段內容包標籤名」而不是「標籤包內容」，下一位玩家
  收到的 user turn 因此結構錯亂。比對 `upstream/main`（`git diff upstream/main --
  negotiationarena/utils.py` 無輸出）確認這是 upstream 自己的 bug（commit
  `c447fafd`，作者 vinid），不是這個 fork 引入的。已在 commit `0d38d09b`
  修正，並加了 `tests/test_message_format.py` 回歸測試。修正前收集的 35 局
  一律標記 `data_version=pre_fix`，分析時不採用；`0d38d09b`（含）之後的局才是
  `post_fix`。
- 決定把賣方第一口價腳本化（`FixedFirstOfferSellerAgent`，只固定第一口，
  第二口起交還模型），理由：基準條件下賣方常常自己開成本價，測不出買方在
  「面對明顯有利/不利開價」時會不會殺價；固定開價才能把「買方怎麼反應」
  和「賣方自己開多少」這兩個變因分開看。
- `summarize.py` 指標調整：`breach_B` 改名 `seller_below_cost`（改成「成交
  價 < cost」，歸為賣方側指標，跟原本「cost > wtp 卻成交」的定義不同了）；
  `breach_C` 改名 `buyer_no_counter`（改成純描述性指標，不算買方失守）；
  買方失守只保留 `breach_A`（成交價 > wtp）；新增 `buyer_surplus_share` 與
  `buyer_surplus_uncond`（後者把沒成交的 `max_rounds` 局計為 0，不排除在
  平均之外）。
- 探針 `no_range` 條件的腳本開價從 50 改成 65：原本 50 同時低於賣方自稱
  成本 60、又高於買方 wtp 40，情境本身就矛盾（賣方被腳本逼著賣低於己方
  成本的價格）；改成 65（高於成本也高於 wtp）之後，情境乾淨很多——這批
  資料裡 `no_range` 兩個語言都是 0/3 成交，沒有出現 `breach_A`/`seller_below_cost`。
- post_fix pilot 結果（`baseline_v2`/`rephrase_check`/`probe_v2`，共 42
  局）：
  - 賣方第一口價分布（`baseline_v2` v1 + `rephrase_check` v2 合計 12 局
    每語言）：英文 12/12 開 40（=成本）；中文 9/12 開 50（明顯加價），
    只有 3/12 開 40。改寫句（v2，語意相同、換句式）沒有改變這個語言差異，
    支持這是模型對中英文語意對等指令的反應差異，不是特定用詞造成的。
  - 買方 `breach_A`（付超過自己上限）42 局裡 0 次。
  - `wide` 條件（開價在買方預算內）兩語言 6/6 完全不還價（`buyer_no_counter`）。
  - `narrow` 條件（開價超出買方 wtp）成交率只有 3/6，其餘耗到 `max_rounds`
    沒談成——證明買方不是完全不會議價，是「開價明顯超預算才會被迫議價」。
- 「買方複製賣方訊息」掃描：限定在 43 局 `post_fix` 資料裡重跑，演算法抓到
  2 組高相似度，人工核對後都是議局結束時雙方各自說的道別語（例如兩邊都說
  「感謝你的參與，但我們無法達成交易。再見！」），不是原本 bug 那種
  「買方講出只有賣方會講的話」的異常模式——原本 bug 的症狀在 post_fix 資料
  裡是 0。
- 評估過原本的 `webapp/`：對 buy-sell game 完全無法載入任何一局（跟語言、
  跟這次加的任何新欄位都無關）。原因有三層：(1) `Game.from_dict()` 靠
  Python `__subclasses__()` 動態找類別，但 `webapp/utils.py` 從沒 import
  過 `BuySellGame`，一開始就找不到類別；(2) 補 import 後，`Agent.from_dict()`
  想用 `ChatGPTAgent(**state_dict)` 整包關鍵字重建 agent，但
  `state_dict` 裡的 `prompt_entity_initializer`（每個 `ChatGPTAgent`
  一直都有的欄位）根本不是建構子參數，直接 `TypeError`；(3) 預設 log
  路徑用 `__file__.split("/")[:-3]` 切字串，在 Windows 上完全失效。三層
  都是既有問題，連最舊、什麼新欄位都沒有的局都讀不出來。因此決定保留
  `webapp/` 原狀不動，另外寫 `experiments/viewer.py`，直接 `json.load`
  讀 `game_state.json`，不經過壞掉的 `Game.from_dict`/`Agent.from_dict`。
- `summarize.py` 語言判斷修正（資料夾名 → 讀 `run_metadata.language`，
  舊局以系統提示詞內容備援）包含於 commit `50d75734`。

## 2026-10-16

- 政府採購案例資料：原規劃的 data.gov.tw 900002／900001 其實是 opendatatw.org
  的鏡像編號，data.gov.tw 原頁已失效，而且招標資料只有 6 個欄位、沒有預算，
  無法用案號串接。改用 g0v 標案 API（資料源自政府電子採購網），單筆決標公告
  就含預算、底價、決標金額、品項與數量。抽樣框架為決標公告日期 2025-10-01
  至 2026-09-30 的 172,290 筆；依月分層、每月 250 筆共 3,000 筆（種子
  20261016），全部取得明細。8 條基本篩選後 586 筆合格。細節、授權與限制見
  `data/procurement/README.md`；原始檔備份為
  `backups/procurement_raw_20261016_1442.zip`，雜湊值記在 `MANIFEST.json`。
- 找到上游引擎的 REJECT 問題：`AlternatingGameEndsOnTag` 只在 ACCEPT 時結束
  （原程式註解寫著 "this is pretty buggy"），但提示詞告訴雙方 ACCEPT 或
  REJECT 都會結束賽局。前導中有 REJECT 的 25 局，全部在 REJECT 之後繼續，雙方
  互道再見直到回合上限；在無交集條件下，等於讓賣方多出好幾回合可以施壓。改成
  REJECT 也會結束，並新增 `status=rejected`（`summarize.py`、`run_logger.py`、
  `viewer.py` 同步，`rejected` 視為正常的未成交）。修正前的證據局保存在
  `.logs_archive/smoke_pre_reject_fix/`。
- 貨幣 `MONEY_TOKEN` 由虛構的 ZUP 改為 TWD（兩語言相同，中文不寫成新臺幣或
  元）；`summarize.py` 新舊紀錄都能解析。
- 建立 H1 實驗工具：`experiment_config.json`、`cases.py`、`plan.py`（條件配置
  器，中英成對、執行順序隨機）、`batch_runner.py`。決策：
  - 回合上限為雙方合計 20 次發言（每方最多提案 9 次）。
  - 案例資訊以情境句附在提示詞最後（目前是草稿，用詞待定）。
  - 買方資金為 2B。2 倍是開價的天花板：之後的施壓腳本，開價不得超過約
    1.8–1.9B，程式會檢查。
  - C、O 比例暫用前導比例（寬鬆 0.667／0.833、緊縮 0.889／1.111、無交集
    1.5／1.625），待與教授確認。
- 預設模型改為 `gpt-6-luna`（`reasoning_effort=medium`），同一把 API 金鑰即可
  使用。實測：開啟推理時只接受預設溫度 1；必須用 `max_completion_tokens`，
  上限不足時會直接報錯而不是截斷；推理強度不支援 max；沒有帶日期的版本快照。
  `chatgpt.py` 加入推理模型支援，設定檔改為模型設定檔（`--profile` 可切換）。
- Luna 探索性前導 `pilot_luna10`（5 案例 × 中英，價格結構輪流分配）：10 局中
  9 局首次回應就還價，出價都有收斂，無交集的 2 局都拒絕，沒有失守；買方剩餘
  份額 0.45–1.00。發現英文賣方常直接說出成本數字、中文賣方很少，可能混入 H1
  的語言差異，處理方式待決定。前導用過的案例列入 `pool_rules.json` 的
  `exclude_case_ids`，不會再被分到任何階段。

## 2026-10-18

- 主實驗模型改為 `gpt-6-luna` 之後，把 Luna 之前的所有 gpt-4o-mini 紀錄
  （共 87 局）從 `.logs/` 移到 `.logs_archive/`（已列入 `.gitignore`），
  沒有刪除，資料夾結構照原樣保留。`.logs/` 只剩 Luna 的局，Viewer 與
  `results.csv` 只讀 `.logs/`，所以封存的局不會再出現。
  - 前導 78 局：`baseline_v2`、`probe_v2`、`rephrase_check`（post_fix 42
    局）、`probe_seller50`、`zh_baseline_test`、`en_baseline_test` 的舊局。
  - 驗證程式用的測試局 9 局：`smoke_pre_reject_fix`、`smoke_zup`、
    `smoke/*_gpt4omini`、`en_baseline_test` 中 2026-10-16 的 3 局。
- 例如寫附錄時要看 gpt-4o-mini 前導，把對應的資料夾從 `.logs_archive/`
  搬回 `.logs/`，再重新產生 `results.csv`
  （`python -m experiments.summarize`）即可。比如前導的 42 局（post_fix）
  是 `baseline_v2`、`probe_v2`、`rephrase_check` 這三個資料夾。
- 另外，`backups/` 裡的 `logs_*.zip` 也都有這些局的完整備份。
- 買賣雙方的提示詞版本分開記錄。新增 `experiments/goal_versions.py`（版本
  對照表加防呆：一局最多只有一方可以偏離 v1，違規組合在產生計畫時就擋下）；
  計畫與批次執行器分別記錄賣方／買方版本。`summarize.py` 改用每局
  `game_state.json` 裡實際的目標句類別判定版本，不再相信執行時自報的標籤；
  封存的 `rephrase_check` 因此正確顯示為賣方 v2、買方 v1（以前只記成 v2）。
  新增 `BuyerGoalV3` 草稿（H3 介入：預算重申、反錨定提醒、成交前驗證；措辭
  待審核）。另一個環境（claude.ai Project）做過同類修改，但沒有進入 repo，
  而且是以舊版檔案為基礎，直接覆蓋會改回 REJECT、TWD、Luna 的修改，所以沒有
  採用，改在 repo 裡重新實作。
- Viewer 重整：先選資料集（H1／前導／測試）再看內容，欄位改為中文；局依
  h1_001、h1_002…編號（案例 → 價格結構 → 語言，中英相鄰），實際執行順序仍
  隨機、另記一欄。`summarize.py` 依階段另存 `experiments/results/<stage>.csv`。
  Viewer 改用獨立程序重新產生 `results.csv`：長駐的 Streamlit 程序會沿用啟動
  時載入的舊版 `summarize`，曾因此寫出缺欄位的結果表而出現 KeyError。
- 全面檢查公平性：H1 的 120 組案例 × 結構，中英文數字 0 差異；執行順序中英
  先後各半（59／120）。發現並修正兩個問題：
  - 腳本賣方的第一口開價，在賣方自己的紀錄裡寫著英文的「scripted opening
    offer, not generated by the model」，會讓賣方知道自己在實驗中，而且只有
    中文局混入英文。改為該局賣方真正的目標句，加上一句中性推理（英文「I will
    open with this price.」、中文「我以這個價格作為開價。」，中文待審核）。
    買方收到的內容不變。
  - 每局只記錄 HEAD commit，不記錄未 commit 的修改。實例：Luna 的 smoke 局記錄
    的是 `d01cf905`，但 Luna 支援到 17:18 才 commit 進 `59581f83`；`smoke_v3`
    用了當時還沒 commit 的 v3。現在正式階段（設定檔 `formal: true`，目前是
    H1）在有未 commit 修改時拒絕執行；其他階段則把未 commit 的檔案清單記進每局
    的 `experiment.uncommitted_changes`。
  - 以 `smoke_seller` 實跑一組中英局驗證，該案例已列入排除清單。
- 尚待決定：賣方揭露成本的處理方式、品項中英對照表、情境句與 v3 的措辭、英文
  提示詞是否修正上游原文的文法錯誤、白名單與金額範圍、C／O 比例、H3 判準。
