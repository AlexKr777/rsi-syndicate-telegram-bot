from __future__ import annotations

import asyncio
import html
import json
import re
from pathlib import Path
from typing import Any

import aiohttp

from src.core.config import Settings
from src.core.utils import retry_async

TELEGRAM_TEXT_LIMIT = 4096
TELEGRAM_CAPTION_LIMIT = 1024


class TelegramRateLimitError(RuntimeError):
    def __init__(
        self,
        method: str,
        retry_after: float,
        response_json: dict[str, Any],
        *,
        chat_id: str | None = None,
    ) -> None:
        self.method = method
        self.retry_after = max(float(retry_after), 0.0)
        self.response_json = response_json
        self.chat_id = chat_id or ""
        super().__init__(
            f"Telegram {method} rate limited for chat_id={self.chat_id or 'n/a'}, "
            f"retry_after={self.retry_after:.1f}s, response={response_json}"
        )


class TelegramPermanentError(RuntimeError):
    non_retryable = True

    def __init__(
        self,
        method: str,
        status_code: int,
        response_json: dict[str, Any],
        *,
        chat_id: str | None = None,
    ) -> None:
        self.method = method
        self.status_code = int(status_code)
        self.response_json = response_json
        self.chat_id = chat_id or ""
        super().__init__(
            f"Telegram {method} permanent failure for chat_id={self.chat_id or 'n/a'}: "
            f"status={self.status_code}, response={response_json}"
        )


class TelegramClient:
    def __init__(
        self,
        settings: Settings,
        *,
        bot_token: str | None = None,
        bot_label: str = "primary",
    ) -> None:
        self.settings = settings
        self._bot_token = (bot_token or settings.telegram_bot_token).strip()
        self.bot_label = bot_label
        self._session: aiohttp.ClientSession | None = None
        self._send_lock = asyncio.Lock()
        self._last_send_at_by_chat: dict[str, float] = {}
        self._blocked_until_by_chat: dict[str, float] = {}

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.settings.http_timeout_seconds)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _apply_chat_pacing(self, chat_id: str) -> None:
        if not chat_id:
            return
        loop = asyncio.get_running_loop()
        async with self._send_lock:
            while True:
                now = loop.time()
                blocked_until = self._blocked_until_by_chat.get(chat_id, 0.0)
                backoff_wait = blocked_until - now
                last_sent = self._last_send_at_by_chat.get(chat_id)
                pacing_wait = 0.0
                if last_sent is not None:
                    pacing_wait = self.settings.telegram_chat_min_interval_seconds - (now - last_sent)
                wait_for = max(backoff_wait, pacing_wait, 0.0)
                if wait_for <= 0:
                    self._last_send_at_by_chat[chat_id] = loop.time()
                    return
                await asyncio.sleep(wait_for)

    async def _register_chat_rate_limit(self, chat_id: str, retry_after: float) -> None:
        if not chat_id:
            return
        loop = asyncio.get_running_loop()
        async with self._send_lock:
            blocked_until = loop.time() + max(float(retry_after), 0.0)
            self._blocked_until_by_chat[chat_id] = max(
                blocked_until,
                self._blocked_until_by_chat.get(chat_id, 0.0),
            )

    async def get_me(self) -> dict[str, Any]:
        return await self._request("getMe", data={})

    async def send_message(
        self,
        *,
        chat_id: str,
        text: str,
        disable_web_page_preview: bool = True,
        parse_mode: str | None = "HTML",
        reply_markup: dict[str, Any] | None = None,
        reply_to_message_id: int | None = None,
    ) -> dict[str, Any]:
        prepared_text, prepared_parse_mode = self._prepare_outbound_text(
            text,
            limit=TELEGRAM_TEXT_LIMIT,
            parse_mode=parse_mode,
        )
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": prepared_text,
            "disable_web_page_preview": disable_web_page_preview,
        }
        if prepared_parse_mode:
            payload["parse_mode"] = prepared_parse_mode
        if reply_markup is not None:
            payload["reply_markup"] = self._serialize_reply_markup(reply_markup)
        if reply_to_message_id is not None:
            payload["reply_to_message_id"] = reply_to_message_id
        return await self._request_with_html_fallback("sendMessage", payload, text_field="text")

    async def send_photo(
        self,
        *,
        chat_id: str,
        photo_path: Path,
        caption: str,
        parse_mode: str | None = "HTML",
        reply_markup: dict[str, Any] | None = None,
        reply_to_message_id: int | None = None,
    ) -> dict[str, Any]:
        prepared_caption, prepared_parse_mode = self._prepare_outbound_text(
            caption,
            limit=TELEGRAM_CAPTION_LIMIT,
            parse_mode=parse_mode,
        )
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "caption": prepared_caption,
        }
        if prepared_parse_mode:
            payload["parse_mode"] = prepared_parse_mode
        if reply_markup is not None:
            payload["reply_markup"] = self._serialize_reply_markup(reply_markup)
        if reply_to_message_id is not None:
            payload["reply_to_message_id"] = reply_to_message_id
        return await self._request_with_html_fallback(
            "sendPhoto",
            payload,
            text_field="caption",
            file_path=photo_path,
        )

    async def edit_message_text(
        self,
        *,
        chat_id: str,
        message_id: int,
        text: str,
        disable_web_page_preview: bool = True,
        parse_mode: str | None = "HTML",
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        prepared_text, prepared_parse_mode = self._prepare_outbound_text(
            text,
            limit=TELEGRAM_TEXT_LIMIT,
            parse_mode=parse_mode,
        )
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": prepared_text,
            "disable_web_page_preview": disable_web_page_preview,
        }
        if prepared_parse_mode:
            payload["parse_mode"] = prepared_parse_mode
        if reply_markup is not None:
            payload["reply_markup"] = self._serialize_reply_markup(reply_markup)
        return await self._request_with_html_fallback("editMessageText", payload, text_field="text")

    async def edit_message_caption(
        self,
        *,
        chat_id: str,
        message_id: int,
        caption: str,
        parse_mode: str | None = "HTML",
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        prepared_caption, prepared_parse_mode = self._prepare_outbound_text(
            caption,
            limit=TELEGRAM_CAPTION_LIMIT,
            parse_mode=parse_mode,
        )
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "caption": prepared_caption,
        }
        if prepared_parse_mode:
            payload["parse_mode"] = prepared_parse_mode
        if reply_markup is not None:
            payload["reply_markup"] = self._serialize_reply_markup(reply_markup)
        return await self._request_with_html_fallback("editMessageCaption", payload, text_field="caption")

    async def edit_message_media(
        self,
        *,
        chat_id: str,
        message_id: int,
        photo_path: Path,
        caption: str,
        parse_mode: str | None = "HTML",
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        prepared_caption, prepared_parse_mode = self._prepare_outbound_text(
            caption,
            limit=TELEGRAM_CAPTION_LIMIT,
            parse_mode=parse_mode,
        )
        media_payload: dict[str, Any] = {
            "type": "photo",
            "media": "attach://photo",
            "caption": prepared_caption,
        }
        if prepared_parse_mode:
            media_payload["parse_mode"] = prepared_parse_mode
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "media": json.dumps(media_payload, ensure_ascii=False, separators=(",", ":")),
        }
        if reply_markup is not None:
            payload["reply_markup"] = self._serialize_reply_markup(reply_markup)
        return await self._request_with_html_fallback(
            "editMessageMedia",
            payload,
            text_field="media",
            file_path=photo_path,
            file_field_name="photo",
        )

    async def answer_callback_query(
        self,
        *,
        callback_query_id: str,
        text: str | None = None,
        show_alert: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "callback_query_id": callback_query_id,
            "show_alert": show_alert,
        }
        if text:
            payload["text"] = text
        return await self._request("answerCallbackQuery", data=payload)

    async def delete_message(
        self,
        *,
        chat_id: str,
        message_id: int,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
        }
        return await self._request("deleteMessage", data=payload)

    async def get_updates(
        self,
        *,
        offset: int | None = None,
        timeout: int = 0,
        allowed_updates: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            payload["offset"] = offset
        if allowed_updates is not None:
            payload["allowed_updates"] = json.dumps(allowed_updates, ensure_ascii=False, separators=(",", ":"))
        return await self._request("getUpdates", data=payload)

    def _serialize_reply_markup(self, reply_markup: dict[str, Any]) -> str:
        return json.dumps(reply_markup, ensure_ascii=False, separators=(",", ":"))

    def _should_retry_without_html(self, exc: TelegramPermanentError, payload: dict[str, Any]) -> bool:
        description = str((exc.response_json or {}).get("description") or "").lower()
        return payload.get("parse_mode") == "HTML" and "can't parse entities" in description

    def _strip_html_for_plaintext(self, value: str) -> str:
        plain = re.sub(r"<br\s*/?>", "\n", str(value or ""), flags=re.IGNORECASE)
        plain = re.sub(r"</?[^>]+>", "", plain)
        plain = html.unescape(plain)
        plain = re.sub(r"\n{3,}", "\n\n", plain)
        return plain.strip()

    def _truncate_plaintext(self, value: str, *, limit: int) -> str:
        plain = str(value or "").strip()
        if len(plain) <= limit:
            return plain
        suffix = "..."
        if limit <= len(suffix):
            return plain[:limit]
        return plain[: limit - len(suffix)].rstrip() + suffix

    def _prepare_outbound_text(
        self,
        value: str,
        *,
        limit: int,
        parse_mode: str | None,
    ) -> tuple[str, str | None]:
        text = str(value or "")
        if len(text) <= limit:
            return text, parse_mode
        plain = self._truncate_plaintext(self._strip_html_for_plaintext(text), limit=limit)
        return plain, None

    def _media_payload_without_html(self, media_json: str) -> str:
        try:
            media = json.loads(media_json)
        except Exception:
            return self._strip_html_for_plaintext(media_json)
        caption = media.get("caption")
        if isinstance(caption, str):
            media["caption"] = self._strip_html_for_plaintext(caption)
        media.pop("parse_mode", None)
        return json.dumps(media, ensure_ascii=False, separators=(",", ":"))

    async def _request_with_html_fallback(
        self,
        method: str,
        payload: dict[str, Any],
        *,
        text_field: str,
        file_path: Path | None = None,
        file_field_name: str = "photo",
    ) -> dict[str, Any]:
        try:
            return await self._request(method, data=payload, file_path=file_path, file_field_name=file_field_name)
        except TelegramPermanentError as exc:
            if not self._should_retry_without_html(exc, payload):
                raise
            fallback_payload = dict(payload)
            if text_field == "media":
                fallback_payload[text_field] = self._media_payload_without_html(str(fallback_payload.get(text_field) or ""))
            else:
                fallback_payload[text_field] = self._strip_html_for_plaintext(str(fallback_payload.get(text_field) or ""))
            fallback_payload.pop("parse_mode", None)
            return await self._request(
                method,
                data=fallback_payload,
                file_path=file_path,
                file_field_name=file_field_name,
            )

    async def _request(
        self,
        method: str,
        *,
        data: dict[str, Any],
        file_path: Path | None = None,
        file_field_name: str = "photo",
    ) -> dict[str, Any]:
        session = await self._ensure_session()
        url = f"https://api.telegram.org/bot{self._bot_token}/{method}"
        request_timeout = None
        if method == "getUpdates":
            request_timeout = aiohttp.ClientTimeout(
                total=max(
                    self.settings.http_timeout_seconds,
                    self.settings.interactive_callback_poll_timeout_seconds + 10,
                )
            )

        async def _send() -> dict[str, Any]:
            chat_id = str(data.get("chat_id", ""))
            await self._apply_chat_pacing(chat_id)
            if file_path is not None:
                form = aiohttp.FormData()
                for key, value in data.items():
                    form.add_field(key, str(value))
                form.add_field(
                    file_field_name,
                    file_path.read_bytes(),
                    filename=file_path.name,
                    content_type="image/png",
                )
                payload = form
            else:
                payload = data

            async with session.post(url, data=payload, timeout=request_timeout) as response:
                response_json = await response.json(content_type=None)
                if response.status >= 400 or not response_json.get("ok", False):
                    retry_after = (
                        response_json.get("parameters", {}) or {}
                    ).get("retry_after")
                    if response.status == 429 and retry_after is not None:
                        await self._register_chat_rate_limit(chat_id, float(retry_after))
                        raise TelegramRateLimitError(method, retry_after, response_json, chat_id=chat_id)
                    if response.status in {400, 401, 403, 404}:
                        raise TelegramPermanentError(method, response.status, response_json, chat_id=chat_id)
                    raise RuntimeError(
                        f"Telegram {method} failed for chat_id={chat_id or 'n/a'}: "
                        f"status={response.status}, response={response_json}"
                    )
                return response_json["result"]

        return await retry_async(
            _send,
            retries=max(self.settings.http_max_retries, 5),
            operation_name=f"Telegram {method} chat_id={str(data.get('chat_id', '') or 'n/a')}",
        )
