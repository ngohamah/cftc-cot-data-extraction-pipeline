"""Parity check (pure functions): compare the 1986-2016 history file with per-year CFTC downloads.

Rows are matched on market, report date and CFTC contract code; every column both sources share is
compared cell by cell. Values are compared as numbers when a column is numeric in both sources
(so "001602" equals 1602 and "  -42" equals -42), otherwise as whitespace-trimmed text.
"""

from dataclasses import dataclass, field

import pandas as pd

import config

CODE_COL = "CFTC Contract Market Code"
KEY_COLUMNS = [config.MARKET_COL, config.DATE_COL, CODE_COL]
MAX_EXAMPLES_PER_YEAR = 200


@dataclass(frozen=True)
class YearParity:
    """Result of comparing one year of the history file with that year's official download."""

    year: int
    history_rows: int
    download_rows: int
    columns_only_in_history: list = field(default_factory=list)
    columns_only_in_download: list = field(default_factory=list)
    duplicate_keys_history: int = 0
    duplicate_keys_download: int = 0
    rows_only_in_history: int = 0
    rows_only_in_download: int = 0
    cells_compared: int = 0
    cells_different: int = 0
    different_by_column: dict = field(default_factory=dict)
    examples: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def matches(self):
        """True if both sources have the same columns, rows and values for this year."""
        return not (
            self.columns_only_in_history
            or self.columns_only_in_download
            or self.duplicate_keys_history
            or self.duplicate_keys_download
            or self.rows_only_in_history
            or self.rows_only_in_download
            or self.cells_different
            or self.history_rows != self.download_rows
        )


def strip_column_names(frame):
    """Copy of frame with surrounding whitespace removed from column names (the CFTC files vary)."""
    return frame.rename(columns=lambda c: str(c).strip())


def as_text(series):
    """Whitespace-trimmed text; blanks and NaN become None."""
    text = series.astype("string").str.strip()
    return text.mask(text.isna() | (text == ""), None)


def as_numbers_if_numeric(series):
    """Series as floats if every non-blank value parses as a number, else None."""
    text = as_text(series)
    numbers = pd.to_numeric(text, errors="coerce")
    return numbers if numbers.notna().sum() == text.notna().sum() else None


def normalise_pair(left, right):
    """Put two versions of the same column on a comparable footing (numbers if both numeric, else text)."""
    left_numbers, right_numbers = as_numbers_if_numeric(left), as_numbers_if_numeric(right)
    if left_numbers is not None and right_numbers is not None:
        return left_numbers, right_numbers
    return as_text(left), as_text(right)


def normalise_keys(frame, other):
    """frame with key columns normalised against other (dates as YYYY-MM-DD, codes/markets comparable)."""
    date = pd.to_datetime(as_text(frame[config.DATE_COL]), errors="coerce").dt.strftime("%Y-%m-%d")
    market = as_text(frame[config.MARKET_COL])
    code, _ = normalise_pair(frame[CODE_COL], other[CODE_COL])
    return frame.assign(**{config.DATE_COL: date, config.MARKET_COL: market, CODE_COL: code})


def rows_for_year(history, year):
    """Rows of the history file whose report date falls in year."""
    dates = pd.to_datetime(as_text(history[config.DATE_COL]), errors="coerce")
    return history[dates.dt.year == year]


def display(values):
    """Values as text for the mismatch listing; whole numbers without a trailing .0, blanks as ''."""
    if pd.api.types.is_numeric_dtype(values):
        return values.map(lambda v: "" if pd.isna(v) else (str(int(v)) if float(v).is_integer() else str(v)))
    return values.astype("string").fillna("")


def unequal(left, right):
    """Boolean mask of cells that differ (two blanks count as equal)."""
    both_blank = left.isna() & right.isna()
    return ~(both_blank | (left == right).fillna(False))


def compare_year(year, history_rows, download, columns=None):
    """Compare one year of history rows with the official download for that year.

    columns limits the comparison to those columns (key columns are always used for matching).
    """
    history_rows, download = strip_column_names(history_rows), strip_column_names(download)
    if columns is not None:
        wanted = list(dict.fromkeys(KEY_COLUMNS + list(columns)))
        history_rows, download = history_rows[wanted], download[wanted]
    only_history = sorted(set(history_rows.columns) - set(download.columns))
    only_download = sorted(set(download.columns) - set(history_rows.columns))
    shared = [c for c in history_rows.columns if c in set(download.columns) and c not in KEY_COLUMNS]

    left = normalise_keys(history_rows, download)
    right = normalise_keys(download, history_rows)
    dup_left = int(left.duplicated(subset=KEY_COLUMNS).sum())
    dup_right = int(right.duplicated(subset=KEY_COLUMNS).sum())
    joined = left[KEY_COLUMNS + shared].merge(
        right[KEY_COLUMNS + shared], on=KEY_COLUMNS, how="outer", suffixes=("_history", "_download"), indicator=True
    )
    both = joined[joined["_merge"] == "both"]

    different_by_column, examples = {}, []
    for column in shared:
        history_values, download_values = normalise_pair(both[f"{column}_history"], both[f"{column}_download"])
        mask = unequal(history_values, download_values)
        if mask.any():
            different_by_column[column] = int(mask.sum())
            examples.append(
                both.loc[mask, KEY_COLUMNS].assign(
                    column=column,
                    history_value=display(history_values[mask]),
                    download_value=display(download_values[mask]),
                )
            )
    example_frame = pd.concat(examples, ignore_index=True).head(MAX_EXAMPLES_PER_YEAR) if examples else pd.DataFrame()

    return YearParity(
        year=year,
        history_rows=len(history_rows),
        download_rows=len(download),
        columns_only_in_history=only_history,
        columns_only_in_download=only_download,
        duplicate_keys_history=dup_left,
        duplicate_keys_download=dup_right,
        rows_only_in_history=int((joined["_merge"] == "left_only").sum()),
        rows_only_in_download=int((joined["_merge"] == "right_only").sum()),
        cells_compared=len(both) * len(shared),
        cells_different=sum(different_by_column.values()),
        different_by_column=different_by_column,
        examples=example_frame.assign(year=year) if len(example_frame) else example_frame,
    )


def pipeline_subset(frame):
    """Only the markets the pipeline tracks (names trimmed), for a pipeline-relevant comparison."""
    frame = strip_column_names(frame)
    return frame[as_text(frame[config.MARKET_COL]).isin(config.MARKETS_AND_EXCHANGES)]


def render_parity_report(full, pipeline, history_file, run_time):
    """Plain-language markdown report of the parity check."""
    all_full, all_pipeline = all(r.matches for r in full), all(r.matches for r in pipeline)
    verdict = (
        "**Full match.** Every year of the history file is identical to the CFTC's own yearly files."
        if all_full
        else (
            "**The data the pipeline uses matches**, but other parts of the history file differ from the "
            "yearly downloads (see below)."
            if all_pipeline
            else "**Differences found in data the pipeline uses.** See the tables below and the mismatch CSV."
        )
    )

    def table(results):
        header = (
            "| Year | Rows in history file | Rows in CFTC download | Missing from history | Only in history "
            "| Cells compared | Cells that differ | Match |\n|---|---|---|---|---|---|---|---|\n"
        )
        return header + "".join(
            f"| {r.year} | {r.history_rows:,} | {r.download_rows:,} | {r.rows_only_in_download:,} "
            f"| {r.rows_only_in_history:,} | {r.cells_compared:,} | {r.cells_different:,} "
            f"| {'yes' if r.matches else 'NO'} |\n"
            for r in results
        )

    def notes(results):
        lines = []
        for r in results:
            if r.columns_only_in_history or r.columns_only_in_download:
                lines.append(
                    f"- {r.year}: columns only in history {r.columns_only_in_history or '-'}, "
                    f"only in download {r.columns_only_in_download or '-'}"
                )
            if r.duplicate_keys_history or r.duplicate_keys_download:
                lines.append(
                    f"- {r.year}: repeated market/date/code rows - history {r.duplicate_keys_history}, "
                    f"download {r.duplicate_keys_download}"
                )
            if r.different_by_column:
                worst = sorted(r.different_by_column.items(), key=lambda kv: -kv[1])[:5]
                lines.append(f"- {r.year}: differing cells by column {dict(worst)}")
        return "\n".join(lines) or "- None"

    return (
        "# History file parity check\n\n"
        f"_Generated {run_time:%Y-%m-%d %H:%M}_ - history file: `{history_file}`\n\n"
        "**What this checks:** the pipeline takes 1986-2016 data from one saved file instead of downloading "
        "each year. This check downloads each of those years from the CFTC and compares them with the saved "
        "file row by row (matched on market, report date and contract code) and cell by cell.\n\n"
        f"{verdict}\n\n"
        "## Data the pipeline uses (tracked markets, pipeline columns)\n\n"
        f"{table(pipeline)}\n"
        "## Everything in the files (all markets, all columns)\n\n"
        f"{table(full)}\n"
        "## Details\n\n"
        f"{notes(full)}\n"
    )
