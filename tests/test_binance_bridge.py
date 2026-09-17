from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from src.bot.binance_bridge import build_binance_copy_bridge_url, resolve_binance_copy_bridge_url


class BinanceBridgeTests(unittest.TestCase):
    def test_build_binance_copy_bridge_url_normalizes_symbol(self) -> None:
        self.assertEqual(
            build_binance_copy_bridge_url("https://demo.ngrok-free.app", "clo/usdt"),
            "https://demo.ngrok-free.app/bridge/binance?symbol=CLOUSDT",
        )

    def test_resolve_binance_copy_bridge_url_reads_runtime_tunnel_url(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            tunnel_file = Path(tempdir) / "tunnel.txt"
            tunnel_file.write_text("https://demo.ngrok-free.app\n", encoding="utf-8")
            settings = SimpleNamespace(tunnel_url_file=tunnel_file)

            url = resolve_binance_copy_bridge_url(settings, "edgeusdt")

        self.assertEqual(url, "https://demo.ngrok-free.app/bridge/binance?symbol=EDGEUSDT")

    def test_resolve_binance_copy_bridge_url_returns_none_when_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            tunnel_file = Path(tempdir) / "tunnel.txt"
            tunnel_file.write_text("UNAVAILABLE\n", encoding="utf-8")
            settings = SimpleNamespace(tunnel_url_file=tunnel_file)

            url = resolve_binance_copy_bridge_url(settings, "edgeusdt")

        self.assertIsNone(url)


if __name__ == "__main__":
    unittest.main()
