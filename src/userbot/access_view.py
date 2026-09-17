from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.localization import normalize_language


@dataclass(frozen=True, slots=True)
class AccessViewModel:
    title: str
    status: str
    ends_at: datetime | None
    features: tuple[str, ...]
    profile_label: str
    delivery_label: str
    is_admin: bool = False

    def render(self, *, language_code: str) -> str:
        ru = normalize_language(language_code) == "ru"
        if self.is_admin:
            if ru:
                return (
                    "🛡 <b>Панель администратора</b>\n\n"
                    "Полный доступ к продукту и инструментам контроля.\n\n"
                    "<b>Продукт</b>\n"
                    "• Все стратегии и персональные настройки\n"
                    "• AI-разбор и Gold Desk\n\n"
                    "<b>Контроль</b>\n"
                    "• Результаты и статистика\n"
                    "• Диагностика системы\n\n"
                    "<b>Режим уведомлений</b>\n"
                    f"{self.delivery_label}"
                )
            return (
                "🛡 <b>Administrator panel</b>\n\n"
                "Full access to the product and operational controls.\n\n"
                "<b>Product</b>\n"
                "• All strategies and personal settings\n"
                "• AI analysis and Gold Desk\n\n"
                "<b>Control</b>\n"
                "• Results and statistics\n"
                "• System diagnostics\n\n"
                "<b>Notification mode</b>\n"
                f"{self.delivery_label}"
            )
        expiry = (
            (self.ends_at.strftime("%d.%m.%Y %H:%M") if ru else self.ends_at.strftime("%b %d, %Y %H:%M"))
            if self.ends_at is not None
            else ("без ограничений" if ru else "no expiry")
        )
        features = "\n".join(f"• {item}" for item in self.features)
        profile = "Активный профиль" if ru else "Active profile"
        delivery = "Уведомления" if ru else "Notifications"
        expiry_label = "Действует до" if ru else "Valid until"
        return (
            f"<b>{self.title}</b>\n\n{self.status}\n{expiry_label}: <b>{expiry}</b>\n\n"
            f"{'Доступно сейчас' if ru else 'Available now'}:\n{features}\n\n"
            f"{profile}: <b>{self.profile_label}</b>\n{delivery}: <b>{self.delivery_label}</b>"
        )


def build_access_view_model(*, access_state, is_gold_enabled: bool, profile_label: str, delivery_label: str, language_code: str) -> AccessViewModel:
    ru = normalize_language(language_code) == "ru"
    if access_state.is_admin:
        return AccessViewModel(
            "🛡 Доступ администратора" if ru else "🛡 Administrator access",
            "🟢 Полный доступ" if ru else "🟢 Full access",
            None,
            ("📈 Все стратегии", "🤖 AI-анализ", "🥇 Gold Desk", "📊 Админ-статистика", "🩺 Диагностика системы") if ru else ("📈 All strategies", "🤖 AI analysis", "🥇 Gold Desk", "📊 Admin statistics", "🩺 System diagnostics"),
            profile_label,
            delivery_label,
            is_admin=True,
        )
    if access_state.access_status == "trial":
        return AccessViewModel(
            "💎 Пробный PRO+ доступ" if ru else "💎 PRO+ trial access",
            "🟡 Trial активен" if ru else "🟡 Trial active",
            access_state.ends_at,
            ("📈 Premium-стратегии", "🤖 AI-анализ", "📊 Результаты", "🔔 Персональные настройки") if ru else ("📈 Premium strategies", "🤖 AI analysis", "📊 Results", "🔔 Personal settings"),
            profile_label,
            delivery_label,
        )
    if access_state.has_premium_access:
        gold = "🥇 Gold Desk: доступен" if is_gold_enabled and ru else "🥇 Gold Desk: недоступен" if ru else "🥇 Gold Desk: available" if is_gold_enabled else "🥇 Gold Desk: unavailable"
        return AccessViewModel(
            "💎 Мой доступ" if ru else "💎 My access",
            "🟢 PRO+ активен" if ru else "🟢 PRO+ active",
            access_state.ends_at,
            ("📈 Все Premium-стратегии", "🔔 Персональные уведомления", "🧩 Профили сигналов", "🤖 AI-анализ", "📊 Расширенные результаты", gold) if ru else ("📈 All Premium strategies", "🔔 Personal notifications", "🧩 Signal profiles", "🤖 AI analysis", "📊 Extended results", gold),
            profile_label,
            delivery_label,
        )
    return AccessViewModel(
        "💎 Мой доступ" if ru else "💎 My access",
        "⚪ Доступ не активен" if access_state.access_status == "expired" and ru else "⚪ Access expired" if access_state.access_status == "expired" else "⚪ Classic / free",
        access_state.ends_at,
        ("📈 Базовые сигналы", "👀 Избранное", "💳 Возможность открыть PRO+") if ru else ("📈 Base signals", "👀 Watchlist", "💳 Upgrade path to PRO+"),
        profile_label,
        delivery_label,
    )
