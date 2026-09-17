import os
from anthropic import Anthropic
from negotiationarena.agents.agents import Agent
import time
from copy import deepcopy
from negotiationarena.constants import AGENT_TWO, AGENT_ONE


class ClaudeAgent(Agent):
    def __init__(
        self,
        agent_name: str,
        model: str = "claude-sonnet-5",
        temperature: float = 0.7,
        max_tokens: int = 400,
    ):
        super().__init__(agent_name)
        self.run_epoch_time_ms = str(round(time.time() * 1000))

        self.conversation = []
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.prompt_entity_initializer = "system"
        self.client = Anthropic(
            # defaults to os.environ.get("ANTHROPIC_API_KEY")
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
        )

    def init_agent(self, system_prompt, role):
        if AGENT_ONE in self.agent_name:
            # we use the user role to tell the assistant that it has to start.
            self.update_conversation_tracking(
                self.prompt_entity_initializer, system_prompt
            )
            self.update_conversation_tracking("user", role)

        elif AGENT_TWO in self.agent_name:
            system_prompt = system_prompt + role
            self.update_conversation_tracking(
                self.prompt_entity_initializer, system_prompt
            )
        else:
            raise "No Player 1 or Player 2 in role"

    def __deepcopy__(self, memo):
        """
        Deepcopy is needed because we cannot pickle the anthropic object.
        :param memo:
        :return:
        """
        cls = self.__class__
        result = cls.__new__(cls)
        memo[id(self)] = result
        for k, v in self.__dict__.items():
            if isinstance(v, Anthropic):
                v = "AnthropicObject"
            setattr(result, k, deepcopy(v, memo))
        return result

    def chat(self):
        """
        conversation[0] is always the "system" entry (set by init_agent /
        prompt_entity_initializer); the Messages API takes that separately
        via `system=` and only accepts user/assistant roles in `messages=`.
        """
        system_prompt = self.conversation[0]["content"]
        messages = self.conversation[1:]

        completion = self.client.messages.create(
            model=self.model,
            system=system_prompt,
            messages=messages,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
        time.sleep(0.2)
        return completion.content[0].text

    def update_conversation_tracking(self, role, message):
        self.conversation.append({"role": role, "content": message})
