from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from src.core.config import get_settings
from src.bot.telegram_client import TelegramClient
from src.payments.onboarding import OnboardingPaymentService
from src.payments.service import CryptoPayService
from src.referrals.service import ReferralService
from src.storage.db import initialize_database
from src.storage.repository import Repository


class _SilentTelegramClient:
    async def send_message(self, **kwargs):
        del kwargs
        return {"ok": True}

    async def get_me(self):
        return {"id": 1, "username": "SyndicateProBot"}

    async def close(self) -> None:
        return None


class _SilentCryptoClient:
    async def close(self) -> None:
        return None


async def _create_invoice(args: argparse.Namespace) -> int:
    settings = get_settings()
    if not settings.crypto_pay_is_configured:
        print("CRYPTO_PAY_API_TOKEN is not configured in .env")
        return 1

    await initialize_database(str(settings.sqlite_path))
    repository = Repository(str(settings.sqlite_path))
    await repository.connect()
    service = CryptoPayService(settings, repository, telegram_client=None)
    try:
        response = await service.create_subscription_invoice(
            telegram_user_id=args.user_id,
            bot_kind=args.bot_kind,
            access_level=args.access_level,
            duration_days=args.days,
            amount_usd=args.amount,
            description=args.description,
        )
        invoice_id = response.get("invoice_id")
        pay_url = response.get("pay_url") or response.get("bot_invoice_url")
        print("")
        print("=== Crypto Pay Test Invoice ===")
        print(f"Invoice ID: {invoice_id}")
        print(f"Bot kind: {args.bot_kind}")
        print(f"Access level: {args.access_level}")
        print(f"Duration days: {args.days}")
        if pay_url:
            print(f"Pay URL: {pay_url}")
        else:
            print("Pay URL: unavailable in API response")
        print("")
        return 0
    finally:
        await service.close()
        await repository.close()


async def _show_onboarding(args: argparse.Namespace) -> int:
    settings = get_settings()
    await initialize_database(str(settings.sqlite_path))
    repository = Repository(str(settings.sqlite_path))
    await repository.connect()
    onboarding = OnboardingPaymentService(
        settings,
        repository,
        crypto_pay_service=None,
        premium_telegram_client=TelegramClient(settings),
    )
    try:
        campaign = await repository.get_onboarding_payment_campaign(
            telegram_user_id=args.user_id,
            bot_kind=args.bot_kind,
            campaign_type="trial_48h",
        )
        user = await repository.get_private_user(args.user_id)
        latest_access = await repository.get_latest_user_access(args.user_id)
        effective_access = await onboarding.get_effective_access_state(args.user_id, user=user)
        print("")
        print("=== Onboarding State ===")
        print(f"User: {args.user_id}")
        print(f"Exists: {'yes' if user is not None else 'no'}")
        print(f"configured_admin: {onboarding.is_admin_user(args.user_id)}")
        if user is not None:
            print(f"first_seen_at: {user.first_seen_at.isoformat()}")
            print(f"access_level: {user.access_level}")
            print(f"access_status: {user.access_status}")
            print(f"is_admin: {user.is_admin}")
            print(f"referred_by_user_id: {user.referred_by_user_id}")
        print(f"effective_access.level: {effective_access.access_level}")
        print(f"effective_access.status: {effective_access.access_status}")
        print(f"effective_access.is_admin: {effective_access.is_admin}")
        print(
            "effective_access.ends_at: "
            f"{effective_access.ends_at.isoformat() if effective_access.ends_at is not None else 'None'}"
        )
        if latest_access is not None:
            print(f"latest_access.status: {latest_access.status}")
            print(f"latest_access.starts_at: {latest_access.starts_at.isoformat()}")
            print(
                "latest_access.ends_at: "
                f"{latest_access.ends_at.isoformat() if latest_access.ends_at is not None else 'None'}"
            )
        if campaign is None:
            print("campaign: none")
        else:
            print(f"campaign.status: {campaign.status}")
            print(f"campaign.first_contact_at: {campaign.first_contact_at.isoformat()}")
            print(
                "campaign.trial_ends_at: "
                f"{campaign.trial_ends_at.isoformat() if campaign.trial_ends_at is not None else 'None'}"
            )
            print(f"campaign.invoice_id: {campaign.invoice_id}")
            print(
                "campaign.next_retry_at: "
                f"{campaign.next_retry_at.isoformat() if campaign.next_retry_at is not None else 'None'}"
            )
            print(f"campaign.attempt_count: {campaign.attempt_count}")
            print(f"campaign.last_error: {campaign.last_error}")
        print("")
        return 0
    finally:
        await onboarding.premium_telegram_client.close()
        await repository.close()


async def _force_onboarding_offer(args: argparse.Namespace) -> int:
    settings = get_settings()
    await initialize_database(str(settings.sqlite_path))
    repository = Repository(str(settings.sqlite_path))
    await repository.connect()
    telegram_client = TelegramClient(settings)
    service = CryptoPayService(
        settings,
        repository,
        telegram_client=telegram_client,
    )
    onboarding = OnboardingPaymentService(
        settings,
        repository,
        crypto_pay_service=service,
        premium_telegram_client=telegram_client,
    )
    try:
        forced = await onboarding.force_due_for_testing(args.user_id, bot_kind=args.bot_kind)
        if forced is None:
            print("No onboarding campaign exists and no trial could be created.")
            return 1
        await onboarding.handle_due_campaign(forced)
        refreshed = await repository.get_onboarding_payment_campaign(
            telegram_user_id=args.user_id,
            bot_kind=args.bot_kind,
            campaign_type="trial_48h",
        )
        print("")
        print("=== Forced Onboarding Offer ===")
        print(f"User: {args.user_id}")
        if refreshed is None:
            print("Campaign: missing after force run")
        else:
            print(f"Status: {refreshed.status}")
            print(f"Invoice ID: {refreshed.invoice_id}")
            print(
                "Offer sent at: "
                f"{refreshed.offer_sent_at.isoformat() if refreshed.offer_sent_at is not None else 'None'}"
            )
            print(
                "Next retry at: "
                f"{refreshed.next_retry_at.isoformat() if refreshed.next_retry_at is not None else 'None'}"
            )
        print("")
        return 0
    finally:
        await service.close()
        await telegram_client.close()
        await repository.close()


async def _run_onboarding_check(_: argparse.Namespace) -> int:
    settings = get_settings()
    await initialize_database(str(settings.sqlite_path))
    repository = Repository(str(settings.sqlite_path))
    await repository.connect()
    telegram_client = TelegramClient(settings)
    service = CryptoPayService(
        settings,
        repository,
        telegram_client=telegram_client,
    )
    onboarding = OnboardingPaymentService(
        settings,
        repository,
        crypto_pay_service=service,
        premium_telegram_client=telegram_client,
    )
    try:
        await onboarding.process_due_campaigns()
        print("Onboarding payment check executed.")
        return 0
    finally:
        await service.close()
        await telegram_client.close()
        await repository.close()


async def _show_referral(args: argparse.Namespace) -> int:
    settings = get_settings()
    await initialize_database(str(settings.sqlite_path))
    repository = Repository(str(settings.sqlite_path))
    await repository.connect()
    referral_service = ReferralService(settings, repository, telegram_client=None)
    try:
        user = await repository.get_private_user(args.user_id)
        if user is None:
            print(f"User {args.user_id} was not found.")
            return 1
        referral_code = await referral_service.ensure_referral_code(args.user_id)
        try:
            referral_link = await referral_service.build_referral_link(referral_code)
        except Exception:
            referral_link = "(configure PRIVATE_BOT_SHARE_LINK or bot token to resolve the deep link)"
        stats = await repository.get_referral_cycle_stats(referrer_user_id=args.user_id)
        reward_grants = await repository.list_referral_reward_grants(referrer_user_id=args.user_id, limit=20)
        total_invited = await repository.count_referrals_for_referrer(referrer_user_id=args.user_id)
        print("")
        print("=== Referral State ===")
        print(f"User: {args.user_id}")
        print(f"Referral code: {referral_code}")
        print(f"Referral link: {referral_link}")
        print(f"Referred by: {user.referred_by_user_id}")
        print(f"Registered referrals: {total_invited}")
        if stats is None:
            print("Active cycle paid referrals: 0")
            print("Lifetime paid referrals: 0")
            print("Current cycle number: 1")
        else:
            print(f"Active cycle paid referrals: {stats.active_cycle_paid_referrals_count}")
            print(f"Lifetime paid referrals: {stats.lifetime_paid_referrals_count}")
            print(f"Current cycle number: {stats.current_cycle_number}")
            print(f"Last reward milestone: {stats.last_reward_milestone_reached}")
        if reward_grants:
            print("Reward grants:")
            for grant in reward_grants:
                print(
                    f"  - milestone={grant.milestone_trigger} days={grant.reward_days} "
                    f"cycle={grant.cycle_number} granted_at={grant.granted_at.isoformat()}"
                )
        else:
            print("Reward grants: none")
        print("")
        return 0
    finally:
        await repository.close()


async def _simulate_referral_signup(args: argparse.Namespace) -> int:
    settings = get_settings()
    await initialize_database(str(settings.sqlite_path))
    repository = Repository(str(settings.sqlite_path))
    await repository.connect()
    telegram_client = _SilentTelegramClient()
    onboarding = OnboardingPaymentService(
        settings,
        repository,
        crypto_pay_service=None,
        premium_telegram_client=telegram_client,
    )
    referral_service = ReferralService(settings, repository, telegram_client=telegram_client)
    try:
        await repository.upsert_private_user(
            telegram_user_id=args.referrer_id,
            username=args.referrer_username,
            first_name="Referrer",
            last_name=None,
            is_admin=settings.is_configured_admin(args.referrer_id, args.referrer_username),
        )
        referral_code = await referral_service.ensure_referral_code(args.referrer_id)
        user = await onboarding.register_contact(
            telegram_user_id=args.referred_user_id,
            username=args.referred_username,
            first_name="Referred",
            last_name=None,
            bot_kind=args.bot_kind,
            start_payload=f"ref_{referral_code}",
        )
        referral = await repository.get_referral(referred_user_id=args.referred_user_id)
        print("")
        print("=== Simulated Referral Signup ===")
        print(f"Referrer ID: {args.referrer_id}")
        print(f"Referred ID: {args.referred_user_id}")
        print(f"Referral code: {referral_code}")
        print(f"Stored referred_by_user_id: {user.referred_by_user_id}")
        print(f"Referral row created: {'yes' if referral is not None else 'no'}")
        print("")
        return 0
    finally:
        await telegram_client.close()
        await repository.close()


async def _simulate_referral_payment(args: argparse.Namespace) -> int:
    settings = get_settings()
    await initialize_database(str(settings.sqlite_path))
    repository = Repository(str(settings.sqlite_path))
    await repository.connect()
    telegram_client = _SilentTelegramClient()
    service = CryptoPayService(
        settings,
        repository,
        client=_SilentCryptoClient(),
        telegram_client=telegram_client,
    )
    try:
        user = await repository.get_private_user(args.referred_user_id)
        if user is None:
            print(f"Referred user {args.referred_user_id} was not found.")
            return 1
        invoice_id = args.invoice_id or int(datetime.now(timezone.utc).timestamp())
        created_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        paid_at = datetime.now(timezone.utc)
        custom_payload = json.dumps(
            {
                "telegram_user_id": args.referred_user_id,
                "bot_kind": args.bot_kind,
                "target_access_level": "pro",
                "duration_days": args.days,
                "purpose": "subscription_purchase",
            },
            ensure_ascii=True,
            separators=(",", ":"),
        )
        await repository.upsert_crypto_pay_invoice(
            invoice_id=invoice_id,
            invoice_hash=f"hash-{invoice_id}",
            telegram_user_id=args.referred_user_id,
            bot_kind=args.bot_kind,
            target_access_level="pro",
            target_duration_days=args.days,
            amount=f"{args.amount:.2f}",
            asset="USDT",
            currency_type="crypto",
            description="Simulated referral payment",
            status="active",
            pay_url=f"https://t.me/invoice/{invoice_id}",
            custom_payload=custom_payload,
            created_at=created_at,
            paid_at=None,
            activated_at=None,
            metadata={"simulated": True},
        )
        payload = {
            "update_type": "invoice_paid",
            "request_date": paid_at.isoformat(),
            "payload": {
                "invoice_id": invoice_id,
                "hash": f"hash-{invoice_id}",
                "status": "paid",
                "payload": custom_payload,
                "amount": f"{args.amount:.2f}",
                "asset": "USDT",
                "currency_type": "crypto",
                "description": "Simulated referral payment",
                "pay_url": f"https://t.me/invoice/{invoice_id}",
                "created_at": created_at.isoformat(),
                "paid_at": paid_at.isoformat(),
            },
        }
        raw_body = json.dumps(payload, sort_keys=True).encode("utf-8")
        result = await service.handle_webhook(payload, raw_body=raw_body)
        referral = await repository.get_referral(referred_user_id=args.referred_user_id)
        stats = None
        if referral is not None:
            stats = await repository.get_referral_cycle_stats(referrer_user_id=referral.referrer_user_id)
        print("")
        print("=== Simulated Referral Payment ===")
        print(f"Referred user: {args.referred_user_id}")
        print(f"Invoice ID: {invoice_id}")
        print(f"Webhook result: {result.status}")
        if referral is not None:
            print(f"Referrer ID: {referral.referrer_user_id}")
            print(f"Counted as paid referral: {referral.counted_as_paid_referral}")
            print(f"Conversion invoice ID: {referral.conversion_invoice_id}")
        if stats is not None:
            print(f"Active cycle paid referrals: {stats.active_cycle_paid_referrals_count}")
            print(f"Lifetime paid referrals: {stats.lifetime_paid_referrals_count}")
            print(f"Current cycle number: {stats.current_cycle_number}")
        print("")
        return 0
    finally:
        await service.close()
        await telegram_client.close()
        await repository.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.payments.devtools",
        description="Local Crypto Pay developer helpers.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_invoice = subparsers.add_parser(
        "create-invoice",
        help="Create a Crypto Pay test invoice tied to a Telegram user ID.",
    )
    create_invoice.add_argument("--user-id", type=int, required=True, help="Telegram user ID to activate after payment.")
    create_invoice.add_argument("--bot-kind", choices=("premium", "classic"), default="premium")
    create_invoice.add_argument("--access-level", default="pro")
    create_invoice.add_argument("--days", type=int, default=get_settings().crypto_pay_subscription_days)
    create_invoice.add_argument("--amount", type=float, default=get_settings().crypto_pay_invoice_amount_usd)
    create_invoice.add_argument("--description", default=None)

    show_onboarding = subparsers.add_parser(
        "show-onboarding",
        help="Show persisted onboarding/payment state for one Telegram user.",
    )
    show_onboarding.add_argument("--user-id", type=int, required=True)
    show_onboarding.add_argument("--bot-kind", choices=("premium", "classic"), default="premium")

    force_offer = subparsers.add_parser(
        "force-onboarding-offer",
        help="Force the 48h onboarding campaign due now and run the invoice/send flow once.",
    )
    force_offer.add_argument("--user-id", type=int, required=True)
    force_offer.add_argument("--bot-kind", choices=("premium", "classic"), default="premium")

    subparsers.add_parser(
        "run-onboarding-check",
        help="Run one onboarding due-campaign processing pass immediately.",
    )

    show_referral = subparsers.add_parser(
        "show-referral",
        help="Show referral code, attribution, cycle stats, and reward history for one user.",
    )
    show_referral.add_argument("--user-id", type=int, required=True)

    simulate_signup = subparsers.add_parser(
        "simulate-referral-signup",
        help="Create a deep-link-style referral attribution for a referred user.",
    )
    simulate_signup.add_argument("--referrer-id", type=int, required=True)
    simulate_signup.add_argument("--referred-user-id", type=int, required=True)
    simulate_signup.add_argument("--bot-kind", choices=("premium", "classic"), default="premium")
    simulate_signup.add_argument("--referrer-username", default=None)
    simulate_signup.add_argument("--referred-username", default=None)

    simulate_payment = subparsers.add_parser(
        "simulate-referral-payment",
        help="Seed a local invoice and process a paid webhook for a referred user.",
    )
    simulate_payment.add_argument("--referred-user-id", type=int, required=True)
    simulate_payment.add_argument("--invoice-id", type=int, default=None)
    simulate_payment.add_argument("--bot-kind", choices=("premium", "classic"), default="premium")
    simulate_payment.add_argument("--days", type=int, default=get_settings().crypto_pay_subscription_days)
    simulate_payment.add_argument("--amount", type=float, default=get_settings().crypto_pay_invoice_amount_usd)

    return parser


async def _run(args: argparse.Namespace) -> int:
    if args.command == "create-invoice":
        return await _create_invoice(args)
    if args.command == "show-onboarding":
        return await _show_onboarding(args)
    if args.command == "force-onboarding-offer":
        return await _force_onboarding_offer(args)
    if args.command == "run-onboarding-check":
        return await _run_onboarding_check(args)
    if args.command == "show-referral":
        return await _show_referral(args)
    if args.command == "simulate-referral-signup":
        return await _simulate_referral_signup(args)
    if args.command == "simulate-referral-payment":
        return await _simulate_referral_payment(args)
    print(f"Unsupported command: {args.command}")
    return 1


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
