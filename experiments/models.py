"""
The one place API-calling scripts get their model settings from: the
model profiles in experiments/experiment_config.json (by default its
model_profile, gpt-6-luna with reasoning). Every script that builds a
ChatGPTAgent passes agent_kwargs(), so none of them can fall back to an
older model on its own.
"""

from experiments.cases import load_config


def profile_settings(config=None, profile_name=None):
    """(profile name, profile dict); the config's model_profile unless
    another profile is named."""
    config = config or load_config()
    name = profile_name or config["model_profile"]
    return name, config["model_profiles"][name]


def agent_kwargs(language, config=None, profile_name=None):
    """ChatGPTAgent keyword arguments for one language under a profile."""
    _, profile = profile_settings(config, profile_name)
    return dict(
        model=profile["model"],
        temperature=profile["temperature"],
        max_tokens=profile["max_tokens"][language],
        reasoning_effort=profile["reasoning_effort"],
    )
