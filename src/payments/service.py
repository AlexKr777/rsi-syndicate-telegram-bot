from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from src.bot.telegram_client import TelegramClient
from src.core.config import Settings
from src.core.utils import utc_now
from src.payments.crypto_pay_client import CryptoPayClient
from src.referrals.service import ReferralService
from src.storage.repository import Repository

LOGGER = logging.getLogger(__name__)


def _parse_dt(value: Any) -> datetime | None:
    if value in {None, ""}:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass(slots=True)
class CryptoWebhookProcessResult:
    ok: bool
    status: str
    message: str
    invoice_id: int | None = None
    telegram_user_id: int | None = None


class CryptoPayService:
    def __init__(
        self,
        settings: Settings,
        repository: Repository,
        *,
        client: CryptoPayClient | None = None,
        telegram_client: TelegramClient | None = None,
        classic_telegram_client: TelegramClient | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.client = client or CryptoPayClient(settings)
        self.telegram_client = telegram_client
        self.classic_telegram_client = classic_telegram_client
        self.referral_service = ReferralService(
            settings,
            repository,
            telegram_client=telegram_client,
        )

    async def startup_validate(self) -> None:
        if not self.settings.crypto_pay_is_configured:
            LOGGER.info("Crypto Pay integration disabled: CRYPTO_PAY_API_TOKEN is not configured")
            return
        try:
            app_info = await self.client.get_me()
            app_name = app_info.get("name") or app_info.get("app_name") or "unknown"
            LOGGER.info("Crypto Pay integration ready for app=%s", app_name)
        except Exception as exc:
            LOGGER.warning("Crypto Pay validation failed: %s", exc)

    async def close(self) -> None:
        await self.client.close()

    def compose_webhook_url(self, base_url: str) -> str:
        return f"{base_url.rstrip('/')}{self.settings.normalized_crypto_pay_webhook_path}"

    async def create_subscription_invoice(
        self,
        *,
        telegram_user_id: int,
        bot_kind: str = "premium",
        access_level: str = "pro",
        duration_days: int | None = None,
        amount_usd: float | None = None,
        description: str | None = None,
        paid_btn_url: str | None = None,
        purpose: str = "subscription_purchase",
        campaign_type: str | None = None,
        referred_by_user_id: int | None = None,
        extra_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        duration_value = max(duration_days or self.settings.crypto_pay_subscription_days, 1)
        amount_value = amount_usd or self.settings.crypto_pay_invoice_amount_usd
        if paid_btn_url is None:
            if bot_kind == "classic":
                paid_btn_url = self.settings.resolved_classic_bot_share_link or None
            else:
                paid_btn_url = self.settings.resolved_private_bot_share_link or None
        payload = json.dumps(
            {
                "telegram_user_id": telegram_user_id,
                "bot_kind": bot_kind,
                "target_access_level": access_level,
                "duration_days": duration_value,
                "purpose": purpose,
                "campaign_type": campaign_type,
                "referred_by_user_id": referred_by_user_id,
                "extra": extra_payload or {},
            },
            ensure_ascii=True,
            separators=(",", ":"),
        )
        response = await self.client.create_invoice(
            amount=f"{amount_value:.2f}",
            asset=self.settings.crypto_pay_invoice_asset,
            description=description or f"Syndicate PRO+ access for {duration_value} days",
            payload=payload,
            paid_btn_url=paid_btn_url,
        )
        invoice_id = int(response.get("invoice_id") or 0)
        if invoice_id <= 0:
            raise RuntimeError(f"Crypto Pay returned an invalid invoice_id: {response}")
        await self.repository.upsert_crypto_pay_invoice(
            invoice_id=invoice_id,
            invoice_hash=str(response.get("hash") or "") or None,
            telegram_user_id=telegram_user_id,
            bot_kind=bot_kind,
            target_access_level=access_level,
            target_duration_days=duration_value,
            amount=str(response.get("amount") or f"{amount_value:.2f}"),
            asset=str(response.get("asset") or self.settings.crypto_pay_invoice_asset),
            currency_type=str(response.get("currency_type") or "crypto"),
            description=str(response.get("description") or description or ""),
            status=str(response.get("status") or "active"),
            pay_url=str(response.get("pay_url") or response.get("bot_invoice_url") or "") or None,
            custom_payload=payload,
            created_at=_parse_dt(response.get("created_at")) or utc_now(),
            paid_at=_parse_dt(response.get("paid_at")),
            activated_at=None,
            metadata=response,
        )
        LOGGER.info(
            "Crypto Pay invoice created invoice_id=%s user=%s bot_kind=%s amount=%s asset=%s",
            invoice_id,
            telegram_user_id,
            bot_kind,
            response.get("amount") or f"{amount_value:.2f}",
            response.get("asset") or self.settings.crypto_pay_invoice_asset,
        )
        return response

    async def handle_webhook(self, payload: dict[str, Any], *, raw_body: bytes) -> CryptoWebhookProcessResult:
        event_hash = hashlib.sha256(raw_body).hexdigest()
        update_type = str(payload.get("update_type") or "").strip()
        request_date = _parse_dt(payload.get("request_date"))
        invoice = payload.get("payload")
        if not update_type:
            return CryptoWebhookProcessResult(ok=False, status="invalid", message="Missing update_type")
        if not isinstance(invoice, dict):
            return CryptoWebhookProcessResult(ok=False, status="invalid", message="Missing invoice payload")

        invoice_id = int(invoice.get("invoice_id") or 0) or None
        inserted = await self.repository.record_crypto_pay_webhook_event(
            event_hash=event_hash,
            update_type=update_type,
            invoice_id=invoice_id,
            request_date=request_date,
            status="received",
            raw_payload=payload,
        )
        if not inserted:
            LOGGER.info("Crypto Pay webhook duplicate ignored update_type=%s invoice_id=%s", update_type, invoice_id)
            return CryptoWebhookProcessResult(
                ok=True,
                status="duplicate",
                message="Duplicate webhook ignored",
                invoice_id=invoice_id,
            )

        try:
            result = await self._process_webhook_payload(update_type=update_type, invoice=invoice)
            await self.repository.update_crypto_pay_webhook_event_status(
                event_hash=event_hash,
                status=result.status,
            )
            return result
        except Exception as exc:
            await self.repository.update_crypto_pay_webhook_event_status(
                event_hash=event_hash,
                status="failed",
                last_error=str(exc),
            )
            raise

    async def _process_webhook_payload(
        self,
        *,
        update_type: str,
        invoice: dict[str, Any],
    ) -> CryptoWebhookProcessResult:
        invoice_id = int(invoice.get("invoice_id") or 0) or None
        if invoice_id is None:
            raise RuntimeError("Crypto Pay webhook is missing invoice_id")
        invoice_hash = str(invoice.get("hash") or "").strip() or None
        status = str(invoice.get("status") or "").strip().lower()
        existing = await self.repository.get_crypto_pay_invoice(invoice_id=invoice_id, invoice_hash=invoice_hash)
        payload_data = self._decode_invoice_payload(str(invoice.get("payload") or ""))
        telegram_user_id = self._coerce_optional_int(
            payload_data.get("telegram_user_id") if payload_data else None
        )
        if telegram_user_id is None and existing is not None:
            telegram_user_id = existing.telegram_user_id

        bot_kind = str(
            (payload_data.get("bot_kind") if payload_data else None)
            or (existing.bot_kind if existing is not None else "premium")
            or "premium"
        ).strip() or "premium"
        target_access_level = str(
            (payload_data.get("target_access_level") if payload_data else None)
            or (existing.target_access_level if existing is not None else "pro")
            or "pro"
        ).strip() or "pro"
        duration_days = self._coerce_int(
            (payload_data.get("duration_days") if payload_data else None)
            or (existing.target_duration_days if existing is not None else None)
            or self.settings.crypto_pay_subscription_days,
            minimum=1,
        )
        created_at = _parse_dt(invoice.get("created_at")) or (existing.created_at if existing is not None else utc_now())
        paid_at = _parse_dt(invoice.get("paid_at")) or (existing.paid_at if existing is not None else None)

        record = await self.repository.upsert_crypto_pay_invoice(
            invoice_id=invoice_id,
            invoice_hash=invoice_hash,
            telegram_user_id=telegram_user_id,
            bot_kind=bot_kind,
            target_access_level=target_access_level,
            target_duration_days=duration_days,
            amount=str(invoice.get("amount") or (existing.amount if existing is not None else "")) or None,
            asset=str(invoice.get("asset") or (existing.asset if existing is not None else "")) or None,
            currency_type=str(invoice.get("currency_type") or (existing.currency_type if existing is not None else "crypto")) or None,
            description=str(invoice.get("description") or (existing.description if existing is not None else "")) or None,
            status=status or (existing.status if existing is not None else "unknown"),
            pay_url=str(invoice.get("pay_url") or invoice.get("bot_invoice_url") or (existing.pay_url if existing is not None else "")) or None,
            custom_payload=str(invoice.get("payload") or (existing.custom_payload if existing is not None else "")) or None,
            created_at=created_at,
            paid_at=paid_at,
            activated_at=existing.activated_at if existing is not None else None,
            metadata=invoice,
        )

        if update_type != "invoice_paid" or status != "paid":
            LOGGER.info(
                "Crypto Pay webhook ignored update_type=%s invoice_id=%s status=%s",
                update_type,
                record.invoice_id,
                status,
            )
            return CryptoWebhookProcessResult(
                ok=True,
                status="ignored",
                message=f"Ignored update_type={update_type} status={status}",
                invoice_id=record.invoice_id,
                telegram_user_id=telegram_user_id,
            )

        if record.activated_at is not None:
            LOGGER.info("Crypto Pay invoice already activated invoice_id=%s user=%s", record.invoice_id, record.telegram_user_id)
            return CryptoWebhookProcessResult(
                ok=True,
                status="duplicate",
                message="Invoice was already activated",
                invoice_id=record.invoice_id,
                telegram_user_id=record.telegram_user_id,
            )

        if telegram_user_id is None:
            raise RuntimeError(f"Crypto Pay invoice {record.invoice_id} has no telegram_user_id in payload or storage")

        now = utc_now()
        latest_access = await self.repository.get_latest_user_access(telegram_user_id)
        extension_anchor = now
        if (
            latest_access is not None
            and latest_access.ends_at is not None
            and latest_access.ends_at > now
            and str(latest_access.status or "").strip().lower() in {"paid_active", "trial_active"}
        ):
            extension_anchor = latest_access.ends_at
        ends_at = extension_anchor + timedelta(days=max(duration_days, 1))
        await self.repository.upsert_private_user(
            telegram_user_id=telegram_user_id,
            username=None,
            first_name=None,
            last_name=None,
            is_active=True,
        )
        await self.repository.set_user_access_level(
            telegram_user_id=telegram_user_id,
            access_level=target_access_level,
            status="paid_active",
            starts_at=now,
            ends_at=ends_at,
            metadata={
                "source": "crypto_pay",
                "invoice_id": record.invoice_id,
                "invoice_hash": record.invoice_hash,
                "bot_kind": bot_kind,
                "duration_days": duration_days,
                "extension_anchor": extension_anchor.isoformat(),
                "amount": record.amount,
                "asset": record.asset,
                "paid_at": paid_at.isoformat() if paid_at is not None else None,
                "purpose": payload_data.get("purpose") if payload_data else None,
                "campaign_type": payload_data.get("campaign_type") if payload_data else None,
                "referred_by_user_id": payload_data.get("referred_by_user_id") if payload_data else None,
            },
            user_access_status="paid",
            is_admin=False,
        )
        await self.repository.upsert_user_settings(
            telegram_user_id=telegram_user_id,
            bot_kind=bot_kind,
            direct_signal_delivery_enabled=True,
            followup_delivery_enabled=(
                self.settings.private_bot_followups_default
                if bot_kind == "premium"
                else self.settings.classic_bot_followups_default
            ),
            menu_collapsed=False,
        )
        await self.repository.mark_crypto_pay_invoice_activated(
            invoice_id=record.invoice_id,
            activated_at=now,
            status="paid",
            metadata={
                **record.metadata,
                "activated_access_level": target_access_level,
                "activated_bot_kind": bot_kind,
                "activated_ends_at": ends_at.isoformat(),
            },
        )
        onboarding_campaign = await self.repository.get_onboarding_payment_campaign_by_invoice(
            invoice_id=record.invoice_id,
        )
        if onboarding_campaign is not None:
            await self.repository.update_onboarding_payment_campaign(
                onboarding_campaign.id,
                status="converted",
                metadata={
                    **onboarding_campaign.metadata,
                    "converted_at": now.isoformat(),
                    "conversion_invoice_id": record.invoice_id,
                },
            )
        referral_outcome = await self.referral_service.process_paid_conversion(
            referred_user_id=telegram_user_id,
            invoice_id=record.invoice_id,
            converted_at=paid_at or now,
        )
        await self._notify_user_payment_activated(
            telegram_user_id=telegram_user_id,
            duration_days=duration_days,
            bot_kind=bot_kind,
            ends_at=ends_at,
        )
        LOGGER.info(
            "Crypto Pay invoice activated invoice_id=%s user=%s access=%s days=%s bot_kind=%s referral_status=%s",
            record.invoice_id,
            telegram_user_id,
            target_access_level,
            duration_days,
            bot_kind,
            referral_outcome.status,
        )
        return CryptoWebhookProcessResult(
            ok=True,
            status="processed",
            message="Payment processed and access activated",
            invoice_id=record.invoice_id,
            telegram_user_id=telegram_user_id,
        )

    async def _notify_user_payment_activated(
        self,
        *,
        telegram_user_id: int,
        duration_days: int,
        bot_kind: str,
        ends_at: datetime,
    ) -> None:
        if self.telegram_client is None:
            if bot_kind != "classic" or self.classic_telegram_client is None:
                return
        target_client = (
            self.classic_telegram_client
            if bot_kind == "classic" and self.classic_telegram_client is not None
            else self.telegram_client
        )
        if target_client is None:
            return
        try:
            text = (
                "<b>✅ Payment received</b>\n\n"
                f"PRO+ is active for <b>{duration_days} days</b>.\n"
                f"Active until: <b>{ends_at.astimezone(self.settings.timezone).strftime('%Y-%m-%d %H:%M %Z')}</b>\n\n"
                "Use <b>/menu</b> to open the bot controls."
            )
            await target_client.send_message(
                chat_id=str(telegram_user_id),
                text=text,
                parse_mode="HTML",
            )
        except Exception as exc:
            LOGGER.warning(
                "Crypto Pay activation notice failed user=%s bot_kind=%s error=%s",
                telegram_user_id,
                bot_kind,
                exc,
            )

    def _decode_invoice_payload(self, value: str) -> dict[str, Any]:
        text = str(value or "").strip()
        if not text:
            return {}
        try:
            decoded = json.loads(text)
            return decoded if isinstance(decoded, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _coerce_optional_int(self, value: Any) -> int | None:
        if value in {None, ""}:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _coerce_int(self, value: Any, *, minimum: int = 0) -> int:
        try:
            return max(int(value), minimum)
        except (TypeError, ValueError):
            return minimum
