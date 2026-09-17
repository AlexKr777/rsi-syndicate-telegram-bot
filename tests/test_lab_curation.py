from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from src.ai.generators import DraftGenerator
from src.core.config import get_settings
from src.core.models import AlertSignal, FollowUpResult, GeneratedPost, TwitterDraft
from src.jobs.followups import FollowUpService
from src.jobs.generated_posts import ScheduledGeneratedPostService
from src.jobs.twitter_drafts import TwitterDraftService
from src.storage.models import AlertRecord, FollowUpResultRecord


class _GeneratorRepository:
    async def list_generated_posts_history(self, **kwargs):
        del kwargs
        return []

    async def count_posts_history_since(self, **kwargs):
        del kwargs
        return 0


class _FakeDraftRepository:
    def __init__(self) -> None:
        self.saved: list[tuple[TwitterDraft, object | None]] = []

    async def save_twitter_draft(self, draft: TwitterDraft, sent_at=None) -> None:
        self.saved.append((draft, sent_at))


class _FakeDraftRouter:
    def __init__(self) -> None:
        self.sent_drafts: list[TwitterDraft] = []
        self.lab_bundles: list[dict[str, object]] = []

    async def send_twitter_draft(self, draft: TwitterDraft):
        self.sent_drafts.append(draft)
        return SimpleNamespace(sent=True, rate_limited=False, telegram_message_id=101, metadata={})

    async def send_lab_review_bundle(self, **kwargs):
        self.lab_bundles.append(kwargs)
        return SimpleNamespace(sent=True, rate_limited=False, telegram_message_id=202, metadata={})


class _FakeChartRenderer:
    def __init__(self) -> None:
        self.cleaned: list[object] = []

    def cleanup(self, path) -> None:
        self.cleaned.append(path)


class LabCurationTests(unittest.IsolatedAsyncioTestCase):
    def _settings(self, **updates):
        return get_settings().model_copy(update={"curated_lab_only_mode": True, **updates})

    def _signal(self) -> AlertSignal:
        now = datetime.now(timezone.utc)
        return AlertSignal(
            symbol="BTCUSDT",
            direction="oversold",
            timeframe="15m",
            candle_open_time=now - timedelta(minutes=15),
            candle_close_time=now,
            price=100.0,
            rsi=24.0,
            day_change_pct=None,
            day_volume=25_000_000.0,
            quote_volume=25_000_000.0,
            last_candle_volume=0.0,
            avg_volume_20=0.0,
            atr=0.0,
            atr_pct=0.0,
            ema20=0.0,
            ema50=0.0,
            score=92,
            explanation="",
            metadata={},
        )

    def _followup(self) -> FollowUpResult:
        now = datetime.now(timezone.utc)
        return FollowUpResult(
            alert_id=11,
            symbol="BTCUSDT",
            direction="oversold",
            timeframe="15m",
            alert_price=100.0,
            current_price=106.0,
            alert_rsi=24.0,
            current_rsi=36.0,
            move_pct=6.0,
            summary="",
            score=92,
            observed_at=now,
            stage="6h",
            thesis_result_state="favorable",
            favorable_move_pct=6.0,
            metadata={"thesis_result_state": "favorable", "favorable_move_pct": 6.0},
        )

    async def test_curated_lab_only_mode_disables_generated_channel_posts(self) -> None:
        settings = self._settings(
            public_startup_posts_enabled=True,
            lab_startup_posts_enabled=True,
            community_startup_posts_enabled=True,
            public_best_setups_enabled=True,
            public_result_posts_enabled=True,
            public_market_takeaways_enabled=True,
            results_channel_enabled=True,
            results_all_followups_enabled=True,
        )
        generator = DraftGenerator(settings, ollama_client=None, repository=_GeneratorRepository())

        self.assertEqual(await generator.generate_startup_posts(), [])
        self.assertEqual(await generator.generate_for_alert(self._signal(), related_alert_id=7), [])
        followup_posts = await generator.generate_for_followup(self._signal(), self._followup())
        self.assertEqual(len(followup_posts), 1)
        self.assertEqual(followup_posts[0].channel_kind, "results")
        self.assertEqual(followup_posts[0].content_type, "results_followup_post")
        self.assertFalse(followup_posts[0].send_lab_copy)

    async def test_finalize_draft_mirrors_non_preview_x_draft_to_lab(self) -> None:
        settings = self._settings()
        repository = _FakeDraftRepository()
        router = _FakeDraftRouter()
        chart_renderer = _FakeChartRenderer()
        service = TwitterDraftService(
            settings,
            repository,
            binance_client=SimpleNamespace(),
            chart_renderer=chart_renderer,
            router=router,
            generator=SimpleNamespace(),
        )
        draft = TwitterDraft(
            destination=settings.twitter_drafts_chat,
            content_type="twitter_operator_opinion_post",
            main_text="Best operator thought of the day.",
            angle="thought",
            value_types=("learning value",),
            status="generated",
        )

        finalized = await service._finalize_draft(draft)

        self.assertEqual(finalized.status, "sent")
        self.assertEqual(len(router.sent_drafts), 1)
        self.assertEqual(len(router.lab_bundles), 1)
        self.assertEqual(router.lab_bundles[0]["symbol"], "MARKET")
        self.assertEqual(router.lab_bundles[0]["scope"], "alert")
        self.assertIs(router.lab_bundles[0]["twitter_draft"], finalized)

    async def test_finalize_preview_x_draft_does_not_mirror_to_lab(self) -> None:
        settings = self._settings()
        repository = _FakeDraftRepository()
        router = _FakeDraftRouter()
        service = TwitterDraftService(
            settings,
            repository,
            binance_client=SimpleNamespace(),
            chart_renderer=_FakeChartRenderer(),
            router=router,
            generator=SimpleNamespace(),
        )
        draft = TwitterDraft(
            destination=settings.twitter_drafts_chat,
            content_type="twitter_market_insight_post",
            main_text="Preview-only market thought.",
            angle="insight",
            value_types=("learning value",),
            status="generated",
            preview_mode=True,
        )

        await service._finalize_draft(draft)

        self.assertEqual(len(router.sent_drafts), 1)
        self.assertEqual(router.lab_bundles, [])


class ScheduledPostCurationTests(unittest.TestCase):
    def test_curated_lab_only_mode_skips_external_and_internal_lab_scheduled_posts(self) -> None:
        settings = get_settings().model_copy(update={"curated_lab_only_mode": True})
        service = ScheduledGeneratedPostService(
            settings,
            repository=SimpleNamespace(),
            router=SimpleNamespace(),
            binance_client=SimpleNamespace(),
            chart_renderer=SimpleNamespace(),
            interactive_alert_service=None,
        )

        self.assertTrue(
            service._skip_for_curated_lab_only_mode(
                GeneratedPost(
                    channel_kind="public",
                    destination="@public",
                    content_type="public_best_setup",
                    generated_text="text",
                    status="scheduled",
                )
            )
        )
        self.assertFalse(
            service._skip_for_curated_lab_only_mode(
                GeneratedPost(
                    channel_kind="results",
                    destination="@results",
                    content_type="results_followup_post",
                    generated_text="text",
                    status="scheduled",
                )
            )
        )
        self.assertTrue(
            service._skip_for_curated_lab_only_mode(
                GeneratedPost(
                    channel_kind="lab",
                    destination="@lab",
                    content_type="internal_summary",
                    generated_text="text",
                    status="scheduled",
                )
            )
        )
        self.assertFalse(
            service._skip_for_curated_lab_only_mode(
                GeneratedPost(
                    channel_kind="lab",
                    destination="@lab",
                    content_type="manual_review",
                    generated_text="text",
                    status="scheduled",
                )
            )
        )


class _FakeResultsDigestRepository:
    def __init__(self, alerts: list[AlertRecord], followups: list[FollowUpResultRecord]) -> None:
        self.alerts = {alert.id: alert for alert in alerts}
        self.followups = followups
        self.sent_posts: list[dict[str, object]] = []

    async def list_generated_posts_history(self, **kwargs):
        since = kwargs.get("since")
        content_types = set(kwargs.get("content_types") or [])
        statuses = set(kwargs.get("statuses") or [])
        items = []
        for post in self.sent_posts:
            if since is not None and datetime.fromisoformat(str(post["created_at"])) < since:
                continue
            if content_types and str(post["content_type"]) not in content_types:
                continue
            if statuses and str(post["status"]) not in statuses:
                continue
            items.append(post)
        return list(reversed(items))[: int(kwargs.get("limit") or 20)]

    async def list_followup_results_between(self, **kwargs):
        start = kwargs["start"]
        end = kwargs["end"]
        limit = int(kwargs.get("limit") or len(self.followups))
        return [item for item in self.followups if start <= item.observed_at < end][:limit]

    async def get_alert(self, alert_id: int):
        return self.alerts.get(alert_id)


class _FakeResultsDigestRouter:
    def __init__(self, repository: _FakeResultsDigestRepository) -> None:
        self.repository = repository
        self.posts: list[GeneratedPost] = []

    async def route_generated_post(self, post: GeneratedPost):
        self.posts.append(post)
        self.repository.sent_posts.append(
            {
                "destination": post.destination,
                "channel_kind": post.channel_kind,
                "status": "sent",
                "content_type": post.content_type,
                "related_alert_id": post.related_alert_id,
                "source_symbol": post.source_symbol,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "metadata": dict(post.metadata),
            }
        )
        return SimpleNamespace(sent=True, rate_limited=False, telegram_message_id=len(self.posts), metadata={})


class ResultsChannelDigestTests(unittest.IsolatedAsyncioTestCase):
    def _alert(self, alert_id: int, symbol: str, *, score: int) -> AlertRecord:
        now = datetime(2026, 3, 16, 15, 0, tzinfo=timezone.utc)
        return AlertRecord(
            id=alert_id,
            symbol=symbol,
            direction="oversold",
            timeframe="15m",
            candle_open_time=now - timedelta(minutes=15),
            candle_close_time=now,
            alert_price=100.0,
            alert_rsi=28.0,
            day_change_pct=None,
            day_volume=25_000_000.0,
            score=score,
            alert_sent_at=now,
            followup_due_at=now + timedelta(hours=2),
            followup_sent_at=None,
            lab_message_id=None,
            metadata={"quote_volume": 25_000_000.0, "asset_class": "crypto"},
            strategy_key="rsi",
        )

    def _followup(self, alert_id: int, symbol: str, *, favorable_move: float, observed_at: datetime) -> FollowUpResultRecord:
        return FollowUpResultRecord(
            alert_id=alert_id,
            stage="4h",
            symbol=symbol,
            direction="oversold",
            timeframe="15m",
            alert_price=100.0,
            alert_rsi=28.0,
            score=85,
            current_price=100.0 + favorable_move,
            current_rsi=39.0,
            move_pct=-favorable_move,
            summary="follow-up",
            observed_at=observed_at,
            metadata={
                "followup_stage": "4h",
                "thesis_result_state": "favorable",
                "favorable_move_pct": favorable_move,
            },
        )

    async def test_results_digest_sends_two_slots_without_repeating_alerts(self) -> None:
        settings = get_settings().model_copy(
            update={
                "results_channel_enabled": True,
                "curated_lab_only_mode": True,
                "results_channel": "@resultrsi",
                "app_timezone": "Europe/Chisinau",
            }
        )
        alerts = [
            self._alert(101, "AAAUSDT", score=92),
            self._alert(102, "BBBUSDT", score=88),
            self._alert(103, "CCCUSDT", score=84),
        ]
        followups = [
            self._followup(101, "AAAUSDT", favorable_move=12.0, observed_at=datetime(2026, 3, 16, 15, 10, tzinfo=timezone.utc)),
            self._followup(102, "BBBUSDT", favorable_move=10.0, observed_at=datetime(2026, 3, 16, 15, 20, tzinfo=timezone.utc)),
            self._followup(103, "CCCUSDT", favorable_move=8.0, observed_at=datetime(2026, 3, 16, 15, 30, tzinfo=timezone.utc)),
        ]
        repository = _FakeResultsDigestRepository(alerts, followups)
        router = _FakeResultsDigestRouter(repository)
        service = FollowUpService(
            settings,
            repository,
            binance_client=SimpleNamespace(),
            chart_renderer=SimpleNamespace(),
            router=router,
            draft_generator=SimpleNamespace(),
        )

        await service._send_results_channel_best_followups_if_due(
            now=datetime(2026, 3, 16, 16, 5, tzinfo=timezone.utc)
        )
        await service._send_results_channel_best_followups_if_due(
            now=datetime(2026, 3, 16, 19, 5, tzinfo=timezone.utc)
        )

        self.assertEqual(len(router.posts), 2)
        self.assertEqual(router.posts[0].metadata["slot_hour"], 18)
        self.assertEqual(router.posts[0].metadata["alert_ids"], [101, 102])
        self.assertEqual(router.posts[1].metadata["slot_hour"], 21)
        self.assertEqual(router.posts[1].metadata["alert_ids"], [103])
        self.assertIn("AAAUSDT", router.posts[0].generated_text)
        self.assertIn("CCCUSDT", router.posts[1].generated_text)


if __name__ == "__main__":
    unittest.main()
