from __future__ import annotations

import unittest

from src.core.models import DeliveryResult
from src.main import summarize_alert_deliveries


class LogHygieneTests(unittest.TestCase):
    def test_alert_summary_does_not_claim_sent_when_everything_was_skipped(self) -> None:
        summary = summarize_alert_deliveries(
            lab_delivery=None,
            external_deliveries=[],
            curated_mode=True,
        )

        self.assertEqual(summary["lab_status"], "skipped_curated")
        self.assertEqual(summary["external_sent"], 0)
        self.assertEqual(summary["external_scheduled"], 0)
        self.assertEqual(summary["external_skipped"], 0)

    def test_alert_summary_distinguishes_sent_scheduled_and_skipped(self) -> None:
        summary = summarize_alert_deliveries(
            lab_delivery=DeliveryResult(
                destination="lab",
                message_type="raw_alert",
                sent=True,
                rate_limited=False,
            ),
            external_deliveries=[
                DeliveryResult(
                    destination="public",
                    message_type="post",
                    sent=True,
                    rate_limited=False,
                ),
                DeliveryResult(
                    destination="results",
                    message_type="post",
                    sent=False,
                    rate_limited=False,
                    metadata={"scheduled": True},
                ),
                DeliveryResult(
                    destination="pro",
                    message_type="post",
                    sent=False,
                    rate_limited=False,
                ),
            ],
            curated_mode=False,
        )

        self.assertEqual(summary["lab_status"], "sent")
        self.assertEqual(summary["external_sent"], 1)
        self.assertEqual(summary["external_scheduled"], 1)
        self.assertEqual(summary["external_skipped"], 1)


if __name__ == "__main__":
    unittest.main()
