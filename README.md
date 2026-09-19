# RSI Syndicate

RSI Syndicate is a Python application for scanning configured market instruments, producing technical-analysis signals, and delivering configured alerts through Telegram. It also includes local SQLite persistence, optional chart generation, and focused research utilities.

## What it does

The service loads settings from environment variables, obtains market data through its configured clients, evaluates strategy scanners, records signals and their lifecycle in SQLite, and sends eligible alerts to configured Telegram destinations. Optional components support follow-up tracking, a separate classic bot flow, payment/onboarding workflows, and locally hosted AI-assisted copy generation.

The repository does not contain live credentials, operational databases, user data, alert history, or market caches.

## Key features

- Asynchronous market-data clients and several RSI, Bollinger, breakout, pullback, VWAP, and gold-oriented scanners.
- Telegram delivery flows with interactive keyboards, routing, throttling, and a classic-bot variant.
- SQLite schema initialization and migrations for local signal, preference, onboarding, referral, and lifecycle data.
- Signal follow-up and operational-maintenance jobs.
- Optional chart rendering with `matplotlib` and `mplfinance`.
- Optional Crypto Pay and ngrok development integrations, configured entirely through environment variables.
- Standalone backtesting and futures-research utilities in their own directories.

## Architecture

```text
environment configuration
        |
        v
src.main -> market clients / strategy scanners -> signals -> SQLite storage
        |                                              |
        +-> scheduled jobs / follow-ups <--------------+
        |
        +-> Telegram clients, routing, keyboards, and optional payment flows
```

## Tech stack

Python, `aiohttp`, `aiosqlite`, SQLite, `pandas`, `numpy`, `pydantic-settings`, `matplotlib`, and `mplfinance`.

## Project structure

- `src/main.py` — application entry point and service orchestration.
- `src/market/` — market clients, indicators, and scanners.
- `src/bot/`, `src/classicbot/`, `src/userbot/` — Telegram delivery and interaction layers.
- `src/storage/` — SQLite initialization, models, and repositories.
- `src/jobs/`, `src/signals/`, `src/payments/`, `src/referrals/` — background workflows and optional integrations.
- `tests/` — `unittest` test suite.
- `backtesting_double_top/`, `strategy_research_lab/`, `test/`, `test2/` — independent local research utilities.

## Setup

Requires Python 3.12 or a compatible Python version.

```powershell
git clone <REPOSITORY_URL>
cd rsi-syndicate-telegram-bot
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

On Linux or macOS, activate the environment with `source .venv/bin/activate` and use `python` in the remaining commands.

Review `.env` before starting: real Telegram credentials and any enabled optional integration settings must be supplied locally. `run.bat` automates the Windows setup/start flow; it may also synchronize the optional Windows autostart setting.

## Configuration

All settings are read from `.env` by `src.core.config.Settings`. The checked-in `.env.example` contains safe placeholders and defaults only.

| Variable group | Required when enabled | Purpose |
| --- | --- | --- |
| `TELEGRAM_*` | Telegram delivery | Bot credentials, destinations, and delivery controls. |
| `BINANCE_*`, `GOLD_*` | Corresponding scanner | Market-data endpoints and scanner settings. |
| `SQLITE_PATH`, `RUNTIME_DIR`, `LOG_FILE` | No | Local persistence and runtime locations. |
| `CRYPTO_PAY_*` | Crypto Pay workflow | Payment provider configuration. |
| `NGROK_*`, `LOCAL_WEBHOOK_*` | Local webhook workflow | Local development tunnel and webhook settings. |
| `OLLAMA_*` | AI-assisted copy | Local Ollama integration settings. |

Never commit `.env`, session files, generated databases, logs, or runtime market data.

## Running

Start the main service only after configuring local credentials:

```powershell
.\.venv\Scripts\python -m src.main
```

Windows users can instead run `run.bat`. Supporting developer and maintenance entry points are available as Python modules under `src.tools` and `src.payments.devtools`; inspect their command help before using them with operational data.

## Tests

The deterministic offline suite uses forced, clearly named dummy Telegram settings and does not read real credentials from your environment:

```powershell
.\.venv\Scripts\python tests\offline_runner.py
```

The runner configures the seven required Telegram/destination fields for the test process and clears optional credential/private-identifier fields so local values cannot leak into test behavior. Production startup remains strict: `src.core.config.Settings` still requires real authorized values from the local environment or ignored `.env` file. Existing tests replace Telegram, Binance, and other outbound operations with local fakes at their client/service boundaries; the offline suite does not claim to verify live Telegram delivery.

Live-service checks, if added or run separately, require authorized test-only credentials and destinations. Do not use production tokens or channel identifiers for test automation.

Compile the primary application with:

```powershell
.\.venv\Scripts\python -m compileall -q src
```

## Data and privacy

SQLite databases, WAL/SHM sidecars, Telegram sessions, logs, charts, runtime state, operational data, generated reports, and research outputs are local-only and covered by `.gitignore`. The application initializes its database schema in code; no production database is included.

## Limitations

- The project relies on configured external services for data and Telegram delivery; this repository does not provide credentials or a hosted deployment.
- Research utilities are independent local tools and may require their own dependencies or market-data setup.
- No performance, profitability, or production-availability claim is made by this repository.

## License

No license has been selected for this repository yet.

## Disclaimer

This project is for software, educational, and analytical purposes and is not financial advice.
