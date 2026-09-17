from __future__ import annotations

import base64
import unittest
from urllib.parse import parse_qs, urlsplit

from src.bot.telegram_client import TELEGRAM_CAPTION_LIMIT, TELEGRAM_TEXT_LIMIT, TelegramClient
from src.core.config import get_settings
from src.market.symbols import build_futures_app_link, build_futures_link, build_tradingview_futures_link


class TelegramClientLimitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TelegramClient(get_settings())

    def test_prepare_outbound_text_keeps_html_when_under_limit(self) -> None:
        text, parse_mode = self.client._prepare_outbound_text(  # type: ignore[attr-defined]
            "<b>Hello</b>",
            limit=TELEGRAM_CAPTION_LIMIT,
            parse_mode="HTML",
        )

        self.assertEqual(text, "<b>Hello</b>")
        self.assertEqual(parse_mode, "HTML")

    def test_prepare_outbound_text_falls_back_to_plaintext_when_caption_is_too_long(self) -> None:
        source = "<b>" + ("A" * (TELEGRAM_CAPTION_LIMIT + 100)) + "</b>"

        text, parse_mode = self.client._prepare_outbound_text(  # type: ignore[attr-defined]
            source,
            limit=TELEGRAM_CAPTION_LIMIT,
            parse_mode="HTML",
        )

        self.assertIsNone(parse_mode)
        self.assertLessEqual(len(text), TELEGRAM_CAPTION_LIMIT)
        self.assertNotIn("<b>", text)
        self.assertTrue(text.endswith("..."))

    def test_prepare_outbound_text_truncates_plain_text_limit(self) -> None:
        source = "A" * (TELEGRAM_TEXT_LIMIT + 50)

        text, parse_mode = self.client._prepare_outbound_text(  # type: ignore[attr-defined]
            source,
            limit=TELEGRAM_TEXT_LIMIT,
            parse_mode=None,
        )

        self.assertIsNone(parse_mode)
        self.assertLessEqual(len(text), TELEGRAM_TEXT_LIMIT)
        self.assertTrue(text.endswith("..."))

    def test_build_futures_link_points_to_canonical_futures_pair_route(self) -> None:
        self.assertEqual(
            build_futures_link("https://www.binance.com/en/futures", "ethusdt"),
            "https://www.binance.com/en/futures/ETHUSDT",
        )

    def test_build_futures_app_link_wraps_binance_download_deeplink(self) -> None:
        url = build_futures_app_link("https://app.binance.com/en/futures", "ethusdt")

        parts = urlsplit(url)
        params = parse_qs(parts.query)
        self.assertEqual(f"{parts.scheme}://{parts.netloc}{parts.path}", "https://app.binance.com/en/download")
        self.assertIn("_dp", params)

        outer = base64.b64decode(params["_dp"][0]).decode("utf-8")
        outer_parts = urlsplit(outer)
        outer_params = parse_qs(outer_parts.query)
        self.assertEqual(f"{outer_parts.scheme}://{outer_parts.netloc}{outer_parts.path}", "bnc://app.binance.com/mp/app")
        self.assertEqual(outer_params["appId"][0], "yFK5FCqYprrXDiVFbhyRx7")
        self.assertEqual(
            base64.b64decode(outer_params["startPagePath"][0]).decode("utf-8"),
            "/pages/browser/index",
        )
        self.assertEqual(
            base64.b64decode(outer_params["startPageQuery"][0]).decode("utf-8"),
            "url=https://www.binance.com/en/futures/ETHUSDT&defaultChainId=1",
        )

    def test_build_futures_link_formats_prefixed_symbols_for_trade_route(self) -> None:
        self.assertEqual(
            build_futures_link("https://www.binance.com/en/futures", "1000pepeusdt"),
            "https://www.binance.com/en/futures/1000PEPEUSDT",
        )

    def test_build_tradingview_futures_link_uses_perp_symbol_format(self) -> None:
        self.assertEqual(
            build_tradingview_futures_link("clousdt"),
            "https://www.tradingview.com/chart/?symbol=BINANCE%3ACLOUSDT.P",
        )


if __name__ == "__main__":
    unittest.main()
