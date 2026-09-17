from __future__ import annotations

from urllib.parse import quote, urlsplit

from src.core.config import Settings
from src.core.utils import normalize_symbol

BINANCE_BRIDGE_PATH = "/bridge/binance"


def resolve_runtime_public_base_url(settings: Settings) -> str | None:
    try:
        first_line = settings.tunnel_url_file.read_text(encoding="utf-8").splitlines()[0].strip()
    except Exception:
        return None
    if not first_line or first_line.upper() == "UNAVAILABLE":
        return None
    parsed = urlsplit(first_line)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return first_line.rstrip("/")


def build_binance_copy_bridge_url(public_base_url: str, symbol: str) -> str:
    normalized_symbol = quote(normalize_symbol(symbol))
    return f"{public_base_url.rstrip('/')}{BINANCE_BRIDGE_PATH}?symbol={normalized_symbol}"


def resolve_binance_copy_bridge_url(settings: Settings, symbol: str) -> str | None:
    public_base_url = resolve_runtime_public_base_url(settings)
    if not public_base_url:
        return None
    return build_binance_copy_bridge_url(public_base_url, symbol)
