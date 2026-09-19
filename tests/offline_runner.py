from __future__ import annotations

import os
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


TESTS_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.config import get_settings


OFFLINE_TEST_ENV = {
    "TELEGRAM_BOT_TOKEN": "000000000:TEST_ONLY_OFFLINE_TOKEN_DO_NOT_USE",
    "TELEGRAM_CLASSIC_BOT_TOKEN": "",
    "PUBLIC_CHANNEL": "@offline_public",
    "PRO_CHANNEL": "@offline_pro",
    "LAB_CHANNEL": "@offline_lab",
    "COMMUNITY_CHAT": "-1000000000001",
    "RESULTS_CHANNEL": "@offline_results",
    "TWITTER_DRAFTS_CHAT": "-1000000000002",
    "COMMUNITY_LINK": "",
    "CHANNELS_FOLDER_LINK": "",
    "PRIVATE_BOT_SHARE_LINK": "",
    "CLASSIC_BOT_SHARE_LINK": "",
    "CLASSIC_BOT_USERNAME": "@offline_classic_bot",
    "ADMIN_TELEGRAM_USER_IDS": "",
    "ADMIN_TELEGRAM_USERNAMES": "",
    "PUBLIC_DELAY_PREMIUM_BOT_LINK": "",
    "PRIVATE_BOT_RESULTS_MIRROR_ADMIN_USERNAME": "",
    "PRIVATE_BOT_RESULTS_MIRROR_CHANNEL": "",
    "CRYPTO_PAY_API_TOKEN": "",
    "NGROK_AUTHTOKEN": "",
}


@contextmanager
def offline_test_environment() -> Iterator[None]:
    """Force credential-free settings for tests, then restore the caller's environment."""
    previous = {name: os.environ.get(name) for name in OFFLINE_TEST_ENV}
    os.environ.update(OFFLINE_TEST_ENV)
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def main() -> int:
    with offline_test_environment():
        suite = unittest.defaultTestLoader.discover(
            start_dir=str(TESTS_ROOT),
            pattern="test_*.py",
            top_level_dir=str(TESTS_ROOT),
        )
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
