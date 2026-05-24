from langchain_core.messages import HumanMessage, RemoveMessage

# Import tools from separate utility files
from tradingagents.agents.utils.core_stock_tools import (
    get_stock_data
)
from tradingagents.agents.utils.technical_indicators_tools import (
    get_indicators
)
from tradingagents.agents.utils.fundamental_data_tools import (
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement
)
from tradingagents.agents.utils.news_data_tools import (
    get_news,
    get_insider_transactions,
    get_global_news
)


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


def _lookup_company_name(ticker: str, market: str) -> str:
    """Return the official company name for a ticker, or empty string on failure."""
    try:
        if market in ("a_share", "hk"):
            import baostock as bs
            if market == "a_share":
                suffix = ticker.upper()
                if suffix.endswith(".SS"):
                    bs_code = "sh." + suffix[:-3]
                elif suffix.endswith(".SZ"):
                    bs_code = "sz." + suffix[:-3]
                else:
                    return ""
            else:
                return ""  # BaoStock doesn't cover HK
            lg = bs.login()
            rs = bs.query_stock_basic(code=bs_code)
            name = ""
            while rs.error_code == "0" and rs.next():
                row = rs.get_row_data()
                name = row[1] if len(row) > 1 else ""
            bs.logout()
            return name
    except Exception:
        pass
    return ""


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

    from tradingagents.dataflows.akshare_data import is_etf
    if is_etf(ticker):
        return (
            f"The instrument to analyze is `{ticker}`, which is an **A-share ETF** "
            "(Exchange Traded Fund). "
            "Use this exact ticker in every tool call. "
            "ETFs hold a basket of securities and do NOT have traditional corporate financial statements. "
            "ETF-specific data (price performance, top holdings, NAV history) is available via "
            "the fundamental data tool. Traditional financial statement tools "
            "(balance sheet, income statement, cash flow) are not applicable to ETFs. "
            "CRITICAL: Do not invent or guess the ETF name, index tracked, or holdings — "
            "use only data returned by tool calls. "
            "Do NOT output JSON or tool-call syntax in your report — write plain analysis text only."
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

    no_hallucination = (
        " CRITICAL: You MUST use only data returned by tool calls. "
        "If a tool returns empty data, an error, or 'No data found', you MUST explicitly state "
        "'Data unavailable for this ticker' in your report — do NOT substitute with knowledge "
        "from training data or invent figures. The ticker symbol in your report must match "
        f"exactly: `{ticker}`. Never replace it with a different ticker or security name."
    )

    # Look up the canonical company name so the LLM never guesses
    company_name = _lookup_company_name(ticker, market)
    name_hint = f" The official company name is: {company_name}." if company_name else ""

    return (
        f"The instrument to analyze is `{ticker}`{name_hint} "
        "Use this exact ticker in every tool call, report, and recommendation, "
        "preserving any exchange suffix (e.g. `.TO`, `.L`, `.HK`, `.T`, `.SS`, `.SZ`, `-USD`)."
        + market_hint
        + no_hallucination
    )


def create_msg_delete():
    def delete_messages(state):
        """Clear messages and add placeholder for Anthropic compatibility"""
        messages = state["messages"]

        # Remove all messages
        removal_operations = [RemoveMessage(id=m.id) for m in messages]

        # Add a minimal placeholder message
        placeholder = HumanMessage(content="Continue")

        return {"messages": removal_operations + [placeholder]}

    return delete_messages
