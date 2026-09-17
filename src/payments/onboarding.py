from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from src.bot.telegram_client import TelegramClient, TelegramPermanentError
from src.core.config import Settings
from src.core.utils import escape_html, utc_now
from src.payments.service import CryptoPayService
from src.referrals.service import ReferralService
from src.storage.models import OnboardingCampaignRecord, PrivateBotUserRecord, UserAccessRecord
from src.storage.repository import Repository

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class EffectiveAccessState:
    telegram_user_id: int
    access_level: str
    access_status: str
    starts_at: datetime | None
    ends_at: datetime | None
    metadata: dict[str, Any]
    is_admin: bool

    @property
    def has_premium_access(self) -> bool:
        return self.is_admin or self.access_status in {"trial", "paid", "admin"}

    @property
    def is_paid(self) -> bool:
        return self.access_status == "paid"


class OnboardingPaymentService:
    CAMPAIGN_TYPE = "trial_48h"

    def __init__(
        self,
        settings: Settings,
        repository: Repository,
        *,
        crypto_pay_service: CryptoPayService | None,
        premium_telegram_client: TelegramClient,
        classic_telegram_client: TelegramClient | None = None,
        schedule_wakeup: Callable[[], None] | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.crypto_pay_service = crypto_pay_service
        self.premium_telegram_client = premium_telegram_client
        self.classic_telegram_client = classic_telegram_client
        self.schedule_wakeup = schedule_wakeup
        self.referral_service = ReferralService(
            settings,
            repository,
            telegram_client=premium_telegram_client,
        )

    async def register_contact(
        self,
        *,
        telegram_user_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
        bot_kind: str,
        start_payload: str | None = None,
    ) -> PrivateBotUserRecord:
        existing_user = await self.repository.get_private_user(telegram_user_id)
        referred_by_user_id = await self._resolve_referral_user_id(
            telegram_user_id=telegram_user_id,
            payload=start_payload,
            existing_user=existing_user,
        )
        user = await self.repository.upsert_private_user(
            telegram_user_id=telegram_user_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            is_active=True,
            is_admin=self.is_admin_user(telegram_user_id, username),
            referred_by_user_id=referred_by_user_id,
        )
        if referred_by_user_id is not None and existing_user is None:
            await self.repository.upsert_referral(
                referrer_user_id=referred_by_user_id,
                referred_user_id=telegram_user_id,
                bot_kind=bot_kind,
                source_payload=start_payload,
                metadata={"source": "telegram_start"},
            )

        await self.reconcile_access_state(telegram_user_id)
        if self.is_admin_user(telegram_user_id, username):
            await self.ensure_admin_access(telegram_user_id)
        elif bot_kind == "premium" and self.settings.onboarding_payment_campaign_enabled:
            await self.ensure_onboarding_trial(telegram_user_id)

        updated = await self.repository.get_private_user(telegram_user_id)
        assert updated is not None
        return updated

    async def get_effective_access_state(
        self,
        telegram_user_id: int,
        *,
        user: PrivateBotUserRecord | None = None,
    ) -> EffectiveAccessState:
        user_record = user or await self.repository.get_private_user(telegram_user_id)
        if user_record is None:
            return EffectiveAccessState(
                telegram_user_id=telegram_user_id,
                access_level="free",
                access_status="free",
                starts_at=None,
                ends_at=None,
                metadata={},
                is_admin=self.is_admin_user(telegram_user_id),
            )
        if self.is_admin_user(telegram_user_id, user_record.username) or user_record.is_admin:
            return EffectiveAccessState(
                telegram_user_id=telegram_user_id,
                access_level="admin",
                access_status="admin",
                starts_at=None,
                ends_at=None,
                metadata={"source": "admin_override"},
                is_admin=True,
            )

        latest = await self.repository.get_latest_user_access(telegram_user_id)
        if latest is None:
            return EffectiveAccessState(
                telegram_user_id=telegram_user_id,
                access_level=user_record.access_level,
                access_status=user_record.access_status or "free",
                starts_at=None,
                ends_at=None,
                metadata={},
                is_admin=False,
            )

        now = utc_now()
        latest_status = (latest.status or "").strip().lower()
        active_until = latest.ends_at
        active_window_open = active_until is None or active_until > now
        if latest_status == "trial_active" and active_window_open:
            return EffectiveAccessState(
                telegram_user_id=telegram_user_id,
                access_level="pro",
                access_status="trial",
                starts_at=latest.starts_at,
                ends_at=latest.ends_at,
                metadata=latest.metadata,
                is_admin=False,
            )
        if latest_status == "paid_active" and active_window_open:
            return EffectiveAccessState(
                telegram_user_id=telegram_user_id,
                access_level="pro",
                access_status="paid",
                starts_at=latest.starts_at,
                ends_at=latest.ends_at,
                metadata=latest.metadata,
                is_admin=False,
            )
        if latest_status == "admin_active":
            return EffectiveAccessState(
                telegram_user_id=telegram_user_id,
                access_level="admin",
                access_status="admin",
                starts_at=latest.starts_at,
                ends_at=latest.ends_at,
                metadata=latest.metadata,
                is_admin=True,
            )
        if latest_status in {"trial_expired", "paid_expired"}:
            return EffectiveAccessState(
                telegram_user_id=telegram_user_id,
                access_level="free",
                access_status="expired",
                starts_at=latest.starts_at,
                ends_at=latest.ends_at,
                metadata=latest.metadata,
                is_admin=False,
            )
        return EffectiveAccessState(
            telegram_user_id=telegram_user_id,
            access_level=user_record.access_level or "free",
            access_status=user_record.access_status or "free",
            starts_at=latest.starts_at,
            ends_at=latest.ends_at,
            metadata=latest.metadata,
            is_admin=False,
        )

    async def ensure_admin_access(self, telegram_user_id: int) -> None:
        user = await self.repository.get_private_user(telegram_user_id)
        latest = await self.repository.get_latest_user_access(telegram_user_id)
        if (
            user is not None
            and user.access_level == "admin"
            and user.access_status == "admin"
            and latest is not None
            and latest.status == "admin_active"
        ):
            return
        now = utc_now()
        await self.repository.set_user_access_level(
            telegram_user_id=telegram_user_id,
            access_level="admin",
            status="admin_active",
            starts_at=now,
            ends_at=None,
            metadata={"source": "admin_override"},
            user_access_status="admin",
            is_admin=True,
        )
        LOGGER.info("Admin access ensured user=%s", telegram_user_id)

    async def reconcile_access_state(self, telegram_user_id: int) -> EffectiveAccessState:
        user = await self.repository.get_private_user(telegram_user_id)
        if user is None:
            return await self.get_effective_access_state(telegram_user_id)
        if self.is_admin_user(telegram_user_id, user.username) or user.is_admin:
            await self.ensure_admin_access(telegram_user_id)
            updated_user = await self.repository.get_private_user(telegram_user_id)
            return await self.get_effective_access_state(telegram_user_id, user=updated_user)

        latest = await self.repository.get_latest_user_access(telegram_user_id)
        if latest is None or latest.ends_at is None or latest.ends_at > utc_now():
            return await self.get_effective_access_state(telegram_user_id, user=user)

        latest_status = (latest.status or "").strip().lower()
        if latest_status == "trial_active":
            await self.repository.set_user_access_level(
                telegram_user_id=telegram_user_id,
                access_level="free",
                status="trial_expired",
                starts_at=utc_now(),
                ends_at=latest.ends_at,
                metadata={
                    **latest.metadata,
                    "expired_from": "trial_active",
                    "expired_at": utc_now().isoformat(),
                },
                user_access_status="expired",
                is_admin=False,
            )
            LOGGER.info("Trial access expired user=%s ends_at=%s", telegram_user_id, latest.ends_at.isoformat())
        elif latest_status == "paid_active":
            await self.repository.set_user_access_level(
                telegram_user_id=telegram_user_id,
                access_level="free",
                status="paid_expired",
                starts_at=utc_now(),
                ends_at=latest.ends_at,
                metadata={
                    **latest.metadata,
                    "expired_from": "paid_active",
                    "expired_at": utc_now().isoformat(),
                },
                user_access_status="expired",
                is_admin=False,
            )
            LOGGER.info("Paid access expired user=%s ends_at=%s", telegram_user_id, latest.ends_at.isoformat())

        refreshed_user = await self.repository.get_private_user(telegram_user_id)
        return await self.get_effective_access_state(telegram_user_id, user=refreshed_user)

    async def ensure_onboarding_trial(self, telegram_user_id: int) -> OnboardingCampaignRecord | None:
        user = await self.repository.get_private_user(telegram_user_id)
        if user is None:
            return None
        first_contact_at = user.first_seen_at
        now = utc_now()
        if self.is_admin_user(telegram_user_id, user.username) or user.is_admin:
            return await self.repository.upsert_onboarding_payment_campaign(
                telegram_user_id=telegram_user_id,
                bot_kind="premium",
                campaign_type=self.CAMPAIGN_TYPE,
                first_contact_at=first_contact_at,
                trial_started_at=None,
                trial_ends_at=None,
                referred_by_user_id=user.referred_by_user_id,
                invoice_id=None,
                offer_sent_at=None,
                status="skipped_admin",
                metadata={"source": "admin_bypass"},
            )

        existing = await self.repository.get_onboarding_payment_campaign(
            telegram_user_id=telegram_user_id,
            bot_kind="premium",
            campaign_type=self.CAMPAIGN_TYPE,
        )
        access_state = await self.get_effective_access_state(telegram_user_id, user=user)
        if existing is not None:
            expected_trial_started_at = existing.trial_started_at or first_contact_at
            expected_trial_ends_at = expected_trial_started_at + timedelta(seconds=self.settings.onboarding_trial_seconds)
            if access_state.access_status == "trial" and (
                access_state.starts_at != expected_trial_started_at or access_state.ends_at != expected_trial_ends_at
            ):
                await self.repository.set_user_access_level(
                    telegram_user_id=telegram_user_id,
                    access_level="pro" if expected_trial_ends_at > now else "free",
                    status="trial_active" if expected_trial_ends_at > now else "trial_expired",
                    starts_at=expected_trial_started_at,
                    ends_at=expected_trial_ends_at,
                    metadata={
                        "source": "onboarding_trial_repaired",
                        "bot_kind": "premium",
                        "campaign_type": self.CAMPAIGN_TYPE,
                        "referred_by_user_id": user.referred_by_user_id,
                    },
                    user_access_status="trial" if expected_trial_ends_at > now else "expired",
                    is_admin=False,
                )
            if (
                existing.first_contact_at != first_contact_at
                or existing.trial_started_at != expected_trial_started_at
                or (
                    existing.status in {"trial_active", "invoice_ready", "send_retry"}
                    and existing.trial_ends_at != expected_trial_ends_at
                )
            ):
                await self.repository.update_onboarding_payment_campaign(
                    existing.id,
                    first_contact_at=first_contact_at,
                    trial_started_at=expected_trial_started_at,
                    trial_ends_at=expected_trial_ends_at,
                    metadata={
                        **existing.metadata,
                        "anchor_repaired_at": now.isoformat(),
                        "anchor_repaired_from_first_seen": first_contact_at.isoformat(),
                    },
                )
                existing = await self.repository.get_onboarding_payment_campaign(
                    telegram_user_id=telegram_user_id,
                    bot_kind="premium",
                    campaign_type=self.CAMPAIGN_TYPE,
                )
            assert existing is not None
            if access_state.is_paid and existing.status not in {"converted", "skipped_paid"}:
                await self.repository.update_onboarding_payment_campaign(
                    existing.id,
                    status="skipped_paid",
                    metadata={**existing.metadata, "reason": "already_paid_before_due"},
                )
                existing = await self.repository.get_onboarding_payment_campaign(
                    telegram_user_id=telegram_user_id,
                    bot_kind="premium",
                    campaign_type=self.CAMPAIGN_TYPE,
                )
            assert existing is not None
            return existing

        if access_state.access_status == "trial" and access_state.starts_at is not None and access_state.ends_at is not None:
            restored = await self.repository.upsert_onboarding_payment_campaign(
                telegram_user_id=telegram_user_id,
                bot_kind="premium",
                campaign_type=self.CAMPAIGN_TYPE,
                first_contact_at=first_contact_at,
                trial_started_at=access_state.starts_at,
                trial_ends_at=access_state.ends_at,
                referred_by_user_id=user.referred_by_user_id,
                invoice_id=None,
                offer_sent_at=None,
                status="trial_active" if access_state.ends_at > now else "invoice_ready",
                metadata={
                    "source": "restored_from_existing_trial",
                    "trial_hours": self.settings.onboarding_trial_hours,
                },
            )
            self._notify_scheduler()
            return restored

        if access_state.is_paid:
            return await self.repository.upsert_onboarding_payment_campaign(
                telegram_user_id=telegram_user_id,
                bot_kind="premium",
                campaign_type=self.CAMPAIGN_TYPE,
                first_contact_at=first_contact_at,
                trial_started_at=None,
                trial_ends_at=None,
                referred_by_user_id=user.referred_by_user_id,
                invoice_id=None,
                offer_sent_at=None,
                status="skipped_paid",
                metadata={"reason": "already_paid_before_trial"},
            )

        trial_started_at = first_contact_at
        trial_ends_at = trial_started_at + timedelta(seconds=self.settings.onboarding_trial_seconds)
        campaign_status = "trial_active" if trial_ends_at > now else "invoice_ready"
        if campaign_status == "trial_active":
            await self.repository.set_user_access_level(
                telegram_user_id=telegram_user_id,
                access_level="pro",
                status="trial_active",
                starts_at=trial_started_at,
                ends_at=trial_ends_at,
                metadata={
                    "source": "onboarding_trial",
                    "bot_kind": "premium",
                    "campaign_type": self.CAMPAIGN_TYPE,
                    "referred_by_user_id": user.referred_by_user_id,
                },
                user_access_status="trial",
                is_admin=False,
            )
        else:
            await self.repository.set_user_access_level(
                telegram_user_id=telegram_user_id,
                access_level="free",
                status="trial_expired",
                starts_at=trial_started_at,
                ends_at=trial_ends_at,
                metadata={
                    "source": "onboarding_trial_expired_before_resume",
                    "bot_kind": "premium",
                    "campaign_type": self.CAMPAIGN_TYPE,
                    "referred_by_user_id": user.referred_by_user_id,
                },
                user_access_status="expired",
                is_admin=False,
            )
        campaign = await self.repository.upsert_onboarding_payment_campaign(
            telegram_user_id=telegram_user_id,
            bot_kind="premium",
            campaign_type=self.CAMPAIGN_TYPE,
            first_contact_at=first_contact_at,
            trial_started_at=trial_started_at,
            trial_ends_at=trial_ends_at,
            referred_by_user_id=user.referred_by_user_id,
            invoice_id=None,
            offer_sent_at=None,
            status=campaign_status,
            metadata={
                "source": "onboarding_trial",
                "trial_hours": self.settings.onboarding_trial_hours,
            },
        )
        LOGGER.info(
            "48h onboarding trial anchored user=%s first_seen=%s ends_at=%s status=%s referred_by=%s",
            telegram_user_id,
            first_contact_at.isoformat(),
            trial_ends_at.isoformat(),
            campaign_status,
            user.referred_by_user_id,
        )
        self._notify_scheduler()
        return campaign

    async def process_due_campaigns(self) -> None:
        due_campaigns = await self.repository.get_due_onboarding_payment_campaigns()
        for campaign in due_campaigns:
            await self.handle_due_campaign(campaign)

    async def handle_due_campaign(self, campaign: OnboardingCampaignRecord) -> None:
        user = await self.repository.get_private_user(campaign.telegram_user_id)
        if user is None:
            await self.repository.update_onboarding_payment_campaign(
                campaign.id,
                status="expired_no_payment",
                metadata={**campaign.metadata, "reason": "user_missing"},
            )
            return

        access_state = await self.reconcile_access_state(campaign.telegram_user_id)
        if access_state.is_admin:
            await self.repository.update_onboarding_payment_campaign(
                campaign.id,
                status="skipped_admin",
                metadata={**campaign.metadata, "reason": "admin_bypass"},
            )
            LOGGER.info("Skipping onboarding payment campaign user=%s: admin", campaign.telegram_user_id)
            return
        if access_state.is_paid:
            await self.repository.update_onboarding_payment_campaign(
                campaign.id,
                status="converted",
                metadata={**campaign.metadata, "reason": "already_paid"},
            )
            LOGGER.info("Skipping onboarding payment campaign user=%s: already paid", campaign.telegram_user_id)
            return

        if campaign.status == "trial_active" and campaign.trial_ends_at is not None and campaign.trial_ends_at <= utc_now():
            await self.repository.update_onboarding_payment_campaign(
                campaign.id,
                status="invoice_ready",
                metadata={
                    **campaign.metadata,
                    "trial_expired_at": utc_now().isoformat(),
                },
            )
            campaign = await self.repository.get_onboarding_payment_campaign(
                telegram_user_id=campaign.telegram_user_id,
                bot_kind=campaign.bot_kind,
                campaign_type=campaign.campaign_type,
            ) or campaign

        invoice_record = None
        if campaign.invoice_id is not None:
            invoice_record = await self.repository.get_crypto_pay_invoice(invoice_id=campaign.invoice_id)
            if invoice_record is not None and invoice_record.activated_at is not None:
                await self.repository.update_onboarding_payment_campaign(
                    campaign.id,
                    status="converted",
                    metadata={**campaign.metadata, "reason": "invoice_already_paid"},
                )
                LOGGER.info(
                    "Onboarding payment campaign converted before send retry user=%s invoice_id=%s",
                    campaign.telegram_user_id,
                    campaign.invoice_id,
                )
                return

        if self.crypto_pay_service is None or not self.settings.crypto_pay_is_configured:
            await self._schedule_retry(
                campaign,
                error="Crypto Pay is not configured, onboarding invoice cannot be created yet",
            )
            return

        if invoice_record is None:
            try:
                invoice_response = await self.crypto_pay_service.create_subscription_invoice(
                    telegram_user_id=campaign.telegram_user_id,
                    bot_kind="premium",
                    access_level="pro",
                    duration_days=self.settings.crypto_pay_subscription_days,
                    amount_usd=self.settings.crypto_pay_invoice_amount_usd,
                    description="Continue Syndicate PRO+ after your 48h onboarding trial",
                    purpose="onboarding_trial_conversion",
                    campaign_type=campaign.campaign_type,
                    referred_by_user_id=campaign.referred_by_user_id,
                    extra_payload={
                        "first_contact_at": campaign.first_contact_at.isoformat(),
                        "trial_started_at": campaign.trial_started_at.isoformat() if campaign.trial_started_at else None,
                        "trial_ends_at": campaign.trial_ends_at.isoformat() if campaign.trial_ends_at else None,
                    },
                )
                invoice_id = int(invoice_response.get("invoice_id") or 0)
                if invoice_id <= 0:
                    raise RuntimeError(f"Crypto Pay returned invalid invoice_id: {invoice_response}")
                invoice_record = await self.repository.get_crypto_pay_invoice(invoice_id=invoice_id)
                await self.repository.update_onboarding_payment_campaign(
                    campaign.id,
                    status="invoice_ready",
                    invoice_id=invoice_id,
                    metadata={
                        **campaign.metadata,
                        "invoice_created_at": utc_now().isoformat(),
                    },
                )
                LOGGER.info(
                    "Onboarding invoice created user=%s invoice_id=%s campaign=%s",
                    campaign.telegram_user_id,
                    invoice_id,
                    campaign.campaign_type,
                )
            except Exception as exc:
                await self._schedule_retry(campaign, error=f"invoice_create_failed: {exc}")
                LOGGER.warning(
                    "Onboarding invoice creation failed user=%s campaign=%s error=%s",
                    campaign.telegram_user_id,
                    campaign.campaign_type,
                    exc,
                )
                return

        pay_url = (invoice_record.pay_url if invoice_record is not None else None) or ""
        if not pay_url:
            await self._schedule_retry(campaign, error="invoice_has_no_pay_url")
            LOGGER.warning(
                "Onboarding invoice has no pay_url user=%s invoice_id=%s",
                campaign.telegram_user_id,
                campaign.invoice_id,
            )
            return

        try:
            await self.premium_telegram_client.send_message(
                chat_id=str(campaign.telegram_user_id),
                text=self._render_payment_offer_message(),
                parse_mode="HTML",
                reply_markup=self._build_payment_offer_keyboard(pay_url),
            )
            await self.repository.update_onboarding_payment_campaign(
                campaign.id,
                status="offer_sent",
                offer_sent_at=utc_now(),
                attempt_count=campaign.attempt_count + 1,
                metadata={
                    **campaign.metadata,
                    "offer_sent_at": utc_now().isoformat(),
                },
            )
            LOGGER.info(
                "Onboarding payment offer sent user=%s invoice_id=%s attempts=%s",
                campaign.telegram_user_id,
                campaign.invoice_id,
                campaign.attempt_count + 1,
            )
        except TelegramPermanentError as exc:
            if self._is_unreachable_telegram_error(exc):
                await self.repository.update_onboarding_payment_campaign(
                    campaign.id,
                    status="delivery_unreachable",
                    attempt_count=campaign.attempt_count + 1,
                    last_error=f"invoice_send_failed: {exc}",
                    metadata={
                        **campaign.metadata,
                        "delivery_unreachable_at": utc_now().isoformat(),
                        "delivery_unreachable_reason": str(exc),
                    },
                )
                LOGGER.warning(
                    "Stopped onboarding payment retries for unreachable user=%s invoice_id=%s error=%s",
                    campaign.telegram_user_id,
                    campaign.invoice_id,
                    exc,
                )
                return
            await self._schedule_retry(campaign, error=f"invoice_send_failed: {exc}")
            LOGGER.warning(
                "Onboarding payment offer send failed user=%s invoice_id=%s error=%s",
                campaign.telegram_user_id,
                campaign.invoice_id,
                exc,
            )
        except Exception as exc:
            await self._schedule_retry(campaign, error=f"invoice_send_failed: {exc}")
            LOGGER.warning(
                "Onboarding payment offer send failed user=%s invoice_id=%s error=%s",
                campaign.telegram_user_id,
                campaign.invoice_id,
                exc,
            )

    async def force_due_for_testing(self, telegram_user_id: int, *, bot_kind: str = "premium") -> OnboardingCampaignRecord | None:
        campaign = await self.repository.get_onboarding_payment_campaign(
            telegram_user_id=telegram_user_id,
            bot_kind=bot_kind,
            campaign_type=self.CAMPAIGN_TYPE,
        )
        if campaign is None:
            campaign = await self.ensure_onboarding_trial(telegram_user_id)
        if campaign is None:
            return None
        due_at = utc_now() - timedelta(seconds=5)
        await self.repository.update_onboarding_payment_campaign(
            campaign.id,
            status="trial_active" if campaign.invoice_id is None else "invoice_ready",
            trial_ends_at=due_at,
            next_retry_at=due_at,
            metadata={**campaign.metadata, "forced_due_for_testing": True},
        )
        self._notify_scheduler()
        return await self.repository.get_onboarding_payment_campaign(
            telegram_user_id=telegram_user_id,
            bot_kind=bot_kind,
            campaign_type=self.CAMPAIGN_TYPE,
        )

    def is_admin_user(self, telegram_user_id: int, username: str | None = None) -> bool:
        return self.settings.is_configured_admin(telegram_user_id=telegram_user_id, username=username)

    async def _resolve_referral_user_id(
        self,
        *,
        telegram_user_id: int,
        payload: str | None,
        existing_user: PrivateBotUserRecord | None = None,
    ) -> int | None:
        return await self.referral_service.resolve_referrer_user_id(
            joining_user_id=telegram_user_id,
            payload=payload,
            existing_user=existing_user,
        )

    async def _schedule_retry(self, campaign: OnboardingCampaignRecord, *, error: str) -> None:
        retry_at = utc_now() + timedelta(seconds=self.settings.onboarding_invoice_retry_seconds)
        await self.repository.update_onboarding_payment_campaign(
            campaign.id,
            status="send_retry",
            attempt_count=campaign.attempt_count + 1,
            next_retry_at=retry_at,
            last_error=error,
            metadata={
                **campaign.metadata,
                "last_retry_scheduled_at": utc_now().isoformat(),
            },
        )
        self._notify_scheduler()

    def _is_unreachable_telegram_error(self, exc: TelegramPermanentError) -> bool:
        description = str((exc.response_json or {}).get("description") or "").casefold()
        return exc.status_code == 403 or any(
            marker in description
            for marker in ("bot was blocked by the user", "chat not found", "user is deactivated")
        )

    def _format_payment_offer_message(self) -> str:
        return self._render_payment_offer_message()

    def _build_payment_offer_keyboard(self, pay_url: str) -> dict[str, Any]:
        rows: list[list[dict[str, str]]] = [
            [{"text": "Continue with PRO+", "url": pay_url}],
        ]
        if self.settings.results_channel:
            rows.append([{"text": "Open Results Channel", "url": self._telegram_target_url(self.settings.results_channel)}])
        return {"inline_keyboard": rows}

    def _telegram_target_url(self, target: str) -> str:
        clean = target.strip()
        if clean.startswith("https://") or clean.startswith("http://"):
            return clean
        if clean.startswith("@"):
            return f"https://t.me/{clean.lstrip('@')}"
        return clean

    def _notify_scheduler(self) -> None:
        if self.schedule_wakeup is not None:
            self.schedule_wakeup()

    def _render_payment_offer_message(self) -> str:
        amount = f"{self.settings.crypto_pay_invoice_amount_usd:.2f}"
        asset = escape_html(self.settings.crypto_pay_invoice_asset)
        trial_hours = max(1, int(self.settings.onboarding_trial_hours))
        if trial_hours % 24 == 0 and trial_hours >= 24:
            trial_label = f"{trial_hours // 24}-day"
        else:
            trial_label = f"{trial_hours}-hour"
        return (
            f"⏳ <b>Your {trial_label} PRO+ trial ended</b>\n\n"
            "Premium is paused, but you can unlock it again in one tap.\n\n"
            "<b>Inside PRO+:</b>\n"
            "• earlier signals\n"
            "• AI analysis and risk cards\n"
            "• follow-ups and deeper context\n\n"
            f"Use the button below to continue with <b>{amount} {asset}</b>."
        )
