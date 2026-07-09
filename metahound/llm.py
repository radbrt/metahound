"""
Pluggable LLM providers for optional discovery features.

The CLI never requires an LLM: providers are constructed only when a source
opts in (llm_discovery: true) and the provider's API key is present in the
environment. Providers expose one method, complete_json, which returns the
model's answer parsed as a JSON object. Everything is plain HTTP through the
existing requests dependency — no vendor SDKs.

Mistral is the first-class provider (small models are sufficient for the
filename-pattern work these features do). Add a provider by subclassing
LLMProvider and registering it in PROVIDERS.
"""
import json
import logging
import os

logger = logging.getLogger(__name__)

DEFAULT_MISTRAL_MODEL = "mistral-small-latest"


class LLMProvider:
    """Interface: complete a prompt, get a JSON object back."""

    name = "base"

    def complete_json(self, system: str, user: str) -> dict:
        raise NotImplementedError


class MistralProvider(LLMProvider):
    name = "mistral"

    def __init__(self, api_key: str, model: str | None = None):
        if not api_key:
            raise ValueError("Mistral provider requires an API key")
        self.api_key = api_key
        self.model = model or DEFAULT_MISTRAL_MODEL

    def complete_json(self, system: str, user: str) -> dict:
        import requests

        response = requests.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.1,
            },
            timeout=30,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return json.loads(content)


PROVIDERS = {
    "mistral": (MistralProvider, "MISTRAL_API_KEY"),
}


def get_provider(model: str | None = None) -> LLMProvider | None:
    """Build the configured provider, or None (with a warning) if unavailable.

    Provider selection: METAHOUND_LLM_PROVIDER env var, default "mistral".
    The provider's API key env var (e.g. MISTRAL_API_KEY) must be set.
    """
    name = os.getenv("METAHOUND_LLM_PROVIDER", "mistral").lower()
    if name not in PROVIDERS:
        logger.warning(
            "Unknown LLM provider %r (available: %s) — LLM discovery disabled",
            name, ", ".join(sorted(PROVIDERS)),
        )
        return None

    cls, key_var = PROVIDERS[name]
    api_key = os.getenv(key_var)
    if not api_key:
        logger.warning(
            "llm_discovery is enabled but %s is not set — LLM discovery disabled", key_var,
        )
        return None
    return cls(api_key=api_key, model=model)
