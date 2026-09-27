# COT Analysis

[![CI](https://github.com/ngohamah/cot_analysis/actions/workflows/ci.yml/badge.svg)](https://github.com/ngohamah/cot_analysis/actions/workflows/ci.yml)

The Commitment of Traders reports are Commodity futures reported by the Commodity Futures Trading Commission (CFTC) based on position data supplied by reporting firms (Futures Commission Merchants(FCMs), clearing members, foreign brokers and exchanges) on their investment behaviours in the futures and options markets across different exchanges in the US. Understanding this behaviour over time presents a good opportunity to identify trends and  investment opportunities in different markets.

## Simple Workflow

                ┌──────────────────────┐
                │  Input Configuration │
                │ (Symbols, Exchanges) │
                └──────────┬───────────┘
                           │
                           ▼
                ┌──────────────────────┐
                │   Data Ingestion     │
                │     (Reports)        │
                └──────────┬───────────┘
                           │
                           ▼
                ┌──────────────────────┐
                │ Data Synchronization │
                │(Date + Naming Align) │
                └──────────┬───────────┘
                           │
                           ▼
                ┌──────────────────────┐
                │ Data Transformation  │
                │ (Column Extraction)  │
                └──────────┬───────────┘
                           │
                           ▼
                ┌──────────────────────┐
                │ Feature Engineering  │
                │   (Net + Signals)    │
                └──────────┬───────────┘
                           │
                           ▼
                ┌──────────────────────┐
                │    Data Storage      │
                │       (CSV)          │
                └──────────┬───────────┘
                           │
                           ▼
                ┌──────────────────────┐
                │  Consumption Layer   │
                │ (Trading / Analysis) │
                └──────────────────────┘

## How to run code

```sh
# activate your virtual environment
virtualenv .venv
source .venv/bin/activate

# clone repository
git clone https://github.com/ngohamah/cot_analysis.git
cd cot_analysis

# install dependencies
pip install -r requirements.txt

# run the full pipeline (download -> clean -> merge -> signals -> report)
python pipeline.py

# useful options
python pipeline.py --offline   # use saved reports in raw/ only, no downloads
python pipeline.py --rebuild   # rebuild data/*.csv from raw/FUT86_16.txt + yearly reports
python pipeline.py --help

# run lint and unit tests (same checks as CI)
ruff check . && ruff format --check .
pytest

# optional: explore the data in the notebook (ensure you have jupyter installed)
jupyter lab
```

Each run:
- keeps all source data in `raw/`: the 1986-2016 history (`raw/FUT86_16.txt`, saved once, never downloaded) and one zip per year from 2017 on; each year is downloaded once and only the current year is re-downloaded on later runs,
- **appends only new weeks** to `data/<symbol>.csv` and `signal/<symbol>.csv` (files are stored oldest-first; rows already saved are never rewritten, and a run with no new report writes nothing),
- creates missing files from scratch, with the 1986-2016 history from `raw/FUT86_16.txt` placed before the 2017+ reports; a saved file that starts in 2017 or later gets that history added once (one full rewrite, logged); a file is rewritten in full only when it can't be appended to safely (e.g. the one-time switch from newest-first to oldest-first order), and the reason is logged,
- keeps saved values if the CFTC revises a past week and logs a warning; run `python pipeline.py --rebuild` to apply revisions,
- writes a plain-language summary to `reports/latest_signals.md`,
- logs every step, including skipped years, dropped rows and missing files, to `logs/pipeline.log`.

Constants (paths, markets, symbols, columns) live in `config.py`. The pipeline code is split by stage:

| File | What it does |
|---|---|
| `pipeline.py` | Command-line entry point (options, then calls `run`) |
| `cot_pipeline/extract.py` | Downloads yearly CFTC reports once, saves them to `raw/`, loads them and `raw/FUT86_16.txt` |
| `cot_pipeline/transform.py` | Cleans reports, unifies market names, merges/de-duplicates, computes net positions |
| `cot_pipeline/signals.py` | Bullish / Bearish / Reversal signal per week |
| `cot_pipeline/storage.py` | Appending new rows, safe (atomic) full writes, reading saved CSVs |
| `cot_pipeline/report.py` | Plain-language summary in `reports/latest_signals.md` |
| `cot_pipeline/orchestrate.py` | Runs the stages in order for every symbol |
| `cot_pipeline/logging_setup.py` | Logging to `logs/pipeline.log` and the console |

The plan and implementation status are in [`docs/PIPELINE.md`](docs/PIPELINE.md); the original notebook is in `docs/`.

## Where to find data

You may find the extracted data only in the ```data/``` folder and the data + signal infos in the ```signal``` for the different symbols queried. 


## References
- [The Commitments of Traders Bible Book by Stephen Briese on Amazon](https://www.amazon.com/Commitments-Traders-Bible-Insider-Intelligence/dp/0470178426)
- [Learn more on the COT Report on Investopedia](https://www.investopedia.com/terms/c/cot.asp)
- [COT_Reports package by NDelventhal](https://github.com/NDelventhal/cot_reports)

