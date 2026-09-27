# Building a Fully Automated COT Pipeline

`cot_report_analysis.ipynb` currently does everything by hand: cells are run in order,
some are commented out to avoid re-downloading data, and outputs are saved by
re-executing the notebook. This doc describes how to turn that notebook into an
unattended pipeline (`pipeline.py`) that runs on a schedule with no manual steps.

## 0. Status (updated 2026-09-27)

`pipeline.py` now runs the notebook end to end (`python pipeline.py`) and reproduces the
notebook's `data/` and `signal/` output row-for-row. What was built, and where it
differs from the plan below:

| Plan item | What was done | Change from plan |
|---|---|---|
| Package layout (`pipeline/ingest.py`, `normalize.py`, …) | Single `pipeline.py` with stage sections (extract / transform / load / orchestration) + `config.py` for constants | Kept to one script + config for now; stages are pure functions so they can be split into modules later without changes |
| Ingest via `cot.cot_year()` | Downloads the same CFTC zip (`deacot<year>.zip`) directly over **one** `requests.Session` (retries + timeout, closed after use) and saves each year to `raw/legacy_fut_<year>.zip`; past years are reused, only the current year is re-downloaded | Replaces `cot_reports` (it opened a new connection per call and wrote temp files to the working directory) |
| Backfill as separate `scripts/backfill_legacy.py` | Integrated: `FUT86_16.txt` is read only when a `data/<symbol>.csv` is missing or with `--rebuild`; logs a warning if the file is absent | Keeps the "recreate deleted files" requirement working in one command |
| Normalization | DJIA, USD index **and NZ dollar** (`NZ DOLLAR - CHICAGO MERCANTILE EXCHANGE`, CFTC name since Feb 2022) unified | NZ mapping was missing in the notebook, so NEW ZEALAND data stopped at 2022-02-01 |
| De-dup / validation / atomic writes | Done: de-dup on market + date, required-column check, refuse to overwrite a file with fewer rows, temp-file-then-rename writes | — |
| Signals | Vectorised (`np.select`), same codes 1-4 and same `signal/*.csv` columns | — |
| Prices (`saveClosingPrice`) | Not implemented | The function is no longer in the notebook; revisit if price enrichment is still wanted |
| Logging | `logs/pipeline.log` + console; logs skipped years, dropped/duplicate rows, missing files | — |
| Reporting | `reports/latest_signals.md`: plain-language table of each market's latest week | New (for non-technical readers) |
| Tests / lint / CI | `tests/test_pipeline.py` (pytest, no network), `ruff` lint + format, GitHub Actions `ci.yml` on every push/PR, badge in README | CI runs lint + tests only; the weekly **scheduled** run (section 3) is not set up yet |
| Dependencies | `requirements.txt` (pinned: numpy, pandas, requests, urllib3, pytest, ruff) | — |

Still open: scheduled weekly run (section 3), price enrichment (stage 5), and the
Airflow version described in `plan.md`.

## 1. What the notebook does today

Reading the notebook top to bottom, the logic falls into six stages:

1. **Config** (cells 6) — three hardcoded lists: `special_columns` (CFTC columns to
   keep), `markets_and_exchanges` (every historical spelling of each market name),
   `symbol_names` (the canonical name we normalize each market to), plus
   `symbols_and_tickers` (cell 22, canonical name → Yahoo Finance ticker).
2. **Historical backfill** (cells 8-13) — reads a local file
   `../large files/FUT86_16.txt` (legacy futures 1986-2016, *not* in this repo),
   filters it to `markets_and_exchanges`, collapses DJIA naming variants, and writes
   one CSV per symbol to `data/<symbol>.csv`.
3. **Incremental update** (cells 15-17) — for each year from 2017 to the present,
   calls `cot.cot_year(year, cot_report_type="legacy_fut")` to pull that year's
   report from the CFTC, normalizes names (`handle_nzusd_usindex_case`), concatenates
   it onto the existing `data/<symbol>.csv`, and recomputes `Net Positions` /
   `Change Net Positions`.
4. **Signal engineering** (cells 19-21, 23) — `assign_signal_and_interpretation`
   turns `Change Net Positions` + `Change in Open Interest` into a 1-4 signal code
   (Bullish / Bearish / Bullish Reversal / Bearish Reversal). `perform_signal()`
   applies this per symbol and writes `signal/<symbol>.csv`.
5. **Price enrichment** (cell 23, `saveClosingPrice`) — pulls daily closes from
   `yfinance` per ticker and merges them onto the asset data. Defined but not
   wired into `perform_signal()`, and its `return` sits inside the `for` loop, so
   today it only ever produces one merged frame instead of saving all symbols.
6. **Run** (cell 24) — `perform_signal()` is called once, at the bottom of the
   notebook, on whatever `data/*.csv` happens to be on disk at that moment.

### Gaps that block automation

- **External dependency**: the 1986-2016 backfill needs `../large files/FUT86_16.txt`,
  a file outside the repo. A scheduled job can't re-run this step; it must run once
  and be excluded from the recurring pipeline.
- **No idempotency**: `modify_old_with_new` concatenates the new year's rows onto
  the old CSV with no de-dup on date. Running the update twice for the same year
  duplicates rows.
- **No incremental price fetch**: `saveClosingPrice` re-downloads full history
  (`start="1986-01-01"`) every run and only completes for one symbol due to the
  early `return`.
- **No scheduling, logging, retries, or validation** — everything depends on a
  human opening Jupyter and running cells in order.
- **No dependency manifest** — the notebook imports `cot_reports`, `pandas`,
  `numpy`, `yfinance`, `matplotlib`, `pandas_ta`, but there's no `requirements.txt`.

## 2. Target pipeline shape

Replace the notebook run-order with an idempotent, resumable script structured as
a small package, driven by `pipeline.py` as the CLI entrypoint:

```
pipeline/
  config.py       # special_columns, markets_and_exchanges, symbol_names, symbols_and_tickers
  ingest.py        # cot.cot_year() calls, one per year since the last run
  normalize.py     # name unification (DJIA / NZ dollar / USD index cases)
  features.py      # Net Positions, Change Net Positions, signal/interpretation
  prices.py        # incremental yfinance fetch + merge, fixed to loop over all symbols
  storage.py       # read/write data/*.csv and signal/*.csv with de-dup on date
pipeline.py         # CLI: parses args, wires the stages above, logs progress
```

Each stage should be a pure function that takes/returns DataFrames — the notebook's
`for sn in symbol_names: ... .to_csv(...)` pattern works for a one-off script but
makes it impossible to unit test or re-run a single stage in isolation.

### Stage-by-stage changes

| Stage | Notebook today | Pipeline change |
|---|---|---|
| Config | Inline lists in cells | Move to `pipeline/config.py` (or a YAML file) so adding a symbol doesn't require editing pipeline logic |
| Backfill | Manual, one-time, reads local txt | Keep as a **separate one-off script** (`scripts/backfill_legacy.py`), not part of the recurring pipeline |
| Update | `update_for_multiple_years(np.arange(2017, 2027))` — refetches every year, every run | Track the max date already in `data/<symbol>.csv`; only call `cot.cot_year()` for the current year (CFTC republishes the current year's file weekly) |
| De-dup | `pd.concat([old_df, new_df])` | Concat then `drop_duplicates(subset=["Market and Exchange Names", "As of Date in Form YYYY-MM-DD"], keep="last")` before writing — **done in notebook** (`merge_symbol_data`) |
| Missing files | `pd.read_csv("data/<symbol>.csv")` crashed with `FileNotFoundError` if the file was deleted | If `data/<symbol>.csv` (or `data/`/`signal/` itself) is missing or unreadable, create it from the new report and log a warning; symbols with no rows and no file are skipped and logged — **done in notebook** (`modify_old_with_new`, `perform_signal`) |
| Signals | `perform_signal()` reruns on entire history | Fine to keep recomputing signals for the whole file (cheap, ensures consistency) but only after ingestion has updated the source data |
| Prices | `saveClosingPrice()` — full history, breaks after first symbol | Fix the loop (accumulate results per symbol, don't `return` early); fetch only from the last saved date forward |
| Storage | Direct `to_csv` overwrite | Write to a temp file and rename on success, so a failed run never leaves a half-written CSV |

## 3. Automation / scheduling

The CFTC publishes the Commitments of Traders report every **Friday at 3:30pm ET**
for positions as of the prior Tuesday. The pipeline should run once after that,
e.g. Saturday morning UTC.

Options, in order of how much infra they need:

- **Local cron** (`crontab -e`): `0 8 * * 6 /path/to/.venv/bin/python /path/to/pipeline.py`
- **GitHub Actions** (recommended if this repo is the source of truth): a scheduled
  workflow (`.github/workflows/pipeline.yml`) with `on: schedule: cron: '0 8 * * 6'`,
  that installs dependencies, runs `python pipeline.py`, and commits the updated
  `data/` and `signal/` CSVs back with a bot commit if anything changed.
- **Managed scheduler** (Airflow/Prefect/Dagster) — only worth it if this pipeline
  grows beyond COT data (e.g. joins with other datasets, alerting, backfill UI).

For a repo this size, GitHub Actions + a bot commit is the simplest fully-automated
option and keeps the CSVs versioned in git history.

## 4. Reliability additions the notebook skips

- **Logging**: replace `print`/silent failures with the `logging` module; log
  row counts written per symbol so a silent empty-write is visible in CI logs.
- **Retries**: wrap `cot.cot_year()` and `yf.download()` calls with retry/backoff
  (both hit external services that occasionally rate-limit or time out).
- **Validation**: before overwriting `data/<symbol>.csv`, assert the new frame has
  at least as many rows as the old one and that `special_columns` are all present —
  fail loud rather than silently truncating history.
- **Dependency manifest**: add a `requirements.txt` (or `pyproject.toml`) pinning
  `cot_reports`, `pandas`, `numpy`, `yfinance`, `pandas_ta` so CI installs a known
  environment.

## 5. Migration steps

1. Extract cells 6 and 22 into `pipeline/config.py` as plain Python constants.
2. Extract `handle_nzusd_usindex_case` and the DJIA replacement into
   `pipeline/normalize.py`.
3. Extract `assign_signal_and_interpretation` and `perform_signal` into
   `pipeline/features.py`, keeping the same signal codes (1-4) so `signal/*.csv`
   stays backward-compatible.
4. Rewrite `update_for_particular_year` / `update_for_multiple_years` in
   `pipeline/ingest.py`, adding the date-based de-dup described above.
5. Fix and extract `saveClosingPrice` into `pipeline/prices.py`.
6. Write `pipeline.py` as the CLI: `python pipeline.py --since-last-run` (default)
   or `python pipeline.py --year 2024` (manual re-run of a specific year).
7. Move the one-time 1986-2016 backfill (cells 8-13) into `scripts/backfill_legacy.py`
   — run once locally, never scheduled.
8. Add `requirements.txt` and a GitHub Actions workflow that runs `pipeline.py`
   on the weekly schedule and commits changed CSVs.
9. Once `pipeline.py` is verified against the notebook's output (same row counts,
   same signal values), the notebook becomes exploratory/analysis-only — it should
   no longer be the thing that produces `data/` and `signal/`.

## References

- [COT_Reports package by NDelventhal](https://github.com/NDelventhal/cot_reports)
- [CFTC Commitments of Traders release schedule](https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm)
