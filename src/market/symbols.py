from __future__ import annotations

from base64 import b64encode
from dataclasses import dataclass
from urllib.parse import quote, urlsplit, urlunsplit


@dataclass(slots=True)
class TickerStats:
    symbol: str
    last_price: float
    price_change_percent: float | None
    volume: float | None
    quote_volume: float | None


_BINANCE_APP_BROWSER_APP_ID = "yFK5FCqYprrXDiVFbhyRx7"
_BINANCE_APP_BROWSER_PATH = "/pages/browser/index"
_BINANCE_APP_DEEPLINK_BASE = "bnc://app.binance.com/mp/app"
_TRADINGVIEW_FUTURES_BASE_URL = "https://www.tradingview.com/chart/?symbol="
_STABLECOIN_ASSETS = {
    "USDT",
    "USDC",
    "FDUSD",
    "BUSD",
    "TUSD",
    "USDP",
    "USDS",
    "DAI",
    "USDE",
    "PYUSD",
    "USD0",
}


def is_active_usdt_perpetual(symbol_payload: dict) -> bool:
    if (
        symbol_payload.get("status") != "TRADING"
        or symbol_payload.get("contractType") != "PERPETUAL"
        or _normalize_asset(symbol_payload.get("quoteAsset")) != "USDT"
    ):
        return False
    return is_supported_futures_symbol(
        str(symbol_payload.get("symbol") or ""),
        base_asset=symbol_payload.get("baseAsset"),
        quote_asset=symbol_payload.get("quoteAsset"),
    )


def _normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def _normalize_asset(value: object) -> str:
    return str(value or "").strip().upper()


def _effective_base_asset(symbol: str, base_asset: object, quote_asset: object) -> str:
    normalized_base = _normalize_asset(base_asset)
    if normalized_base:
        return normalized_base
    normalized_quote = _normalize_asset(quote_asset)
    normalized_symbol = _normalize_symbol(symbol)
    if normalized_quote and normalized_symbol.endswith(normalized_quote) and len(normalized_symbol) > len(normalized_quote):
        return normalized_symbol[: -len(normalized_quote)]
    return ""


def is_supported_futures_symbol(
    symbol: str,
    *,
    base_asset: object | None = None,
    quote_asset: object | None = "USDT",
) -> bool:
    normalized_symbol = _normalize_symbol(symbol)
    normalized_quote = _normalize_asset(quote_asset)
    effective_base = _effective_base_asset(normalized_symbol, base_asset, normalized_quote)
    if not normalized_symbol or not normalized_quote:
        return False
    if normalized_symbol == normalized_quote:
        return False
    if not effective_base:
        return False
    if effective_base == normalized_quote:
        return False
    if effective_base in _STABLECOIN_ASSETS:
        return False
    return True


def _futures_base_url(base_url: str) -> str:
    parts = urlsplit(str(base_url or "").strip())
    path_parts = [part for part in parts.path.split("/") if part]
    if path_parts and path_parts[-1] in {"futures", "trade", "download"}:
        path_parts[-1] = "futures"
    else:
        path_parts.append("futures")
    normalized_path = "/" + "/".join(path_parts)
    return urlunsplit((parts.scheme, parts.netloc, normalized_path, "", ""))


def _download_base_url(base_url: str) -> str:
    parts = urlsplit(str(base_url or "").strip())
    path_parts = [part for part in parts.path.split("/") if part]
    if path_parts and path_parts[-1] in {"futures", "trade", "download"}:
        path_parts[-1] = "download"
    else:
        path_parts.append("download")
    normalized_path = "/" + "/".join(path_parts)
    return urlunsplit((parts.scheme, parts.netloc, normalized_path, "", ""))


def _web_host_base_url(base_url: str) -> str:
    parts = urlsplit(str(base_url or "").strip())
    netloc = parts.netloc
    if netloc.startswith("app."):
        netloc = f"www.{netloc[4:]}"
    normalized_path = "/" + "/".join(part for part in parts.path.split("/") if part)
    return urlunsplit((parts.scheme, netloc, normalized_path, "", ""))


def build_futures_link(base_url: str, symbol: str) -> str:
    futures_base = _futures_base_url(base_url).rstrip("/")
    normalized_symbol = quote(_normalize_symbol(symbol))
    return f"{futures_base}/{normalized_symbol}"


def build_futures_app_link(base_url: str, symbol: str) -> str:
    target_url = build_futures_link(_web_host_base_url(base_url), symbol)
    start_page_path = b64encode(_BINANCE_APP_BROWSER_PATH.encode("utf-8")).decode("ascii")
    start_page_query = b64encode(f"url={target_url}&defaultChainId=1".encode("utf-8")).decode("ascii")
    deeplink = (
        f"{_BINANCE_APP_DEEPLINK_BASE}"
        f"?appId={_BINANCE_APP_BROWSER_APP_ID}"
        f"&startPagePath={start_page_path}"
        f"&startPageQuery={start_page_query}"
    )
    encoded_deeplink = b64encode(deeplink.encode("utf-8")).decode("ascii")
    download_base = _download_base_url(base_url)
    return f"{download_base}?_dp={encoded_deeplink}"


def build_tradingview_futures_link(symbol: str) -> str:
    normalized_symbol = _normalize_symbol(symbol)
    tradingview_symbol = quote(f"BINANCE:{normalized_symbol}.P", safe="")
    return f"{_TRADINGVIEW_FUTURES_BASE_URL}{tradingview_symbol}"
