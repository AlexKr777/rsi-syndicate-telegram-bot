from __future__ import annotations

import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.core.config import get_settings
from src.payments.onboarding import OnboardingPaymentService
from src.payments.service import CryptoPayService
from src.referrals.service import ReferralService
from src.storage.db import initialize_database
from src.storage.repository import Repository


class _FakeTelegramClient:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    async def send_message(self, **kwargs):
        self.messages.append(kwargs)
        return {"message_id": len(self.messages)}

    async def get_me(self):
        return {"id": 1, "username": "SyndicateProBot"}

    async def close(self) -> None:
        return None


class _FakeCryptoClient:
    async def close(self) -> None:
        return None


class ReferralFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tempdir = None
        self.temp_root = Path(".tmp_test_refs")
        self.temp_root.mkdir(exist_ok=True)
        self.sqlite_path = self.temp_root / f"referrals_{uuid.uuid4().hex}.db"
        await initialize_database(str(self.sqlite_path))
        self.repository = Repository(str(self.sqlite_path))
        await self.repository.connect()
        self.settings = get_settings()
        self.settings.private_bot_share_link = "https://t.me/SyndicateProBot"
        self.telegram = _FakeTelegramClient()
        self.referral_service = ReferralService(
            self.settings,
            self.repository,
            telegram_client=self.telegram,
        )
        self.onboarding = OnboardingPaymentService(
            self.settings,
            self.repository,
            crypto_pay_service=None,
            premium_telegram_client=self.telegram,
        )
        self.payments = CryptoPayService(
            self.settings,
            self.repository,
            client=_FakeCryptoClient(),
            telegram_client=self.telegram,
        )

    async def asyncTearDown(self) -> None:
        await self.payments.close()
        await self.repository.close()
        if self.sqlite_path.exists():
            self.sqlite_path.unlink()

    async def _create_user(
        self,
        telegram_user_id: int,
        *,
        username: str | None = None,
        is_admin: bool = False,
    ):
        return await self.repository.upsert_private_user(
            telegram_user_id=telegram_user_id,
            username=username,
            first_name=f"User{telegram_user_id}",
            last_name=None,
            is_admin=is_admin,
        )

    async def _register_referred_user(
        self,
        *,
        referrer_user_id: int,
        referred_user_id: int,
    ) -> str:
        referral_code = await self.referral_service.ensure_referral_code(referrer_user_id)
        await self.onboarding.register_contact(
            telegram_user_id=referred_user_id,
            username=f"user{referred_user_id}",
            first_name=f"User{referred_user_id}",
            last_name=None,
            bot_kind="premium",
            start_payload=f"ref_{referral_code}",
        )
        return referral_code

    async def _seed_invoice(
        self,
        *,
        invoice_id: int,
        telegram_user_id: int,
        duration_days: int = 30,
    ) -> None:
        created_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        custom_payload = json.dumps(
            {
                "telegram_user_id": telegram_user_id,
                "bot_kind": "premium",
                "target_access_level": "pro",
                "duration_days": duration_days,
                "purpose": "subscription_purchase",
            },
            ensure_ascii=True,
            separators=(",", ":"),
        )
        await self.repository.upsert_crypto_pay_invoice(
            invoice_id=invoice_id,
            invoice_hash=f"hash-{invoice_id}",
            telegram_user_id=telegram_user_id,
            bot_kind="premium",
            target_access_level="pro",
            target_duration_days=duration_days,
            amount="30.00",
            asset="USDT",
            currency_type="crypto",
            description="Syndicate PRO+ access",
            status="active",
            pay_url=f"https://t.me/invoice/{invoice_id}",
            custom_payload=custom_payload,
            created_at=created_at,
            paid_at=None,
            activated_at=None,
            metadata={"seeded": True},
        )

    async def _pay_invoice(
        self,
        *,
        invoice_id: int,
        telegram_user_id: int,
        paid_at: datetime | None = None,
    ):
        effective_paid_at = paid_at or datetime.now(timezone.utc)
        payload = {
            "update_type": "invoice_paid",
            "request_date": effective_paid_at.isoformat(),
            "payload": {
                "invoice_id": invoice_id,
                "hash": f"hash-{invoice_id}",
                "status": "paid",
                "payload": json.dumps(
                    {
                        "telegram_user_id": telegram_user_id,
                        "bot_kind": "premium",
                        "target_access_level": "pro",
                        "duration_days": 30,
                        "purpose": "subscription_purchase",
                    },
                    ensure_ascii=True,
                    separators=(",", ":"),
                ),
                "amount": "30.00",
                "asset": "USDT",
                "currency_type": "crypto",
                "description": "Syndicate PRO+ access",
                "pay_url": f"https://t.me/invoice/{invoice_id}",
                "created_at": (effective_paid_at - timedelta(minutes=5)).isoformat(),
                "paid_at": effective_paid_at.isoformat(),
            },
        }
        raw_body = json.dumps(payload, sort_keys=True).encode("utf-8")
        return await self.payments.handle_webhook(payload, raw_body=raw_body)

    async def test_referral_attribution_is_saved_once(self) -> None:
        await self._create_user(900001, username="referrer")
        referral_code = await self._register_referred_user(
            referrer_user_id=900001,
            referred_user_id=900101,
        )

        referred = await self.repository.get_private_user(900101)
        self.assertIsNotNone(referred)
        assert referred is not None
        self.assertEqual(referred.referred_by_user_id, 900001)

        referral = await self.repository.get_referral(referred_user_id=900101)
        self.assertIsNotNone(referral)
        assert referral is not None
        self.assertEqual(referral.referrer_user_id, 900001)
        self.assertEqual(referral.source_payload, f"ref_{referral_code}")

        await self._create_user(900002, username="other_referrer")
        second_code = await self.referral_service.ensure_referral_code(900002)
        updated = await self.onboarding.register_contact(
            telegram_user_id=900101,
            username="user900101",
            first_name="User900101",
            last_name=None,
            bot_kind="premium",
            start_payload=f"ref_{second_code}",
        )
        self.assertEqual(updated.referred_by_user_id, 900001)

    async def test_self_referral_is_blocked(self) -> None:
        await self._create_user(900003, username="selfref")
        own_code = await self.referral_service.ensure_referral_code(900003)

        resolved = await self.referral_service.resolve_referrer_user_id(
            joining_user_id=900003,
            payload=f"ref_{own_code}",
            existing_user=None,
        )

        self.assertIsNone(resolved)

    async def test_referral_dashboard_message_uses_stage_copy_and_clean_progress_bar(self) -> None:
        await self._create_user(900004, username="copytest")

        dashboard = await self.referral_service.get_dashboard(900004)
        message = self.referral_service.format_referral_message(dashboard, language_code="en")

        self.assertIn("Cycle Progress", message)
        self.assertIn("Reward Stages", message)
        self.assertIn("Stage 1", message)
        self.assertIn("+30 PRO+ days", message)
        self.assertIn(dashboard.progress_bar, message)
        self.assertIn("Invite Tools", message)

    async def test_paid_referral_counts_once_after_real_payment_only(self) -> None:
        await self._create_user(900010, username="referrer")
        await self._register_referred_user(
            referrer_user_id=900010,
            referred_user_id=900110,
        )

        stats_before = await self.repository.get_referral_cycle_stats(referrer_user_id=900010)
        self.assertIsNone(stats_before)

        await self._seed_invoice(invoice_id=5010, telegram_user_id=900110)
        first_result = await self._pay_invoice(invoice_id=5010, telegram_user_id=900110)
        self.assertTrue(first_result.ok)
        self.assertEqual(first_result.status, "processed")

        stats_after_first = await self.repository.get_referral_cycle_stats(referrer_user_id=900010)
        self.assertIsNotNone(stats_after_first)
        assert stats_after_first is not None
        self.assertEqual(stats_after_first.active_cycle_paid_referrals_count, 1)
        self.assertEqual(stats_after_first.lifetime_paid_referrals_count, 1)

        duplicate_result = await self._pay_invoice(invoice_id=5010, telegram_user_id=900110)
        self.assertEqual(duplicate_result.status, "duplicate")

        await self._seed_invoice(invoice_id=5011, telegram_user_id=900110)
        second_invoice_result = await self._pay_invoice(invoice_id=5011, telegram_user_id=900110)
        self.assertEqual(second_invoice_result.status, "processed")

        stats_after_second_invoice = await self.repository.get_referral_cycle_stats(referrer_user_id=900010)
        self.assertIsNotNone(stats_after_second_invoice)
        assert stats_after_second_invoice is not None
        self.assertEqual(stats_after_second_invoice.active_cycle_paid_referrals_count, 1)
        self.assertEqual(stats_after_second_invoice.lifetime_paid_referrals_count, 1)

        referral = await self.repository.get_referral(referred_user_id=900110)
        self.assertIsNotNone(referral)
        assert referral is not None
        self.assertTrue(referral.counted_as_paid_referral)
        self.assertEqual(referral.conversion_invoice_id, 5010)

    async def test_rewards_extend_existing_access_at_three_and_five_paid_referrals(self) -> None:
        await self._create_user(900020, username="reward_referrer")
        anchor = datetime.now(timezone.utc) + timedelta(days=12)
        await self.repository.set_user_access_level(
            telegram_user_id=900020,
            access_level="pro",
            status="paid_active",
            starts_at=datetime.now(timezone.utc) - timedelta(days=3),
            ends_at=anchor,
            metadata={"source": "seed"},
            user_access_status="paid",
            is_admin=False,
        )

        for offset in range(1, 6):
            referred_user_id = 900120 + offset
            await self._register_referred_user(
                referrer_user_id=900020,
                referred_user_id=referred_user_id,
            )
            await self._seed_invoice(invoice_id=5100 + offset, telegram_user_id=referred_user_id)
            result = await self._pay_invoice(
                invoice_id=5100 + offset,
                telegram_user_id=referred_user_id,
                paid_at=datetime.now(timezone.utc) + timedelta(minutes=offset),
            )
            self.assertTrue(result.ok)

        grants = await self.repository.list_referral_reward_grants(referrer_user_id=900020, limit=10)
        self.assertEqual(len(grants), 2)
        grants_by_milestone = {grant.milestone_trigger: grant for grant in grants}
        self.assertEqual(sorted(grants_by_milestone), [3, 5])

        first_grant = grants_by_milestone[3]
        second_grant = grants_by_milestone[5]
        self.assertEqual(first_grant.reward_days, 30)
        self.assertEqual(second_grant.reward_days, 30)
        self.assertEqual(first_grant.access_extension_from, anchor)
        self.assertEqual(first_grant.access_extension_to, anchor + timedelta(days=30))
        self.assertEqual(second_grant.access_extension_from, anchor + timedelta(days=30))
        self.assertEqual(second_grant.access_extension_to, anchor + timedelta(days=60))

        stats = await self.repository.get_referral_cycle_stats(referrer_user_id=900020)
        self.assertIsNotNone(stats)
        assert stats is not None
        self.assertEqual(stats.active_cycle_paid_referrals_count, 0)
        self.assertEqual(stats.lifetime_paid_referrals_count, 5)
        self.assertEqual(stats.current_cycle_number, 2)

        latest_access = await self.repository.get_latest_user_access(900020)
        self.assertIsNotNone(latest_access)
        assert latest_access is not None
        self.assertEqual(latest_access.ends_at, anchor + timedelta(days=60))
