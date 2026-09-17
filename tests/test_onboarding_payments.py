from __future__ import annotations

import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from src.bot.telegram_client import TelegramPermanentError
from src.core.config import get_settings
from src.core.utils import utc_now
from src.payments.onboarding import OnboardingPaymentService
from src.storage.db import initialize_database
from src.storage.repository import Repository


class _BlockedTelegramClient:
    async def send_message(self, **kwargs):
        raise TelegramPermanentError(
            "sendMessage",
            403,
            {"ok": False, "error_code": 403, "description": "Forbidden: bot was blocked by the user"},
            chat_id=str(kwargs.get("chat_id") or ""),
        )


class _ConfiguredCryptoPayService:
    async def create_subscription_invoice(self, **kwargs):
        raise AssertionError("existing invoice should be reused")


class OnboardingPaymentDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.sqlite_path = Path(self.tempdir.name) / "onboarding.sqlite3"
        await initialize_database(str(self.sqlite_path))
        self.repository = Repository(str(self.sqlite_path))
        await self.repository.connect()
        self.settings = get_settings().model_copy(deep=True)
        self.settings.admin_telegram_user_ids_raw = ""
        self.settings.admin_telegram_usernames_raw = ""
        self.settings.crypto_pay_enabled = True
        self.settings.crypto_pay_api_token = "test-token"
        self.telegram_user_id = 123456
        await self.repository.upsert_private_user(
            telegram_user_id=self.telegram_user_id,
            username="blocked_user",
            first_name="Blocked",
            last_name=None,
        )
        now = utc_now()
        await self.repository.upsert_crypto_pay_invoice(
            invoice_id=1001,
            invoice_hash="invoice-hash",
            telegram_user_id=self.telegram_user_id,
            bot_kind="premium",
            target_access_level="pro",
            target_duration_days=30,
            amount="30.00",
            asset="USDT",
            currency_type="crypto",
            description="Test invoice",
            status="active",
            pay_url="https://pay.example/invoice",
            custom_payload="{}",
            created_at=now,
            paid_at=None,
            activated_at=None,
            metadata={},
        )
        self.campaign = await self.repository.upsert_onboarding_payment_campaign(
            telegram_user_id=self.telegram_user_id,
            bot_kind="premium",
            campaign_type="trial_48h",
            first_contact_at=now - timedelta(days=3),
            trial_started_at=now - timedelta(days=3),
            trial_ends_at=now - timedelta(days=1),
            referred_by_user_id=None,
            invoice_id=1001,
            offer_sent_at=None,
            status="invoice_ready",
            next_retry_at=now - timedelta(minutes=1),
        )

    async def asyncTearDown(self) -> None:
        await self.repository.close()
        self.tempdir.cleanup()

    async def test_permanent_telegram_failure_stops_onboarding_retries(self) -> None:
        service = OnboardingPaymentService(
            self.settings,
            self.repository,
            crypto_pay_service=_ConfiguredCryptoPayService(),
            premium_telegram_client=_BlockedTelegramClient(),
        )

        await service.handle_due_campaign(self.campaign)

        refreshed = await self.repository.get_onboarding_payment_campaign(
            telegram_user_id=self.telegram_user_id,
            bot_kind="premium",
        )
        assert refreshed is not None
        self.assertEqual(refreshed.status, "delivery_unreachable")
        self.assertIsNone(refreshed.next_retry_at)
        self.assertEqual(refreshed.attempt_count, 1)
