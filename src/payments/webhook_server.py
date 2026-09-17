from __future__ import annotations

import json
import logging
from html import escape
from dataclasses import dataclass

from aiohttp import web

from src.core.config import Settings
from src.core.utils import normalize_symbol
from src.market.symbols import build_futures_app_link, build_futures_link
from src.payments.service import CryptoPayService

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class WebhookServerStatus:
    local_base_url: str
    local_webhook_url: str
    health_url: str


class PaymentWebhookServer:
    def __init__(self, settings: Settings, service: CryptoPayService) -> None:
        self.settings = settings
        self.service = service
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    async def start(self) -> WebhookServerStatus:
        if self._runner is not None:
            return self._status()
        self._app = web.Application()
        self._app.router.add_post(
            self.settings.normalized_crypto_pay_webhook_path,
            self._handle_crypto_webhook,
        )
        self._app.router.add_get(
            self.settings.normalized_crypto_pay_webhook_path,
            self._handle_webhook_info,
        )
        self._app.router.add_get(
            self.settings.local_webhook_health_path,
            self._handle_health,
        )
        self._app.router.add_get(
            "/bridge/binance",
            self._handle_binance_bridge,
        )
        self._runner = web.AppRunner(self._app, access_log=None)
        await self._runner.setup()
        self._site = web.TCPSite(
            self._runner,
            host=self.settings.local_webhook_host,
            port=self.settings.local_webhook_port,
        )
        await self._site.start()
        status = self._status()
        LOGGER.info("Crypto Pay webhook server started local=%s", status.local_webhook_url)
        return status

    async def stop(self) -> None:
        if self._site is not None:
            await self._site.stop()
            self._site = None
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
        self._app = None

    def _status(self) -> WebhookServerStatus:
        local_base_url = self.settings.local_webhook_base_url
        return WebhookServerStatus(
            local_base_url=local_base_url,
            local_webhook_url=f"{local_base_url}{self.settings.normalized_crypto_pay_webhook_path}",
            health_url=f"{local_base_url}{self.settings.local_webhook_health_path}",
        )

    async def _handle_webhook_info(self, request: web.Request) -> web.Response:
        return web.json_response(
            {
                "ok": True,
                "service": "crypto_pay_webhook",
                "method": "POST",
                "path": self.settings.normalized_crypto_pay_webhook_path,
            }
        )

    async def _handle_health(self, request: web.Request) -> web.Response:
        return web.json_response(
            {
                "ok": True,
                "service": "payments",
                "webhook_path": self.settings.normalized_crypto_pay_webhook_path,
            }
        )

    async def _handle_binance_bridge(self, request: web.Request) -> web.Response:
        symbol = normalize_symbol(request.query.get("symbol"))
        if not symbol:
            return web.Response(text="Missing symbol", status=400, content_type="text/plain")
        app_url = build_futures_app_link(self.settings.binance_futures_app_base_url, symbol)
        browser_url = build_futures_link(self.settings.binance_futures_web_base_url, symbol)
        return web.Response(
            text=self._render_binance_bridge_page(symbol=symbol, app_url=app_url, browser_url=browser_url),
            content_type="text/html",
        )

    def _render_binance_bridge_page(self, *, symbol: str, app_url: str, browser_url: str) -> str:
        symbol_json = json.dumps(symbol)
        app_url_json = json.dumps(app_url)
        browser_url_json = json.dumps(browser_url)
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Binance Quick Open</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #0f141b;
      --panel: #171f29;
      --panel-2: #202b38;
      --text: #f3f6fb;
      --muted: #a7b2c2;
      --accent: #f3ba2f;
      --accent-text: #181818;
      --line: rgba(255,255,255,0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      padding: 20px;
      background: radial-gradient(circle at top, #1d2732 0%, var(--bg) 60%);
      color: var(--text);
      font-family: "Segoe UI", system-ui, sans-serif;
    }}
    .card {{
      width: min(100%, 430px);
      padding: 22px;
      border-radius: 22px;
      border: 1px solid var(--line);
      background: linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0.015));
      box-shadow: 0 20px 50px rgba(0,0,0,0.35);
    }}
    .eyebrow {{
      color: var(--accent);
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    h1 {{
      margin: 8px 0 10px;
      font-size: 28px;
      line-height: 1.06;
    }}
    .symbol {{
      margin: 14px 0;
      padding: 14px 16px;
      border-radius: 16px;
      border: 1px solid var(--line);
      background: var(--panel);
      font-size: 26px;
      font-weight: 800;
      letter-spacing: 0.02em;
    }}
    p {{
      margin: 0 0 14px;
      color: var(--muted);
      line-height: 1.45;
    }}
    .status {{
      color: var(--text);
      font-weight: 600;
      margin-bottom: 8px;
    }}
    .actions {{
      margin-top: 16px;
      display: none;
      gap: 10px;
    }}
    button, a {{
      display: block;
      width: 100%;
      padding: 14px 16px;
      border-radius: 14px;
      border: 0;
      text-align: center;
      text-decoration: none;
      font-size: 16px;
      font-weight: 700;
      cursor: pointer;
    }}
    .primary {{
      background: var(--accent);
      color: var(--accent-text);
    }}
    .secondary {{
      background: var(--panel-2);
      color: var(--text);
      border: 1px solid var(--line);
    }}
    .tiny {{
      margin-top: 12px;
      font-size: 13px;
      color: var(--muted);
    }}
  </style>
</head>
<body>
  <div class="card">
    <div class="eyebrow">Quick open</div>
    <h1>Binance + copy</h1>
    <div class="symbol">{escape(symbol)}</div>
    <p id="status" class="status">Copying ticker and opening Binance...</p>
    <p id="hint">If Binance opens on the last screen, just tap search and paste the copied ticker.</p>
    <div id="actions" class="actions">
      <button id="copy" class="primary">Copy {escape(symbol)}</button>
      <a id="open-app" class="secondary" href="{escape(app_url)}">Open Binance app</a>
      <a id="open-web" class="secondary" href="{escape(browser_url)}">Open in browser</a>
    </div>
    <div class="tiny">This page tries to do the copy and open step for you automatically.</div>
  </div>
  <script>
    const symbol = {symbol_json};
    const appUrl = {app_url_json};
    const browserUrl = {browser_url_json};
    const statusEl = document.getElementById("status");
    const hintEl = document.getElementById("hint");
    const actionsEl = document.getElementById("actions");
    const copyButton = document.getElementById("copy");
    const openAppButton = document.getElementById("open-app");
    const openWebButton = document.getElementById("open-web");
    openAppButton.href = appUrl;
    openWebButton.href = browserUrl;

    function legacyCopyText(value) {{
      const input = document.createElement("textarea");
      input.value = value;
      input.setAttribute("readonly", "");
      input.style.position = "absolute";
      input.style.left = "-9999px";
      document.body.appendChild(input);
      input.select();
      input.setSelectionRange(0, value.length);
      let copied = false;
      try {{
        copied = document.execCommand("copy");
      }} catch (_error) {{
        copied = false;
      }}
      document.body.removeChild(input);
      return copied;
    }}

    async function copySymbol() {{
      if (navigator.clipboard && navigator.clipboard.writeText) {{
        try {{
          await navigator.clipboard.writeText(symbol);
          return true;
        }} catch (_error) {{}}
      }}
      return legacyCopyText(symbol);
    }}

    async function quickOpen() {{
      const copied = await copySymbol();
      if (copied) {{
        statusEl.textContent = "Ticker copied. Opening Binance...";
      }} else {{
        statusEl.textContent = "Opening Binance...";
        hintEl.textContent = "If the ticker was not copied automatically, use the copy button below.";
      }}
      setTimeout(() => {{
        window.location.replace(appUrl);
      }}, 120);
      setTimeout(() => {{
        actionsEl.style.display = "grid";
      }}, 1800);
    }}

    copyButton.addEventListener("click", async () => {{
      const copied = await copySymbol();
      statusEl.textContent = copied ? "Ticker copied." : "Copy was blocked by this device.";
    }});

    window.addEventListener("load", () => {{
      quickOpen().catch(() => {{
        statusEl.textContent = "Could not auto-run the quick open. Use the buttons below.";
        actionsEl.style.display = "grid";
      }});
    }});
  </script>
</body>
</html>"""

    async def _handle_crypto_webhook(self, request: web.Request) -> web.Response:
        remote = request.headers.get("X-Forwarded-For") or request.remote
        raw_body = await request.read()
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except Exception:
            LOGGER.warning("Crypto Pay webhook rejected: invalid JSON remote=%s", remote)
            return web.json_response({"ok": False, "error": "invalid_json"}, status=400)
        if not isinstance(payload, dict):
            LOGGER.warning("Crypto Pay webhook rejected: JSON root is not an object remote=%s", remote)
            return web.json_response({"ok": False, "error": "invalid_payload"}, status=400)
        try:
            result = await self.service.handle_webhook(payload, raw_body=raw_body)
        except Exception:
            LOGGER.exception("Crypto Pay webhook processing failed remote=%s", remote)
            return web.json_response({"ok": False, "error": "processing_failed"}, status=500)
        LOGGER.info(
            "Crypto Pay webhook processed status=%s invoice_id=%s user=%s remote=%s",
            result.status,
            result.invoice_id,
            result.telegram_user_id,
            remote,
        )
        return web.json_response(
            {
                "ok": result.ok,
                "status": result.status,
                "message": result.message,
                "invoice_id": result.invoice_id,
                "telegram_user_id": result.telegram_user_id,
            }
        )
