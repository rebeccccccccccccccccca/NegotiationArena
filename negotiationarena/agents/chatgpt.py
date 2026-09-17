import copy
import openai
from openai import OpenAI
import os

import os
import random
from negotiationarena.agents.agents import Agent
import time
from negotiationarena.constants import AGENT_TWO, AGENT_ONE
from negotiationarena.agents.agent_behaviours import SelfCheckingAgent
from copy import deepcopy

# Transient errors worth retrying (rate limits, connection hiccups, 5xx).
# Anything else (bad request, auth, content filter, ...) fails immediately --
# retrying won't fix a malformed request or a bad API key.
RETRYABLE_OPENAI_ERRORS = (
    openai.RateLimitError,
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.InternalServerError,
)
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 1


class ChatGPTAgent(Agent):
    def __init__(
        self,
        agent_name: str,
        model="gpt-4-1106-preview",
        temperature=0.7,
        max_tokens=400,
        seed=None,
    ):
        super().__init__(agent_name)
        self.run_epoch_time_ms = str(round(time.time() * 1000))
        self.model = model
        self.conversation = []
        self.prompt_entity_initializer = "system"
        self.seed = (
            int(self.run_epoch_time_ms) + random.randint(0, 2**16)
            if seed is None
            else seed
        )
        self.client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        self.temperature = temperature
        self.max_tokens = max_tokens

        # Per-call usage, accumulated for cost/token accounting in
        # game_state.json (see AlternatingGame.run()'s run_metadata).
        self.usage_log = []
        self.retry_count = 0

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
        Deepcopy is needed because we cannot pickle the llama object.
        :param memo:
        :return:
        """
        cls = self.__class__
        result = cls.__new__(cls)
        memo[id(self)] = result
        for k, v in self.__dict__.items():
            if k == "client" and not isinstance(v, str):
                v = v.__class__.__name__
            setattr(result, k, deepcopy(v, memo))
        return result

    def chat(self):
        for attempt in range(MAX_RETRIES + 1):
            try:
                chat = self.client.chat.completions.create(
                    model=self.model,
                    messages=self.conversation,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    seed=self.seed,
                )
                break
            except RETRYABLE_OPENAI_ERRORS:
                self.retry_count += 1
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_BACKOFF_SECONDS * (2**attempt))
                    continue
                raise

        self.usage_log.append(
            {
                "served_model": chat.model,
                "prompt_tokens": chat.usage.prompt_tokens,
                "completion_tokens": chat.usage.completion_tokens,
            }
        )

        return chat.choices[0].message.content

    def update_conversation_tracking(self, role, message):
        self.conversation.append({"role": role, "content": message})


class SelfCheckingChatGPTAgent(ChatGPTAgent, SelfCheckingAgent):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
