import os
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from offline_runner import OFFLINE_TEST_ENV, offline_test_environment
from src.core.config import Settings, get_settings


REQUIRED_SETTINGS = {
    "TELEGRAM_BOT_TOKEN",
    "PUBLIC_CHANNEL",
    "PRO_CHANNEL",
    "LAB_CHANNEL",
    "COMMUNITY_CHAT",
    "RESULTS_CHANNEL",
    "TWITTER_DRAFTS_CHAT",
}


class OfflineRunnerTests(unittest.TestCase):
    def tearDown(self):
        get_settings.cache_clear()

    def test_offline_environment_overrides_and_restores_existing_configuration(self):
        existing = {
            "TELEGRAM_BOT_TOKEN": "existing-value-must-not-survive",
            "TELEGRAM_CLASSIC_BOT_TOKEN": "existing-classic-token-must-not-survive",
            "CRYPTO_PAY_API_TOKEN": "existing-payment-token-must-not-survive",
            "NGROK_AUTHTOKEN": "existing-tunnel-token-must-not-survive",
        }
        with patch.dict(os.environ, existing, clear=True):
            with offline_test_environment():
                self.assertTrue(REQUIRED_SETTINGS.issubset(OFFLINE_TEST_ENV))
                self.assertEqual(
                    os.environ["TELEGRAM_BOT_TOKEN"],
                    "000000000:TEST_ONLY_OFFLINE_TOKEN_DO_NOT_USE",
                )
                self.assertNotEqual(
                    os.environ["TELEGRAM_BOT_TOKEN"],
                    existing["TELEGRAM_BOT_TOKEN"],
                )
                self.assertEqual(os.environ["TELEGRAM_CLASSIC_BOT_TOKEN"], "")
                self.assertEqual(os.environ["CRYPTO_PAY_API_TOKEN"], "")
                self.assertEqual(os.environ["NGROK_AUTHTOKEN"], "")
            self.assertEqual(os.environ, existing)

    def test_production_settings_still_require_telegram_configuration(self):
        with patch.dict(os.environ, {}, clear=True):
            get_settings.cache_clear()
            with self.assertRaises(ValidationError) as raised:
                Settings(_env_file=None)

        missing_fields = {error["loc"][0] for error in raised.exception.errors()}
        self.assertEqual(missing_fields, REQUIRED_SETTINGS)


if __name__ == "__main__":
    unittest.main()
