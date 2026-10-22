"""Live equity and index quotes. The language model may phrase the result; it does not supply the numbers."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

from ccr_xva.agents.explain import money
from ccr_xva.models.schemas import Citation, NumericClaim

logger = logging.getLogger(__name__)

_RISK = re.compile(r"\b(cva|dva|fva|xva|pfe|epe|exposure|csa|collateral|netting|recovery)\b", re.IGNORECASE)
_MARKET = re.compile(
    r"\b(stock quote|share price|stock price|stock market|ticker|quote for|price of|trading at|"
    r"how(?:'s| is) the market|market today|s&p|s&p 500|dow|nasdaq|vix)\b|\$[A-Za-z]{1,5}\b",
    re.IGNORECASE,
)
_TICKER = re.compile(r"\$([A-Za-z]{1,5})\b|\b([A-Z]{1,5})\b")
_FILLER = re.compile(
    r"\b(how|is|the|market|today|stock|quote|price|of|for|what|share|shares|doing|right|now|please|"
    r"show|me|a|an|current|trading|at|s|p)\b",
    re.IGNORECASE,
)
_STOP = {
    "HOW", "IS", "THE", "MARKET", "TODAY", "STOCK", "QUOTE", "PRICE", "WHAT", "SHARE", "SHARES",
    "FOR", "OF", "A", "AN", "AND", "OR", "IN", "ON", "USD", "PLEASE", "SHOW", "ME", "CURRENT",
    "DOING", "RIGHT", "NOW", "AT", "IT", "TO", "BY", "UP", "DOWN", "VS", "ETF", "INDEX", "INDEXES",
    "INDICES", "OPEN", "CLOSE", "US", "EU", "UK", "USA",
}
_INDEXES = (
    (re.compile(r"s&p|sp500|spx|gspc", re.IGNORECASE), "^GSPC"),
    (re.compile(r"\bdow\b|djia", re.IGNORECASE), "^DJI"),
    (re.compile(r"nasdaq", re.IGNORECASE), "^IXIC"),
    (re.compile(r"\bvix\b", re.IGNORECASE), "^VIX"),
    (re.compile(r"stoxx", re.IGNORECASE), "^STOXX50E"),
    (re.compile(r"\bdax\b", re.IGNORECASE), "^GDAXI"),
    (re.compile(r"\bcac\b", re.IGNORECASE), "^FCHI"),
    (re.compile(r"\bftse\b", re.IGNORECASE), "^FTSE"),
)
_US_INDEXES = ["^GSPC", "^DJI", "^IXIC"]
_EU_INDEXES = ["^STOXX50E", "^GDAXI", "^FCHI", "^FTSE"]
_NAMES = {
    "^GSPC": "S&P",
    "^DJI": "Dow Jones",
    "^IXIC": "Nasdaq Composite",
    "^VIX": "VIX",
    "^STOXX50E": "Euro Stoxx",
    "^GDAXI": "DAX",
    "^FCHI": "CAC",
    "^FTSE": "FTSE",
}
_BROAD = re.compile(r"market today|stock market|how(?:'s| is) the market|\bthe market\b", re.IGNORECASE)
_INDEX_WORD = re.compile(r"\b(index|indexes|indices)\b", re.IGNORECASE)
_US_REGION = re.compile(r"\b(us|u\.s\.|united states|america|american)\b", re.IGNORECASE)
_EU_REGION = re.compile(r"\b(europe|european|eurozone|euro|stoxx|dax|cac|ftse|germany|france|london)\b", re.IGNORECASE)
_HEADERS = {"User-Agent": "CCR-XVA-Monitor"}


def is_market_query(query: str) -> bool:
    if _RISK.search(query):
        return False
    if re.search(r"counterpart", query, re.IGNORECASE) and re.search(r"\b(risk|risky|credit)\b", query, re.IGNORECASE):
        return False
    if _INDEX_WORD.search(query) and (_regions(query) or re.search(r"\bmarket\b", query, re.IGNORECASE)):
        return True
    return bool(_MARKET.search(query) or _explicit_tickers(query))


def market_answer(query: str) -> dict:
    quotes = fetch_quotes(query)
    if not quotes:
        answer = "A live market quote could not be retrieved."
        return {"answer": answer, "claims": [], "citations": [], "calculation_id": None, "chart": None}
    sentences = []
    claims: list[NumericClaim] = []
    citations: list[Citation] = []
    for quote in quotes:
        price_text, price_value = money(quote["price"])
        change_text, change_value = money(quote["change"])
        percent_value = round(float(quote["change_percent"]), 2)
        percent_text = f"{percent_value:.2f}"
        sentence = (
            f"{quote['name']} ({quote['symbol']}) on {quote['exchange']} is {price_text} {quote['currency']}, "
            f"change {change_text} {quote['currency']} ({percent_text} percent), as of {quote['as_of']}."
        )
        source_id = f"yahoo:{quote['symbol']}"
        sentences.append(sentence)
        claims.extend(
            [
                NumericClaim(name=f"{quote['symbol']}_price", value=price_value, unit=quote["currency"], source="retrieval", source_id=source_id),
                NumericClaim(name=f"{quote['symbol']}_change", value=change_value, unit=quote["currency"], source="retrieval", source_id=source_id),
                NumericClaim(name=f"{quote['symbol']}_change_percent", value=percent_value, unit="percent", source="retrieval", source_id=source_id),
            ]
        )
        citations.append(Citation(source="retrieval", source_id=source_id, text=sentence))
    return {
        "answer": " ".join(sentences),
        "claims": claims,
        "citations": citations,
        "calculation_id": None,
        "chart": None,
    }


def fetch_quotes(query: str) -> list[dict]:
    quotes = []
    for symbol in symbols_for(query):
        quote = _chart_quote(symbol)
        if quote is not None:
            quotes.append(quote)
    return quotes


def symbols_for(query: str) -> list[str]:
    named = [symbol for pattern, symbol in _INDEXES if pattern.search(query)]
    regions = _regions(query)
    wants_board = bool(_INDEX_WORD.search(query)) or (bool(regions) and bool(re.search(r"\bmarket\b", query, re.IGNORECASE)))
    if wants_board and not named:
        include_us = "us" in regions or not regions
        include_eu = "eu" in regions or (not regions and bool(_INDEX_WORD.search(query)))
        chosen: list[str] = []
        if include_us:
            chosen.extend(_US_INDEXES)
        if include_eu:
            chosen.extend(_EU_INDEXES)
        return chosen
    found = list(dict.fromkeys(named))
    for ticker in _explicit_tickers(query):
        if ticker not in found:
            found.append(ticker)
    if found:
        return found[:8]
    if _BROAD.search(query):
        return list(_US_INDEXES)
    cleaned = " ".join(_FILLER.sub(" ", query).split())
    if len(cleaned) >= 2:
        symbol = _search_symbol(cleaned)
        if symbol:
            return [symbol]
    return []


def _regions(query: str) -> set[str]:
    found: set[str] = set()
    if _US_REGION.search(query):
        found.add("us")
    if _EU_REGION.search(query):
        found.add("eu")
    return found


def _explicit_tickers(query: str) -> list[str]:
    tickers = []
    for match in _TICKER.finditer(query):
        ticker = (match.group(1) or match.group(2) or "").upper()
        if ticker and ticker not in _STOP and ticker not in tickers:
            tickers.append(ticker)
    return tickers


def _chart_quote(symbol: str) -> dict | None:
    try:
        payload = _get(f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}", {"interval": "1d", "range": "5d"})
    except Exception:
        logger.warning("Market quote failed for %s", symbol, exc_info=True)
        return None
    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        return None
    meta = result[0].get("meta") or {}
    price = meta.get("regularMarketPrice")
    if price is None:
        return None
    previous = meta.get("chartPreviousClose") or meta.get("previousClose")
    change = meta.get("regularMarketChange")
    if change is None:
        change = meta.get("fulldayChange")
    if change is None and previous not in (None, 0):
        change = float(price) - float(previous)
    percent = meta.get("regularMarketChangePercent")
    if percent is None:
        percent = meta.get("fulldayChangePercent")
    if percent is None and previous not in (None, 0) and change is not None:
        percent = float(change) / float(previous) * 100.0
    when = meta.get("regularMarketTime")
    as_of = datetime.fromtimestamp(int(when), timezone.utc).date().isoformat() if when else datetime.now(timezone.utc).date().isoformat()
    return {
        "symbol": meta.get("symbol") or symbol,
        "name": _display_name(meta, symbol),
        "exchange": meta.get("fullExchangeName") or meta.get("exchangeName") or "the listed exchange",
        "currency": meta.get("currency") or "USD",
        "price": float(price),
        "change": float(change or 0.0),
        "change_percent": float(percent or 0.0),
        "as_of": as_of,
    }


def _display_name(meta: dict, symbol: str) -> str:
    fallback = _NAMES.get(symbol, symbol)
    if symbol in _NAMES:
        return fallback
    name = meta.get("shortName") or meta.get("longName") or fallback
    if re.search(r"\d", str(name)):
        name = fallback
    if re.search(r"\d", str(name)):
        name = symbol
    return str(name)


def _search_symbol(text: str) -> str | None:
    try:
        payload = _get(
            "https://query1.finance.yahoo.com/v1/finance/search",
            {"q": text, "quotesCount": 6, "newsCount": 0},
        )
    except Exception:
        logger.warning("Market symbol search failed", exc_info=True)
        return None
    for item in payload.get("quotes") or []:
        if item.get("quoteType") in {"EQUITY", "ETF", "INDEX", "MUTUALFUND"} and item.get("symbol"):
            return item["symbol"]
    return None


def _get(url: str, params: dict) -> dict:
    _enable_trust()
    response = httpx.get(url, params=params, headers=_HEADERS, timeout=12, follow_redirects=True)
    response.raise_for_status()
    return response.json()


def _enable_trust() -> None:
    try:
        import truststore

        truststore.inject_into_ssl()
    except Exception:
        return
