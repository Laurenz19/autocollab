"""Measures the tokens the AI provider actually bills, per agent step and per run.

A LangChain callback reads the usage each provider returns with every answer (Anthropic, OpenAI,
Mistral and DeepSeek all report it), so the figures are the provider's, not an estimate. The run
takes what was used since its previous step at each step (see TaskRun._on_step) and adds it up.
"""

from langchain_core.callbacks import AsyncCallbackHandler

from . import pricing
from .db import connect


def _usage_of(message) -> dict | None:
    meta = getattr(message, "usage_metadata", None)
    if not meta:
        return None
    details = meta.get("input_token_details") or {}
    cache_read, cache_write = details.get("cache_read") or 0, details.get("cache_creation") or 0
    # LangChain counts cached tokens inside input_tokens: keep only those billed at the full price.
    return {"input_tokens": max(0, (meta.get("input_tokens") or 0) - cache_read - cache_write),
            "output_tokens": meta.get("output_tokens") or 0,
            "cache_read_tokens": cache_read, "cache_write_tokens": cache_write}


def empty() -> dict:
    return {**{field: 0 for field in pricing.TOKEN_FIELDS}, "calls": 0}


class UsageMeter(AsyncCallbackHandler):
    """Attached to the run's model: counts every call, including page extraction and retries."""

    def __init__(self):
        self.total = empty()
        self._taken = empty()
        # browser-use reports every failed model call as "Error 401: LLM API call failed"; the
        # provider's real message is kept here so the run can show it instead.
        self.last_error: str | None = None

    async def on_llm_error(self, error, **kwargs) -> None:
        self.last_error = str(error)

    async def on_llm_end(self, response, **kwargs) -> None:
        for generations in response.generations:
            for generation in generations:
                usage = _usage_of(getattr(generation, "message", None))
                if usage:
                    for field, value in usage.items():
                        self.total[field] += value
                    self.total["calls"] += 1

    def take(self) -> dict:
        """What was used since the previous take()."""
        delta = {field: self.total[field] - self._taken[field] for field in self.total}
        self._taken = dict(self.total)
        return delta


def monthly_report(month: str) -> dict:
    """Tokens, AI cost and credits of every run started in a month ("2026-10"), by user and by model."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT owner, provider, model, COUNT(*) AS runs, SUM(steps) AS steps,"
            " SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens,"
            " SUM(cache_read_tokens) AS cache_read_tokens, SUM(cache_write_tokens) AS cache_write_tokens,"
            " SUM(cost_usd) AS cost_usd, SUM(credits) AS credits"
            " FROM runs WHERE substr(created_at, 1, 7) = ? AND credits > 0"
            " GROUP BY owner, provider, model ORDER BY credits DESC",
            (month,),
        ).fetchall()
    numbers = ("runs", "steps", *pricing.TOKEN_FIELDS, "cost_usd", "credits")
    lines = [{**dict(row), **{key: row[key] or 0 for key in numbers}} for row in rows]
    total = {key: sum(line[key] for line in lines) for key in numbers}
    return {"month": month, "credit_value_usd": pricing.CREDIT_VALUE_USD, "total": total, "lines": lines}
