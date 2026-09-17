# Futures Research Utility

This directory contains a standalone local research script for futures-market analysis. It is separate from the RSI Syndicate service and does not run as part of the main bot.

## Setup

From this directory, create and activate a virtual environment, then install the listed dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
```

## Running

Run `run_futures_research.bat` on Windows, or invoke the script directly after reviewing its command-line options:

```powershell
.\.venv\Scripts\python run_futures_research.py --help
```

Generated data and output remain local and are excluded from Git.
