"""Interchangeable model providers for refactoring trials.

Every provider exposes one method,

    complete(model, system, prompt, max_tokens) -> Completion

so that the trial runner and the cost accounting never depend on a vendor.
Keys are read from files in ~/.config/secrets/ (one KEY=value per line) and
are never printed or logged. Adding a provider means adding one class here and
its prices to pricing.json.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

SECRETS = os.path.expanduser("~/.config/secrets")


@dataclass
class Completion:
    text: str
    input_tokens: int
    cached_tokens: int
    output_tokens: int
    stop: str
    raw_model: str
    extra: dict = field(default_factory=dict)


def read_key(filename: str, var: str) -> str:
    path = os.path.join(SECRETS, filename)
    if not os.path.exists(path):
        raise RuntimeError(f"no key file {path} (expected a line {var}=...)")
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("export "):
                line = line[len("export "):]
            if line.startswith(var + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError(f"{var} not found in {path}")


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, effort: str = "high"):
        import anthropic  # official SDK
        self.client = anthropic.Anthropic(api_key=read_key("anthropic.env", "ANTHROPIC_API_KEY"))
        self.effort = effort

    def complete(self, model: str, system: str, prompt: str, max_tokens: int) -> Completion:
        # Streaming avoids HTTP timeouts on long outputs. No server-side
        # fallback: a refusal must count against the model that refused, or
        # the per-model comparison would be wrong.
        with self.client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system,
            output_config={"effort": self.effort},
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            r = stream.get_final_message()
        text = "".join(b.text for b in r.content if b.type == "text")
        u = r.usage
        return Completion(text, u.input_tokens + (u.cache_creation_input_tokens or 0),
                          u.cache_read_input_tokens or 0, u.output_tokens, r.stop_reason or "", r.model)


class OpenAIProvider:
    name = "openai"

    def __init__(self, effort: str = "high"):
        import openai  # official SDK
        self.client = openai.OpenAI(api_key=read_key("openai.env", "OPENAI_API_KEY"))
        self.effort = effort

    def complete(self, model: str, system: str, prompt: str, max_tokens: int) -> Completion:
        r = self.client.responses.create(
            model=model,
            instructions=system,
            input=prompt,
            max_output_tokens=max_tokens,
            reasoning={"effort": self.effort},
        )
        u = r.usage
        cached = getattr(getattr(u, "input_tokens_details", None), "cached_tokens", 0) or 0
        return Completion(r.output_text or "", u.input_tokens - cached, cached, u.output_tokens,
                          r.status or "", r.model)


PROVIDERS = {"anthropic": AnthropicProvider, "openai": OpenAIProvider}


def make(spec: str, effort: str = "high"):
    """'anthropic/claude-opus-5-5' -> (provider instance, model id)."""
    vendor, model = spec.split("/", 1)
    return PROVIDERS[vendor](effort=effort), model
