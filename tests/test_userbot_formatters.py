from __future__ import annotations

import unittest

from src.userbot.product import MessageRenderService
from src.userbot.formatters import (
    format_access_message,
    format_classic_first_start_message,
    format_classic_start_message,
    format_classic_vs_pro_message,
    format_example_signal_message,
    format_first_start_message,
    format_help_page_message,
    format_signal_reading_guide_message,
    format_start_message,
)


class UserbotFormatterTests(unittest.TestCase):
    def test_first_start_message_focuses_on_product_trial_and_risk(self) -> None:
        text = format_first_start_message(
            channels_folder_link="https://t.me/addlist/OoRiRoEMra03NTdi",
            trial_hours=48,
            language_code="en",
        )

        self.assertIn("scans the crypto market", text)
        self.assertIn("structured signal", text)
        self.assertIn("48-hour", text)
        self.assertIn("My Access", text)
        self.assertIn("not financial advice", text)
        self.assertNotIn("https://t.me/addlist/", text)
        self.assertNotIn("guaranteed profit", text.lower())

    def test_returning_start_message_is_product_oriented_and_includes_access(self) -> None:
        text = format_start_message(
            language_code="en",
            access_state_line="Trial active for 18 more hours",
        )

        self.assertIn("Syndicate PRO+", text)
        self.assertIn("scans the market", text)
        self.assertIn("Trial active for 18 more hours", text)
        self.assertNotIn("direct Telegram interface", text)

    def test_example_signal_is_clearly_demo_content(self) -> None:
        text = format_example_signal_message(language_code="en")

        self.assertIn("Example signal", text)
        self.assertIn("demonstration", text)
        self.assertIn("not a live signal", text)
        self.assertIn("not financial advice", text)
        self.assertIn("What to notice", text)
        self.assertIn("Invalidation", text)

    def test_signal_reading_guide_explains_fields_and_risk(self) -> None:
        text = format_signal_reading_guide_message(language_code="en")

        for expected in ("Symbol", "Direction", "Timeframe", "Strategy", "Entry", "Target", "Chart", "Follow-up"):
            self.assertIn(expected, text)
        self.assertIn("No result is guaranteed", text)
        self.assertIn("decide independently", text)
        self.assertIn("Read it in this order", text)
        self.assertIn("After the signal", text)

    def test_access_message_english_ai_state_stays_english(self) -> None:
        text = format_access_message(
            access_level="Trial",
            access_state_line="Trial ends: 2026-06-11 10:00 UTC",
            user_label="test user",
            enabled_notifications="Signals, follow-ups",
            enabled_strategies="Breakout",
            delivery_mode_label="Instant",
            language_code="en",
            workspace_count=1,
            saved_sets_count=2,
            ai_access_enabled=True,
        )

        self.assertIn("AI Access: <b>Enabled</b>", text)
        self.assertNotIn("Включ", text)
        self.assertIn("What is open now", text)
        self.assertIn("Trial", text)

    def test_access_message_names_free_expired_and_paid_states(self) -> None:
        free_text = format_access_message(
            access_level="Free",
            access_state_line="Status: free access",
            language_code="en",
        )
        expired_text = format_access_message(
            access_level="Expired",
            access_state_line="Expired: 2026-06-01 10:00 UTC",
            language_code="en",
        )
        paid_text = format_access_message(
            access_level="Paid",
            access_state_line="Paid until: 2026-07-01 10:00 UTC",
            language_code="en",
            ai_access_enabled=True,
        )

        self.assertIn("Free access", free_text)
        self.assertIn("Upgrade to PRO+", free_text)
        self.assertIn("Expired access", expired_text)
        self.assertIn("Renew PRO+", expired_text)
        self.assertIn("Paid PRO+", paid_text)
        self.assertIn("full PRO+ flow", paid_text)

    def test_classic_first_start_message_includes_channels_folder_link_when_configured(self) -> None:
        text = format_classic_first_start_message(
            premium_link="https://t.me/syndicateproobot",
            channels_folder_link="https://t.me/addlist/OoRiRoEMra03NTdi",
            language_code="en",
        )

        self.assertIn("https://t.me/addlist/OoRiRoEMra03NTdi", text)
        self.assertIn("Stay in the loop", text)

    def test_classic_returning_start_is_a_dashboard_not_first_run_copy(self) -> None:
        first_run = format_classic_first_start_message(delay_minutes=30, language_code="en")
        returning = format_classic_start_message(delay_minutes=30, language_code="en")

        self.assertIn("Welcome to Syndicate Classic", first_run)
        self.assertIn("Syndicate Classic", returning)
        self.assertIn("Welcome back", returning)
        self.assertIn("Latest Classic Signals", returning)
        self.assertIn("Classic vs PRO+", returning)
        self.assertNotEqual(first_run, returning)

    def test_classic_vs_pro_copy_is_clear_and_does_not_promise_results(self) -> None:
        text = format_classic_vs_pro_message(delay_minutes=30, language_code="en")

        self.assertIn("Classic vs PRO+", text)
        self.assertIn("delayed", text)
        self.assertIn("earlier", text)
        self.assertIn("not financial advice", text)
        self.assertNotIn("guaranteed profit", text.lower())

    def test_help_pages_cover_no_signals_risk_and_support_without_fake_contact(self) -> None:
        no_signals = format_help_page_message("no_signals", language_code="en")
        risk = format_help_page_message("risk", language_code="en")
        support = format_help_page_message("support", language_code="en", support_target=None)

        self.assertIn("not an error", no_signals)
        self.assertIn("quality filters", no_signals)
        self.assertIn("not financial advice", risk)
        self.assertIn("Past results do not guarantee", risk)
        self.assertIn("official support channel configured by the owner", support)
        self.assertNotIn("@support", support)

    def test_results_center_explains_methodology_without_fake_winrate(self) -> None:
        text = MessageRenderService().render_results_hub(language_code="en")

        self.assertIn("How results are calculated", text)
        self.assertIn("invalidated", text)
        self.assertIn("expired", text)
        self.assertIn("Past results do not guarantee", text)
        self.assertNotIn("win rate", text.lower())


if __name__ == "__main__":
    unittest.main()
