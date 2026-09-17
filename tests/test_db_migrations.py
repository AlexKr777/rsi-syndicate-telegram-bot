from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import aiosqlite

from src.core.models import FollowUpResult
from src.storage.db import initialize_database
from src.storage.repository import Repository


class DatabaseMigrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_initialize_database_migrates_legacy_referral_tables_without_referral_columns(self) -> None:
        tempdir = tempfile.TemporaryDirectory()
        sqlite_path = Path(tempdir.name) / "legacy_referrals.db"
        connection = sqlite3.connect(str(sqlite_path))
        try:
            connection.executescript(
                """
                CREATE TABLE bot_users (
                    telegram_user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    access_level TEXT NOT NULL DEFAULT 'free',
                    access_status TEXT NOT NULL DEFAULT 'free',
                    is_admin INTEGER NOT NULL DEFAULT 0,
                    referred_by_user_id INTEGER
                );

                CREATE TABLE referrals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    referrer_user_id INTEGER NOT NULL,
                    referred_user_id INTEGER NOT NULL UNIQUE,
                    bot_kind TEXT NOT NULL DEFAULT 'premium',
                    status TEXT NOT NULL DEFAULT 'registered',
                    source_payload TEXT,
                    created_at TEXT NOT NULL,
                    converted_at TEXT,
                    updated_at TEXT NOT NULL,
                    metadata_json TEXT
                );
                """
            )
            connection.commit()
        finally:
            connection.close()

        await initialize_database(str(sqlite_path))

        async with aiosqlite.connect(str(sqlite_path)) as migrated:
            cursor = await migrated.execute("PRAGMA table_info(bot_users)")
            bot_user_columns = {row[1] for row in await cursor.fetchall()}
            self.assertIn("referral_code", bot_user_columns)

            cursor = await migrated.execute("PRAGMA table_info(referrals)")
            referral_columns = {row[1] for row in await cursor.fetchall()}
            self.assertIn("first_paid_conversion_at", referral_columns)
            self.assertIn("counted_as_paid_referral", referral_columns)
            self.assertIn("conversion_invoice_id", referral_columns)

            cursor = await migrated.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name IN ('referral_cycle_stats', 'referral_reward_grants')
                ORDER BY name
                """
            )
            names = [row[0] for row in await cursor.fetchall()]
            self.assertEqual(names, ["referral_cycle_stats", "referral_reward_grants"])

        tempdir.cleanup()

    async def test_initialize_database_migrates_legacy_alerts_without_strategy_key(self) -> None:
        tempdir = tempfile.TemporaryDirectory()
        sqlite_path = Path(tempdir.name) / "legacy.db"
        connection = sqlite3.connect(str(sqlite_path))
        try:
            connection.executescript(
                """
                CREATE TABLE alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    candle_open_time TEXT NOT NULL,
                    candle_close_time TEXT NOT NULL,
                    alert_price REAL NOT NULL,
                    alert_rsi REAL NOT NULL,
                    day_change_pct REAL,
                    day_volume REAL,
                    score INTEGER NOT NULL,
                    alert_sent_at TEXT NOT NULL,
                    followup_due_at TEXT NOT NULL,
                    followup_sent_at TEXT,
                    lab_message_id INTEGER,
                    metadata_json TEXT,
                    UNIQUE(symbol, direction, timeframe, candle_open_time)
                );

                INSERT INTO alerts (
                    symbol,
                    direction,
                    timeframe,
                    candle_open_time,
                    candle_close_time,
                    alert_price,
                    alert_rsi,
                    day_change_pct,
                    day_volume,
                    score,
                    alert_sent_at,
                    followup_due_at,
                    followup_sent_at,
                    lab_message_id,
                    metadata_json
                )
                VALUES (
                    'BTCUSDT',
                    'oversold',
                    '15m',
                    '2026-03-16T10:00:00+00:00',
                    '2026-03-16T10:14:59+00:00',
                    100.0,
                    25.0,
                    NULL,
                    NULL,
                    84,
                    '2026-03-16T10:15:00+00:00',
                    '2026-03-16T12:15:00+00:00',
                    NULL,
                    NULL,
                    '{"asset_class":"crypto"}'
                );
                """
            )
            connection.commit()
        finally:
            connection.close()

        await initialize_database(str(sqlite_path))

        async with aiosqlite.connect(str(sqlite_path)) as migrated:
            cursor = await migrated.execute("PRAGMA table_info(alerts)")
            columns = {row[1] for row in await cursor.fetchall()}
            self.assertIn("strategy_key", columns)

            cursor = await migrated.execute(
                """
                SELECT strategy_key
                FROM alerts
                WHERE symbol = 'BTCUSDT'
                """
            )
            row = await cursor.fetchone()
            self.assertIsNotNone(row)
            assert row is not None
            self.assertEqual(row[0], "rsi")

        tempdir.cleanup()

    async def test_initialize_database_migrates_legacy_watchlist_themes_into_premium_rsi_scope(self) -> None:
        tempdir = tempfile.TemporaryDirectory()
        sqlite_path = Path(tempdir.name) / "legacy_watchlists.db"
        connection = sqlite3.connect(str(sqlite_path))
        try:
            connection.executescript(
                """
                CREATE TABLE user_watchlist_themes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_user_id INTEGER NOT NULL,
                    bot_kind TEXT NOT NULL,
                    theme_name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata_json TEXT
                );

                CREATE TABLE user_watchlist_theme_symbols (
                    theme_id INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (theme_id, symbol)
                );

                INSERT INTO user_watchlist_themes (
                    telegram_user_id,
                    bot_kind,
                    theme_name,
                    created_at,
                    updated_at,
                    metadata_json
                )
                VALUES (
                    777001,
                    'premium',
                    'Desk',
                    '2026-03-16T10:00:00+00:00',
                    '2026-03-16T10:05:00+00:00',
                    '{}'
                );

                INSERT INTO user_watchlist_theme_symbols (theme_id, symbol, created_at)
                VALUES (1, 'BTCUSDT', '2026-03-16T10:00:00+00:00');
                """
            )
            connection.commit()
        finally:
            connection.close()

        await initialize_database(str(sqlite_path))

        async with aiosqlite.connect(str(sqlite_path)) as migrated:
            migrated.row_factory = aiosqlite.Row
            cursor = await migrated.execute(
                """
                SELECT telegram_user_id, bot_kind, strategy_key, theme_name
                FROM premium_strategy_watchlist_themes
                WHERE telegram_user_id = 777001
                """
            )
            row = await cursor.fetchone()
            self.assertIsNotNone(row)
            assert row is not None
            self.assertEqual(row["bot_kind"], "premium")
            self.assertEqual(row["strategy_key"], "rsi")
            self.assertEqual(row["theme_name"], "Desk")

            cursor = await migrated.execute(
                """
                SELECT symbol
                FROM premium_strategy_watchlist_theme_symbols
                """
            )
            symbol_row = await cursor.fetchone()
            self.assertIsNotNone(symbol_row)
            assert symbol_row is not None
            self.assertEqual(symbol_row["symbol"], "BTCUSDT")

        tempdir.cleanup()

    async def test_initialize_database_preserves_gold_substrategy_alert_keys(self) -> None:
        tempdir = tempfile.TemporaryDirectory()
        sqlite_path = Path(tempdir.name) / "gold_substrategy.db"
        connection = sqlite3.connect(str(sqlite_path))
        try:
            connection.executescript(
                """
                CREATE TABLE alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    strategy_key TEXT NOT NULL DEFAULT 'rsi',
                    timeframe TEXT NOT NULL,
                    candle_open_time TEXT NOT NULL,
                    candle_close_time TEXT NOT NULL,
                    alert_price REAL NOT NULL,
                    alert_rsi REAL NOT NULL,
                    day_change_pct REAL,
                    day_volume REAL,
                    score INTEGER NOT NULL,
                    alert_sent_at TEXT NOT NULL,
                    followup_due_at TEXT NOT NULL,
                    followup_sent_at TEXT,
                    lab_message_id INTEGER,
                    metadata_json TEXT,
                    UNIQUE(symbol, direction, strategy_key, timeframe, candle_open_time)
                );

                INSERT INTO alerts (
                    symbol,
                    direction,
                    strategy_key,
                    timeframe,
                    candle_open_time,
                    candle_close_time,
                    alert_price,
                    alert_rsi,
                    day_change_pct,
                    day_volume,
                    score,
                    alert_sent_at,
                    followup_due_at,
                    followup_sent_at,
                    lab_message_id,
                    metadata_json
                )
                VALUES (
                    'XAUUSD',
                    'long',
                    'gold_breakout',
                    '1h',
                    '2026-03-18T09:00:00+00:00',
                    '2026-03-18T09:59:59+00:00',
                    3020.5,
                    58.0,
                    NULL,
                    NULL,
                    88,
                    '2026-03-18T10:00:00+00:00',
                    '2026-03-18T14:00:00+00:00',
                    NULL,
                    NULL,
                    '{"asset_class":"gold","strategy_key":"gold_breakout"}'
                );
                """
            )
            connection.commit()
        finally:
            connection.close()

        await initialize_database(str(sqlite_path))

        async with aiosqlite.connect(str(sqlite_path)) as migrated:
            cursor = await migrated.execute(
                """
                SELECT strategy_key
                FROM alerts
                WHERE symbol = 'XAUUSD'
                """
            )
            row = await cursor.fetchone()
            self.assertIsNotNone(row)
            assert row is not None
            self.assertEqual(row[0], "gold_breakout")

        tempdir.cleanup()

    async def test_initialize_database_merges_conflicting_alert_strategy_rows_and_repairs_references(self) -> None:
        tempdir = tempfile.TemporaryDirectory()
        sqlite_path = Path(tempdir.name) / "conflicting_alerts.db"
        connection = sqlite3.connect(str(sqlite_path))
        try:
            connection.executescript(
                """
                CREATE TABLE alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    strategy_key TEXT NOT NULL DEFAULT 'rsi',
                    timeframe TEXT NOT NULL,
                    candle_open_time TEXT NOT NULL,
                    candle_close_time TEXT NOT NULL,
                    alert_price REAL NOT NULL,
                    alert_rsi REAL NOT NULL,
                    day_change_pct REAL,
                    day_volume REAL,
                    score INTEGER NOT NULL,
                    alert_sent_at TEXT NOT NULL,
                    followup_due_at TEXT NOT NULL,
                    followup_sent_at TEXT,
                    lab_message_id INTEGER,
                    metadata_json TEXT,
                    UNIQUE(symbol, direction, strategy_key, timeframe, candle_open_time)
                );

                CREATE TABLE delivered_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_user_id INTEGER NOT NULL,
                    alert_id INTEGER,
                    content_kind TEXT NOT NULL,
                    message_kind TEXT NOT NULL,
                    telegram_message_id INTEGER,
                    delivered_at TEXT NOT NULL,
                    metadata_json TEXT,
                    UNIQUE(telegram_user_id, alert_id, content_kind, message_kind),
                    FOREIGN KEY(alert_id) REFERENCES alerts(id)
                );

                INSERT INTO alerts (
                    id,
                    symbol,
                    direction,
                    strategy_key,
                    timeframe,
                    candle_open_time,
                    candle_close_time,
                    alert_price,
                    alert_rsi,
                    day_change_pct,
                    day_volume,
                    score,
                    alert_sent_at,
                    followup_due_at,
                    followup_sent_at,
                    lab_message_id,
                    metadata_json
                )
                VALUES
                (
                    1,
                    'BTCUSDT',
                    'long',
                    'breakout',
                    '1h',
                    '2026-03-18T08:00:00+00:00',
                    '2026-03-18T08:59:59+00:00',
                    81250.0,
                    61.0,
                    NULL,
                    NULL,
                    86,
                    '2026-03-18T09:00:00+00:00',
                    '2026-03-18T13:00:00+00:00',
                    NULL,
                    NULL,
                    '{"asset_class":"crypto","strategy_key":"breakout"}'
                ),
                (
                    2,
                    'BTCUSDT',
                    'long',
                    'legacy_breakout',
                    '1h',
                    '2026-03-18T08:00:00+00:00',
                    '2026-03-18T08:59:59+00:00',
                    81250.0,
                    61.0,
                    NULL,
                    NULL,
                    86,
                    '2026-03-18T09:00:00+00:00',
                    '2026-03-18T13:00:00+00:00',
                    NULL,
                    NULL,
                    '{"asset_class":"crypto","strategy_key":"breakout"}'
                );

                INSERT INTO delivered_signals (
                    telegram_user_id,
                    alert_id,
                    content_kind,
                    message_kind,
                    telegram_message_id,
                    delivered_at,
                    metadata_json
                )
                VALUES (
                    777001,
                    2,
                    'signal',
                    'alert',
                    99,
                    '2026-03-18T09:05:00+00:00',
                    '{}'
                );
                """
            )
            connection.commit()
        finally:
            connection.close()

        await initialize_database(str(sqlite_path))

        async with aiosqlite.connect(str(sqlite_path)) as migrated:
            migrated.row_factory = aiosqlite.Row
            cursor = await migrated.execute(
                """
                SELECT id, strategy_key
                FROM alerts
                WHERE symbol = 'BTCUSDT'
                ORDER BY id
                """
            )
            rows = await cursor.fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["id"], 1)
            self.assertEqual(rows[0]["strategy_key"], "breakout")

            cursor = await migrated.execute(
                """
                SELECT alert_id
                FROM delivered_signals
                WHERE telegram_user_id = 777001
                """
            )
            delivered_row = await cursor.fetchone()
            self.assertIsNotNone(delivered_row)
            assert delivered_row is not None
            self.assertEqual(delivered_row["alert_id"], 1)

        tempdir.cleanup()

    async def test_initialize_database_repairs_broken_followup_foreign_keys_after_alerts_rebuild(self) -> None:
        tempdir = tempfile.TemporaryDirectory()
        sqlite_path = Path(tempdir.name) / "broken_followups.db"
        connection = sqlite3.connect(str(sqlite_path))
        try:
            connection.executescript(
                """
                CREATE TABLE alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    strategy_key TEXT NOT NULL DEFAULT 'rsi',
                    timeframe TEXT NOT NULL,
                    candle_open_time TEXT NOT NULL,
                    candle_close_time TEXT NOT NULL,
                    alert_price REAL NOT NULL,
                    alert_rsi REAL NOT NULL,
                    day_change_pct REAL,
                    day_volume REAL,
                    score INTEGER NOT NULL,
                    alert_sent_at TEXT NOT NULL,
                    followup_due_at TEXT NOT NULL,
                    followup_sent_at TEXT,
                    lab_message_id INTEGER,
                    metadata_json TEXT,
                    UNIQUE(symbol, direction, strategy_key, timeframe, candle_open_time)
                );

                INSERT INTO alerts (
                    id,
                    symbol,
                    direction,
                    strategy_key,
                    timeframe,
                    candle_open_time,
                    candle_close_time,
                    alert_price,
                    alert_rsi,
                    day_change_pct,
                    day_volume,
                    score,
                    alert_sent_at,
                    followup_due_at,
                    followup_sent_at,
                    lab_message_id,
                    metadata_json
                )
                VALUES (
                    1,
                    'ARKUSDT',
                    'oversold',
                    'rsi',
                    '15m',
                    '2026-03-16T10:00:00+00:00',
                    '2026-03-16T10:14:59+00:00',
                    1.25,
                    24.0,
                    NULL,
                    NULL,
                    80,
                    '2026-03-16T10:15:00+00:00',
                    '2026-03-16T14:15:00+00:00',
                    NULL,
                    NULL,
                    '{}'
                );

                CREATE TABLE followup_results (
                    alert_id INTEGER PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    alert_price REAL NOT NULL,
                    alert_rsi REAL NOT NULL,
                    score INTEGER NOT NULL,
                    current_price REAL NOT NULL,
                    current_rsi REAL NOT NULL,
                    move_pct REAL NOT NULL,
                    summary TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    metadata_json TEXT,
                    FOREIGN KEY(alert_id) REFERENCES alerts_legacy_strategy_migration(id)
                );

                CREATE TABLE followup_stage_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_id INTEGER NOT NULL,
                    stage TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    alert_price REAL NOT NULL,
                    alert_rsi REAL NOT NULL,
                    score INTEGER NOT NULL,
                    current_price REAL NOT NULL,
                    current_rsi REAL NOT NULL,
                    move_pct REAL NOT NULL,
                    summary TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    metadata_json TEXT,
                    UNIQUE(alert_id, stage),
                    FOREIGN KEY(alert_id) REFERENCES alerts_legacy_strategy_migration(id)
                );
                """
            )
            connection.commit()
        finally:
            connection.close()

        await initialize_database(str(sqlite_path))

        repository = Repository(str(sqlite_path))
        await repository.connect()
        try:
            await repository.save_followup_result(
                FollowUpResult(
                    alert_id=1,
                    symbol="ARKUSDT",
                    direction="oversold",
                    timeframe="15m",
                    alert_price=1.25,
                    current_price=1.31,
                    alert_rsi=24.0,
                    current_rsi=33.0,
                    move_pct=4.8,
                    summary="Recovered cleanly.",
                    score=84,
                    observed_at=datetime.fromisoformat("2026-03-16T14:30:00+00:00"),
                    stage="4h",
                    thesis_result_state="favorable",
                    favorable_move_pct=4.8,
                    metadata={"thesis_result_state": "favorable", "favorable_move_pct": 4.8},
                )
            )

            async with aiosqlite.connect(str(sqlite_path)) as migrated:
                migrated.row_factory = aiosqlite.Row
                cursor = await migrated.execute(
                    """
                    SELECT sql
                    FROM sqlite_master
                    WHERE type = 'table'
                      AND name = 'followup_stage_results'
                    """
                )
                row = await cursor.fetchone()
                self.assertIsNotNone(row)
                assert row is not None
                self.assertNotIn("alerts_legacy_strategy_migration", str(row["sql"] or ""))

                cursor = await migrated.execute(
                    """
                    SELECT stage, summary
                    FROM followup_stage_results
                    WHERE alert_id = 1
                    """
                )
                saved_row = await cursor.fetchone()
                self.assertIsNotNone(saved_row)
                assert saved_row is not None
                self.assertEqual(saved_row["stage"], "4h")
                self.assertEqual(saved_row["summary"], "Recovered cleanly.")
        finally:
            await repository.close()
            tempdir.cleanup()

    async def test_initialize_database_creates_tracked_signal_candles_table(self) -> None:
        tempdir = tempfile.TemporaryDirectory()
        sqlite_path = Path(tempdir.name) / "tracked_signal_candles.db"
        try:
            await initialize_database(str(sqlite_path))
            async with aiosqlite.connect(str(sqlite_path)) as connection:
                connection.row_factory = aiosqlite.Row
                cursor = await connection.execute(
                    """
                    SELECT sql
                    FROM sqlite_master
                    WHERE type = 'table'
                      AND name = 'tracked_signal_candles'
                    """
                )
                row = await cursor.fetchone()
                self.assertIsNotNone(row)
                assert row is not None
                sql = str(row["sql"] or "")
                self.assertIn("signal_id INTEGER NOT NULL", sql)
                self.assertIn("processed_at TEXT", sql)
        finally:
            tempdir.cleanup()


if __name__ == "__main__":
    unittest.main()
