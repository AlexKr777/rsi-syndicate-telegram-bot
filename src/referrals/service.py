from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import quote

from src.bot.telegram_client import TelegramClient
from src.core.config import Settings
from src.core.utils import escape_html
from src.localization import normalize_language
from src.storage.models import PrivateBotUserRecord
from src.storage.repository import Repository

LOGGER = logging.getLogger(__name__)

_PAYLOAD_PREFIXES = ("ref_", "invite_", "r_", "ref-", "invite-", "r-")


def _base36(value: int) -> str:
    number = max(int(value), 0)
    if number == 0:
        return "0"
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    digits: list[str] = []
    while number:
        number, remainder = divmod(number, 36)
        digits.append(alphabet[remainder])
    return "".join(reversed(digits))


@dataclass(frozen=True, slots=True)
class ReferralDashboard:
    referrer_user_id: int
    referral_code: str
    referral_link: str
    share_url: str
    active_cycle_paid_referrals_count: int
    lifetime_paid_referrals_count: int
    registered_referrals_count: int
    total_reward_days: int
    progress_bar: str
    next_milestone: int | None
    next_milestone_reward_days: int | None
    remaining_to_next_milestone: int
    cycle_target: int


@dataclass(frozen=True, slots=True)
class ReferralConversionOutcome:
    status: str
    counted: bool
    referrer_user_id: int | None = None
    referred_user_id: int | None = None
    cycle_progress_before_reset: int = 0
    cycle_progress_after: int = 0
    lifetime_paid_referrals_count: int = 0
    milestone_trigger: int | None = None
    reward_days_granted: int = 0
    reward_granted: bool = False
    cycle_reset: bool = False
    access_extension_from: datetime | None = None
    access_extension_to: datetime | None = None
    referrer_is_admin: bool = False


class ReferralService:
    def __init__(
        self,
        settings: Settings,
        repository: Repository,
        *,
        telegram_client: TelegramClient | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.telegram_client = telegram_client
        self._bot_base_link_cache: str | None = None

    async def ensure_referral_code(self, telegram_user_id: int) -> str:
        user = await self.repository.get_private_user(telegram_user_id)
        if user is None:
            raise RuntimeError(f"Referral code requested for missing user {telegram_user_id}")
        if user.referral_code:
            return user.referral_code
        referral_code = self._build_referral_code(telegram_user_id)
        existing = await self.repository.get_private_user_by_referral_code(referral_code)
        if existing is not None and existing.telegram_user_id != telegram_user_id:
            referral_code = f"{referral_code}{hashlib.sha1(str(telegram_user_id).encode('utf-8')).hexdigest()[:4]}"
        await self.repository.set_private_user_referral_code(
            telegram_user_id=telegram_user_id,
            referral_code=referral_code,
        )
        return referral_code

    async def resolve_referrer_user_id(
        self,
        *,
        joining_user_id: int,
        payload: str | None,
        existing_user: PrivateBotUserRecord | None = None,
    ) -> int | None:
        if existing_user is not None:
            return None
        raw_payload = str(payload or "").strip()
        if not raw_payload:
            return None
        candidates = [raw_payload]
        lowered = raw_payload.casefold()
        for prefix in _PAYLOAD_PREFIXES:
            if lowered.startswith(prefix):
                candidates.append(raw_payload[len(prefix) :].strip())
        for candidate in candidates:
            normalized = str(candidate or "").strip()
            if not normalized:
                continue
            if normalized.isdigit():
                referrer_user_id = int(normalized)
                if referrer_user_id > 0 and referrer_user_id != joining_user_id:
                    referrer_user = await self.repository.get_private_user(referrer_user_id)
                    if referrer_user is not None:
                        return referrer_user_id
                continue
            cleaned = re.sub(r"[^A-Za-z0-9]", "", normalized)
            if not cleaned:
                continue
            referrer_user = await self.repository.get_private_user_by_referral_code(cleaned)
            if referrer_user is None:
                continue
            if referrer_user.telegram_user_id == joining_user_id:
                return None
            return referrer_user.telegram_user_id
        return None

    async def get_dashboard(self, telegram_user_id: int) -> ReferralDashboard:
        referral_code = await self.ensure_referral_code(telegram_user_id)
        referral_link = await self.build_referral_link(referral_code)
        share_url = self._build_share_url(referral_link)
        stats = await self.repository.get_referral_cycle_stats(referrer_user_id=telegram_user_id)
        reward_grants = await self.repository.list_referral_reward_grants(referrer_user_id=telegram_user_id, limit=100)
        registered_referrals_count = await self.repository.count_referrals_for_referrer(referrer_user_id=telegram_user_id)
        milestones = self.settings.referral_reward_milestones
        cycle_target = milestones[-1][0]
        current_cycle_count = stats.active_cycle_paid_referrals_count if stats is not None else 0
        lifetime_paid_referrals_count = stats.lifetime_paid_referrals_count if stats is not None else 0
        next_milestone: int | None = None
        next_milestone_reward_days: int | None = None
        for milestone_count, reward_days in milestones:
            if current_cycle_count < milestone_count:
                next_milestone = milestone_count
                next_milestone_reward_days = reward_days
                break
        remaining_to_next = max((next_milestone or cycle_target) - current_cycle_count, 0)
        total_reward_days = sum(max(item.reward_days, 0) for item in reward_grants)
        return ReferralDashboard(
            referrer_user_id=telegram_user_id,
            referral_code=referral_code,
            referral_link=referral_link,
            share_url=share_url,
            active_cycle_paid_referrals_count=current_cycle_count,
            lifetime_paid_referrals_count=lifetime_paid_referrals_count,
            registered_referrals_count=registered_referrals_count,
            total_reward_days=total_reward_days,
            progress_bar=self._progress_bar(current_cycle_count, cycle_target),
            next_milestone=next_milestone,
            next_milestone_reward_days=next_milestone_reward_days,
            remaining_to_next_milestone=remaining_to_next,
            cycle_target=cycle_target,
        )

    async def process_paid_conversion(
        self,
        *,
        referred_user_id: int,
        invoice_id: int,
        converted_at: datetime,
    ) -> ReferralConversionOutcome:
        reward_days_by_milestone = {
            milestone_count: reward_days
            for milestone_count, reward_days in self.settings.referral_reward_milestones
        }
        raw_outcome = await self.repository.process_paid_referral_conversion(
            referred_user_id=referred_user_id,
            invoice_id=invoice_id,
            converted_at=converted_at,
            reward_days_by_milestone=reward_days_by_milestone,
        )
        outcome = ReferralConversionOutcome(
            status=str(raw_outcome.get("status") or "unknown"),
            counted=bool(raw_outcome.get("counted")),
            referrer_user_id=raw_outcome.get("referrer_user_id"),
            referred_user_id=raw_outcome.get("referred_user_id"),
            cycle_progress_before_reset=int(raw_outcome.get("cycle_progress_before_reset") or 0),
            cycle_progress_after=int(raw_outcome.get("cycle_progress_after") or 0),
            lifetime_paid_referrals_count=int(raw_outcome.get("lifetime_paid_referrals_count") or 0),
            milestone_trigger=raw_outcome.get("milestone_trigger"),
            reward_days_granted=int(raw_outcome.get("reward_days_granted") or 0),
            reward_granted=bool(raw_outcome.get("reward_granted")),
            cycle_reset=bool(raw_outcome.get("cycle_reset")),
            access_extension_from=raw_outcome.get("access_extension_from"),
            access_extension_to=raw_outcome.get("access_extension_to"),
            referrer_is_admin=bool(raw_outcome.get("referrer_is_admin")),
        )
        if outcome.counted and outcome.referrer_user_id is not None:
            await self._notify_referrer(outcome)
        return outcome

    async def build_referral_link(self, referral_code: str) -> str:
        base_link = await self._resolve_bot_base_link()
        payload = f"ref_{referral_code}"
        return f"{base_link}?start={quote(payload, safe='')}"

    def format_referral_message(self, dashboard: ReferralDashboard, *, language_code: str) -> str:
        language = normalize_language(language_code)
        is_ru = language == "ru"
        current_cycle_count = dashboard.active_cycle_paid_referrals_count
        milestones = tuple(self.settings.referral_reward_milestones)
        next_reward_days = dashboard.next_milestone_reward_days or 0
        bullet = "\u2022"
        track_joiner = " \u2500\u2500 "

        if is_ru:
            title = "<b>\U0001F91D Referral</b>"
            intro_lines = [
                "\u041f\u0440\u0438\u0433\u043b\u0430\u0441\u0438\u0442\u0435\u043b\u044c\u043d\u044b\u0439 \u0446\u0435\u043d\u0442\u0440 \u0441 \u0447\u0438\u0441\u0442\u044b\u043c \u043f\u0440\u043e\u0433\u0440\u0435\u0441\u0441\u043e\u043c \u0438 \u0431\u043e\u043d\u0443\u0441\u043d\u044b\u043c\u0438 \u044d\u0442\u0430\u043f\u0430\u043c\u0438.",
                "\u0412 \u0437\u0430\u0447\u0451\u0442 \u0438\u0434\u0451\u0442 \u0442\u043e\u043b\u044c\u043a\u043e \u043f\u0435\u0440\u0432\u0430\u044f \u0443\u0441\u043f\u0435\u0448\u043d\u0430\u044f \u043e\u043f\u043b\u0430\u0442\u0430 PRO+ \u043f\u043e \u0442\u0432\u043e\u0435\u0439 \u0441\u0441\u044b\u043b\u043a\u0435.",
            ]
            progress_title = "<b>\U0001F4C8 \u041f\u0440\u043e\u0433\u0440\u0435\u0441\u0441 \u0446\u0438\u043a\u043b\u0430</b>"
            stages_title = "<b>\U0001F381 \u042d\u0442\u0430\u043f\u044b \u043d\u0430\u0433\u0440\u0430\u0434</b>"
            summary_title = "<b>\U0001F4CA \u0421\u0432\u043e\u0434\u043a\u0430</b>"
            tools_title = "<b>\U0001F517 \u0418\u043d\u0441\u0442\u0440\u0443\u043c\u0435\u043d\u0442\u044b \u043f\u0440\u0438\u0433\u043b\u0430\u0448\u0435\u043d\u0438\u044f</b>"
        else:
            title = "<b>\U0001F91D Referral</b>"
            intro_lines = [
                "Your private invite desk with clean progress tracking and bonus stages.",
                "Only the first successful PRO+ payment from each invited user counts toward rewards.",
            ]
            progress_title = "<b>\U0001F4C8 Cycle Progress</b>"
            stages_title = "<b>\U0001F381 Reward Stages</b>"
            summary_title = "<b>\U0001F4CA Summary</b>"
            tools_title = "<b>\U0001F517 Invite Tools</b>"

        stage_lines: list[str] = []
        stage_markers: list[str] = []
        for index, (milestone_count, reward_days) in enumerate(milestones, start=1):
            is_complete = current_cycle_count >= milestone_count
            is_next = dashboard.next_milestone == milestone_count
            marker = "\u2713" if is_complete else "\u25CE" if is_next else "\u25CB"
            stage_markers.append(marker)
            if is_ru:
                state_label = (
                    "\u043e\u0442\u043a\u0440\u044b\u0442"
                    if is_complete
                    else "\u0441\u043b\u0435\u0434\u0443\u044e\u0449\u0438\u0439"
                    if is_next
                    else "\u043f\u043e\u0437\u0436\u0435"
                )
                stage_lines.append(
                    f"{marker} <b>\u042d\u0442\u0430\u043f {index}</b> {bullet} {milestone_count} "
                    f"\u043e\u043f\u043b\u0430\u0447\u0435\u043d\u043d\u044b\u0445 \u043f\u0440\u0438\u0433\u043b\u0430\u0448\u0435\u043d\u0438\u0439 "
                    f"{bullet} <b>+{reward_days} \u0434\u043d\u0435\u0439 PRO+</b> {bullet} {state_label}"
                )
            else:
                state_label = "unlocked" if is_complete else "next" if is_next else "later"
                stage_lines.append(
                    f"{marker} <b>Stage {index}</b> {bullet} {milestone_count} paid referrals "
                    f"{bullet} <b>+{reward_days} PRO+ days</b> {bullet} {state_label}"
                )

        if dashboard.next_milestone is None:
            next_block = (
                "\u0422\u0435\u043a\u0443\u0449\u0438\u0439 \u0446\u0438\u043a\u043b \u0437\u0430\u043a\u0440\u044b\u0442. \u0421\u043b\u0435\u0434\u0443\u044e\u0449\u0438\u0439 \u0431\u043e\u043d\u0443\u0441\u043d\u044b\u0439 \u043a\u0440\u0443\u0433 \u0443\u0436\u0435 \u043e\u0442\u043a\u0440\u044b\u0442."
                if is_ru
                else "This cycle is complete. The next reward track is already open."
            )
        else:
            if is_ru:
                next_block = (
                    f"\u0414\u043e \u0441\u043b\u0435\u0434\u0443\u044e\u0449\u0435\u0439 \u043d\u0430\u0433\u0440\u0430\u0434\u044b: "
                    f"<b>{dashboard.remaining_to_next_milestone}</b> \u043e\u043f\u043b\u0430\u0447\u0435\u043d\u043d\u044b\u0445 "
                    f"\u043f\u0440\u0438\u0433\u043b\u0430\u0448\u0435\u043d\u0438\u0439 {bullet} <b>+{next_reward_days} \u0434\u043d\u0435\u0439 PRO+</b>"
                )
            else:
                plural = "" if dashboard.remaining_to_next_milestone == 1 else "s"
                verb_suffix = "s" if dashboard.remaining_to_next_milestone == 1 else ""
                next_block = (
                    f"{dashboard.remaining_to_next_milestone} more paid referral{plural} unlock{verb_suffix} "
                    f"<b>+{next_reward_days} PRO+ days</b>."
                )

        summary_lines = [
            (
                f"{bullet} \u0412 \u044d\u0442\u043e\u043c \u0446\u0438\u043a\u043b\u0435: <b>{current_cycle_count}</b>"
                if is_ru
                else f"{bullet} Counted in this cycle: <b>{current_cycle_count}</b>"
            ),
            (
                f"{bullet} \u0412\u0441\u0435\u0433\u043e \u043e\u043f\u043b\u0430\u0442 \u043f\u043e \u0441\u0441\u044b\u043b\u043a\u0435: <b>{dashboard.lifetime_paid_referrals_count}</b>"
                if is_ru
                else f"{bullet} Lifetime paid referrals: <b>{dashboard.lifetime_paid_referrals_count}</b>"
            ),
            (
                f"{bullet} \u0412\u0441\u0435\u0433\u043e \u0440\u0435\u0433\u0438\u0441\u0442\u0440\u0430\u0446\u0438\u0439: <b>{dashboard.registered_referrals_count}</b>"
                if is_ru
                else f"{bullet} Registered invites: <b>{dashboard.registered_referrals_count}</b>"
            ),
            (
                f"{bullet} \u041d\u0430\u0447\u0438\u0441\u043b\u0435\u043d\u043e \u0431\u043e\u043d\u0443\u0441-\u0434\u043d\u0435\u0439: <b>{dashboard.total_reward_days}</b>"
                if is_ru
                else f"{bullet} Bonus days granted: <b>{dashboard.total_reward_days}</b>"
            ),
        ]
        tools_lines = [
            (
                f"{bullet} \u041a\u043e\u0434: <code>{escape_html(dashboard.referral_code)}</code>"
                if is_ru
                else f"{bullet} Code: <code>{escape_html(dashboard.referral_code)}</code>"
            ),
            (
                f"{bullet} \u0421\u0441\u044b\u043b\u043a\u0430 \u0441\u043f\u0440\u044f\u0442\u0430\u043d\u0430 \u0432 \u043a\u043d\u043e\u043f\u043a\u0430\u0445 \u043d\u0438\u0436\u0435: \u043e\u0442\u043a\u0440\u044b\u0442\u044c, \u0441\u043a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u0442\u044c \u0438\u043b\u0438 \u043f\u043e\u0434\u0435\u043b\u0438\u0442\u044c\u0441\u044f."
                if is_ru
                else f"{bullet} Your invite link stays in the buttons below for a cleaner screen: open it, copy it, or share it."
            ),
            (
                "\u0411\u043e\u043d\u0443\u0441\u043d\u044b\u0435 \u0434\u043d\u0438 \u043f\u0440\u043e\u0441\u0442\u043e \u0434\u043e\u0431\u0430\u0432\u043b\u044f\u044e\u0442\u0441\u044f \u043a \u0430\u043a\u0442\u0438\u0432\u043d\u043e\u043c\u0443 PRO+."
                if is_ru
                else "Bonus days extend your active premium access instead of replacing it."
            ),
        ]
        targets_line = (
            f"{bullet} \u0426\u0435\u043b\u0438: <b>{' / '.join(str(count) for count, _ in milestones)}</b>"
            if is_ru
            else f"{bullet} Targets: <b>{' / '.join(str(count) for count, _ in milestones)}</b>"
        )
        return "\n".join(
            [
                title,
                "",
                *intro_lines,
                "",
                progress_title,
                dashboard.progress_bar,
                (
                    f"<b>{current_cycle_count}/{dashboard.cycle_target}</b> \u043e\u043f\u043b\u0430\u0447\u0435\u043d\u043d\u044b\u0445 \u043f\u0440\u0438\u0433\u043b\u0430\u0448\u0435\u043d\u0438\u0439 \u0432 \u044d\u0442\u043e\u043c \u0446\u0438\u043a\u043b\u0435"
                    if is_ru
                    else f"<b>{current_cycle_count}/{dashboard.cycle_target}</b> paid referrals in this cycle"
                ),
                track_joiner.join(stage_markers),
                targets_line,
                next_block,
                "",
                stages_title,
                *stage_lines,
                "",
                summary_title,
                *summary_lines,
                "",
                tools_title,
                *tools_lines,
            ]
        )

    def _build_referral_code(self, telegram_user_id: int) -> str:
        encoded = _base36(telegram_user_id)
        checksum = hashlib.sha1(f"syndicate-ref:{telegram_user_id}".encode("utf-8")).hexdigest()[:6]
        return f"r{encoded}{checksum}"

    async def _resolve_bot_base_link(self) -> str:
        if self._bot_base_link_cache:
            return self._bot_base_link_cache
        explicit = str(self.settings.resolved_private_bot_share_link or "").strip()
        if explicit:
            match = re.search(r"t\.me/([A-Za-z0-9_]+)", explicit)
            if match:
                self._bot_base_link_cache = f"https://t.me/{match.group(1)}"
                return self._bot_base_link_cache
            if explicit.startswith("@"):
                self._bot_base_link_cache = f"https://t.me/{explicit.lstrip('@')}"
                return self._bot_base_link_cache
        if self.telegram_client is not None:
            identity = await self.telegram_client.get_me()
            username = str(identity.get("username") or "").strip().lstrip("@")
            if username:
                self._bot_base_link_cache = f"https://t.me/{username}"
                return self._bot_base_link_cache
        raise RuntimeError("Unable to resolve premium bot username for referral links")

    def _build_share_url(self, referral_link: str) -> str:
        share_text = "Syndicate PRO+: fewer weak setups, cleaner filters, and deeper Telegram-native workflow."
        return (
            "https://t.me/share/url"
            f"?url={quote(referral_link, safe='')}"
            f"&text={quote(share_text, safe='')}"
        )

    def _progress_bar(self, current: int, total: int) -> str:
        normalized_total = max(int(total), 1)
        bounded_current = max(0, min(int(current), normalized_total))
        width = 10
        filled = min(width, round(width * bounded_current / normalized_total))
        return ("\u25B0" * filled) + ("\u25B1" * (width - filled))

    async def _notify_referrer(self, outcome: ReferralConversionOutcome) -> None:
        if self.telegram_client is None or outcome.referrer_user_id is None:
            return
        referrer_settings = await self.repository.get_user_settings(outcome.referrer_user_id, bot_kind="premium")
        language = normalize_language(referrer_settings.language_code if referrer_settings is not None else "en")
        referred_user = await self.repository.get_private_user(outcome.referred_user_id or 0)
        referred_label = self._referred_label(referred_user)
        cycle_target = self.settings.referral_reward_milestones[-1][0]
        if language == "ru":
            progress_text = (
                "<b>🤝 Referral обновлён</b>\n\n"
                f"<b>{escape_html(referred_label)}</b> оформил PRO+ по твоей ссылке.\n\n"
                f"📈 Прогресс цикла: <b>{outcome.cycle_progress_before_reset}/{cycle_target}</b>\n"
                f"• Всего оплат по ссылке: <b>{outcome.lifetime_paid_referrals_count}</b>"
            )
            if outcome.cycle_reset:
                progress_text += "\n• Цикл закрыт и новый круг уже начался."
        else:
            progress_text = (
                "<b>🤝 Referral updated</b>\n\n"
                f"<b>{escape_html(referred_label)}</b> activated PRO+ from your link.\n\n"
                f"📈 Cycle progress: <b>{outcome.cycle_progress_before_reset}/{cycle_target}</b>\n"
                f"• Lifetime paid referrals: <b>{outcome.lifetime_paid_referrals_count}</b>"
            )
            if outcome.cycle_reset:
                progress_text += "\n• This completed the cycle and the next round already started."
        await self._send_notice(outcome.referrer_user_id, progress_text)

        if not outcome.reward_granted or outcome.reward_days_granted <= 0:
            return
        if language == "ru":
            if outcome.referrer_is_admin:
                reward_text = (
                    "<b>🎁 Referral bonus зафиксирован</b>\n\n"
                    f"Достигнут этап <b>{outcome.milestone_trigger}</b>.\n"
                    f"Бонус <b>+{outcome.reward_days_granted} дней PRO+</b> записан в историю.\n"
                    "Админ-доступ остаётся без изменений."
                )
            else:
                reward_text = (
                    "<b>🎁 Referral bonus выдан</b>\n\n"
                    f"Достигнут этап <b>{outcome.milestone_trigger}</b>.\n"
                    f"Добавлено: <b>+{outcome.reward_days_granted} дней PRO+</b>\n"
                    f"Продление от: <b>{self._format_dt(outcome.access_extension_from)}</b>\n"
                    f"Активно до: <b>{self._format_dt(outcome.access_extension_to)}</b>"
                )
        else:
            if outcome.referrer_is_admin:
                reward_text = (
                    "<b>🎁 Referral bonus recorded</b>\n\n"
                    f"You reached stage <b>{outcome.milestone_trigger}</b>.\n"
                    f"Bonus: <b>+{outcome.reward_days_granted} PRO+ days</b> was recorded in history.\n"
                    "Admin access stays unchanged."
                )
            else:
                reward_text = (
                    "<b>🎁 Referral bonus granted</b>\n\n"
                    f"You reached stage <b>{outcome.milestone_trigger}</b>.\n"
                    f"Added: <b>+{outcome.reward_days_granted} PRO+ days</b>\n"
                    f"Extension from: <b>{self._format_dt(outcome.access_extension_from)}</b>\n"
                    f"Active until: <b>{self._format_dt(outcome.access_extension_to)}</b>"
                )
        await self._send_notice(outcome.referrer_user_id, reward_text)

    async def _send_notice(self, telegram_user_id: int, text: str) -> None:
        if self.telegram_client is None:
            return
        try:
            await self.telegram_client.send_message(
                chat_id=str(telegram_user_id),
                text=text,
                parse_mode="HTML",
            )
        except Exception as exc:
            LOGGER.warning(
                "Referral notification failed user=%s error=%s",
                telegram_user_id,
                exc,
            )

    def _referred_label(self, user: PrivateBotUserRecord | None) -> str:
        if user is None:
            return "New user"
        if user.username:
            return f"@{user.username.lstrip('@')}"
        if user.first_name:
            return user.first_name
        return f"User {user.telegram_user_id}"

    def _format_dt(self, value: datetime | None) -> str:
        if value is None:
            return "-"
        return value.astimezone(self.settings.timezone).strftime("%Y-%m-%d %H:%M %Z")
