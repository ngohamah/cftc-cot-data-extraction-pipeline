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
python pipeline.py --rebuild   # rebuild data/*.csv from FUT86_16.txt + yearly reports
python pipeline.py --help

# run lint and unit tests (same checks as CI)
ruff check . && ruff format --check .
pytest

# optional: explore the data in the notebook (ensure you have jupyter installed)
jupyter lab
```

Each run:
- downloads each year's CFTC report once and saves it to `raw/` (only the current year is re-downloaded on later runs),
- creates or updates `data/<symbol>.csv` and `signal/<symbol>.csv` (missing files are recreated; the 1986-2016 history comes from `FUT86_16.txt` if it is present),
- writes a plain-language summary to `reports/latest_signals.md`,
- logs every step, including skipped years, dropped rows and missing files, to `logs/pipeline.log`.

Constants (paths, markets, symbols, columns) live in `config.py`.

## Where to find data

You may find the extracted data only in the ```data/``` folder and the data + signal infos in the ```signal``` for the different symbols queried. 


## References
- [The Commitments of Traders Bible Book by Stephen Briese on Amazon](https://www.amazon.com/Commitments-Traders-Bible-Insider-Intelligence/dp/0470178426)
- [Learn more on the COT Report on Investopedia](https://www.investopedia.com/terms/c/cot.asp)
- [COT_Reports package by NDelventhal](https://github.com/NDelventhal/cot_reports)

