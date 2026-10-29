from negotiationarena.constants import *


def buy_sell_prompt(
    resources_available_in_game,
    starting_initial_resources,
    player_goal,
    maximum_number_of_proposals,
    player_social_behaviour,
):
    # Prompt version v1.1 (h1_decision_record.md A8, A13, A16) has its own
    # template below; v1 keeps the original text so earlier games stay
    # reproducible. The version travels with the goal: the v1.1 goal
    # classes carry prompt_template = "v1.1".
    if getattr(player_goal, "prompt_template", "v1") == "v1.1":
        return _buy_sell_prompt_v11(
            resources_available_in_game,
            starting_initial_resources,
            player_goal,
            maximum_number_of_proposals,
            player_social_behaviour,
        )
    prompt = f"""你正在玩一個買賣物品的賽局。市場上只有一件物品可供買賣。

{AGENT_ONE} 將出售一件物品。{AGENT_TWO} 支付 {MONEY_TOKEN} 來購買物品。

規則：

```
1. 你每次回覆都必須是以下三者之一：

    A) 提出交易（只能以整數金額交易，不可使用小數）：
    <{PLAYER_ANSWER_TAG}> PROPOSAL </{PLAYER_ANSWER_TAG}>
    <{PROPOSED_TRADE_TAG}> {AGENT_ONE} Gives {resources_available_in_game}: amount, ...| {AGENT_TWO} Gives {MONEY_TOKEN}: amount </{PROPOSED_TRADE_TAG}>

    B) 接受交易：
    <{PLAYER_ANSWER_TAG}> {ACCEPTING_TAG} </{PLAYER_ANSWER_TAG}>
    <{PROPOSED_TRADE_TAG}> NONE </{PROPOSED_TRADE_TAG}>

    C) 拒絕並結束賽局：
    <{PLAYER_ANSWER_TAG}> {REJECTION_TAG} </{PLAYER_ANSWER_TAG}>
    <{PROPOSED_TRADE_TAG}> NONE </{PROPOSED_TRADE_TAG}>

    注意：只要有一方回覆 {ACCEPTING_TAG} 或 {REJECTION_TAG}，賽局就會結束。因此無論是要接受、拒絕，還是提出交易，都請謹慎考慮。

2. 你最多可以提出 {maximum_number_of_proposals} 次自己的交易提案，超過此次數後就只能回覆 {ACCEPTING_TAG} 或 {REJECTION_TAG}。
超過 {maximum_number_of_proposals} 次提案後請勿再提出新的交易。你的提案次數上限是 {maximum_number_of_proposals} 次。

3. 你可以逐步說明你為什麼要 A) 提出交易、B) 拒絕，或 C) 接受交易：

<{REASONING_TAG}> [在此填寫理由] </{REASONING_TAG}> 可以寫下任意長度的文字

這段資訊不會傳送給對方，僅供你自己記錄推理過程。

4. 每一回合請使用以下格式向對方傳送訊息：

<{MESSAGE_TAG}>你的訊息內容</{MESSAGE_TAG}>

你可以自行決定是否要在訊息中透露你的資源、目標、成本或願付價格。
```

以下是你可以取得的資訊：
```
正在買賣的物品：{resources_available_in_game}
<{RESOURCES_TAG}> {starting_initial_resources} </{RESOURCES_TAG}>
<{GOALS_TAG}> {player_goal} </{GOALS_TAG}>,
```

你傳送的每則回覆都必須依照以下順序包含所有欄位：

```
<{PROPOSAL_COUNT_TAG}> [在此填寫（含本次）] </{PROPOSAL_COUNT_TAG}>
<{RESOURCES_TAG}> [在此填寫] </{RESOURCES_TAG}>
<{GOALS_TAG}> [在此填寫] </{GOALS_TAG}>
<{REASONING_TAG}> [在此填寫] </{REASONING_TAG}>
<{PLAYER_ANSWER_TAG}> [在此填寫] </{PLAYER_ANSWER_TAG}>
<{PROPOSED_TRADE_TAG}> [在此填寫] </{PROPOSED_TRADE_TAG}>
<{MESSAGE_TAG}> [在此填寫] </{MESSAGE_TAG}
```

請務必包含以上所有欄位。

{player_social_behaviour}
"""

    return prompt


def _buy_sell_prompt_v11(
    resources_available_in_game,
    starting_initial_resources,
    player_goal,
    maximum_number_of_proposals,
    player_social_behaviour,
):
    # v1.1: the wording aligned with the English template (see
    # games/buy_sell_game/prompt.py); the blank line at the end separates
    # the second player's role sentence, which chatgpt.py appends.
    return f"""你正在玩一個買賣物品的賽局。只有一件物品可供買賣。

{AGENT_ONE} 出售這件物品。{AGENT_TWO} 支付 {MONEY_TOKEN} 購買這件物品。

規則：

```
1. 你每次回覆都必須採取以下三種動作之一：

    A) 提出交易（只能使用整數金額，不得使用小數）：
    <{PLAYER_ANSWER_TAG}> PROPOSAL </{PLAYER_ANSWER_TAG}>
    <{PROPOSED_TRADE_TAG}> {AGENT_ONE} Gives {resources_available_in_game}: amount, ...| {AGENT_TWO} Gives {MONEY_TOKEN}: amount </{PROPOSED_TRADE_TAG}>

    B) 接受交易：
    <{PLAYER_ANSWER_TAG}> {ACCEPTING_TAG} </{PLAYER_ANSWER_TAG}>
    <{PROPOSED_TRADE_TAG}> NONE </{PROPOSED_TRADE_TAG}>

    C) 拒絕交易並結束賽局：
    <{PLAYER_ANSWER_TAG}> {REJECTION_TAG} </{PLAYER_ANSWER_TAG}>
    <{PROPOSED_TRADE_TAG}> NONE </{PROPOSED_TRADE_TAG}>

    注意：只要有一方回覆 {ACCEPTING_TAG} 或 {REJECTION_TAG}，賽局就會結束。提出、接受或拒絕交易時，請謹慎考慮。

2. 你最多可以提出 {maximum_number_of_proposals} 次自己的交易提案。此後，你只能回覆 {ACCEPTING_TAG} 或 {REJECTION_TAG}。
已提出 {maximum_number_of_proposals} 次提案後，不得再提出新的交易。你的提案次數上限是 {maximum_number_of_proposals} 次。

3. 你可以逐步說明為什麼要 A) 提出、B) 接受，或 C) 拒絕交易：

<{REASONING_TAG}> [在此填寫理由] </{REASONING_TAG}> 可以寫下任意長度的文字。

這段資訊不會傳送給對方，僅供你自己記錄推理過程。

4. 每一回合，使用以下格式向對方傳送訊息：

<{MESSAGE_TAG}>你的訊息內容</{MESSAGE_TAG}>

你可以自行決定是否要在訊息中透露你的資源、目標、成本及願付價格。
```

以下是你可以取得的資訊：
```
正在買賣的物品：{resources_available_in_game}
<{RESOURCES_TAG}> {starting_initial_resources} </{RESOURCES_TAG}>
<{GOALS_TAG}> {player_goal} </{GOALS_TAG}>
```

你傳送的每則回覆都必須依照以下順序包含所有欄位：

```
<{PROPOSAL_COUNT_TAG}> [在此填寫提案次數，含本次提案] </{PROPOSAL_COUNT_TAG}>
<{RESOURCES_TAG}> [在此填寫] </{RESOURCES_TAG}>
<{GOALS_TAG}> [在此填寫] </{GOALS_TAG}>
<{REASONING_TAG}> [在此填寫] </{REASONING_TAG}>
<{PLAYER_ANSWER_TAG}> [在此填寫] </{PLAYER_ANSWER_TAG}>
<{PROPOSED_TRADE_TAG}> [在此填寫] </{PROPOSED_TRADE_TAG}>
<{MESSAGE_TAG}> [在此填寫] </{MESSAGE_TAG}>
```

包含全部七個欄位。

{player_social_behaviour}

"""
