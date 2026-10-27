import json
import logging
from dataclasses import dataclass
from collections import defaultdict
from negotiationarena.game_objects.resource import Resources
from negotiationarena.game_objects.valuation import Valuation
from abc import abstractmethod
from negotiationarena.constants import *


class Goal:
    def __init__(self):
        pass

    @abstractmethod
    def goal_reached(self):
        pass

    @abstractmethod
    def json(self):
        pass


@dataclass
class ResourceGoal(Goal, Resources):
    def goal_reached(self, resources: Resources):
        return all(
            resources.resource_dict.get(k, 0) >= v
            for k, v in self.resource_dict.items()
        )

    def json(self):
        return {"_type": "resource_goal", "_value": self.resource_dict}


class MaximisationGoal(Goal):
    goal = "Acquire as many resources as possible"

    def __init__(self, inital_resources: Resources):
        self.inital_resources = inital_resources

    def __str__(self):
        return self.goal

    def to_prompt(self):
        return self.goal

    def goal_reached(self, final_resources: Resources):
        return final_resources - self.inital_resources

    def json(self):
        return {"_type": "maximisation_goal", "_value": self.inital_resources}


class UltimatumGoal(Goal):
    goal = ""

    def __str__(self):
        return self.goal

    def __repr__(self):
        return self.goal

    def to_prompt(self):
        return self.goal

    def goal_reached(
        self, inital_resource: Resources, final_resources: Resources
    ):
        return final_resources - inital_resource

    def json(self):
        return {"_type": "ultimatum_goal", "_value": self.goal}


class BuyerGoal(Goal):
    def __init__(self, willingness_to_pay: Valuation):
        super().__init__()
        self.willingness_to_pay = willingness_to_pay
        self.goal = f"Buy resources for as few {MONEY_TOKEN} as possible. You are willing to pay at most {willingness_to_pay} for the resources. Never pay more than that."

    def __repr__(self):
        return self.goal

    def get_valuation(self):
        return self.willingness_to_pay

    def __str__(self):
        return self.goal

    def to_prompt(self):
        return self.goal

    def json(self):
        return {
            "_type": "buyer_goal",
            "_value": self.willingness_to_pay.json(),
        }


class SellerGoal(Goal):
    def __init__(self, cost_of_production: Valuation):
        super().__init__()
        self.cost_of_production = cost_of_production
        self.goal = f"Sell resources for as many {MONEY_TOKEN} as possible. It costed {self.cost_of_production} to produce the resources. Never sell below cost."

    def __repr__(self):
        return self.goal

    def get_valuation(self):
        return self.cost_of_production

    def __str__(self):
        return self.goal

    def to_prompt(self):
        return self.goal

    def json(self):
        return {
            "_type": "seller_goal",
            "_value": self.cost_of_production.json(),
        }


class BuyerGoalZH(Goal):
    def __init__(self, willingness_to_pay: Valuation):
        super().__init__()
        self.willingness_to_pay = willingness_to_pay
        self.goal = f"盡量以最少的 {MONEY_TOKEN} 購買物品。你最多願意支付 {willingness_to_pay} 來購買這件物品，絕對不要超過這個金額。"

    def __repr__(self):
        return self.goal

    def get_valuation(self):
        return self.willingness_to_pay

    def __str__(self):
        return self.goal

    def to_prompt(self):
        return self.goal

    def json(self):
        return {
            "_type": "buyer_goal_zh",
            "_value": self.willingness_to_pay.json(),
        }


class SellerGoalZH(Goal):
    def __init__(self, cost_of_production: Valuation):
        super().__init__()
        self.cost_of_production = cost_of_production
        self.goal = f"盡量以最高的 {MONEY_TOKEN} 售出物品。生產這件物品花費了 {self.cost_of_production}，絕對不要低於成本出售。"

    def __repr__(self):
        return self.goal

    def get_valuation(self):
        return self.cost_of_production

    def __str__(self):
        return self.goal

    def to_prompt(self):
        return self.goal

    def json(self):
        return {
            "_type": "seller_goal_zh",
            "_value": self.cost_of_production.json(),
        }


class SellerGoalV2(Goal):
    """Paraphrase of SellerGoal's cost sentence (task04 wording check),
    same meaning, different wording -- kept separate so it doesn't
    overwrite the v1 wording SellerGoal already uses."""

    def __init__(self, cost_of_production: Valuation):
        super().__init__()
        self.cost_of_production = cost_of_production
        self.goal = (
            f"Your goal is to earn as much {MONEY_TOKEN} as possible from this sale. "
            f"Producing the resource cost you {self.cost_of_production}, and you must "
            f"not accept any price below that amount."
        )

    def __repr__(self):
        return self.goal

    def get_valuation(self):
        return self.cost_of_production

    def __str__(self):
        return self.goal

    def to_prompt(self):
        return self.goal

    def json(self):
        return {
            "_type": "seller_goal_v2",
            "_value": self.cost_of_production.json(),
        }


class SellerGoalZHV2(Goal):
    """Paraphrase of SellerGoalZH's cost sentence (task04 wording check),
    same meaning, different wording -- kept separate so it doesn't
    overwrite the v1 wording SellerGoalZH already uses."""

    def __init__(self, cost_of_production: Valuation):
        super().__init__()
        self.cost_of_production = cost_of_production
        self.goal = (
            f"你的目標是從這筆交易中賺到越多 {MONEY_TOKEN} 越好。製造這件物品花了你 "
            f"{self.cost_of_production}，任何低於這個金額的價格都不能接受。"
        )

    def __repr__(self):
        return self.goal

    def get_valuation(self):
        return self.cost_of_production

    def __str__(self):
        return self.goal

    def to_prompt(self):
        return self.goal

    def json(self):
        return {
            "_type": "seller_goal_zh_v2",
            "_value": self.cost_of_production.json(),
        }


class BuyerGoalV3(Goal):
    """H3 intervention (DRAFT wording, pending the researcher's review):
    BuyerGoal's v1 sentence plus a budget restatement, an anti-anchoring
    reminder and a check before accepting. Kept separate so v1 stays
    the baseline the intervention is compared against."""

    def __init__(self, willingness_to_pay: Valuation):
        super().__init__()
        self.willingness_to_pay = willingness_to_pay
        self.goal = (
            f"Buy resources for as few {MONEY_TOKEN} as possible. You are willing to pay "
            f"at most {willingness_to_pay} for the resources. Never pay more than that. "
            f"This maximum is a hard budget limit and cannot be exceeded under any "
            f"circumstances. The seller's asking price says nothing about what the "
            f"resources are worth: base your offers on your own budget and goal, not on "
            f"the seller's numbers. Before you {ACCEPTING_TAG} or propose a trade, check "
            f"that the price is not above your maximum; if it is, do not {ACCEPTING_TAG}."
        )

    def __repr__(self):
        return self.goal

    def get_valuation(self):
        return self.willingness_to_pay

    def __str__(self):
        return self.goal

    def to_prompt(self):
        return self.goal

    def json(self):
        return {
            "_type": "buyer_goal_v3",
            "_value": self.willingness_to_pay.json(),
        }


class BuyerGoalZHV3(Goal):
    """H3 intervention, Chinese (DRAFT translation, pending the
    researcher's review): BuyerGoalZH's v1 sentence plus the same three
    additions as BuyerGoalV3."""

    def __init__(self, willingness_to_pay: Valuation):
        super().__init__()
        self.willingness_to_pay = willingness_to_pay
        self.goal = (
            f"盡量以最少的 {MONEY_TOKEN} 購買物品。你最多願意支付 {willingness_to_pay} "
            f"來購買這件物品，絕對不要超過這個金額。這個上限是不可逾越的預算限制，"
            f"在任何情況下都不能超過。賣方的開價並不代表物品的實際價值：請依你自己的預算"
            f"與目標決定出價，不要以賣方提出的數字為基準。在回覆 {ACCEPTING_TAG} 或提出交易之前，"
            f"先確認價格沒有高於你的上限；如果高於上限，就不要 {ACCEPTING_TAG}。"
        )

    def __repr__(self):
        return self.goal

    def get_valuation(self):
        return self.willingness_to_pay

    def __str__(self):
        return self.goal

    def to_prompt(self):
        return self.goal

    def json(self):
        return {
            "_type": "buyer_goal_zh_v3",
            "_value": self.willingness_to_pay.json(),
        }


# Prompt version v1.1 (h1_decision_record.md A8, A13): v1 with the upstream
# slips fixed. Only the English seller sentence changes ("It costed" ->
# "It cost"); the other three keep the v1 text, and are separate classes so
# that every game records which version it ran (their own _type) and the
# prompt template renders its v1.1 text (prompt_template). The v1 classes
# above stay as they were.


class SellerGoalV11(SellerGoal):
    prompt_template = "v1.1"

    def __init__(self, cost_of_production: Valuation):
        super().__init__(cost_of_production)
        self.goal = f"Sell resources for as many {MONEY_TOKEN} as possible. It cost {self.cost_of_production} to produce the resources. Never sell below cost."

    def json(self):
        return {
            "_type": "seller_goal_v1_1",
            "_value": self.cost_of_production.json(),
        }


class SellerGoalZHV11(SellerGoalZH):
    prompt_template = "v1.1"

    def json(self):
        return {
            "_type": "seller_goal_zh_v1_1",
            "_value": self.cost_of_production.json(),
        }


class BuyerGoalV11(BuyerGoal):
    prompt_template = "v1.1"

    def json(self):
        return {
            "_type": "buyer_goal_v1_1",
            "_value": self.willingness_to_pay.json(),
        }


class BuyerGoalZHV11(BuyerGoalZH):
    prompt_template = "v1.1"

    def json(self):
        return {
            "_type": "buyer_goal_zh_v1_1",
            "_value": self.willingness_to_pay.json(),
        }
