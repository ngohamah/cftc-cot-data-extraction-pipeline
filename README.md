# COT Analysis

[![CI](https://github.com/ngohamah/cot_analysis/actions/workflows/ci.yml/badge.svg)](https://github.com/ngohamah/cot_analysis/actions/workflows/ci.yml)
[![Weekly COT update](https://github.com/ngohamah/cot_analysis/actions/workflows/weekly-update.yml/badge.svg)](https://github.com/ngohamah/cot_analysis/actions/workflows/weekly-update.yml)

The Commitments of Traders (COT) reports are published weekly by the Commodity Futures Trading Commission (CFTC) based on position data supplied by reporting firms (Futures Commission Merchants(FCMs), clearing members, foreign brokers and exchanges) on their investment behaviours in the futures and options markets across different exchanges in the US. Understanding this behaviour over time presents a good opportunity to identify trends and investment opportunities in different markets.

## Simple Workflow

```text
┌──────────────┐
│   History    │
│  1986-2016   │──┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│ FUT86_16.txt │  │  │ Clean, merge│  │   Signals   │  │  Append to  │  │ Report, logs│  │  Frontend,  │
└──────────────┘  ├─▶│  new weeks  │─▶│ Bull / Bear │─▶│ data, signal│─▶│   reports/  │─▶│   trading,  │
┌──────────────┐  │  │ transform.py│  │  signals.py │  │  storage.py │  │  report.py  │  │   analysis  │
│ Yearly zips  │  │  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘
│  2017-today  │──┘
│  extract.py  │
└──────────────┘
```

`config.py` sets the tracked markets, columns and folders. `extract.py` reads the saved 1986-2016 history and
the yearly CFTC files, downloading a year only when its file is missing or a new weekly report is due (Fridays
15:30 US Eastern). Each run appends only the weeks not saved yet, and `orchestrate.py` runs the steps for every
market (`pipeline.py` is the command you run). A separate check, `scripts/verify_history_parity.py`, confirms the
saved history is identical to the CFTC's own yearly files (last run 2026-09-27: 31 of 31 years identical).

## What the signals mean

Each week the pipeline compares the change in large speculators' **net position** (longs minus shorts) with the
change in **open interest** (total contracts outstanding):

| Net position | Open interest | Reading | Code |
|---|---|---|---|
| Rising | Rising | Bullish - speculators add to bets on rising prices while new money enters | 1 |
| Falling | Rising | Bearish - speculators cut bets on rising prices while new money enters | 2 |
| Falling | Falling | Bearish Reversal - money leaving the market; direction may be about to change | 3 |
| Rising | Falling | Bullish Reversal - money leaving the market; direction may be about to change | 4 |

These are indicators, not trading recommendations.

## How to run code

```sh
# clone repository
git clone https://github.com/ngohamah/cot_analysis.git
cd cot_analysis

# create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# install dependencies
pip install -r requirements.txt

# run the full pipeline (download if needed -> clean -> merge -> signals -> report)
python pipeline.py

# useful options
python pipeline.py --offline   # use saved reports in raw/ only, no downloads
python pipeline.py --refresh   # re-download every year even if saved copies are up to date
python pipeline.py --rebuild   # rebuild data/*.csv from raw/FUT86_16.txt + yearly reports
python pipeline.py --help

# run lint and unit tests (same checks as CI)
ruff check . && ruff format --check .
pytest

# verify raw/FUT86_16.txt matches the CFTC's own 1986-2016 yearly files (downloads each year once)
python scripts/verify_history_parity.py

# optional: explore the data in the notebook (ensure you have jupyter installed)
jupyter lab
```

`raw/FUT86_16.txt` is not stored in git (it is 168 MB). Without it the pipeline still runs, but the data
starts in 2017 and a warning is logged.

## How each run behaves

- **Downloads only what is needed.** Every year from 2017 on is checked first: it is downloaded only if the saved
  zip in `raw/` is missing, unreadable, or lacks the latest report the CFTC should have published by now (reports
  come out on Fridays at 15:30 US Eastern with positions as of the Tuesday before). Years before 2017 always come
  from `raw/FUT86_16.txt`, and years with nothing published yet are skipped.
- **Writes only new weeks.** Files in `data/` and `signal/` are stored oldest-first, and each run appends only the
  weeks they don't have yet. Rows already saved are never rewritten, and a run with no new report writes nothing.
- **Rewrites a file in full only when it must.** That happens when a file is missing, when `--rebuild` is used,
  when a file that starts in 2017 is missing its 1986-2016 history, or when a file can't be appended to safely
  (for example the one-time switch from newest-first to oldest-first order). The reason is logged.
- **Keeps saved values if the CFTC corrects a past week.** The correction is logged as a warning; run
  `python pipeline.py --rebuild` to apply it.
- **Explains itself.** Every decision (downloaded or not, appended, rewritten, skipped, dropped rows) is logged to
  `logs/pipeline.log`, and a plain-language summary is written to `reports/latest_signals.md`.

## Weekly automatic update

The GitHub Actions workflow [`weekly-update.yml`](.github/workflows/weekly-update.yml) runs the pipeline every
**Saturday and Sunday at 06:00 UTC** (the CFTC publishes on Friday afternoon US time; Sunday is a catch-up run
for late releases and does nothing if Saturday already got the new week). It can also be started by hand from the
repository's **Actions** tab ("Run workflow"). Each run:

1. runs the unit tests - no data is written if they fail,
2. reuses the CFTC files saved by the previous run and downloads only if a new weekly report is due,
3. appends the new week to `data/` and `signal/` and refreshes `reports/latest_signals.md`,
4. commits those changes to the repository as `github-actions[bot]`, together with its own log
   `logs/ci/pipeline.log` (nothing is committed if there is no new report),
5. shows the plain-language summary on the run's page and keeps the run's log as a download for 90 days,
6. marks the run as failed (GitHub emails you) if a download or a market could not be updated.

Applications can read the latest signals straight from the repository, e.g.
`https://raw.githubusercontent.com/ngohamah/cot_analysis/master/signal/GOLD.csv` (spaces in names are written
`%20`, e.g. `signal/EURO%20FX.csv`). Columns are in the order: date, longs, shorts, change in longs, change in
shorts, open interest, net positions, reading.

## Where to find data

| Folder | What is in it |
|---|---|
| `data/` | One CSV per market: weekly positions of large speculators, open interest, net positions and their weekly change (oldest week first) |
| `signal/` | One CSV per market: the same weeks with the signal reading (Bullish, Bearish, ...) |
| `reports/` | `latest_signals.md` - latest week per market in plain language; `history_parity.md` - result of the history check |
| `raw/` | Source data: `FUT86_16.txt` (1986-2016) and `legacy_fut_<year>.zip` (2017 on); not stored in git |
| `logs/` | `pipeline.log` - what your local runs did (not stored in git); `ci/pipeline.log` - what the weekly bot did, committed by the bot, each run starting with a link to its GitHub Actions run |

## Code layout

Constants (paths, markets, symbols, columns, CFTC schedule) live in `config.py`. The pipeline code is split by
stage:

| File | What it does |
|---|---|
| `pipeline.py` | Command-line entry point (options, then calls `run`) |
| `cot_pipeline/extract.py` | Decides which years need downloading, downloads them once to `raw/`, loads them and `raw/FUT86_16.txt` |
| `cot_pipeline/transform.py` | Cleans reports, unifies market names, finds new weeks, computes net positions |
| `cot_pipeline/signals.py` | Bullish / Bearish / Reversal signal per week |
| `cot_pipeline/storage.py` | Appending new rows, safe (atomic) full writes, reading saved CSVs |
| `cot_pipeline/report.py` | Plain-language summary in `reports/latest_signals.md` |
| `cot_pipeline/orchestrate.py` | Runs the stages in order for every market |
| `cot_pipeline/logging_setup.py` | Logging to `logs/pipeline.log` and the console |
| `cot_pipeline/parity.py` | Compares the history file with per-year CFTC files (used by `scripts/verify_history_parity.py`) |

The plan and implementation status are in [`docs/PIPELINE.md`](docs/PIPELINE.md); the original notebook is in `docs/`.

## References
- [The Commitments of Traders Bible Book by Stephen Briese on Amazon](https://www.amazon.com/Commitments-Traders-Bible-Insider-Intelligence/dp/0470178426)
- [Learn more on the COT Report on Investopedia](https://www.investopedia.com/terms/c/cot.asp)
- [COT_Reports package by NDelventhal](https://github.com/NDelventhal/cot_reports)

