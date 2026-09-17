from __future__ import annotations

from src.core.utils import escape_html
from src.localization import is_russian


def format_admin_health_message(
    *,
    generated_at_label: str,
    signals_generated: int | None,
    premium_delivery_records: int | None,
    classic_delivery_records: int | None,
    pending_followups: int | None,
    processing_followups: int | None,
    stale_followups: int | None,
    database_size_label: str,
    funnel_counts: dict[str, int] | None,
    language_code: str = "en",
) -> str:
    def metric(value: int | None) -> str:
        if value is None:
            return "—"
        return str(value)

    counts = funnel_counts or {}
    if is_russian(language_code):
        return (
            "🛡 <b>Операционный центр</b>\n"
            f"Данные на {escape_html(generated_at_label)}\n\n"
            "<b>Состояние</b>\n"
            "Сервис: <b>отвечает</b>\n"
            f"База данных: <b>доступна · {escape_html(database_size_label)}</b>\n\n"
            "<b>Сигналы и доставка</b>\n"
            f"Сформировано: <b>{metric(signals_generated)}</b>\n"
            f"Premium: <b>{metric(premium_delivery_records)}</b> · Classic: <b>{metric(classic_delivery_records)}</b>\n\n"
            "<b>Очередь follow-up</b>\n"
            f"Ожидают: <b>{metric(pending_followups)}</b> · в работе: <b>{metric(processing_followups)}</b> · просрочены: <b>{metric(stale_followups)}</b>\n\n"
            "<b>Путь пользователя</b>\n"
            f"Старт: <b>{counts.get('start_seen', 0)}</b> · пример: <b>{counts.get('example_signal_opened', 0)}</b> · чтение: <b>{counts.get('how_to_read_opened', 0)}</b>\n"
            f"Доступ: <b>{counts.get('my_access_opened', 0)}</b> · помощь: <b>{counts.get('help_opened', 0)}</b> · поддержка: <b>{counts.get('support_opened', 0)}</b>"
        )
    return (
        "🛡 <b>Operations center</b>\n"
        f"Data at {escape_html(generated_at_label)}\n\n"
        "<b>State</b>\n"
        "Service: <b>responding</b>\n"
        f"Database: <b>available · {escape_html(database_size_label)}</b>\n\n"
        "<b>Signals and delivery</b>\n"
        f"Generated: <b>{metric(signals_generated)}</b>\n"
        f"Premium: <b>{metric(premium_delivery_records)}</b> · Classic: <b>{metric(classic_delivery_records)}</b>\n\n"
        "<b>Follow-up queue</b>\n"
        f"Pending: <b>{metric(pending_followups)}</b> · processing: <b>{metric(processing_followups)}</b> · stale: <b>{metric(stale_followups)}</b>\n\n"
        "<b>User journey</b>\n"
        f"Start: <b>{counts.get('start_seen', 0)}</b> · example: <b>{counts.get('example_signal_opened', 0)}</b> · reading: <b>{counts.get('how_to_read_opened', 0)}</b>\n"
        f"Access: <b>{counts.get('my_access_opened', 0)}</b> · help: <b>{counts.get('help_opened', 0)}</b> · support: <b>{counts.get('support_opened', 0)}</b>"
    )


def format_menu_panel_message(*, bot_kind: str = "premium", language_code: str = "en") -> str:
    classic = str(bot_kind or "").strip().lower() == "classic"
    if is_russian(language_code):
        if classic:
            return (
                "<b>🧭 Главное меню</b>\n\n"
                "Все основные действия Classic собраны здесь.\n\n"
                "📌 <b>Что можно сделать</b>\n"
                "• открыть последние сигналы\n"
                "• проверить тикер вручную\n"
                "• настроить фильтры, watchlist и доставку\n"
                "• посмотреть доступ и перейти в PRO+\n\n"
                "Отправь <b>BTC</b> или <b>ETH 1h</b> прямо в чат, если нужен быстрый разбор."
            )
        return (
            "<b>🧭 Главное меню</b>\n\n"
            "Сверху собраны самые важные вещи: сигналы, твой список монет, уведомления и золото.\n\n"
            "📌 <b>Что можно сделать</b>\n"
            "• открыть последние сигналы\n"
            "• проверить любой тикер вручную\n"
            "• настроить фильтры и свой список монет\n"
            "• открыть золото, AI-разбор, доступ и статус бота\n\n"
            "Отправь <b>BTC</b>, <b>ETH 1h</b> или <b>XAUUSD</b> прямо в чат для быстрого разбора."
        )
    if classic:
        return (
            "<b>🧭 Main Menu</b>\n\n"
            "Everything important in Classic is here.\n\n"
            "📌 <b>What you can do</b>\n"
            "• open recent signals\n"
            "• check any ticker manually\n"
            "• tune filters, watchlist, and delivery\n"
            "• review access details and open PRO+\n\n"
            "Send <b>BTC</b> or <b>ETH 1h</b> in chat anytime for a quick check."
        )
    return (
        "<b>🧭 Main Menu</b>\n\n"
        "The most important things live at the top: signals, your coin list, alerts, and gold.\n\n"
        "📌 <b>What you can do</b>\n"
        "• open recent signals\n"
        "• check any ticker manually\n"
        "• tune filters and your coin list\n"
        "• open gold, AI review, access, and bot status\n\n"
        "Send <b>BTC</b>, <b>ETH 1h</b>, or <b>XAUUSD</b> directly in chat for a quick review."
    )


def _channels_folder_welcome_note(
    channels_folder_link: str | None,
    *,
    language_code: str = "en",
) -> str:
    cleaned = str(channels_folder_link or "").strip()
    if not cleaned:
        return ""
    escaped = escape_html(cleaned)
    if is_russian(language_code):
        return (
            "\n\n"
            "\U0001f4e1 <b>\u0427\u0442\u043e\u0431\u044b \u0431\u044b\u0442\u044c \u0432 \u043a\u0443\u0440\u0441\u0435 \u0432\u0441\u0435\u0433\u043e</b>\n"
            f'\u041f\u043e\u0434\u043a\u043b\u044e\u0447\u0438 <a href="{escaped}">\u0432\u0441\u0435 \u043a\u0430\u043d\u0430\u043b\u044b \u0441\u0440\u0430\u0437\u0443</a>, '
            "\u0447\u0442\u043e\u0431\u044b \u043d\u0435 \u043f\u0440\u043e\u043f\u0443\u0441\u043a\u0430\u0442\u044c \u0432\u0430\u0436\u043d\u044b\u0435 \u043e\u0431\u043d\u043e\u0432\u043b\u0435\u043d\u0438\u044f."
        )
    return (
        "\n\n"
        "\U0001f4e1 <b>Stay in the loop</b>\n"
        f'Connect <a href="{escaped}">all channels in one folder</a> so you do not miss important updates.'
    )


def format_first_start_message(
    *,
    channels_folder_link: str | None = None,
    trial_hours: int = 48,
    language_code: str = "en",
) -> str:
    del channels_folder_link
    hours = max(int(trial_hours), 1)
    if is_russian(language_code):
        return (
            "<b>Добро пожаловать в Syndicate PRO+</b>\n\n"
            "RSI Syndicate сканирует крипторынок, отфильтровывает слабые условия "
            "и отправляет структурированные сигналы: пара, направление, таймфрейм, "
            "стратегия, график и контекст риска. Follow-up показывает, как сетап развивался дальше.\n\n"
            f"<b>{hours}-часовой PRO+ trial активирован</b>\n"
            "В trial открыты ранние сетапы, полный поток, AI/risk-контекст, follow-up и настройки. "
            "Срок и статус можно проверить в разделе «Мой доступ».\n\n"
            "<b>С чего начать</b>\n"
            "Выбери один из понятных шагов ниже. Если сильных сетапов сейчас нет, "
            "фильтры могли пропустить слабые рыночные условия — это не означает, что бот не работает.\n\n"
            "<b>Риск</b>\n"
            "Это аналитический инструмент, а не финансовая рекомендация. Крипторынок рискован, "
            "результат не гарантирован, и решение по сделке пользователь принимает самостоятельно."
        )
    return (
        "<b>Welcome to Syndicate PRO+</b>\n\n"
        "RSI Syndicate scans the crypto market, filters weak conditions, and sends a structured signal "
        "with the pair, direction, timeframe, strategy, chart, and risk context. "
        "Follow-ups show how the setup developed afterward.\n\n"
        f"<b>Your {hours}-hour PRO+ trial is active</b>\n"
        "The trial includes earlier setups, the full signal flow, AI/risk context, follow-ups, and settings. "
        "Check the exact status in My Access.\n\n"
        "<b>Start here</b>\n"
        "Choose one of the guided actions below. If no strong setup is available, "
        "the quality filters may simply be skipping weak market conditions.\n\n"
        "<b>Risk</b>\n"
        "This is an analytical tool, not financial advice. Crypto markets are risky, "
        "results are not guaranteed, and you decide independently."
    )


def format_classic_first_start_message(
    *,
    premium_link: str | None = None,
    channels_folder_link: str | None = None,
    trial_days: int = 2,
    delay_minutes: int = 30,
    language_code: str = "en",
) -> str:
    premium_target = escape_html(premium_link or "https://t.me/syndicateproobot")
    channels_folder_note = _channels_folder_welcome_note(channels_folder_link, language_code=language_code)
    if is_russian(language_code):
        return (
            "<b>👋 Добро пожаловать в Syndicate Classic</b>\n\n"
            "Это бесплатный слой с более чистой и спокойной лентой сигналов.\n\n"
            "📦 <b>Что внутри</b>\n"
            "• отфильтрованные сигналы и follow-up\n"
            "• ручная проверка тикеров\n"
            "• watchlist и персональные фильтры\n"
            f"• задержка примерно <b>{delay_minutes} минут</b> относительно PRO+\n\n"
            "🚀 <b>Если нужен полный режим</b>\n"
            "• PRO+ добавляет AI, risk-карточки и ранние сигналы\n"
            f"• новым пользователям доступен <b>{trial_days}-дневный триал</b>\n\n"
            "<b>Открыть PRO+</b>\n"
            f"{premium_target}\n\n"
            "⚠️ Всегда управляй риском самостоятельно."
        ) + channels_folder_note
    return (
        "<b>👋 Welcome to Syndicate Classic</b>\n\n"
        "This is the free layer with a cleaner, simpler signal feed.\n\n"
        "📦 <b>What is inside</b>\n"
        "• filtered alerts and selected follow-ups\n"
        "• manual ticker checks\n"
        "• watchlist and personal filters\n"
        f"• about <b>{delay_minutes} minutes</b> of delay vs PRO+\n\n"
        "🚀 <b>If you want the full flow</b>\n"
        "• PRO+ adds AI, risk cards, and earlier signals\n"
        f"• new users get a <b>{trial_days}-day trial</b>\n\n"
        "<b>Open PRO+</b>\n"
        f"{premium_target}\n\n"
        "⚠️ Always manage your own risk."
    ) + channels_folder_note


def format_start_message(
    *,
    variant: str | None = None,
    access_state_line: str | None = None,
    language_code: str = "en",
) -> str:
    del variant
    status = str(access_state_line or "").strip()
    if is_russian(language_code):
        lines = [
            "<b>RSI Syndicate · Syndicate PRO+</b>",
            "",
            "Бот сканирует рынок, отбирает сильные сетапы и показывает сигналы "
            "с графиком, стратегией, контекстом риска и follow-up.",
        ]
        if status:
            lines.extend(["", f"<b>Доступ:</b> {escape_html(status)}"])
        lines.extend(
            [
                "",
                "Продолжи с одного из быстрых действий ниже или открой полное меню.",
            ]
        )
        return "\n".join(lines)
    lines = [
        "<b>RSI Syndicate · Syndicate PRO+</b>",
        "",
        "The bot scans the market, filters stronger setups, and presents signals "
        "with chart, strategy, risk context, and follow-up.",
    ]
    if status:
        lines.extend(["", f"<b>Access:</b> {escape_html(status)}"])
    lines.extend(["", "Continue with a quick action below or open the full menu."])
    return "\n".join(lines)


def format_example_signal_message(*, language_code: str = "en") -> str:
    if is_russian(language_code):
        return (
            "<b>Пример сигнала</b>\n\n"
            "<i>Это демонстрация структуры, не живой сигнал и не финансовая рекомендация.</i>\n\n"
            "<b>[DEMO] BTCUSDT · 1h</b>\n"
            "Направление: <b>Long</b>\n"
            "Стратегия: <b>Breakout</b>\n"
            "Сила сетапа: <b>82/100</b>\n"
            "Зона наблюдения: <b>100–101</b>\n"
            "Инвалидация: <b>97</b>\n"
            "Ориентир: <b>108</b>\n\n"
            "<b>На что смотреть</b>\n"
            "• направление показывает сценарий, а не команду открыть сделку\n"
            "• зона наблюдения помогает понять, где сетап был найден\n"
            "• Invalidation показывает, где идея перестаёт быть актуальной\n"
            "• Follow-up позже сравнит цену и RSI с моментом сигнала\n\n"
            "График показывает момент появления сетапа и RSI-контекст. "
            "Follow-up позже сравнивает текущую цену и RSI с исходным сигналом.\n\n"
            "Числа вымышлены. Результат не гарантирован, решение пользователь принимает самостоятельно."
        )
    return (
        "<b>Example signal</b>\n\n"
        "<i>This is a demonstration of the structure, not a live signal and not financial advice.</i>\n\n"
        "<b>[DEMO] BTCUSDT · 1h</b>\n"
        "Direction: <b>Long</b>\n"
        "Strategy: <b>Breakout</b>\n"
        "Setup strength: <b>82/100</b>\n"
        "Reference zone: <b>100–101</b>\n"
        "Invalidation: <b>97</b>\n"
        "Target reference: <b>108</b>\n\n"
        "<b>What to notice</b>\n"
        "• direction is a scenario, not an order to trade\n"
        "• the reference zone shows where the setup was detected\n"
        "• Invalidation marks where the idea stops being valid\n"
        "• follow-up later compares price and RSI with the original alert\n\n"
        "The chart marks the setup moment and RSI context. "
        "A follow-up later compares current price and RSI with the original signal.\n\n"
        "All numbers are fictional. No result is guaranteed; you decide independently."
    )


def format_signal_reading_guide_message(*, language_code: str = "en") -> str:
    if is_russian(language_code):
        return (
            "<b>Как читать сигналы</b>\n\n"
            "<b>Читай в таком порядке</b>\n"
            "1. Пара, таймфрейм и направление.\n"
            "2. Стратегия и score.\n"
            "3. Entry / зона наблюдения, target и invalidation.\n"
            "4. График, RSI и рыночный контекст.\n"
            "5. Follow-up после сигнала.\n\n"
            "• <b>Пара</b> — инструмент, например BTCUSDT.\n"
            "• <b>Направление</b> — сценарий Long или Short, а не команда открыть сделку.\n"
            "• <b>Таймфрейм</b> — период свечей, на котором найден сетап.\n"
            "• <b>Стратегия</b> — рыночная логика, вызвавшая сигнал.\n"
            "• <b>Зона входа / наблюдения</b> — ориентир, если он доступен.\n"
            "• <b>Target и invalidation</b> — ориентир сценария и условие его отмены, не гарантия TP/SL.\n"
            "• <b>Score и риск</b> — качество условий и контекст, а не вероятность прибыли.\n"
            "• <b>График</b> — цена, RSI и точка появления сигнала.\n"
            "• <b>Follow-up</b> — что произошло с ценой и RSI после сигнала.\n\n"
            "<b>После сигнала</b>\n"
            "Follow-up не доказывает будущую эффективность. Он показывает, как именно развился конкретный сетап.\n\n"
            "<b>Важно:</b> крипторынок рискован. Прошлые результаты не гарантируют будущие. "
            "Сигналы дают аналитический контекст, а решение пользователь принимает самостоятельно."
        )
    return (
        "<b>How to read signals</b>\n\n"
        "<b>Read it in this order</b>\n"
        "1. Symbol, timeframe, and direction.\n"
        "2. Strategy and score.\n"
        "3. Entry/reference zone, target, and invalidation.\n"
        "4. Chart, RSI, and market context.\n"
        "5. Follow-up after the signal.\n\n"
        "• <b>Symbol</b> — the instrument, for example BTCUSDT.\n"
        "• <b>Direction</b> — a Long or Short scenario, not an order to trade.\n"
        "• <b>Timeframe</b> — the candle period where the setup was detected.\n"
        "• <b>Strategy</b> — the market logic behind the trigger.\n"
        "• <b>Entry / reference zone</b> — an analytical area when available.\n"
        "• <b>Target and invalidation</b> — scenario references, not guaranteed TP/SL.\n"
        "• <b>Score and risk</b> — setup quality and context, not profit probability.\n"
        "• <b>Chart</b> — price, RSI, and the signal marker.\n"
        "• <b>Follow-up</b> — what happened to price and RSI after the alert.\n\n"
        "<b>After the signal</b>\n"
        "Follow-up does not prove future performance. It only shows how that specific setup developed.\n\n"
        "<b>Important:</b> crypto markets are risky. Past results do not guarantee future results. "
        "Signals provide analytical context; you decide independently. No result is guaranteed."
    )


def format_classic_start_message(*, delay_minutes: int = 30, language_code: str = "en") -> str:
    if is_russian(language_code):
        return (
            "<b>С возвращением в Syndicate Classic</b>\n\n"
            "Classic продолжает следить за рынком и показывает базовый, более спокойный поток "
            f"с задержкой примерно <b>{delay_minutes} минут</b> относительно PRO+.\n\n"
            "<b>Доступно сейчас</b>\n"
            "• последние Classic-сигналы\n"
            "• пример карточки и инструкция\n"
            "• результаты и настройки уведомлений\n"
            "• понятное сравнение Classic и PRO+\n\n"
            "Выбери действие ниже. Сигналы носят информационный характер и не являются финансовой рекомендацией."
        )
    return (
        "<b>Welcome back to Syndicate Classic</b>\n\n"
        "Classic keeps scanning the market and provides a basic, calmer signal flow "
        f"with about <b>{delay_minutes} minutes</b> of delay compared with PRO+.\n\n"
        "<b>Available now</b>\n"
        "• Latest Classic Signals\n"
        "• example card and reading guide\n"
        "• results and notification settings\n"
        "• a clear Classic vs PRO+ comparison\n\n"
        "Choose an action below. Signals are informational and are not financial advice."
    )


def format_classic_vs_pro_message(*, delay_minutes: int = 30, language_code: str = "en") -> str:
    if is_russian(language_code):
        return (
            "<b>Classic vs PRO+</b>\n\n"
            "<b>Syndicate Classic</b>\n"
            "• базовый и более спокойный поток\n"
            f"• сигналы могут приходить примерно на {delay_minutes} минут позже\n"
            "• меньше контекста и продвинутых инструментов\n\n"
            "<b>Syndicate PRO+</b>\n"
            "• более ранние сигналы и полный поток\n"
            "• расширенный контекст, AI-разбор и risk-карточки\n"
            "• follow-up, персональные настройки и рабочие режимы\n\n"
            "Оба режима используют фильтры качества, но ни один сигнал не гарантирует результат. "
            "Это аналитический инструмент, а не финансовая рекомендация."
        )
    return (
        "<b>Classic vs PRO+</b>\n\n"
        "<b>Syndicate Classic</b>\n"
        "• a basic, calmer signal flow\n"
        f"• alerts are delayed by about {delay_minutes} minutes compared with PRO+\n"
        "• less context and fewer advanced tools\n\n"
        "<b>Syndicate PRO+</b>\n"
        "• earlier alerts and the fuller signal flow\n"
        "• deeper context, AI analysis, and risk cards\n"
        "• follow-ups, personal settings, and workspaces\n\n"
        "Both tiers use quality filters, but no signal guarantees an outcome. "
        "This is an analytical tool, not financial advice."
    )


def format_help_page_message(
    page: str,
    *,
    language_code: str = "en",
    delay_minutes: int = 30,
    support_target: str | None = None,
) -> str:
    key = str(page or "").strip().lower()
    support = escape_html(str(support_target or "").strip())
    if key == "compare":
        return format_classic_vs_pro_message(
            delay_minutes=delay_minutes,
            language_code=language_code,
        )
    if is_russian(language_code):
        pages = {
            "quick_start": (
                "<b>Быстрый старт</b>\n\n"
                "1. Открой «Сильные сетапы» или «Свежие сигналы».\n"
                "2. Для ручной проверки отправь <b>BTC</b> или <b>ETH 1h</b>.\n"
                "3. Проверь направление, уровни, invalidation и риск.\n"
                "4. Настрой уведомления и watchlist под себя."
            ),
            "no_signals": (
                "<b>Почему сейчас может не быть сигналов</b>\n\n"
                "Это не ошибка: фильтры качества могли не пропустить слабые или шумные условия. "
                "Сканирование продолжается. Пока можно открыть пример сигнала, посмотреть результаты "
                "или дождаться следующего рыночного цикла."
            ),
            "risk": (
                "<b>Риск</b>\n\n"
                "Крипторынок волатилен, и любой сетап может быстро сломаться. Сигналы носят "
                "информационный характер и не являются финансовой рекомендацией. Бот может ошибаться; "
                "решение принимает пользователь. Прошлые результаты не гарантируют будущие. "
                "Всегда используй собственный риск-менеджмент."
            ),
            "notifications": (
                "<b>Уведомления</b>\n\n"
                "Здесь можно включить или выключить сигналы и follow-up, выбрать режим доставки, "
                "тихие часы и уровень шума. Если всё выключено, карточки не приходят автоматически."
            ),
            "access": (
                "<b>Trial и доступ</b>\n\n"
                "Текущий статус и срок отображаются в «Мой доступ». Classic остаётся базовым слоем, "
                "а PRO+ открывает более ранний поток, расширенный контекст и персональные инструменты."
            ),
            "ai": (
                "<b>Что делает AI-разбор</b>\n\n"
                "AI помогает структурировать доступный контекст по тикеру и объяснить сетап понятнее. "
                "Это дополнительное мнение, а не предсказание прибыли и не команда открыть сделку."
            ),
            "gold": (
                "<b>Gold Desk</b>\n\n"
                "Раздел показывает доступные XAUUSD-сетапы и рыночный контекст. Если рынок закрыт "
                "или данных нет, бот сообщает об этом без вымышленных уровней."
            ),
            "support": (
                "<b>Поддержка</b>\n\n"
                + (
                    f"Официальный канал поддержки: {support}"
                    if support
                    else "Используй официальный канал поддержки, настроенный владельцем. "
                    "Если он пока не указан, открой «Мой доступ» или «Статус бота» и повтори действие позже."
                )
            ),
            "commands": (
                "<b>Команды</b>\n\n"
                "<code>/start</code> стартовый экран\n"
                "<code>/last</code> последние сигналы\n"
                "<code>/strong</code> сильные сетапы\n"
                "<code>/menu</code> главное меню\n"
                "<code>/lang</code> сменить язык"
            ),
            "results": (
                "<b>Как считаются результаты</b>\n\n"
                "Результаты основаны на сохранённых lifecycle-статусах и follow-up. "
                "Сломанные и истёкшие сигналы остаются видимыми и не считаются успехом. "
                "Прошлые результаты не гарантируют будущие."
            ),
            "example_followup": (
                "<b>Пример follow-up</b>\n\n"
                "<i>Демонстрация, не реальный результат.</i>\n\n"
                "BTCUSDT · 1h\n"
                "На сигнале: 100 → Сейчас: 103\n"
                "Итог: развивается благоприятно\n"
                "Интерпретация: движение идёт по сценарию сигнала.\n\n"
                "Один follow-up не доказывает будущую эффективность."
            ),
            "more": (
                "<b>Ещё разделы помощи</b>\n\n"
                "Здесь собраны вторичные темы: уведомления, AI-разбор, Gold Desk, команды, методология результатов и пример follow-up."
            ),
        }
    else:
        pages = {
            "quick_start": (
                "<b>Quick Start</b>\n\n"
                "1. Open Strong Setups or Fresh Signals.\n"
                "2. Send <b>BTC</b> or <b>ETH 1h</b> for a manual check.\n"
                "3. Review direction, levels, invalidation, and risk.\n"
                "4. Tune notifications and your watchlist."
            ),
            "no_signals": (
                "<b>Why there may be no signals now</b>\n\n"
                "This is not an error: the quality filters may be rejecting weak or noisy market conditions. "
                "Scanning is still active. Open the example signal, review results, or wait for the next market cycle."
            ),
            "risk": (
                "<b>Risk</b>\n\n"
                "Crypto markets are volatile and any setup can invalidate quickly. Signals are informational "
                "and not financial advice. The bot can be wrong; you make the decision. "
                "Past results do not guarantee future results. Always use independent risk management."
            ),
            "notifications": (
                "<b>Notifications</b>\n\n"
                "Enable or disable signals and follow-ups, choose delivery mode, quiet hours, and noise level. "
                "When everything is disabled, cards will not arrive automatically."
            ),
            "access": (
                "<b>Trial and access basics</b>\n\n"
                "Your current status and end time are shown in My Access. Classic remains the basic layer, "
                "while PRO+ adds earlier flow, deeper context, and personal tools."
            ),
            "ai": (
                "<b>What AI analysis does</b>\n\n"
                "AI analysis helps structure available ticker context and explain a setup more clearly. "
                "Use it as an additional explanation, not a profit prediction or a trade command."
            ),
            "gold": (
                "<b>Gold Desk</b>\n\n"
                "Gold Desk presents available XAUUSD setups and market context. If the market is closed "
                "or data is unavailable, the bot reports that without inventing levels."
            ),
            "support": (
                "<b>Support</b>\n\n"
                + (
                    f"Official support channel: {support}"
                    if support
                    else "Use the official support channel configured by the owner. "
                    "If none is shown yet, open My Access or Bot Status and retry the action later."
                )
            ),
            "commands": (
                "<b>Commands</b>\n\n"
                "<code>/start</code> start screen\n"
                "<code>/last</code> latest signals\n"
                "<code>/strong</code> strong setups\n"
                "<code>/menu</code> main menu\n"
                "<code>/lang</code> switch language"
            ),
            "results": (
                "<b>How results are calculated</b>\n\n"
                "Results use recorded lifecycle statuses and follow-ups. Invalidated and expired signals "
                "remain visible and are not counted as success. Past results do not guarantee future results."
            ),
            "example_followup": (
                "<b>Example follow-up</b>\n\n"
                "<i>Demonstration only, not a real result.</i>\n\n"
                "BTCUSDT · 1h\n"
                "Alert: 100 → Now: 103\n"
                "Outcome: developing favorably\n"
                "Interpretation: moved in the direction of the signal.\n\n"
                "One follow-up does not prove future performance."
            ),
            "more": (
                "<b>More Help Topics</b>\n\n"
                "Secondary topics live here: notifications, AI analysis, Gold Desk, commands, result methodology, and an example follow-up."
            ),
        }
    return pages.get(key, pages["quick_start"])


def format_help_message(*, language_code: str = "en") -> str:
    if is_russian(language_code):
        return (
            "<b>Помощь</b>\n\n"
            "🎯 <b>Быстрый старт</b>\n"
            "Отправь <b>BTC</b>, <b>ETH 1h</b> или <b>XAUUSD</b> и бот сразу откроет разбор по инструменту.\n"
            "Используй <b>+BTC</b> и <b>-BTC</b>, чтобы управлять своим списком монет.\n\n"
            "⚙️ <b>Главное в меню</b>\n"
            "<b>Свежие сигналы</b> - новые сетапы под твои фильтры\n"
            "<b>Фильтры сигналов</b> - RSI, объем, направление, список монет и золото\n"
            "<b>Мой доступ</b> - trial, подписка и продление\n\n"
            "⌨️ <b>Полезные команды</b>\n"
            "<code>/last</code> последние сигналы\n"
            "<code>/strong</code> сильные сетапы\n"
            "<code>/analyze BTC 1h</code> ручной анализ\n"
            "<code>/menu</code> открыть меню\n"
            "<code>/lang</code> сменить язык"
        )
    return (
        "<b>Help</b>\n\n"
        "🎯 <b>Quick start</b>\n"
        "Send <b>BTC</b>, <b>ETH 1h</b>, or <b>XAUUSD</b> and the bot will open a symbol analysis.\n"
        "Use <b>+BTC</b> and <b>-BTC</b> to manage your coin list.\n\n"
        "⚙️ <b>Main sections</b>\n"
        "<b>Fresh Signals</b> for new setups\n"
        "<b>Signal Filters</b> for RSI, volume, direction, your coin list, and gold\n"
        "<b>My Access</b> for trial, subscription, and renewal\n\n"
        "⌨️ <b>Useful commands</b>\n"
        "<code>/last</code> recent signals\n"
        "<code>/strong</code> strongest setups\n"
        "<code>/analyze BTC 1h</code> manual analysis\n"
        "<code>/menu</code> open menu\n"
        "<code>/lang</code> switch language"
    )


def format_help_message(*, language_code: str = "en") -> str:
    if is_russian(language_code):
        return (
            "<b>Помощь</b>\n\n"
            "Быстрый ориентир по основным действиям и командам.\n\n"
            "<b>С чего начать</b>\n"
            "Отправь <b>BTC</b>, <b>ETH 1h</b> или <b>XAUUSD</b>, чтобы открыть свежий разбор.\n"
            "Используй <b>+BTC</b> и <b>-BTC</b>, чтобы быстро управлять своим watchlist.\n\n"
            "<b>Куда смотреть</b>\n"
            "• <b>Today</b> для персональной сводки\n"
            "• <b>Signals</b> для новых сетапов и follow-up\n"
            "• <b>Results</b> для прозрачной статистики и жизненного цикла\n"
            "• <b>My Access</b> для статуса плана и включённых возможностей\n\n"
            "<b>Быстрые команды</b>\n"
            "<code>/last</code> последние сигналы\n"
            "<code>/strong</code> сильные сетапы\n"
            "<code>/menu</code> меню\n"
            "<code>/lang</code> язык"
        )
    return (
        "<b>Help</b>\n\n"
        "A quick guide to the main flows and commands.\n\n"
        "<b>Start Here</b>\n"
        "Send <b>BTC</b>, <b>ETH 1h</b>, or <b>XAUUSD</b> to open a fresh symbol read.\n"
        "Use <b>+BTC</b> and <b>-BTC</b> to manage your watchlist in one step.\n\n"
        "<b>Where To Go</b>\n"
        "• <b>Today</b> for your personalized dashboard\n"
        "• <b>Signals</b> for new setups and follow-ups\n"
        "• <b>Results</b> for transparent outcome review\n"
        "• <b>My Access</b> for plan status and enabled premium tools\n\n"
        "<b>Quick Commands</b>\n"
        "<code>/last</code> recent signals\n"
        "<code>/strong</code> strong setups\n"
        "<code>/menu</code> menu\n"
        "<code>/lang</code> language"
    )


def format_classic_help_message(*, delay_minutes: int = 30, language_code: str = "en") -> str:
    if is_russian(language_code):
        return (
            "<b>Помощь</b>\n\n"
            "🎯 <b>Быстрый старт</b>\n"
            "Отправь <b>BTC</b>, <b>ETH 1h</b> или <b>XAUUSD</b> и бот откроет карточку тикера.\n"
            "Используй <b>+BTC</b> и <b>-BTC</b>, чтобы управлять watchlist.\n\n"
            "⚙️ <b>Что важно</b>\n"
            "<b>Последние сигналы</b> - свежие classic-сетапы\n"
            "<b>Фильтры сигналов</b> - RSI, объем, направление и watchlist\n"
            f"Classic приходит примерно на <b>{delay_minutes} минут позже</b>, чем PRO+\n\n"
            "⌨️ <b>Полезные команды</b>\n"
            "<code>/last</code> последние сигналы\n"
            "<code>/analyze BTC 1h</code> ручной анализ\n"
            "<code>/menu</code> открыть меню\n"
            "<code>/lang</code> сменить язык\n\n"
            "AI Analysis и часть продвинутых карточек открываются через PRO+."
        )
    return (
        "<b>Help</b>\n\n"
        "🎯 <b>Quick start</b>\n"
        "Send <b>BTC</b>, <b>ETH 1h</b>, or <b>XAUUSD</b> and the bot will open a symbol card.\n"
        "Use <b>+BTC</b> and <b>-BTC</b> to manage your watchlist.\n\n"
        "⚙️ <b>What matters</b>\n"
        "<b>Latest Signals</b> for fresh classic setups\n"
        "<b>Signal Filters</b> for RSI, volume, direction, and watchlist\n"
        f"Classic alerts arrive about <b>{delay_minutes} minutes later</b> than PRO+\n\n"
        "⌨️ <b>Useful commands</b>\n"
        "<code>/last</code> recent signals\n"
        "<code>/analyze BTC 1h</code> manual analysis\n"
        "<code>/menu</code> open menu\n"
        "<code>/lang</code> switch language\n\n"
        "AI Analysis and some advanced cards are available in PRO+."
    )


def format_access_message(
    *,
    access_level: str,
    access_state_line: str,
    signal_profile: str,
    min_score_label: str,
    min_quote_volume_label: str,
    rsi_window_label: str,
    direction_label: str,
    watchlist_summary: str,
    direct_delivery_enabled: bool,
    followup_delivery_enabled: bool,
    gold_alerts_enabled: bool,
    language_code: str = "en",
) -> str:
    if is_russian(language_code):
        delivery_text = "включено" if direct_delivery_enabled else "выключено"
        followup_text = "включено" if followup_delivery_enabled else "выключено"
        gold_text = "включено" if gold_alerts_enabled else "выключено"
        return (
            "<b>🔐 Мой доступ</b>\n\n"
            "💼 <b>Аккаунт</b>\n"
            f"• Уровень: <b>{escape_html(access_level)}</b>\n"
            f"• {escape_html(access_state_line)}\n\n"
            "📬 <b>Доставка</b>\n"
            f"• Алерты: <b>{delivery_text}</b>\n"
            f"• Фоллоу-апы: <b>{followup_text}</b>\n"
            f"• Золото: <b>{gold_text}</b>\n\n"
            "⚙️ <b>Твои фильтры</b>\n"
            f"• Профиль: <b>{escape_html(signal_profile)}</b>\n"
            f"• Мин. score: <b>{escape_html(min_score_label)}</b>\n"
            f"• Мин. объем: <b>{escape_html(min_quote_volume_label)}</b>\n"
            f"• RSI: <b>{escape_html(rsi_window_label)}</b>\n"
            f"• Направление: <b>{escape_html(direction_label)}</b>\n"
            f"• Watchlist: <b>{escape_html(watchlist_summary)}</b>"
        )
    delivery_text = "enabled" if direct_delivery_enabled else "disabled"
    followup_text = "enabled" if followup_delivery_enabled else "disabled"
    gold_text = "enabled" if gold_alerts_enabled else "disabled"
    return (
        "<b>🔐 My Access</b>\n\n"
        "💼 <b>Account</b>\n"
        f"• Level: <b>{escape_html(access_level)}</b>\n"
        f"• {escape_html(access_state_line)}\n\n"
        "📬 <b>Delivery</b>\n"
        f"• Alerts: <b>{delivery_text}</b>\n"
        f"• Follow-ups: <b>{followup_text}</b>\n"
        f"• Gold: <b>{gold_text}</b>\n\n"
        "⚙️ <b>Your Filters</b>\n"
        f"• Profile: <b>{escape_html(signal_profile)}</b>\n"
        f"• Min score: <b>{escape_html(min_score_label)}</b>\n"
        f"• Min volume: <b>{escape_html(min_quote_volume_label)}</b>\n"
        f"• RSI: <b>{escape_html(rsi_window_label)}</b>\n"
        f"• Direction: <b>{escape_html(direction_label)}</b>\n"
        f"• Watchlist: <b>{escape_html(watchlist_summary)}</b>"
    )


def format_access_message(
    *,
    access_level: str,
    access_state_line: str,
    user_label: str | None = None,
    enabled_notifications: list[str] | None = None,
    enabled_strategies: list[str] | None = None,
    delivery_mode_label: str | None = None,
    language_code: str = "en",
    **_: object,
) -> str:
    notifications = ", ".join(enabled_notifications or [])
    strategies = ", ".join(enabled_strategies or [])
    user_line = user_label or "-"
    delivery_line = delivery_mode_label or "-"
    if is_russian(language_code):
        return (
            "<b>Мой доступ</b>\n\n"
            "Твой план, активные premium-возможности и текущая конфигурация.\n\n"
            "<b>Аккаунт</b>\n"
            f"• <b>{escape_html(user_line)}</b>\n"
            f"• Уровень: <b>{escape_html(access_level)}</b>\n"
            f"• {escape_html(access_state_line)}\n\n"
            "<b>Что активно</b>\n"
            f"• Уведомления: <b>{escape_html(notifications or 'пока ничего')}</b>\n"
            f"• Стратегии: <b>{escape_html(strategies or 'не выбраны')}</b>\n"
            f"• Режим доставки: <b>{escape_html(delivery_line)}</b>\n\n"
            "Открой детали плана, referral или продление через кнопки ниже."
        )
    return (
        "<b>My Access</b>\n\n"
        "Your plan, enabled premium tools, and current setup at a glance.\n\n"
        "<b>Account</b>\n"
        f"• <b>{escape_html(user_line)}</b>\n"
        f"• Level: <b>{escape_html(access_level)}</b>\n"
        f"• {escape_html(access_state_line)}\n\n"
        "<b>What Is Active</b>\n"
        f"• Notifications: <b>{escape_html(notifications or 'nothing enabled')}</b>\n"
        f"• Strategies: <b>{escape_html(strategies or 'not selected')}</b>\n"
        f"• Delivery Mode: <b>{escape_html(delivery_line)}</b>\n\n"
        "Use the buttons below for plan details, referral, renewal, or support."
    )


def format_classic_access_message(
    *,
    access_label: str,
    access_state_line: str,
    signal_profile: str,
    min_score_label: str,
    min_quote_volume_label: str,
    rsi_window_label: str,
    direction_label: str,
    watchlist_summary: str,
    direct_delivery_enabled: bool,
    followup_delivery_enabled: bool,
    trial_days: int,
    delay_minutes: int,
    language_code: str = "en",
) -> str:
    if is_russian(language_code):
        delivery_text = "включено" if direct_delivery_enabled else "выключено"
        followup_text = "включено" if followup_delivery_enabled else "выключено"
        return (
            "<b>🔐 Мой доступ</b>\n\n"
            "💼 <b>Режим</b>\n"
            "• Classic\n"
            f"• Доступ: <b>{escape_html(access_label)}</b>\n"
            f"• {escape_html(access_state_line)}\n\n"
            "📬 <b>Доставка</b>\n"
            f"• Алерты: <b>{delivery_text}</b>\n"
            f"• Фоллоу-апы: <b>{followup_text}</b>\n\n"
            "⚙️ <b>Твои фильтры</b>\n"
            f"• Профиль: <b>{escape_html(signal_profile)}</b>\n"
            f"• Мин. score: <b>{escape_html(min_score_label)}</b>\n"
            f"• Мин. объем: <b>{escape_html(min_quote_volume_label)}</b>\n"
            f"• RSI: <b>{escape_html(rsi_window_label)}</b>\n"
            f"• Направление: <b>{escape_html(direction_label)}</b>\n"
            f"• Watchlist: <b>{escape_html(watchlist_summary)}</b>\n\n"
            f"ℹ️ Classic идет примерно на <b>{delay_minutes} минут позже</b>, чем PRO+.\n"
            f"🎁 Новым пользователям доступен <b>{trial_days}-дневный триал</b> в PRO+."
        )
    delivery_text = "enabled" if direct_delivery_enabled else "disabled"
    followup_text = "enabled" if followup_delivery_enabled else "disabled"
    return (
        "<b>🔐 My Access</b>\n\n"
        "💼 <b>Mode</b>\n"
        "• Classic\n"
        f"• Access: <b>{escape_html(access_label)}</b>\n"
        f"• {escape_html(access_state_line)}\n\n"
        "📬 <b>Delivery</b>\n"
        f"• Alerts: <b>{delivery_text}</b>\n"
        f"• Follow-ups: <b>{followup_text}</b>\n\n"
        "⚙️ <b>Your Filters</b>\n"
        f"• Profile: <b>{escape_html(signal_profile)}</b>\n"
        f"• Min score: <b>{escape_html(min_score_label)}</b>\n"
        f"• Min volume: <b>{escape_html(min_quote_volume_label)}</b>\n"
        f"• RSI: <b>{escape_html(rsi_window_label)}</b>\n"
        f"• Direction: <b>{escape_html(direction_label)}</b>\n"
        f"• Watchlist: <b>{escape_html(watchlist_summary)}</b>\n\n"
        f"ℹ️ Classic runs about <b>{delay_minutes} minutes later</b> than PRO+.\n"
        f"🎁 New users get a <b>{trial_days}-day PRO+ trial</b>."
    )


def format_status_message(
    *,
    timeframe: str,
    access_state_line: str,
    signal_profile: str,
    watchlist_summary: str,
    alerts_delivery_enabled: bool,
    followups_delivery_enabled: bool,
    gold_alerts_enabled: bool,
    access_label: str,
    alerts_last_24h: int,
    followups_last_24h: int,
    last_signal_label: str,
    language_code: str = "en",
) -> str:
    if is_russian(language_code):
        alerts_state = "ВКЛ" if alerts_delivery_enabled else "ВЫКЛ"
        followups_state = "ВКЛ" if followups_delivery_enabled else "ВЫКЛ"
        gold_state = "ВКЛ" if gold_alerts_enabled else "ВЫКЛ"
        return (
            "<b>📡 Статус бота</b>\n\n"
            "🟢 <b>Мониторинг</b>\n"
            "• Статус: <b>Live</b>\n"
            f"• Таймфрейм: <b>{escape_html(timeframe)}</b>\n"
            f"• Доступ: <b>{escape_html(access_label)}</b>\n"
            f"• {escape_html(access_state_line)}\n\n"
            "📬 <b>Доставка</b>\n"
            f"• Алерты: <b>{alerts_state}</b>\n"
            f"• Фоллоу-апы: <b>{followups_state}</b>\n"
            f"• Золото: <b>{gold_state}</b>\n\n"
            "📊 <b>Твой поток</b>\n"
            f"• Профиль: <b>{escape_html(signal_profile)}</b>\n"
            f"• Watchlist: <b>{escape_html(watchlist_summary)}</b>\n"
            f"• Алертов за 24ч: <b>{alerts_last_24h}</b>\n"
            f"• Follow-up за 24ч: <b>{followups_last_24h}</b>\n"
            f"• Последний сигнал: <b>{escape_html(last_signal_label)}</b>"
        )
    alerts_state = "ON" if alerts_delivery_enabled else "OFF"
    followups_state = "ON" if followups_delivery_enabled else "OFF"
    gold_state = "ON" if gold_alerts_enabled else "OFF"
    return (
        "<b>📡 Bot Status</b>\n\n"
        "🟢 <b>Monitoring</b>\n"
        "• Status: <b>Live</b>\n"
        f"• Timeframe: <b>{escape_html(timeframe)}</b>\n"
        f"• Access: <b>{escape_html(access_label)}</b>\n"
        f"• {escape_html(access_state_line)}\n\n"
        "📬 <b>Delivery</b>\n"
        f"• Alerts: <b>{alerts_state}</b>\n"
        f"• Follow-ups: <b>{followups_state}</b>\n"
        f"• Gold: <b>{gold_state}</b>\n\n"
        "📊 <b>Your Feed</b>\n"
        f"• Profile: <b>{escape_html(signal_profile)}</b>\n"
        f"• Watchlist: <b>{escape_html(watchlist_summary)}</b>\n"
        f"• Alerts in 24h: <b>{alerts_last_24h}</b>\n"
        f"• Follow-ups in 24h: <b>{followups_last_24h}</b>\n"
        f"• Last signal: <b>{escape_html(last_signal_label)}</b>"
    )


def format_status_message(
    *,
    timeframe: str,
    access_state_line: str,
    access_label: str,
    alerts_last_24h: int,
    followups_last_24h: int,
    last_signal_label: str,
    feed_label: str | None = None,
    alerts_state_label: str | None = None,
    followups_state_label: str | None = None,
    gold_state_label: str | None = None,
    language_code: str = "en",
    **_: object,
) -> str:
    if is_russian(language_code):
        return (
            "<b>Статус бота</b>\n\n"
            "Короткая сводка по текущему состоянию потока и доставке.\n\n"
            "<b>Сейчас</b>\n"
            f"• Таймфрейм: <b>{escape_html(timeframe)}</b>\n"
            f"• Доступ: <b>{escape_html(access_label)}</b>\n"
            f"• {escape_html(access_state_line)}\n\n"
            "<b>Доставка</b>\n"
            f"• Signals: <b>{escape_html(alerts_state_label or '-')}</b>\n"
            f"• Follow-up: <b>{escape_html(followups_state_label or '-')}</b>\n"
            f"• Gold: <b>{escape_html(gold_state_label or '-')}</b>\n\n"
            "<b>Твой поток</b>\n"
            f"• Активные стратегии: <b>{escape_html(feed_label or '-')}</b>\n"
            f"• Signals за 24ч: <b>{alerts_last_24h}</b>\n"
            f"• Follow-up за 24ч: <b>{followups_last_24h}</b>\n"
            f"• Последний сигнал: <b>{escape_html(last_signal_label)}</b>"
        )
    return (
        "<b>Bot Status</b>\n\n"
        "A quick view of your live flow, delivery state, and recent activity.\n\n"
        "<b>Current State</b>\n"
        f"• Timeframe: <b>{escape_html(timeframe)}</b>\n"
        f"• Access: <b>{escape_html(access_label)}</b>\n"
        f"• {escape_html(access_state_line)}\n\n"
        "<b>Delivery</b>\n"
        f"• Alerts: <b>{escape_html(alerts_state_label or '-')}</b>\n"
        f"• Follow-ups: <b>{escape_html(followups_state_label or '-')}</b>\n"
        f"• Gold: <b>{escape_html(gold_state_label or '-')}</b>\n\n"
        "<b>Your Flow</b>\n"
        f"• Active Strategies: <b>{escape_html(feed_label or '-')}</b>\n"
        f"• Alerts in 24h: <b>{alerts_last_24h}</b>\n"
        f"• Follow-ups in 24h: <b>{followups_last_24h}</b>\n"
        f"• Last signal: <b>{escape_html(last_signal_label)}</b>"
    )


def format_classic_status_message(
    *,
    timeframe: str,
    access_state_line: str,
    signal_profile: str,
    watchlist_summary: str,
    alerts_delivery_enabled: bool,
    followups_delivery_enabled: bool,
    access_label: str,
    alerts_last_24h: int,
    followups_last_24h: int,
    last_signal_label: str,
    delay_minutes: int,
    language_code: str = "en",
) -> str:
    if is_russian(language_code):
        alerts_state = "ВКЛ" if alerts_delivery_enabled else "ВЫКЛ"
        followups_state = "ВКЛ" if followups_delivery_enabled else "ВЫКЛ"
        return (
            "<b>📡 Статус бота</b>\n\n"
            "🟢 <b>Мониторинг</b>\n"
            "• Статус: <b>Live</b>\n"
            f"• Таймфрейм: <b>{escape_html(timeframe)}</b>\n"
            f"• Доступ: <b>{escape_html(access_label)}</b>\n"
            f"• {escape_html(access_state_line)}\n\n"
            "📬 <b>Доставка</b>\n"
            f"• Classic-алерты: <b>{alerts_state}</b>\n"
            f"• Classic follow-up: <b>{followups_state}</b>\n\n"
            "📊 <b>Твой поток</b>\n"
            f"• Профиль: <b>{escape_html(signal_profile)}</b>\n"
            f"• Watchlist: <b>{escape_html(watchlist_summary)}</b>\n"
            f"• Сигналов за 24ч: <b>{alerts_last_24h}</b>\n"
            f"• Follow-up за 24ч: <b>{followups_last_24h}</b>\n"
            f"• Последний сигнал: <b>{escape_html(last_signal_label)}</b>\n\n"
            f"ℹ️ Classic идет примерно на <b>{delay_minutes} минут позже</b>, чем PRO+."
        )
    alerts_state = "ON" if alerts_delivery_enabled else "OFF"
    followups_state = "ON" if followups_delivery_enabled else "OFF"
    return (
        "<b>📡 Bot Status</b>\n\n"
        "🟢 <b>Monitoring</b>\n"
        "• Status: <b>Live</b>\n"
        f"• Timeframe: <b>{escape_html(timeframe)}</b>\n"
        f"• Access: <b>{escape_html(access_label)}</b>\n"
        f"• {escape_html(access_state_line)}\n\n"
        "📬 <b>Delivery</b>\n"
        f"• Classic alerts: <b>{alerts_state}</b>\n"
        f"• Classic follow-ups: <b>{followups_state}</b>\n\n"
        "📊 <b>Your Feed</b>\n"
        f"• Profile: <b>{escape_html(signal_profile)}</b>\n"
        f"• Watchlist: <b>{escape_html(watchlist_summary)}</b>\n"
        f"• Signals in 24h: <b>{alerts_last_24h}</b>\n"
        f"• Follow-ups in 24h: <b>{followups_last_24h}</b>\n"
        f"• Last signal: <b>{escape_html(last_signal_label)}</b>\n\n"
        f"ℹ️ Classic runs about <b>{delay_minutes} minutes later</b> than PRO+."
    )


def format_empty_signals_message(*, strong_only: bool, language_code: str = "en") -> str:
    if is_russian(language_code):
        if strong_only:
            return (
                "<b>📭 Пока пусто</b>\n\n"
                "Сильных сетапов под твои фильтры сейчас нет.\n\n"
                "Это нормально: фильтры пропускают слабые рыночные условия, и бот продолжает сканирование. "
                "Можно открыть пример сигнала, результаты или дождаться следующего цикла."
            )
        return (
            "<b>📭 Пока пусто</b>\n\n"
            "Недавних карточек сигналов сейчас нет.\n\n"
            "Бот продолжает сканирование. Открой пример сигнала или проверь снова после следующего цикла."
        )
    if strong_only:
        return (
            "<b>📭 Nothing yet</b>\n\n"
            "No strong setups matched your current filters.\n\n"
            "That is intentional: quality filters skip weak market conditions while scanning continues. "
            "Open the example signal, review results, or wait for the next cycle."
        )
    return (
        "<b>📭 Nothing yet</b>\n\n"
        "No recent signal cards are available right now.\n\n"
        "Scanning is still active. Open the example signal or try again after the next cycle."
    )


def format_pro_link_message(*, pro_channel: str, language_code: str = "en") -> str:
    if is_russian(language_code):
        return (
            "<b>📣 PRO канал</b>\n\n"
            f"Ссылка: {escape_html(pro_channel)}\n\n"
            "Приватный бот нужен для настроек, AI и интерактивных карточек.\n"
            "Канал оставь как фоновую ленту, если так удобнее."
        )
    return (
        "<b>📣 PRO Channel</b>\n\n"
        f"Link: {escape_html(pro_channel)}\n\n"
        "Use the private bot for settings, AI, and interactive cards.\n"
        "Keep the channel as a background feed if you want a passive stream."
    )


def format_premium_upsell_message(*, feature_name: str, trial_days: int, language_code: str = "en") -> str:
    if is_russian(language_code):
        return (
            f"<b>🔒 {escape_html(feature_name)} доступен в Syndicate PRO+</b>\n\n"
            "В PRO+ открываются:\n"
            "• AI и более глубокий контекст\n"
            "• risk-карточки и follow-up\n"
            "• ранние сигналы без задержки\n\n"
            f"Новые пользователи получают <b>{trial_days}-дневный триал</b>."
        )
    return (
        f"<b>🔒 {escape_html(feature_name)} is available in Syndicate PRO+</b>\n\n"
        "Inside PRO+ you get:\n"
        "• AI and deeper signal context\n"
        "• risk cards and follow-ups\n"
        "• earlier signals without delay\n\n"
        f"New users get a <b>{trial_days}-day trial</b>."
    )


def format_signal_setup_message(
    *,
    profile_label: str,
    base_profile_label: str,
    profile_is_custom: bool,
    min_score_label: str,
    min_quote_volume_label: str,
    lower_rsi_label: str,
    upper_rsi_label: str,
    rsi_mode_label: str,
    direction_label: str,
    universe_label: str,
    gold_alerts_label: str | None = None,
    language_code: str = "en",
) -> str:
    if is_russian(language_code):
        lines = [
            "<b>🎛 Фильтры сигналов</b>",
            "",
            "Настрой, какие сетапы бот должен считать подходящими именно для тебя.",
            "",
            "🧩 <b>Профиль</b>",
            f"• Профиль: <b>{escape_html(profile_label)}</b>",
        ]
        if profile_is_custom:
            lines.append(f"• База: <b>{escape_html(base_profile_label)}</b>")
        lines.extend(
            [
                f"• Порог качества: <b>{escape_html(min_score_label)}</b>",
                "",
                "📉 <b>RSI</b>",
                f"• Нижний: <b>{escape_html(lower_rsi_label)}</b>",
                f"• Верхний: <b>{escape_html(upper_rsi_label)}</b>",
                f"• Быстрый режим: <b>{escape_html(rsi_mode_label)}</b>",
                "",
                "🌊 <b>Рынок</b>",
                f"• Объём: <b>{escape_html(min_quote_volume_label)}</b>",
                f"• Направление: <b>{escape_html(direction_label)}</b>",
                f"• Режим отбора: <b>{escape_html(universe_label)}</b>",
            ]
        )
        if gold_alerts_label is not None:
            lines.extend(["", f"🪙 <b>Золото:</b> <b>{escape_html(gold_alerts_label)}</b>"])
        lines.extend(["", "✨ <b>Кастомное</b> откроет пошаговую настройку нижнего RSI, верхнего RSI, объёма, качества и направления."])
        if profile_is_custom:
            lines.append("↺ <b>Сброс к базе</b> вернёт сохранённые базовые значения профиля.")
        return "\n".join(lines)
    lines = [
        "<b>🎛 Signal Filters</b>",
        "",
        "Choose what the bot should treat as a clean setup for you.",
        "",
        "🧩 <b>Profile</b>",
        f"• Profile: <b>{escape_html(profile_label)}</b>",
    ]
    if profile_is_custom:
        lines.append(f"• Base: <b>{escape_html(base_profile_label)}</b>")
    lines.extend(
        [
            f"• Quality floor: <b>{escape_html(min_score_label)}</b>",
            "",
            "📉 <b>RSI</b>",
            f"• Lower: <b>{escape_html(lower_rsi_label)}</b>",
            f"• Upper: <b>{escape_html(upper_rsi_label)}</b>",
            f"• Quick mode: <b>{escape_html(rsi_mode_label)}</b>",
            "",
            "🌊 <b>Market</b>",
            f"• Volume: <b>{escape_html(min_quote_volume_label)}</b>",
            f"• Direction: <b>{escape_html(direction_label)}</b>",
            f"• Universe: <b>{escape_html(universe_label)}</b>",
        ]
    )
    if gold_alerts_label is not None:
        lines.extend(["", f"🪙 <b>Gold:</b> <b>{escape_html(gold_alerts_label)}</b>"])
    lines.extend(["", "✨ <b>Custom</b> opens the guided setup for lower RSI, upper RSI, volume, quality, and direction."])
    if profile_is_custom:
        lines.append("↺ <b>Reset to Base</b> restores your saved default profile values.")
    return "\n".join(lines)
    if is_russian(language_code):
        lines = [
            "<b>🎛 Фильтры сигналов</b>",
            "",
            "Выбирай кнопки ниже. Активные варианты помечены <code>✓</code>.",
            "",
            "🧩 <b>Пресет</b>",
            f"• Профиль: <b>{escape_html(profile_label)}</b>",
            f"• Порог качества: <b>{escape_html(min_score_label)}</b>",
            "",
            "📉 <b>RSI</b>",
            f"• Окно: <b>{escape_html(rsi_window_label)}</b>",
            f"• Режим: <b>{escape_html(rsi_mode_label)}</b>",
            "",
            "🌊 <b>Фильтры рынка</b>",
            f"• Объем: <b>{escape_html(min_quote_volume_label)}</b>",
            f"• Направление: <b>{escape_html(direction_label)}</b>",
            f"• Режим отбора: <b>{escape_html(universe_label)}</b>",
        ]
        if gold_alerts_label is not None:
            lines.extend(["", f"🪙 <b>Золото:</b> <b>{escape_html(gold_alerts_label)}</b>"])
        lines.extend(
            [
                "",
                "Эти настройки влияют на доставку сигналов и ручной анализ тикеров в боте.",
                "Хочешь больше гибкости - нажми <b>✨ Кастомное</b> и собери свой личный шаблон вручную.",
            ]
        )
        return "\n".join(lines)
    lines = [
        "<b>🎛 Signal Filters</b>",
        "",
        "Tap the buttons below to tune what the bot sends you. Active choices are marked with <code>✓</code>.",
        "",
        "🧩 <b>Preset</b>",
        f"• Profile: <b>{escape_html(profile_label)}</b>",
        f"• Quality floor: <b>{escape_html(min_score_label)}</b>",
        "",
        "📉 <b>RSI</b>",
        f"• Window: <b>{escape_html(rsi_window_label)}</b>",
        f"• Mode: <b>{escape_html(rsi_mode_label)}</b>",
        "",
        "🌊 <b>Market Filters</b>",
        f"• Volume: <b>{escape_html(min_quote_volume_label)}</b>",
        f"• Direction: <b>{escape_html(direction_label)}</b>",
        f"• Universe: <b>{escape_html(universe_label)}</b>",
    ]
    if gold_alerts_label is not None:
        lines.extend(["", f"🪙 <b>Gold:</b> <b>{escape_html(gold_alerts_label)}</b>"])
    lines.extend(
        [
            "",
            "These controls affect live delivery and manual ticker checks in this bot.",
            "Need more control? Tap <b>✨ Custom</b> and build your own personal setup step by step.",
        ]
    )
    return "\n".join(lines)


def format_custom_signal_setup_message(
    *,
    step: str,
    lower_rsi_label: str,
    upper_rsi_label: str,
    min_quote_volume_label: str,
    min_score_label: str,
    direction_label: str,
    language_code: str = "en",
    error_text: str | None = None,
) -> str:
    step_order = {
        "lower_rsi": ("1/5", "Lower RSI", "Send one number from 5 to 45.", "<code>28</code>"),
        "upper_rsi": ("2/5", "Upper RSI", "Send one number from 55 to 95.", "<code>72</code>"),
        "volume": ("3/5", "Volume", "Send the minimum quote volume in millions.", "<code>5</code> or <code>7.5</code>"),
        "score": ("4/5", "Quality Floor", "Send the minimum quality score from 0 to 100.", "<code>82</code>"),
        "direction": ("5/5", "Direction", "Choose which side you want to receive.", "Tap a button below or send <code>all</code>, <code>long</code>, or <code>short</code>."),
    }
    if is_russian(language_code):
        step_order = {
            "lower_rsi": ("1/5", "Нижний RSI", "Отправь одно число от 5 до 45.", "<code>28</code>"),
            "upper_rsi": ("2/5", "Верхний RSI", "Отправь одно число от 55 до 95.", "<code>72</code>"),
            "volume": ("3/5", "Объем", "Отправь минимальный объем в миллионах USDT.", "<code>5</code> или <code>7.5</code>"),
            "score": ("4/5", "Порог качества", "Отправь минимальную оценку качества от 0 до 100.", "<code>82</code>"),
            "direction": ("5/5", "Направление", "Выбери, какую сторону ты хочешь получать.", "Нажми кнопку ниже или напиши <code>все</code>, <code>лонг</code> или <code>шорт</code>."),
        }
    progress_label, title, instruction, example = step_order.get(step, step_order["lower_rsi"])
    if is_russian(language_code):
        lines = [
            "<b>✨ Кастомные фильтры</b>",
            "",
            "Соберем твой личный шаблон сигналов шаг за шагом.",
            "",
            "📌 <b>Черновик</b>",
            f"• Нижний RSI: <b>{escape_html(lower_rsi_label)}</b>",
            f"• Верхний RSI: <b>{escape_html(upper_rsi_label)}</b>",
            f"• Объем: <b>{escape_html(min_quote_volume_label)}</b>",
            f"• Порог качества: <b>{escape_html(min_score_label)}</b>",
            f"• Направление: <b>{escape_html(direction_label)}</b>",
            "",
            f"🪜 <b>{escape_html(progress_label)} · {escape_html(title)}</b>",
            instruction,
            example,
        ]
        if error_text:
            lines[2:2] = ["⚠️ <b>Проверь ввод</b>", escape_html(error_text), ""]
        lines.extend(["", "Можно нажать кнопку ниже и вернуться к обычным фильтрам в любой момент."])
        return "\n".join(lines)
    lines = [
        "<b>✨ Custom Filters</b>",
        "",
        "Build your personal signal template step by step.",
        "",
        "📌 <b>Draft</b>",
        f"• Lower RSI: <b>{escape_html(lower_rsi_label)}</b>",
        f"• Upper RSI: <b>{escape_html(upper_rsi_label)}</b>",
        f"• Volume: <b>{escape_html(min_quote_volume_label)}</b>",
        f"• Quality floor: <b>{escape_html(min_score_label)}</b>",
        f"• Direction: <b>{escape_html(direction_label)}</b>",
        "",
        f"🪜 <b>{escape_html(progress_label)} · {escape_html(title)}</b>",
        instruction,
        example,
    ]
    if error_text:
        lines[2:2] = ["⚠️ <b>Check the input</b>", escape_html(error_text), ""]
    lines.extend(["", "You can use the button below to return to the normal filters at any time."])
    return "\n".join(lines)


def format_custom_signal_setup_saved_message(
    *,
    lower_rsi_label: str,
    upper_rsi_label: str,
    min_quote_volume_label: str,
    min_score_label: str,
    direction_label: str,
    language_code: str = "en",
) -> str:
    if is_russian(language_code):
        return (
            "<b>✨ Кастомный фильтр сохранен</b>\n\n"
            f"• RSI: <b>{escape_html(lower_rsi_label)} / {escape_html(upper_rsi_label)}</b>\n"
            f"• Объем: <b>{escape_html(min_quote_volume_label)}</b>\n"
            f"• Порог качества: <b>{escape_html(min_score_label)}</b>\n"
            f"• Направление: <b>{escape_html(direction_label)}</b>\n\n"
            "Теперь бот будет отбирать сигналы под эти параметры."
        )
    return (
        "<b>✨ Custom filters saved</b>\n\n"
        f"• RSI: <b>{escape_html(lower_rsi_label)} / {escape_html(upper_rsi_label)}</b>\n"
        f"• Volume: <b>{escape_html(min_quote_volume_label)}</b>\n"
        f"• Quality floor: <b>{escape_html(min_score_label)}</b>\n"
        f"• Direction: <b>{escape_html(direction_label)}</b>\n\n"
        "The bot will now filter signals with these settings."
    )


def format_compact_signals_message(
    *,
    title: str,
    summary_line: str,
    entries: list[str],
    language_code: str = "en",
) -> str:
    body = "\n".join(f"{index + 1}. {item}" for index, item in enumerate(entries))
    tail = "Нажми на сетап ниже, чтобы открыть полную карточку." if is_russian(language_code) else "Tap a setup below to open the full card."
    return (
        f"<b>{escape_html(title)}</b>\n\n"
        f"{escape_html(summary_line)}\n\n"
        f"{escape_html(body)}\n\n"
        f"{tail}"
    )


def format_watchlist_message(
    *,
    symbols: list[str],
    watchlist_only: bool,
    active_theme_label: str,
    tracking_label: str,
    builtin_theme_active: bool,
    language_code: str = "en",
) -> str:
    if not symbols:
        if is_russian(language_code):
            return (
                "<b>Текущий watchlist</b>\n\n"
                "Добавь сюда инструменты, которые хочешь отслеживать в первую очередь.\n\n"
                f"• Охват сейчас: <b>{escape_html(tracking_label)}</b>\n"
                f"• Активная тема: <b>{escape_html(active_theme_label)}</b>\n\n"
                "Watchlist пока пуст.\n\n"
                "Как добавить:\n"
                "• <b>+BTC</b>\n"
                "• <b>+ETH</b>\n"
                "• <b>+XAUUSD</b>\n\n"
                "Или открой <b>Themes</b>, выбери готовый набор и отслеживай только его."
            )
        return (
            "<b>Current Watchlist</b>\n\n"
            "Add the symbols you want the bot to prioritize for you.\n\n"
            f"• Tracking now: <b>{escape_html(tracking_label)}</b>\n"
            f"• Active theme: <b>{escape_html(active_theme_label)}</b>\n\n"
            "Your watchlist is still empty.\n\n"
            "How to add:\n"
            "• <b>+BTC</b>\n"
            "• <b>+ETH</b>\n"
            "• <b>+XAUUSD</b>\n\n"
            "You can also open <b>Themes</b>, pick a saved market lens, and track only that set."
        )
    saved = ", ".join(symbols)
    if is_russian(language_code):
        lines = [
            "<b>Текущий watchlist</b>",
            "",
            "Это твои личные инструменты для быстрого доступа и персонализации потока.",
            "",
            f"• Символы: <b>{escape_html(saved)}</b>",
            f"• Охват: <b>{escape_html(tracking_label)}</b>",
            f"• Активная тема: <b>{escape_html(active_theme_label)}</b>",
        ]
        if builtin_theme_active:
            lines.extend(["", "Если начнёшь редактировать активную тему вручную, она станет твоим персональным списком."])
        lines.extend(["", "Нажми на тикер ниже, чтобы открыть карточку, или убери его кнопкой <b>Убрать</b> / командой <b>-BTC</b>."])
        return "\n".join(lines)
    lines = [
        "<b>Current Watchlist</b>",
        "",
        "These are the symbols you want the bot to keep closest to your flow.",
        "",
        f"• Symbols: <b>{escape_html(saved)}</b>",
        f"• Tracking: <b>{escape_html(tracking_label)}</b>",
        f"• Active Theme: <b>{escape_html(active_theme_label)}</b>",
    ]
    if builtin_theme_active:
        lines.extend(["", "If you edit the active theme manually, it turns into <b>your own custom list</b>."])
    lines.extend(["", "Tap a symbol below to open the card, or remove it with the button / <b>-BTC</b>."])
    return "\n".join(lines)
    if is_russian(language_code):
        mode_label = "только watchlist" if watchlist_only else "все тикеры"
    else:
        mode_label = "watchlist only" if watchlist_only else "all symbols"
    if not symbols:
        if is_russian(language_code):
            return (
                "<b>⭐ Watchlist</b>\n\n"
                "Пока нет сохраненных тикеров.\n\n"
                "➕ <b>Как добавить</b>\n"
                "• <b>+BTC</b>\n"
                "• <b>+ETH</b>\n"
                "• <b>+XAUUSD</b>\n\n"
                "🔎 Отправь <b>BTC</b> или <b>ETH 1h</b>, если хочешь сразу открыть карточку.\n"
                f"📌 Режим отбора: <b>{mode_label}</b>."
            )
        return (
            "<b>⭐ Watchlist</b>\n\n"
            "No symbols saved yet.\n\n"
            "➕ <b>How to add</b>\n"
            "• <b>+BTC</b>\n"
            "• <b>+ETH</b>\n"
            "• <b>+XAUUSD</b>\n\n"
            "🔎 Send <b>BTC</b> or <b>ETH 1h</b> to open a symbol card right away.\n"
            f"📌 Universe mode: <b>{mode_label}</b>."
        )
    saved = ", ".join(symbols)
    if is_russian(language_code):
        return (
            "<b>⭐ Watchlist</b>\n\n"
            "📌 <b>Сохранено</b>\n"
            f"• <b>{escape_html(saved)}</b>\n"
            f"• Режим: <b>{escape_html(mode_label)}</b>\n\n"
            "Нажми на тикер ниже, чтобы открыть его.\n"
            "Для удаления используй кнопку Убрать или команду <b>-BTC</b>."
        )
    return (
        "<b>⭐ Watchlist</b>\n\n"
        "📌 <b>Saved</b>\n"
        f"• <b>{escape_html(saved)}</b>\n"
        f"• Mode: <b>{escape_html(mode_label)}</b>\n\n"
        "Tap a symbol below to open it.\n"
        "Use Remove or send <b>-BTC</b> to delete it."
    )


def format_analyze_symbol_message(*, examples: list[str], ai_mode: bool = False, language_code: str = "en") -> str:
    sample_line = ", ".join(examples)
    if is_russian(language_code):
        if ai_mode:
            return (
                "<b>🔎 AI анализ монеты</b>\n\n"
                "Напиши название монеты прямо в чат, и бот соберет AI-анализ графика на текущий момент.\n\n"
                f"📌 <b>Примеры</b>\n• <b>{escape_html(sample_line)}</b>\n\n"
                "Можно сразу указать таймфрейм после пары, например <b>BTC 1h</b> или <b>ETH 4h</b>."
            )
        return (
            "<b>🔎 Анализ тикера</b>\n\n"
            "Отправь тикер прямо в чат, и бот откроет свежую карточку.\n\n"
            f"📌 <b>Примеры</b>\n• <b>{escape_html(sample_line)}</b>\n\n"
            "Можно указать таймфрейм после тикера."
        )
    if ai_mode:
        return (
            "<b>🔎 AI Coin Analysis</b>\n\n"
            "Type a coin in chat and the bot will generate an AI analysis of the chart as it looks right now.\n\n"
            f"📌 <b>Examples</b>\n• <b>{escape_html(sample_line)}</b>\n\n"
            "You can add a timeframe too, for example <b>BTC 1h</b> or <b>ETH 4h</b>."
        )
    return (
        "<b>🔎 Analyze Ticker</b>\n\n"
        "Send a ticker directly in chat and the bot will open a fresh card.\n\n"
        f"📌 <b>Examples</b>\n• <b>{escape_html(sample_line)}</b>\n\n"
        "You can add a timeframe after the symbol."
    )
def format_analyze_symbol_message(*, examples: list[str], ai_mode: bool = False, language_code: str = "en") -> str:
    sample_line = ", ".join(examples)
    if is_russian(language_code):
        if ai_mode:
            return (
                "<b>AI Desk</b>\n\n"
                "Ручной AI-разбор по символу и таймфрейму, который ты сам запросишь.\n\n"
                "<b>Попробуй</b>\n"
                f"• <b>{escape_html(sample_line)}</b>\n\n"
                "Можно сразу указать таймфрейм, например <b>BTC 1h</b> или <b>XAUUSD 15m</b>."
            )
        return (
            "<b>Разбор тикера</b>\n\n"
            "Отправь символ или символ с таймфреймом, и бот откроет свежую карточку.\n\n"
            "<b>Примеры</b>\n"
            f"• <b>{escape_html(sample_line)}</b>\n\n"
            "Пример ввода: <b>BTC</b>, <b>ETH 1h</b>, <b>XAUUSD</b>."
        )
    if ai_mode:
        return (
            "<b>AI Desk</b>\n\n"
            "Manual AI market reads for the symbol and timeframe you request.\n\n"
            "<b>Try</b>\n"
            f"• <b>{escape_html(sample_line)}</b>\n\n"
            "You can add a timeframe too, for example <b>BTC 1h</b> or <b>XAUUSD 15m</b>."
        )
    return (
        "<b>Analyze Ticker</b>\n\n"
        "Send a symbol or symbol + timeframe and the bot will open a fresh structured card.\n\n"
        "<b>Examples</b>\n"
        f"• <b>{escape_html(sample_line)}</b>\n\n"
        "Examples: <b>BTC</b>, <b>ETH 1h</b>, <b>XAUUSD</b>."
    )


def _compact_list(items: object, *, empty_label: str) -> str:
    if items is None:
        iterable: list[object] = []
    elif isinstance(items, str):
        iterable = [items]
    else:
        try:
            iterable = list(items)  # type: ignore[arg-type]
        except TypeError:
            iterable = [items]
    cleaned = [str(item).strip() for item in iterable if str(item).strip()]
    return ", ".join(cleaned) if cleaned else empty_label


def format_help_message(*, language_code: str = "en") -> str:
    if is_russian(language_code):
        return (
            "<b>❓ Помощь</b>\n\n"
            "Подсказки по запуску, настройке и ежедневному использованию.\n\n"
            "<b>Быстрый старт</b>\n"
            "Отправь <b>BTC</b>, <b>ETH 1h</b> или <b>XAUUSD</b>, чтобы сразу открыть разбор.\n\n"
            "<b>Полезно помнить</b>\n"
            "• <b>+BTC</b> и <b>-BTC</b> быстро обновляют избранное\n"
            "• <b>/last</b> открывает последние сигналы\n"
            "• <b>/strong</b> показывает самые сильные сетапы\n"
            "• <b>/menu</b> возвращает на главный экран\n\n"
            "<b>Если сигналов пока нет</b>\n"
            "Бот продолжает сканировать рынок, а фильтры могут пропускать слабые условия. "
            "Открой пример сигнала, результаты или дождись следующего цикла.\n\n"
            "<b>Риск</b>\n"
            "Сигналы дают аналитический контекст, а не гарантированную прибыль. "
            "Крипторынок рискован, прошлые результаты не гарантируют будущие, "
            "и решение пользователь принимает самостоятельно."
        )
    return (
        "<b>❓ Help</b>\n\n"
        "Quick guidance for setup, navigation, and daily use.\n\n"
        "<b>Start here</b>\n"
        "Send <b>BTC</b>, <b>ETH 1h</b>, or <b>XAUUSD</b> to open a fresh read right away.\n\n"
        "<b>Good to know</b>\n"
        "• <b>+BTC</b> and <b>-BTC</b> update favorites in one step\n"
        "• <b>/last</b> opens recent signals\n"
        "• <b>/strong</b> shows strongest setups\n"
        "• <b>/menu</b> takes you back home\n\n"
        "<b>If there are no signals yet</b>\n"
        "Scanning is still active and quality filters may skip weak conditions. "
        "Open the example signal, review results, or wait for the next cycle.\n\n"
        "<b>Risk</b>\n"
        "Signals provide analytical context, not a promise of returns. Crypto markets are risky, "
        "past results do not guarantee future results, and you decide independently."
    )


def format_access_message(
    *,
    access_level: str,
    access_state_line: str,
    user_label: str = "",
    enabled_notifications: list[str] | str | None = None,
    enabled_strategies: list[str] | str | None = None,
    delivery_mode_label: str = "",
    language_code: str = "en",
    workspace_count: int | None = None,
    saved_sets_count: int | None = None,
    ai_access_enabled: bool | None = None,
) -> str:
    notifications_line = _compact_list(
        enabled_notifications,
        empty_label="ничего не включено" if is_russian(language_code) else "nothing enabled",
    )
    strategy_items = enabled_strategies[:6] if isinstance(enabled_strategies, list) else enabled_strategies
    strategies_line = _compact_list(
        strategy_items,
        empty_label="пока не выбраны" if is_russian(language_code) else "not selected yet",
    )
    workspace_total = max(int(workspace_count or 0), 0)
    saved_sets_total = max(int(saved_sets_count or 0), 0)
    language_is_ru = is_russian(language_code)
    ai_state = ("Включён" if ai_access_enabled else "Выключен") if language_is_ru else ("Enabled" if ai_access_enabled else "Disabled")
    normalized_state = f"{access_level} {access_state_line}".casefold()
    if any(token in normalized_state for token in ("trial", "триал")):
        state_key = "trial"
    elif any(token in normalized_state for token in ("paid", "оплачен", "оплачено", "pro+")) and not any(token in normalized_state for token in ("expired", "истек", "истёк")):
        state_key = "paid"
    elif any(token in normalized_state for token in ("expired", "истек", "истёк")):
        state_key = "expired"
    elif "admin" in normalized_state or "админ" in normalized_state:
        state_key = "admin"
    else:
        state_key = "free"
    if is_russian(language_code):
        state_title = {
            "trial": "Активный trial",
            "paid": "Оплаченный PRO+",
            "expired": "Доступ истёк",
            "admin": "Админ-доступ",
            "free": "Бесплатный доступ",
        }[state_key]
        next_step = {
            "trial": "Пока trial активен, можно изучить полный PRO+ поток. Для продолжения после trial открой оплату PRO+.",
            "paid": "Доступ открыт: полный PRO+ поток, настройки и follow-up остаются активны до указанной даты.",
            "expired": "Renew PRO+, чтобы вернуть ранние сигналы, AI/risk-контекст и follow-up.",
            "admin": "Админ-доступ открыт без кнопки оплаты.",
            "free": "Upgrade to PRO+, чтобы открыть ранний поток, AI/risk-контекст и follow-up.",
        }[state_key]
        return (
            "<b>💎 Мой доступ</b>\n\n"
            f"<b>{state_title}</b>\n"
            f"Статус: <b>{escape_html(access_state_line)}</b>\n"
            f"План: <b>{escape_html(access_level)}</b>\n\n"
            "<b>Что открыто сейчас</b>\n"
            f"• Доставка: <b>{escape_html(delivery_mode_label or 'n/a')}</b>\n"
            f"• Уведомления: <b>{escape_html(notifications_line)}</b>\n"
            f"• Стратегии: <b>{escape_html(strategies_line)}</b>\n"
            f"• Профили: <b>{workspace_total}</b>\n"
            f"• Сохранённые наборы: <b>{saved_sets_total}</b>\n"
            f"• AI доступ: <b>{escape_html(ai_state)}</b>\n\n"
            "<b>Дальше</b>\n"
            f"{escape_html(next_step)}\n\n"
            f"План: <b>{escape_html(access_level)}</b>\n"
            f"Статус: <b>{escape_html(access_state_line)}</b>\n"
            f"Пользователь: <b>{escape_html(user_label or 'n/a')}</b>\n"
            f"Режим доставки: <b>{escape_html(delivery_mode_label or 'n/a')}</b>\n"
            f"Уведомления: <b>{escape_html(notifications_line)}</b>\n"
            f"Стратегии: <b>{escape_html(strategies_line)}</b>\n"
            f"Профили: <b>{workspace_total}</b>\n"
            f"Сохранённые наборы: <b>{saved_sets_total}</b>\n"
            f"AI доступ: <b>{escape_html(ai_state)}</b>"
        )
    state_title = {
        "trial": "Active trial",
        "paid": "Paid PRO+",
        "expired": "Expired access",
        "admin": "Admin access",
        "free": "Free access",
    }[state_key]
    next_step = {
        "trial": "Your trial can use the full PRO+ flow now. To keep it after the trial, open Pay PRO+.",
        "paid": "You have the full PRO+ flow: earlier cards, personal settings, AI/risk context, and follow-ups.",
        "expired": "Renew PRO+ to restore earlier signals, AI/risk context, and follow-ups.",
        "admin": "Admin access is active; renewal buttons are hidden.",
        "free": "Upgrade to PRO+ to unlock earlier flow, AI/risk context, and follow-ups.",
    }[state_key]
    return (
        "<b>💎 My Access</b>\n\n"
        f"<b>{state_title}</b>\n"
        f"Status: <b>{escape_html(access_state_line)}</b>\n"
        f"Plan: <b>{escape_html(access_level)}</b>\n\n"
        "<b>What is open now</b>\n"
        f"• Delivery: <b>{escape_html(delivery_mode_label or 'n/a')}</b>\n"
        f"• Notifications: <b>{escape_html(notifications_line)}</b>\n"
        f"• Strategies: <b>{escape_html(strategies_line)}</b>\n"
        f"• Workspaces: <b>{workspace_total}</b>\n"
        f"• Saved Sets: <b>{saved_sets_total}</b>\n"
        f"• AI Access: <b>{escape_html(ai_state)}</b>\n\n"
        "<b>Next</b>\n"
        f"{escape_html(next_step)}\n\n"
        f"Plan: <b>{escape_html(access_level)}</b>\n"
        f"Status: <b>{escape_html(access_state_line)}</b>\n"
        f"User: <b>{escape_html(user_label or 'n/a')}</b>\n"
        f"Delivery: <b>{escape_html(delivery_mode_label or 'n/a')}</b>\n"
        f"Notifications: <b>{escape_html(notifications_line)}</b>\n"
        f"Strategies: <b>{escape_html(strategies_line)}</b>\n"
        f"Workspaces: <b>{workspace_total}</b>\n"
        f"Saved Sets: <b>{saved_sets_total}</b>\n"
        f"AI Access: <b>{escape_html(ai_state)}</b>"
    )


def format_status_message(
    *,
    timeframe: str,
    access_state_line: str,
    access_label: str,
    alerts_last_24h: int,
    followups_last_24h: int,
    last_signal_label: str,
    feed_label: str,
    alerts_state_label: str,
    followups_state_label: str,
    gold_state_label: str,
    language_code: str = "en",
) -> str:
    if is_russian(language_code):
        return (
            "<b>🟢 Статус бота</b>\n\n"
            "Короткая сводка по потоку, доставке и последней активности.\n\n"
            f"План: <b>{escape_html(access_label)}</b>\n"
            f"Статус доступа: <b>{escape_html(access_state_line)}</b>\n"
            f"Скан: <b>{escape_html(timeframe)}</b>\n"
            f"Сигналы за 24ч: <b>{alerts_last_24h}</b>\n"
            f"Фоллоу-апы за 24ч: <b>{followups_last_24h}</b>\n"
            f"Активные стратегии: <b>{escape_html(feed_label)}</b>\n"
            f"Уведомления: <b>{escape_html(alerts_state_label)}</b>\n"
            f"Фоллоу-апы: <b>{escape_html(followups_state_label)}</b>\n"
            f"Gold Desk: <b>{escape_html(gold_state_label)}</b>\n"
            f"Последний сигнал: <b>{escape_html(last_signal_label)}</b>"
        )
    return (
        "<b>🟢 Bot Status</b>\n\n"
        "A quick read on flow, delivery, and recent activity.\n\n"
        f"Plan: <b>{escape_html(access_label)}</b>\n"
        f"Access: <b>{escape_html(access_state_line)}</b>\n"
        f"Scan: <b>{escape_html(timeframe)}</b>\n"
        f"Alerts in 24h: <b>{alerts_last_24h}</b>\n"
        f"Follow-ups in 24h: <b>{followups_last_24h}</b>\n"
        f"Active Strategies: <b>{escape_html(feed_label)}</b>\n"
        f"Alerts: <b>{escape_html(alerts_state_label)}</b>\n"
        f"Follow-ups: <b>{escape_html(followups_state_label)}</b>\n"
        f"Gold Desk: <b>{escape_html(gold_state_label)}</b>\n"
        f"Last Signal: <b>{escape_html(last_signal_label)}</b>"
    )


def format_watchlist_message(
    *,
    symbols: list[str],
    watchlist_only: bool,
    active_theme_label: str,
    tracking_label: str,
    builtin_theme_active: bool,
    language_code: str = "en",
) -> str:
    saved = ", ".join(symbols[:12])
    if not symbols:
        if is_russian(language_code):
            return (
                "<b>⭐ Избранное</b>\n\n"
                "Твой быстрый список для самых важных символов.\n\n"
                "Список пока пуст.\n"
                "Добавь <b>BTC</b>, <b>ETH</b>, <b>SOL</b> или <b>XAUUSD</b> через <b>+BTC</b>."
            )
        return (
            "<b>⭐ Favorites</b>\n\n"
            "Your fastest access list for the symbols that matter most.\n\n"
            "This list is empty for now.\n"
            "Add <b>BTC</b>, <b>ETH</b>, <b>SOL</b>, or <b>XAUUSD</b> with <b>+BTC</b>."
        )
    if is_russian(language_code):
        note = (
            "Текущая тема продолжает работать отдельно от избранного."
            if builtin_theme_active
            else "Избранное используется как твой собственный персональный список."
        )
        return (
            "<b>⭐ Избранное</b>\n\n"
            "Твой быстрый список для самых важных символов.\n\n"
            f"Символы: <b>{escape_html(saved)}</b>\n"
            f"Охват: <b>{escape_html(tracking_label)}</b>\n"
            f"Тема: <b>{escape_html(active_theme_label)}</b>\n"
            f"Режим: <b>{'только список' if watchlist_only else 'весь рынок'}</b>\n\n"
            f"{escape_html(note)}\n"
            "Убирай символы кнопкой ниже или командой <b>-BTC</b>."
        )
    note = (
        "Your active theme keeps working separately from favorites."
        if builtin_theme_active
        else "Favorites are currently acting as your personal custom list."
    )
    return (
        "<b>⭐ Favorites</b>\n\n"
        "Your fastest access list for the symbols you care about most.\n\n"
        f"Symbols: <b>{escape_html(saved)}</b>\n"
        f"Tracking: <b>{escape_html(tracking_label)}</b>\n"
        f"Theme: <b>{escape_html(active_theme_label)}</b>\n"
        f"Mode: <b>{'watchlist only' if watchlist_only else 'full market'}</b>\n\n"
        f"{escape_html(note)}\n"
        "Remove symbols below or send <b>-BTC</b>."
    )


def format_analyze_symbol_message(*, examples: list[str], ai_mode: bool = False, language_code: str = "en") -> str:
    example_block = "\n".join(f"<b>{escape_html(example)}</b>" for example in examples)
    if is_russian(language_code):
        if ai_mode:
            return (
                "<b>🤖 AI Desk</b>\n\n"
                "Ручной анализ по символу, таймфрейму и текущему контексту.\n\n"
                "Введи тикер и получи структурированный разбор:\n"
                f"{example_block}"
            )
        return (
            "<b>🔎 Разбор тикера</b>\n\n"
            "Отправь символ или символ с таймфреймом, и бот откроет свежую карточку.\n\n"
            "Примеры:\n"
            f"{example_block}"
        )
    if ai_mode:
        return (
            "<b>🤖 AI Desk</b>\n\n"
            "Manual analysis for symbols, timeframes, and setup context.\n\n"
            "Type a symbol to get a structured read:\n"
            f"{example_block}"
        )
    return (
        "<b>🔎 Analyze Ticker</b>\n\n"
        "Enter a symbol or symbol + timeframe and the bot will open a fresh structured card.\n\n"
        "Examples:\n"
        f"{example_block}"
    )
