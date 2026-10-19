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
- 外部審查（看 Viewer 與工作日誌）建議暫緩正式 H1，經核對程式後屬實：
  - Viewer 的「剩餘份額（未成交計 0）」其實只算可成交結構（C<B），無交集局
    整個排除；前導可成交結構的 8 局全部成交，所以兩種平均剛好相等（英 0.739、
    中 0.720）。「超預算成交比例」的分母只有成交局。算法說得通，但標籤沒寫明。
  - 失守 B（成本高於預算卻成交）從未實作。
  - 分價格結構看時中英方向相反（寬鬆：英 0.661／中 0.898；緊縮：英 0.817／中
    0.542；每格 2 局，不能推論），合併平均會掩蓋。
  - 決定暫緩正式 H1，先做純程式的部分；估計對象（買方效果或雙代理總效果）、
    主要結果、材料定稿等仍待決定。
- 純程式修正：
  - `summarize.py` 新增 `breach_B`（C>B 的有效局中是否成交）、
    `buyer_first_response`（買方第一步：還價／以開價提案／高於開價／接受／
    拒絕）、`buyer_first_counter`（首次回應是否低於開價還價，分母為買方有回應
    的有效局，取代清單 3.3 所說的 `buyer_no_counter` 新定義；舊欄位保留並標為
    舊定義）、`fbr`（買方第一口出價 ÷ B）。
  - Viewer 的主要指標改為「價格結構 × 語言」分欄、不合併計算；每格寫成
    「k/n（%）」或「平均（n=…）」，最右欄註明分母；剩餘份額只在可成交結構
    計算，失守 B 只在無交集結構計算，其餘標為「不適用」。版本比較表同樣處理。
  - `plan.py` 改為成對相鄰執行：配對順序隨機，同一對的中英文連著跑、誰先跑
    隨機（H1：120 對全部相鄰，英文先跑 61 對）。這樣若模型在收資料期間更新，
    同一對比較的兩局仍用到同一版本。局編號不變。
  - `chatgpt.py` 的每次呼叫紀錄加入 `requested_at`／`responded_at`（含時區、
    到毫秒），因為 `gpt-6-luna` 沒有帶日期的版本，需要靠時間追溯。依 CLAUDE.md
    跑了一局 `buysell_main` 驗證，該局已移到 `.logs_archive/en_baseline_test/`。
- 研究定位定案：主要宣稱為「整場雙代理互動的語言效果」（買賣雙方同模型、同
  語言；首價固定，之後自由談判），不宣稱差異來自買方自身能力。私有資訊揭露
  （賣方成本、買方預算）視為互動路徑，預先編碼、如實報告，不作控制變數。全
  腳本賣方列為事先規劃的探索性補充實驗 B。分析架構草案：H1 以緊縮結構的語言
  差異為唯一主要比較（雙側），主要結果為剩餘份額（未成交計 0、不截斷，另做
  截斷敏感度分析）；寬鬆結構與語言 × 結構交互作用為次要；無交集結構看安全性
  結果。H3 須同時滿足交互作用方向正確與 H3 資料內 |Gap_v3| < |Gap_v1|，以有
  施壓為主要條件。題目、一句話主軸與前三章定位整理在 Notion 頁面「碩士論文：
  題目與前三章定位（草稿）」：
  https://app.notion.com/p/3fd3003b60d38149b75ef19bd2ab6c88
  待與教授確認後寫成正式的預先分析計畫並 commit。

## 2026-10-19

- 案例池收窄（方向已定，細節未定稿）。決定時只看過金額與分類分布，沒有看任何
  對局結果。
  - 金額：傾向收在 15 萬到 150 萬（中央機關小額採購上限到公告金額，剛好 10
    倍，也是資料最密集的區間）。公告金額自 112-01-01 起為 150 萬，財物查核
    金額 5,000 萬、巨額 1 億；資料中「未達公告金額」級距的預算最高 1,499,537，
    與此相符。上下界寫法與是否含端點待定（含端點時只多 1 筆）。
  - 分類：改為排除制，區間內所有分類都納入；兩語言名稱是否對等改由 glossary
    審核控制。
  - 角色需求：校準 20、H1/H2 40、H3 40、備用 10，共 110 筆；措辭穩健性與
    H1 共用案例。人工判讀後至少要 130 筆，否則以新種子、同樣按月分層擴大抽樣。
  - 以初版關鍵字規則試算（排除標題或品項名稱含「系統」「平台」「建置」「統包」
    「暨」，以及食品類 21–24）：區間內 347 筆，剩 289 筆，容量足夠。但被刪的
    37 筆約三分之一是誤刪（「暨」多出現在活動或計畫名稱，「系統」抓到不斷電
    系統、單台冷凍櫃），也有漏網（工程變更設計、後續擴充、動物用菌苗），傾向
    改用編碼手冊人工判讀，手冊待定。
  - 分層：「2 碼大類 × 金額三分位」太碎（24 個大類中 15 個不到 10 筆），考慮
    改為依大類與金額排序後分區塊隨機分配。
- 數字格式：輸入維持阿拉伯數字、不加千分位、不用萬或 million。parser 以逗號
  切分交易欄，千分位會造成解析失敗。Luna 前導中，模型在 `<message>` 裡會自行
  使用千分位，但交易欄 0 次，也沒有出現萬或 million；揭露編碼要能讀
  `1,380,000` 這種寫法。
- `log(B)` 不放進主要模型，語言 × log(B) 列為探索性分析。
- 與 arXiv 2601.04387（Sinha et al., The Language of Bargaining）比較：該研究
  延伸 NegotiationArena，比較英文與四種印度語言，沒有中文；提示詞維持英文，
  只加一句「只用某語言議價」的 persona（英文組沒有這句）；沒有拆解買賣雙方
  的貢獻、沒有研究揭露機制、沒有安全性指標。
- 實驗 B 升格為事前指定的次要分析：全腳本賣方，只做緊縮結構，用同樣 40 筆
  stage1_2 案例；與 H1 排進同一份隨機計畫同期執行（`gpt-6-luna` 沒有帶日期
  的版本，分開跑會混入時間），H1 等全腳本賣方完成才開始。B 的語言差距解讀為
  「賣方策略固定時的語言差距」；H1 減 B 只做描述性報告，不當作中介效果檢定。
  腳本賣方的規則清單（價格路徑、接受條件、訊息模板等 29 項）待定稿。
- `batch_runner.py`：失敗局改為原位立即重試（重試用盡或碰到花費上限才往下或
  停止），同一對的中英兩局不會因單邊失敗而相隔一整批；正式階段若有分類沒有
  glossary 對照，直接拒絕執行（dry run 仍會印出官方名稱供審核）。以假遊戲離線
  測試通過，沒有呼叫 API。另發現舊的 smoke 計畫檔所用案例已在排除清單中，重跑
  那些計畫會找不到案例而出錯；不影響已收的資料。
- 待決定：價格結構的構念（議價區間寬度，或開價相對預算的位置）、校準判準、
  主要結果是一個還是兩個、是否修正上游英文錯字與版本命名、情境句的數量寫法、
  glossary 欄位名稱、H2 的中性對照臂是否與 H2 同期。
- 決策：所有 API 呼叫一律改用 `gpt-6-luna`，不再使用 gpt-4o-mini。
  - 新增 `experiments/models.py`（`agent_kwargs()`），所有建 agent 的腳本都從
    設定檔取模型參數：`batch_runner.py`、`runner/buysell_main.py`、
    `runner/buysell_zh_main.py`、`pilot_wording.py`、`probe_seller_anchor.py`。
  - 移除設定檔裡的 `gpt4omini` 設定檔；`ChatGPTAgent` 的預設改為 Luna
    （reasoning medium、溫度用 API 預設、上限 8000）；`pricing.json` 改列
    `gpt-6-luna`（費率仍待填，`--budget-usd` 暫時無效）。
  - 依 CLAUDE.md 跑 `runner/buysell_main` 一局驗證（Luna，成交），該局已移到
    `.logs_archive/en_baseline_test/`。
- CLAUDE.md 更新：題目、研究定位（整場互動）、實驗 B、只用 Luna、輸入數字格式、
  目錄與 log 路徑、指標以 `summarize.py` 為準、正式階段的防呆。
- 案例池：
  - 新增 `experiments/procurement/export_coding_sheet.py`，匯出人工判讀表
    `data/procurement/case_coding.csv`（區間內 347 筆，關鍵字只標記不刪，84 筆
    帶建議代碼）；編碼手冊初稿 `data/procurement/coding_manual.md`（納入定義、
    排除代碼 E1–E8、易誤判情況），用詞與規則待定稿。
  - `build_pool.py`：讀取判讀表，include = N 的案例排除（`manual_exclusion`）；
    `require_coding` 為 true 時有未判讀案例就拒絕建構；新增 `assignment:
    blocked`（抽出所需案例後依大類與預算排序、分區塊依角色比例隨機分配）。
  - `pool_rules.json`：預算 150,000–1,500,000（含端點，待確認）、角色改為
    校準 20、stage1_2 40、stage3 40、備用 10（措辭穩健性沿用 stage1_2）、
    分配方式 blocked、指定判讀表。尚未重跑 `build_pool`（等判讀完成）；在暫存
    資料夾試跑：區間內 346 筆可用，四個角色的預算中位數 50–65 萬、大類組成相近。
- 實驗 B 實作（規則仍是草稿 `s2-draft`）：`ScriptedSellerAgent`（不呼叫 API）。
  首口與 H1 腳本開價逐字相同；第 k 次提案依線性路徑從 O 降到 C，捨去到千元
  （不會高於理論路徑）；買方最新有效出價 ≥ 本回合要價即接受；最後一回合出價
  ≥ C 才接受，否則拒絕；不讀買方訊息、不提成本。訊息模板放在設定檔
  `scripted_seller.templates`（中文待審）。`plan.py` 支援 `tactic_structures`
  與 `order_blocks: case`；H1 階段併入 B：40 案例 × 8 局 = 320 局，同一案例的
  局連續執行。`batch_runner` 依 tactic 建賣方並記錄腳本設定；Viewer 把 B 的
  局分成獨立欄位，不和 H1 緊縮混算。新增 `tests/test_scripted_seller.py`
  （13 項，離線）。
- `summarize.py` 新增語言遵從（每方訊息的漢字比例，草案定義）與揭露自動標記
  （精確數字、±5%、關鍵字的首次出現步數），只供人工核對參考。
- 實跑 `smoke_b`（Luna 買方 × 腳本賣方，案例 BDM-1-71174773，已加入排除清單）：
  中文局一路還價，第 13 步以 305000 成交（剩餘份額 0.42）；英文局買方出到自己
  的上限 319935 並說明「這是我的上限」，腳本賣方依規則仍開 329000，買方隨即
  拒絕結束。兩局都能正常解析、記錄。由此發現「四捨五入到千」會讓剛好等於 B 的
  要價被推高到 B 以上，已改為捨去（版本 s1 → s2）；另外規則是否要在買方報出
  上限時更寬鬆（例如接受不低於下一次要價的出價），待研究者決定。
- Viewer 資料集清理：已完成任務的三組測試局移到 `.logs_archive/`（沒有刪除，
  結構照舊）：`smoke`（10/16 批次執行器的 Luna 測試，2 局）、`smoke_seller`
  （10/18 賣方腳本開價改寫的驗證，2 局）、`smoke_v3`（10/18 買方 v3 草稿的技術
  測試，2 局，只確認能解析，不是 H3 資料）。`.logs/` 剩 `pilot_luna10` 與
  `smoke_b`。原本出現的「（Luna 之前的舊資料）」其實是今天 `runner/buysell_main`
  的驗證局：該局移到封存後還沒重產結果表；標籤也改成「（非批次執行的單局）」。
  `summarize.py` 改為重產時一併移除已沒有局的 `experiments/results/<stage>.csv`。
- 與外部審查多輪討論 H1 開跑條件後，新增一頁版本化決策紀錄
  `experiments/h1_decision_record.md`（v0.1，草稿）：已決定事項、待確認的
  建議、待校準的數值與選擇規則、數值門檻、樣本數決定規則，並記下每項決定時
  已看過哪批資料（D0 gpt-4o-mini 88 局、D1 `pilot_luna10` 10 局、D2 Luna 測試
  9 局；尚無校準與 H1 資料，已對局的案例都在排除清單）。
  - 價格設計改為「預算內首價」（C < O低 < B）對「超預算首價」（B < O高）：
    同一案例共用 C/B、只改首價；無交集是獨立的安全性情境。H1 唯一主要結果
    是超預算首價情境的剩餘份額（未成交計 0、不截斷），首次還價為次要結果。
    該主要結果草擬時（10-18）已看過 D1 依結構分開的數字，紀錄中已揭露。
  - 數值門檻：整數化後逐案例檢查 C < O低 < B < O高 ≤ 1.9B；實驗 B 的捨去
    步距相對於 B − C 的上限待定。模型自行湊整屬於可能受語言影響的行為，
    不設門檻、只做描述。
  - 版本識別：每局存雙方實際 system prompt 全文與雜湊、宣稱的模板版本；
    稽核時用凍結模板加該局設定重新渲染並比對，目標句類別檢查另為獨立核對。
  - 程式與設定檔尚未依此修改（設定檔仍是 `wide`／`narrow` 與前導比例）。
- 案例判讀第一輪完成（`case_coding.csv`）：347 筆都填了 Y／N，N 都有排除
  代碼，判讀以外的欄位與匯出時相同，檔案仍是 UTF-8。Y 183 筆（1 筆在排除
  清單，可用 182）、N 164 筆（E8 77、E1 30、E7 25、E4 18、E2 6、E5 4、E3 3、
  E6 1）。
  - E8 在編碼手冊中定義為非一般財物（分類 15、17、18、531、532），77 筆中只有
    3 筆符合；另 74 筆是「分類名稱無法代表品項或標的描述不足，暫用 E8」，手冊
    沒有對應代碼，而且手冊寫「無法判斷時先納入」。需先決定這類案例的處理
    （新增代碼或照手冊先納入），否則排除原因的統計會失真。
  - 標註待第二輪覆核的共 110 筆：暫用 E8 的 74 筆、Y 但有疑義 35 筆、E4
    「單價決標」1 筆。第二輪結果決定可用數，範圍約 147–256 筆；目前角色需求
    110 筆、最低門檻 130 筆。
  - 金額端點只影響 1 筆（at_boundary），已判為 N，是否含端點對案例池沒有
    實際影響。
  - 尚未重建案例池：等第二輪覆核與樣本數決定後再跑 `build_pool`。
