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
