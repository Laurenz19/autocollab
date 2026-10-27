from langchain_core.language_models.chat_models import BaseChatModel

from . import settings


def create_llm(overrides: dict | None = None) -> BaseChatModel:
    """Build the chat model chosen in Administration › Intelligence artificielle.

    `overrides` lets the settings page test a configuration before saving it.
    """
    current = {**settings.load(), **(overrides or {})}
    provider, model = current["provider"], current["model"]
    keys = {**settings.load()["api_keys"], **(current.get("api_keys") or {})}

    def key(name: str) -> str:
        value = (keys.get(name) or "").strip()
        if not value:
            raise ValueError(f"Aucune clé d'API {settings.PROVIDERS[name]['label']} : un administrateur doit la saisir "
                             "dans Administration › Intelligence artificielle.")
        return value

    if provider == "deepseek":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=model, base_url=current["deepseek_endpoint"], api_key=key("deepseek"), temperature=0.2)
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        class Claude(ChatAnthropic):
            """Recent Claude models (Sonnet 5.5, Opus 5.5, Haiku 5.5) answer 400 to a forced tool choice ("any" or
            one named tool), which LangChain's with_structured_output, used by browser-use for every step, sends.
            "auto" with that single tool bound gets the same tool call."""

            def bind_tools(self, tools, *, tool_choice=None, **kwargs):
                if tool_choice not in (None, "auto", "none") and not (isinstance(tool_choice, dict) and tool_choice.get("type") in ("auto", "none")):
                    tool_choice = "auto"
                return super().bind_tools(tools, tool_choice=tool_choice, **kwargs)

        # Recent Claude models also reject `temperature` with a 400, so it is left out.
        return Claude(model=model, api_key=key("anthropic"))
    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=model, api_key=key("openai"), temperature=0.2)
    if provider == "mistral":
        from langchain_mistralai import ChatMistralAI

        return ChatMistralAI(model=model, api_key=key("mistral"), temperature=0.2)

    if provider == "nvidia":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=model, base_url=settings.NVIDIA_ENDPOINT, api_key=key("nvidia"), temperature=0.2)

    raise ValueError(f"Fournisseur d'IA inconnu : {provider!r}")


def use_vision() -> bool:
    return bool(settings.load()["use_vision"])
