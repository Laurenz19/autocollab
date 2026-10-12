"""What one AI call costs, and how many credits that makes.

Credits follow the real price of each model, so every model stays profitable, including ones added
later: a new model only needs a line in PRICES. The margin is in the price of a credit (set by the
plans), not here.

Prices are in US dollars per million tokens, as the providers publish them. "checked" says where a
price comes from: the provider's own rate card, or a third-party aggregator to confirm before the
plans' prices are set on it.
"""

import math

# 1 credit = this much AI cost at the provider's price.
CREDIT_VALUE_USD = 0.001
# Every agent step costs at least this, whatever the model: it also pays for the server and the browser.
MIN_CREDITS_PER_STEP = 1.0

# input / output / cache_read / cache_write, in $ per 1M tokens. cache_write = None: same as input.
PRICES: dict[str, dict[str, dict]] = {
    "anthropic": {
        "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "cache_read": 0.01, "cache_write": 0.125, "checked": "Anthropic, 2026-10"},
        "claude-sonnet-5-5": {"input": 2.00, "output": 10.00, "cache_read": 0.20, "cache_write": 2.50, "checked": "Anthropic, 2026-10"},
        "claude-opus-5-5": {"input": 4.00, "output": 20.00, "cache_read": 0.20, "cache_write": 5.00, "checked": "Anthropic, 2026-10"},
    },
    "openai": {
        "gpt-4o": {"input": 2.50, "output": 10.00, "cache_read": 1.25, "cache_write": None, "checked": "à vérifier (agrégateurs, 2026-10)"},
        "gpt-4.1": {"input": 2.00, "output": 8.00, "cache_read": 0.50, "cache_write": None, "checked": "à vérifier (agrégateurs, 2026-10)"},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60, "cache_read": 0.075, "cache_write": None, "checked": "à vérifier (agrégateurs, 2026-10)"},
    },
    "mistral": {
        "mistral-large-latest": {"input": 0.50, "output": 1.50, "cache_read": 0.50, "cache_write": None, "checked": "à vérifier (agrégateurs, 2026-10)"},
        "mistral-medium-latest": {"input": 0.40, "output": 2.00, "cache_read": 0.40, "cache_write": None, "checked": "à vérifier (agrégateurs, 2026-10)"},
        "pixtral-large-latest": {"input": 2.00, "output": 6.00, "cache_read": 2.00, "cache_write": None, "checked": "à vérifier (ancien tarif)"},
    },
    "deepseek": {
        "deepseek-chat": {"input": 0.14, "output": 0.28, "cache_read": 0.0028, "cache_write": None, "checked": "DeepSeek, 2026-10 (alias de deepseek-v4-flash)"},
        "deepseek-reasoner": {"input": 0.14, "output": 0.28, "cache_read": 0.0028, "cache_write": None, "checked": "DeepSeek, 2026-10 (alias de deepseek-v4-flash)"},
    },
}

TOKEN_FIELDS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")


def price_of(provider: str | None, model: str | None) -> dict | None:
    return PRICES.get(provider or "", {}).get(model or "")


def cost_usd(provider: str | None, model: str | None, usage: dict) -> float | None:
    """What these tokens cost at the provider's price; None for a model missing from PRICES.

    input_tokens are the tokens billed at the full input price (cache reads and writes excluded).
    """
    price = price_of(provider, model)
    if not price:
        return None
    write = price["cache_write"] if price["cache_write"] is not None else price["input"]
    return (usage.get("input_tokens", 0) * price["input"] + usage.get("output_tokens", 0) * price["output"]
            + usage.get("cache_read_tokens", 0) * price["cache_read"] + usage.get("cache_write_tokens", 0) * write) / 1_000_000


def step_credits(cost: float | None) -> float:
    """Credits for one agent step: its AI cost converted, never under the minimum, rounded up to 0.1."""
    if cost is None:
        return MIN_CREDITS_PER_STEP
    return max(MIN_CREDITS_PER_STEP, math.ceil(cost / CREDIT_VALUE_USD * 10) / 10)


def estimate_per_step(provider: str, model: str, input_tokens: int = 10_000, output_tokens: int = 400) -> float:
    """Typical credits per step for a model, for the model picker (an agent step reads ~10k tokens)."""
    return step_credits(cost_usd(provider, model, {"input_tokens": input_tokens, "output_tokens": output_tokens}))
