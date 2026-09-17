from __future__ import annotations

import unittest
from types import SimpleNamespace

from src.core.config import get_settings
from src.payments.onboarding import OnboardingPaymentService


class AdminUsernameConfigTests(unittest.TestCase):
    def test_settings_accept_admin_usernames_with_optional_at_prefix(self) -> None:
        settings = get_settings().model_copy(deep=True)
        settings.admin_telegram_user_ids_raw = ""
        settings.admin_telegram_usernames_raw = " sskyv123 , @OWEDFRIK "

        self.assertEqual(settings.admin_telegram_usernames, ("sskyv123", "owedfrik"))
        self.assertTrue(settings.is_configured_admin(username="@sskyv123"))
        self.assertTrue(settings.is_configured_admin(username="OWEDFRIK"))
        self.assertFalse(settings.is_configured_admin(username="missing"))

    def test_onboarding_service_recognizes_configured_admin_username(self) -> None:
        settings = get_settings().model_copy(deep=True)
        settings.admin_telegram_user_ids_raw = ""
        settings.admin_telegram_usernames_raw = "sskyv123"
        onboarding = OnboardingPaymentService(
            settings=settings,
            repository=SimpleNamespace(),
            crypto_pay_service=None,
            premium_telegram_client=SimpleNamespace(),
        )

        self.assertTrue(onboarding.is_admin_user(123456789, "sskyv123"))
        self.assertTrue(onboarding.is_admin_user(123456789, "@sskyv123"))
        self.assertFalse(onboarding.is_admin_user(123456789, "other"))


if __name__ == "__main__":
    unittest.main()
