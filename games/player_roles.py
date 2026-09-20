"""
Shared "you are Player X" role-declaration sentence -- the other piece of
hardcoded, model-facing text a runner needs besides buy_sell_prompt()
(games/buy_sell_game/prompt.py, games/buy_sell_game_zh/prompt.py). Kept
in one place so a wording change can't be applied to only some of the
runner/experiment scripts that construct a BuySellGame.
"""


def player_role_declaration(agent_name, language):
    if language == "zh":
        return f"你是 {agent_name}。"
    return f"You are {agent_name}."
