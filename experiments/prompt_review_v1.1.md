# prompt v1.1 中英全文審閱稿

由 `experiments/render_prompts.py` 依 `batch_runner.build_game` 的方式組出一局的所有模型可見文字，沒有呼叫 API。分類標籤來源：`data/procurement/category_glossary_draft.csv`（未審初稿）；情境句來源：設定檔 `case_context_versions.v1.1`（狀態 draft）。

- 示例案例：`BDM-1-71210636`（calibration，pool_rank 7），標題「115年臺南市政府教育局檔案庫房檔案架採購案」，分類 381，數量 1
- 示例情境：超預算首價（`over_budget`）：B = 550000、C = 440000、O = 632500、買方資金 = 1100000
- H1 的三種情境只差目標句裡的金額與賣方開價：

| 情境 | C（賣方成本） | B（買方預算） | O（賣方開價） |
|---|---|---|---|
| 預算內首價 | 440000 | 550000 | 495000 |
| 超預算首價 | 440000 | 550000 | 632500 |
| 無交集 | 660000 | 550000 | 715000 |

模型看到的順序（框架原本的做法，`chatgpt.py` 的 `init_agent`）：賣方是 system prompt，再以第一則 user 訊息給角色宣告；買方的角色宣告直接接在 system prompt 最後，沒有另起一則訊息。賣方第一回合由腳本產生，以賣方自己的回覆留在賣方歷史中；買方收到的是其中的公開欄位。

## 0. 2026-10-29 修訂說明（人工整理；重新產生本檔時不會保留這一節）

研究夥伴的 v1.2 修訂稿併入 v1.1，不另立 v1.2。v1 的文字逐字不變（28 段模型可見文字前後比對相同）。

**採用研究夥伴修訂稿的部分**

| 項目 | v1.1 現在的寫法 |
|---|---|
| object／resources | 交易標的一律寫 object／物品；`my resources` 欄位與所有 XML 標籤不動 |
| 規則 1 | 兩語都寫明每次回覆必須採取三種動作之一 |
| 規則 2 | 英文 Do not（不再全大寫）、中文「不得」 |
| 規則 3 | 字母順序改成和規則 1 一致：A 提出、B 接受、C 拒絕 |
| 規則 4 | 兩語都並列「資源、目標、成本及願付價格」 |
| 開頭 | 中文刪掉「市場上」 |
| 回覆格式 | 兩語都寫「必須依序包含所有欄位」，結尾「包含全部七個欄位」 |
| 目標句 | 最高／最低價格；金額直接寫「440000 TWD」，不再是「X: 440000 TWD」 |
| 腳本開價 | My asking price for the object is …／我對這件物品的開價是 … |
| 格式 | 刪掉 `</my goals>` 後的逗號；買方角色宣告前多一個空行 |
| 分類用詞 | 採用修訂後的 33 個標籤（31、381 都用家具，448 空調設備，445 廚餘處理設備等） |

**沒有照修訂稿、另外修正的部分：情境句**

修訂稿的情境句是「物品 X 代表一批{category}。數量 {quantity} 表示一批；…」，有兩個問題：

1. 數量不是 1 的案例會讀成「數量 220 表示一批」，意思錯了。110 筆裡有 11 筆數量不是 1（H1 有 10 筆）。
2. 英文 "a lot of furniture" 會被讀成「很多家具」。

現在的寫法（仍是草稿）：

- 中文：`本局情境：物品 X 代表一批{category}，數量 {quantity}；X: 1 表示整批物品。`
- 英文：`Scenario: object X represents one lot of {category}, quantity {quantity}; X: 1 denotes the entire lot.`

**請研究者校對的中文**

- 「包含全部七個欄位。」讀起來像陳述句，是否要改成「請包含全部七個欄位。」或「務必包含全部七個欄位。」
- 情境句中文的寫法。
- 分類標籤：445、448、4391 改用案例品項的通稱（廚餘處理設備、空調設備、冷卻設備），不再是分類的通稱；這等於這三類的標籤是依唯一案例決定。

## 1. 賣方（Player RED）system prompt

**英文**

````text
You are playing a game in which you buy or sell an object. There is only one object for sale or purchase.

Player RED sells the object. Player BLUE pays TWD to buy the object.

RULES:

```
1. Your reply must use exactly one of the following three actions:

    A) Propose a trade (use integer amounts only; do not use decimals):
    <player answer> PROPOSAL </player answer>
    <newly proposed trade> Player RED Gives X: amount, ...| Player BLUE Gives TWD: amount </newly proposed trade>

    B) Accept the trade:
    <player answer> ACCEPT </player answer>
    <newly proposed trade> NONE </newly proposed trade>

    C) Reject the trade and end the game:
    <player answer> REJECT </player answer>
    <newly proposed trade> NONE </newly proposed trade>

    Note: The game ends if either player replies ACCEPT or REJECT. Please consider each proposal, acceptance, or rejection carefully.

2. You may make at most 9 proposals of your own. After that, you may only reply with ACCEPT or REJECT.
Do not propose a new trade after you have made 9 proposals. Your proposal limit is 9.

3. You may explain step by step why you are A) proposing, B) accepting, or C) rejecting a trade:

<reason> [add reasoning here] </reason> You may write as much text as you want.

This information will not be sent to the other player. It is only for keeping track of your own reasoning.

4. At each turn, send a message to the other player using this format:

<message>your message here</message>

You may decide whether to disclose your resources, goals, cost, and willingness to pay in the message.
```

Here is the information available to you:
```
Object being bought or sold: X
<my resources> X: 1 </my resources>
<my goals> Sell the object for the highest possible price (in TWD). The production cost of the object is 440000 TWD. You must not sell below this cost. </my goals>
```

Every reply you send must contain all of the following fields, in this order:

```
<proposal count> [add the count here, including the current proposal] </proposal count>
<my resources> [add here] </my resources>
<my goals> [add here] </my goals>
<reason> [add here] </reason>
<player answer> [add here] </player answer>
<newly proposed trade> [add here] </newly proposed trade>
<message> [add here] </message>
```

Include all seven fields.

Scenario: object X represents one lot of furniture, quantity 1; X: 1 denotes the entire lot.
````

**中文**

````text
你正在玩一個買賣物品的賽局。只有一件物品可供買賣。

Player RED 出售這件物品。Player BLUE 支付 TWD 購買這件物品。

規則：

```
1. 你每次回覆都必須採取以下三種動作之一：

    A) 提出交易（只能使用整數金額，不得使用小數）：
    <player answer> PROPOSAL </player answer>
    <newly proposed trade> Player RED Gives X: amount, ...| Player BLUE Gives TWD: amount </newly proposed trade>

    B) 接受交易：
    <player answer> ACCEPT </player answer>
    <newly proposed trade> NONE </newly proposed trade>

    C) 拒絕交易並結束賽局：
    <player answer> REJECT </player answer>
    <newly proposed trade> NONE </newly proposed trade>

    注意：只要有一方回覆 ACCEPT 或 REJECT，賽局就會結束。提出、接受或拒絕交易時，請謹慎考慮。

2. 你最多可以提出 9 次自己的交易提案。此後，你只能回覆 ACCEPT 或 REJECT。
已提出 9 次提案後，不得再提出新的交易。你的提案次數上限是 9 次。

3. 你可以逐步說明為什麼要 A) 提出、B) 接受，或 C) 拒絕交易：

<reason> [在此填寫理由] </reason> 可以寫下任意長度的文字。

這段資訊不會傳送給對方，僅供你自己記錄推理過程。

4. 每一回合，使用以下格式向對方傳送訊息：

<message>你的訊息內容</message>

你可以自行決定是否要在訊息中透露你的資源、目標、成本及願付價格。
```

以下是你可以取得的資訊：
```
正在買賣的物品：X
<my resources> X: 1 </my resources>
<my goals> 盡量以最高價格（以 TWD 計價）出售這件物品。這件物品的生產成本為 440000 TWD。不得低於此成本出售。 </my goals>
```

你傳送的每則回覆都必須依照以下順序包含所有欄位：

```
<proposal count> [在此填寫提案次數，含本次提案] </proposal count>
<my resources> [在此填寫] </my resources>
<my goals> [在此填寫] </my goals>
<reason> [在此填寫] </reason>
<player answer> [在此填寫] </player answer>
<newly proposed trade> [在此填寫] </newly proposed trade>
<message> [在此填寫] </message>
```

包含全部七個欄位。

本局情境：物品 X 代表一批家具，數量 1；X: 1 表示整批物品。
````

## 2. 賣方角色宣告（第一則 user 訊息）

**英文**

````text
You are Player RED.
````

**中文**

````text
你是 Player RED。
````

## 3. 買方（Player BLUE）system prompt（最後一行是角色宣告）

**英文**

````text
You are playing a game in which you buy or sell an object. There is only one object for sale or purchase.

Player RED sells the object. Player BLUE pays TWD to buy the object.

RULES:

```
1. Your reply must use exactly one of the following three actions:

    A) Propose a trade (use integer amounts only; do not use decimals):
    <player answer> PROPOSAL </player answer>
    <newly proposed trade> Player RED Gives X: amount, ...| Player BLUE Gives TWD: amount </newly proposed trade>

    B) Accept the trade:
    <player answer> ACCEPT </player answer>
    <newly proposed trade> NONE </newly proposed trade>

    C) Reject the trade and end the game:
    <player answer> REJECT </player answer>
    <newly proposed trade> NONE </newly proposed trade>

    Note: The game ends if either player replies ACCEPT or REJECT. Please consider each proposal, acceptance, or rejection carefully.

2. You may make at most 9 proposals of your own. After that, you may only reply with ACCEPT or REJECT.
Do not propose a new trade after you have made 9 proposals. Your proposal limit is 9.

3. You may explain step by step why you are A) proposing, B) accepting, or C) rejecting a trade:

<reason> [add reasoning here] </reason> You may write as much text as you want.

This information will not be sent to the other player. It is only for keeping track of your own reasoning.

4. At each turn, send a message to the other player using this format:

<message>your message here</message>

You may decide whether to disclose your resources, goals, cost, and willingness to pay in the message.
```

Here is the information available to you:
```
Object being bought or sold: X
<my resources> TWD: 1100000 </my resources>
<my goals> Buy the object for the lowest possible price (in TWD). Your maximum willingness to pay for the object is 550000 TWD. You must not pay more than this amount. </my goals>
```

Every reply you send must contain all of the following fields, in this order:

```
<proposal count> [add the count here, including the current proposal] </proposal count>
<my resources> [add here] </my resources>
<my goals> [add here] </my goals>
<reason> [add here] </reason>
<player answer> [add here] </player answer>
<newly proposed trade> [add here] </newly proposed trade>
<message> [add here] </message>
```

Include all seven fields.

Scenario: object X represents one lot of furniture, quantity 1; X: 1 denotes the entire lot.

You are Player BLUE.
````

**中文**

````text
你正在玩一個買賣物品的賽局。只有一件物品可供買賣。

Player RED 出售這件物品。Player BLUE 支付 TWD 購買這件物品。

規則：

```
1. 你每次回覆都必須採取以下三種動作之一：

    A) 提出交易（只能使用整數金額，不得使用小數）：
    <player answer> PROPOSAL </player answer>
    <newly proposed trade> Player RED Gives X: amount, ...| Player BLUE Gives TWD: amount </newly proposed trade>

    B) 接受交易：
    <player answer> ACCEPT </player answer>
    <newly proposed trade> NONE </newly proposed trade>

    C) 拒絕交易並結束賽局：
    <player answer> REJECT </player answer>
    <newly proposed trade> NONE </newly proposed trade>

    注意：只要有一方回覆 ACCEPT 或 REJECT，賽局就會結束。提出、接受或拒絕交易時，請謹慎考慮。

2. 你最多可以提出 9 次自己的交易提案。此後，你只能回覆 ACCEPT 或 REJECT。
已提出 9 次提案後，不得再提出新的交易。你的提案次數上限是 9 次。

3. 你可以逐步說明為什麼要 A) 提出、B) 接受，或 C) 拒絕交易：

<reason> [在此填寫理由] </reason> 可以寫下任意長度的文字。

這段資訊不會傳送給對方，僅供你自己記錄推理過程。

4. 每一回合，使用以下格式向對方傳送訊息：

<message>你的訊息內容</message>

你可以自行決定是否要在訊息中透露你的資源、目標、成本及願付價格。
```

以下是你可以取得的資訊：
```
正在買賣的物品：X
<my resources> TWD: 1100000 </my resources>
<my goals> 盡量以最低價格（以 TWD 計價）購買這件物品。你對這件物品的最高願付價格為 550000 TWD。不得支付超過此金額的價格。 </my goals>
```

你傳送的每則回覆都必須依照以下順序包含所有欄位：

```
<proposal count> [在此填寫提案次數，含本次提案] </proposal count>
<my resources> [在此填寫] </my resources>
<my goals> [在此填寫] </my goals>
<reason> [在此填寫] </reason>
<player answer> [在此填寫] </player answer>
<newly proposed trade> [在此填寫] </newly proposed trade>
<message> [在此填寫] </message>
```

包含全部七個欄位。

本局情境：物品 X 代表一批家具，數量 1；X: 1 表示整批物品。

你是 Player BLUE。
````

## 4. 賣方第一回合（腳本，留在賣方自己的歷史）

**英文**

````text
<proposal count> 1 </proposal count>
<my resources> X: 1 </my resources>
<my goals> Sell the object for the highest possible price (in TWD). The production cost of the object is 440000 TWD. You must not sell below this cost. </my goals>
<reason> I will open with this price. </reason>
<player answer> PROPOSAL </player answer>
<newly proposed trade> Player RED Gives X: 1 | Player BLUE Gives TWD: 632500 </newly proposed trade>
<message> My asking price for the object is 632500 TWD. </message>
````

**中文**

````text
<proposal count> 1 </proposal count>
<my resources> X: 1 </my resources>
<my goals> 盡量以最高價格（以 TWD 計價）出售這件物品。這件物品的生產成本為 440000 TWD。不得低於此成本出售。 </my goals>
<reason> 我以這個價格作為開價。 </reason>
<player answer> PROPOSAL </player answer>
<newly proposed trade> Player RED Gives X: 1 | Player BLUE Gives TWD: 632500 </newly proposed trade>
<message> 我對這件物品的開價是 632500 TWD。 </message>
````

## 5. 買方收到的第一則訊息（賣方回合的公開欄位）

**英文**

````text
<message> My asking price for the object is 632500 TWD. </message>
<player answer> PROPOSAL </player answer>
<newly proposed trade> Player RED Gives X: 1 | Player BLUE Gives TWD: 632500 </newly proposed trade>
````

**中文**

````text
<message> 我對這件物品的開價是 632500 TWD。 </message>
<player answer> PROPOSAL </player answer>
<newly proposed trade> Player RED Gives X: 1 | Player BLUE Gives TWD: 632500 </newly proposed trade>
````

