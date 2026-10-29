from negotiationarena.constants import *


def buy_sell_prompt(
    resources_available_in_game,
    starting_initial_resources,
    player_goal,
    maximum_number_of_proposals,
    player_social_behaviour,
):
    # Prompt version v1.1 (h1_decision_record.md A8, A13, A16) has its own
    # template below; v1 keeps the original text, slips included, so
    # earlier games stay reproducible. The version travels with the goal:
    # the v1.1 goal classes carry prompt_template = "v1.1".
    if getattr(player_goal, "prompt_template", "v1") == "v1.1":
        return _buy_sell_prompt_v11(
            resources_available_in_game,
            starting_initial_resources,
            player_goal,
            maximum_number_of_proposals,
            player_social_behaviour,
        )
    prompt = f"""You are playing game where you are buying or selling an object. There is only one object for sale/purcahse.

{AGENT_ONE} is going to sell one object. {AGENT_TWO} gives {MONEY_TOKEN} to buy resources.

RULES:

```
1. You must always respond with:

    A) Propose a trade with (you can only trade in integer amounts, not decimals):
    <{PLAYER_ANSWER_TAG}> PROPOSAL </{PLAYER_ANSWER_TAG}>
    <{PROPOSED_TRADE_TAG}> {AGENT_ONE} Gives {resources_available_in_game}: amount, ...| {AGENT_TWO} Gives {MONEY_TOKEN}: amount </{PROPOSED_TRADE_TAG}>

    B) Accept the trade by saying:
    <{PLAYER_ANSWER_TAG}> {ACCEPTING_TAG} </{PLAYER_ANSWER_TAG}>
    <{PROPOSED_TRADE_TAG}> NONE </{PROPOSED_TRADE_TAG}>

    C) Reject and end the game:
    <{PLAYER_ANSWER_TAG}> {REJECTION_TAG} </{PLAYER_ANSWER_TAG}>
    <{PROPOSED_TRADE_TAG}> NONE </{PROPOSED_TRADE_TAG}>

    Note: The game will end if one of the players {ACCEPTING_TAG} OR {REJECTION_TAG}. This means that you have to be careful about both accepting, rejecting and proposing a trade.

2. You are allowed at most {maximum_number_of_proposals} proposals of your own to complete the game, after which you can only reply with {ACCEPTING_TAG} or {REJECTION_TAG}.
DO NOT propose a new trade after {maximum_number_of_proposals} proposals. Your limit for proposals is {maximum_number_of_proposals}.

3. You can reason step by step on why you are A) proposing, B) rejecting and C) accepting a trade with:

<{REASONING_TAG}> [add reasoning] </{REASONING_TAG}> add as much text as you want

This information will not be sent to the other player. It is just for you to keep track of your reasoning.

4. At each turn send messages to each other by using the following format:

<{MESSAGE_TAG}>your message here</{MESSAGE_TAG}>

You can decide if you want disclose your resources, goals, cost and willingness to pay in the message.
```

Here is what you have access to:
```
Object that is being bought/sold: {resources_available_in_game}
<{RESOURCES_TAG}> {starting_initial_resources} </{RESOURCES_TAG}>
<{GOALS_TAG}> {player_goal} </{GOALS_TAG}>,
```

All the responses you send should contain the following and in this order:

```
<{PROPOSAL_COUNT_TAG}> [add here (inclusive of current)] </{PROPOSAL_COUNT_TAG}>
<{RESOURCES_TAG}> [add here] </{RESOURCES_TAG}>
<{GOALS_TAG}> [add here] </{GOALS_TAG}>
<{REASONING_TAG}> [add here] </{REASONING_TAG}>
<{PLAYER_ANSWER_TAG}> [add here] </{PLAYER_ANSWER_TAG}>
<{PROPOSED_TRADE_TAG}> [add here] </{PROPOSED_TRADE_TAG}>
<{MESSAGE_TAG}> [add here] </{MESSAGE_TAG}
```

Please be sure to include all.

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
    # v1.1: v1's slips fixed and the wording aligned with the Chinese
    # template (one word for the item, the same strength of "must", rule 3
    # in rule 1's A/B/C order, no comma after </my goals>). The blank line
    # at the end separates the second player's role sentence, which
    # chatgpt.py appends to this prompt.
    return f"""You are playing a game in which you buy or sell an object. There is only one object for sale or purchase.

{AGENT_ONE} sells the object. {AGENT_TWO} pays {MONEY_TOKEN} to buy the object.

RULES:

```
1. Your reply must use exactly one of the following three actions:

    A) Propose a trade (use integer amounts only; do not use decimals):
    <{PLAYER_ANSWER_TAG}> PROPOSAL </{PLAYER_ANSWER_TAG}>
    <{PROPOSED_TRADE_TAG}> {AGENT_ONE} Gives {resources_available_in_game}: amount, ...| {AGENT_TWO} Gives {MONEY_TOKEN}: amount </{PROPOSED_TRADE_TAG}>

    B) Accept the trade:
    <{PLAYER_ANSWER_TAG}> {ACCEPTING_TAG} </{PLAYER_ANSWER_TAG}>
    <{PROPOSED_TRADE_TAG}> NONE </{PROPOSED_TRADE_TAG}>

    C) Reject the trade and end the game:
    <{PLAYER_ANSWER_TAG}> {REJECTION_TAG} </{PLAYER_ANSWER_TAG}>
    <{PROPOSED_TRADE_TAG}> NONE </{PROPOSED_TRADE_TAG}>

    Note: The game ends if either player replies {ACCEPTING_TAG} or {REJECTION_TAG}. Please consider each proposal, acceptance, or rejection carefully.

2. You may make at most {maximum_number_of_proposals} proposals of your own. After that, you may only reply with {ACCEPTING_TAG} or {REJECTION_TAG}.
Do not propose a new trade after you have made {maximum_number_of_proposals} proposals. Your proposal limit is {maximum_number_of_proposals}.

3. You may explain step by step why you are A) proposing, B) accepting, or C) rejecting a trade:

<{REASONING_TAG}> [add reasoning here] </{REASONING_TAG}> You may write as much text as you want.

This information will not be sent to the other player. It is only for keeping track of your own reasoning.

4. At each turn, send a message to the other player using this format:

<{MESSAGE_TAG}>your message here</{MESSAGE_TAG}>

You may decide whether to disclose your resources, goals, cost, and willingness to pay in the message.
```

Here is the information available to you:
```
Object being bought or sold: {resources_available_in_game}
<{RESOURCES_TAG}> {starting_initial_resources} </{RESOURCES_TAG}>
<{GOALS_TAG}> {player_goal} </{GOALS_TAG}>
```

Every reply you send must contain all of the following fields, in this order:

```
<{PROPOSAL_COUNT_TAG}> [add the count here, including the current proposal] </{PROPOSAL_COUNT_TAG}>
<{RESOURCES_TAG}> [add here] </{RESOURCES_TAG}>
<{GOALS_TAG}> [add here] </{GOALS_TAG}>
<{REASONING_TAG}> [add here] </{REASONING_TAG}>
<{PLAYER_ANSWER_TAG}> [add here] </{PLAYER_ANSWER_TAG}>
<{PROPOSED_TRADE_TAG}> [add here] </{PROPOSED_TRADE_TAG}>
<{MESSAGE_TAG}> [add here] </{MESSAGE_TAG}>
```

Please include all seven fields.

{player_social_behaviour}

"""
