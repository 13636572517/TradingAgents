# Heavy dependencies (langchain, tool files) are imported lazily so that
# build_instrument_context and get_language_instruction can be loaded and
# unit-tested without requiring the full langchain stack to be installed.


def __getattr__(name):
    """Module-level lazy attribute lookup for re-exported tool names."""
    _tool_map = {
        "get_stock_data": (
            "tradingagents.agents.utils.core_stock_tools", "get_stock_data"
        ),
        "get_indicators": (
            "tradingagents.agents.utils.technical_indicators_tools", "get_indicators"
        ),
        "get_fundamentals": (
            "tradingagents.agents.utils.fundamental_data_tools", "get_fundamentals"
        ),
        "get_balance_sheet": (
            "tradingagents.agents.utils.fundamental_data_tools", "get_balance_sheet"
        ),
        "get_cashflow": (
            "tradingagents.agents.utils.fundamental_data_tools", "get_cashflow"
        ),
        "get_income_statement": (
            "tradingagents.agents.utils.fundamental_data_tools", "get_income_statement"
        ),
        "get_news": (
            "tradingagents.agents.utils.news_data_tools", "get_news"
        ),
        "get_insider_transactions": (
            "tradingagents.agents.utils.news_data_tools", "get_insider_transactions"
        ),
        "get_global_news": (
            "tradingagents.agents.utils.news_data_tools", "get_global_news"
        ),
    }
    if name in _tool_map:
        import importlib
        module_path, attr = _tool_map[name]
        mod = importlib.import_module(module_path)
        return getattr(mod, attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def get_language_instruction() -> str:
    """Return a prompt instruction for the configured output language.

    Returns empty string when English (default), so no extra tokens are used.
    Applied to every agent whose output reaches the saved report —
    analysts, researchers, debaters, research manager, trader, and
    portfolio manager — so a non-English run produces a fully localized
    report rather than a mix of languages.
    """
    from tradingagents.dataflows.config import get_config
    lang = get_config().get("output_language", "English")
    if lang.strip().lower() == "english":
        return ""
    return f" Write your entire response in {lang}."


def build_instrument_context(ticker: str, asset_type: str = "stock") -> str:
    """Describe the exact instrument so agents preserve exchange-qualified tickers."""
    from tradingagents.dataflows.akshare_data import detect_cn_market

    if asset_type == "crypto":
        return (
            f"The asset to analyze is `{ticker}`. "
            "Use this exact ticker in every tool call, report, and recommendation, "
            "preserving any exchange suffix (e.g. `.TO`, `.L`, `.HK`, `.T`, `-USD`). "
            "Treat it as a crypto asset rather than a company, and do not assume company fundamentals are available."
        )

    market = detect_cn_market(ticker)

    if market == "a_share":
        market_hint = (
            " This is a Chinese A-share stock listed on the Shanghai (suffix .SS) or "
            "Shenzhen (suffix .SZ) Stock Exchange. "
            "Key market rules: T+1 settlement (shares bought today cannot be sold until the next trading day); "
            "daily price limit of ±10% (±5% for ST-prefixed stocks); "
            "currency is CNY (Chinese Yuan). "
            "Financial statements are reported in CNY. "
            "Use AkShare or yfinance data tools with the full ticker including exchange suffix."
        )
    elif market == "hk":
        market_hint = (
            " This is a Hong Kong-listed stock on the Hong Kong Stock Exchange (HKEX). "
            "Key market rules: T+2 settlement; no daily price limit; "
            "currency is HKD (Hong Kong Dollar). "
            "Financial statements may be reported in HKD or USD. "
            "Southbound flow (南向资金) from mainland investors is an important demand signal. "
            "Use yfinance data tools with the full ticker including the .HK suffix."
        )
    else:
        market_hint = ""

    return (
        f"The instrument to analyze is `{ticker}`. "
        "Use this exact ticker in every tool call, report, and recommendation, "
        "preserving any exchange suffix (e.g. `.TO`, `.L`, `.HK`, `.T`, `.SS`, `.SZ`, `-USD`)."
        + market_hint
    )


def create_msg_delete():
    def delete_messages(state):
        """Clear messages and add placeholder for Anthropic compatibility"""
        from langchain_core.messages import HumanMessage, RemoveMessage
        messages = state["messages"]

        # Remove all messages
        removal_operations = [RemoveMessage(id=m.id) for m in messages]

        # Add a minimal placeholder message
        placeholder = HumanMessage(content="Continue")

        return {"messages": removal_operations + [placeholder]}

    return delete_messages
