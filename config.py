"""Constants for the COT pipeline: paths, source URLs, markets and column names."""

from pathlib import Path

# --- paths ---------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
SIGNAL_DIR = PROJECT_ROOT / "signal"
RAW_DIR = PROJECT_ROOT / "raw"
REPORT_DIR = PROJECT_ROOT / "reports"
LOG_FILE = PROJECT_ROOT / "logs" / "pipeline.log"  # local runs; not in git
# log of the weekly GitHub Actions run; committed by the bot so local logs are never overwritten on pull
CI_LOG_FILE = PROJECT_ROOT / "logs" / "ci" / "pipeline.log"

# legacy futures 1986-2016 (downloaded once with cot.cot_hist(store_txt=True)), kept in raw/
# with the yearly batches; only years from FIRST_API_YEAR on are requested over HTTP
HISTORICAL_FILENAME = "FUT86_16.txt"
HISTORICAL_FILE = RAW_DIR / HISTORICAL_FILENAME

# --- CFTC source ---------------------------------------------------------
# yearly legacy futures report (same file cot_reports.cot_year downloads)
CFTC_YEAR_URL = "https://cftc.gov/files/dea/history/deacot{year}.zip"
FIRST_API_YEAR = 2017
# CFTC publishes each Friday 15:30 US Eastern, with positions as of the Tuesday 3 days earlier
RELEASE_TIMEZONE = "America/New_York"
RELEASE_WEEKDAY = 4  # Friday (Monday = 0)
RELEASE_HOUR, RELEASE_MINUTE = 15, 30
REPORT_DAYS_BEFORE_RELEASE = 3
# holiday weeks move the as-of date (e.g. to Monday); a saved copy counts as up to date if it has
# a report within this many days before the expected as-of date
REPORT_DATE_TOLERANCE_DAYS = 6
REQUEST_TIMEOUT_SECONDS = 60
REQUEST_RETRIES = 3

# --- column names --------------------------------------------------------
MARKET_COL = "Market and Exchange Names"
DATE_COL = "As of Date in Form YYYY-MM-DD"
LONG_COL = "Noncommercial Positions-Long (All)"
SHORT_COL = "Noncommercial Positions-Short (All)"
OPEN_INTEREST_COL = "Open Interest (All)"
OPEN_INTEREST_CHANGE_COL = "Change in Open Interest (All)"
NET_COL = "Net Positions"
NET_CHANGE_COL = "Change Net Positions"

# special fields for analysing the commitment of traders report
SPECIAL_COLUMNS = [
    MARKET_COL,
    DATE_COL,
    LONG_COL,
    SHORT_COL,
    "Change in Noncommercial-Long (All)",
    "Change in Noncommercial-Short (All)",
    OPEN_INTEREST_COL,
    OPEN_INTEREST_CHANGE_COL,
]
NUMERIC_COLUMNS = SPECIAL_COLUMNS[2:]
DATA_COLUMNS = SPECIAL_COLUMNS + [NET_COL, NET_CHANGE_COL]

SIGNAL_COLUMNS = [
    DATE_COL,
    LONG_COL,
    SHORT_COL,
    "Change in Noncommercial-Long (All)",
    "Change in Noncommercial-Short (All)",
    "Open Interest (All)",
    NET_COL,
    "Interpretation",
]

# --- markets -------------------------------------------------------------
# specific markets and exchanges with names that changed over the years
MARKETS_AND_EXCHANGES = [
    "MEXICAN PESO - CHICAGO MERCANTILE EXCHANGE",
    "MEXICAN PESO - INTERNATIONAL MONETARY MARKET",
    "JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE",
    "JAPANESE YEN - INTERNATIONAL MONETARY MARKET",
    "EURO FX - CHICAGO MERCANTILE EXCHANGE",
    "EURO FX - INTERNATIONAL MONETARY",
    "DJIA Consolidated - CHICAGO BOARD OF TRADE",
    "DOW JONES INDUSTRIAL AVERAGE - CHICAGO BOARD OF TRADE",
    "NASDAQ-100 Consolidated - CHICAGO MERCANTILE EXCHANGE",
    "NASDAQ-100 STOCK INDEX - CHICAGO MERCANTILE EXCHANGE",
    "NASDAQ-100 STOCK INDEX - INTERNATIONAL MONETARY MARKET",
    "NEW ZEALAND DOLLAR - CHICAGO MERCANTILE EXCHANGE",
    "NEW ZEALAND DOLLARS - CHICAGO MERCANTILE EXCHANGE",
    "NEW ZEALAND DOLLARS - INTERNATIONAL MONETARY MARKET",
    "NZ DOLLAR - CHICAGO MERCANTILE EXCHANGE",
    "AUSTRALIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE",
    "AUSTRALIAN DOLLARS - CHICAGO MERCANTILE EXCHANGE",
    "AUSTRALIAN DOLLARS - INTERNATIONAL MONETARY MARKET",
    "CANADIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE",
    "CANADIAN DOLLAR - INTERNATIONAL MONETARY MARKET",
    "SWISS FRANC - CHICAGO MERCANTILE EXCHANGE",
    "SWISS FRANC - INTERNATIONAL MONETARY MARKET",
    "BRITISH POUND STERLING - INTERNATIONAL MONETARY MARKET",
    "BRITISH POUND STERLING - CHICAGO MERCANTILE EXCHANGE",
    "POUND STERLING - CHICAGO MERCANTILE EXCHANGE",
    "POUND STERLING - INTERNATIONAL MONETARY MARKET",
    "BRITISH POUND - CHICAGO MERCANTILE EXCHANGE",
    "U.S. DOLLAR INDEX - NEW YORK COTTON EXCHANGE",
    "U.S. DOLLAR INDEX - ICE FUTURES U.S.",
    "U.S. DOLLAR INDEX - NEW YORK BOARD OF TRADE",
    "USD INDEX - ICE FUTURES U.S.",
    "1000 TROY OUNCE SILVER - CHICAGO BOARD OF TRADE",
    "SILVER - CHICAGO BOARD OF TRADE",
    "SILVER, 5000 TROY OZ - CHICAGO BOARD OF TRADE",
    "SILVER - COMMODITY EXCHANGE INC.",
    "COPPER - COMMODITY EXCHANGE INC.",
    "COPPER-GRADE #1 - COMMODITY EXCHANGE INC.",
    "COPPER- #1 - COMMODITY EXCHANGE INC.",
    "GOLD, 100 TROY OZ - CHICAGO BOARD OF TRADE",
    "GOLD - COMMODITY EXCHANGE INC.",
    "GOLD - INTERNATIONAL MONETARY MARKET",
    "PLATINUM - NEW YORK MERCANTILE EXCHANGE",
    "PLATINUM - COMMODITY EXCHANGE INC.",
    "BITCOIN - CHICAGO MERCANTILE EXCHANGE",
    "CRUDE OIL, LIGHT SWEET-WTI - ICE FUTURES EUROPE",
]

# unify names that don't contain their symbol (DJIA, USD index, NZ dollar since Feb 2022)
MARKET_NAME_REPLACEMENTS = {
    "DOW JONES INDUSTRIAL AVERAGE - CHICAGO BOARD OF TRADE": "DJIA Consolidated - CHICAGO BOARD OF TRADE",
    "USD INDEX - ICE FUTURES U.S.": "U.S. DOLLAR INDEX - ICE FUTURES U.S.",
    "NZ DOLLAR - CHICAGO MERCANTILE EXCHANGE": "NEW ZEALAND DOLLAR - CHICAGO MERCANTILE EXCHANGE",
}

# naming conventions we adopt; a market belongs to a symbol if its name contains it
SYMBOL_NAMES = [
    "MEXICAN PESO",
    "JAPANESE YEN",
    "EURO FX",
    "DJIA Consolidated",
    "NASDAQ-100",
    "NEW ZEALAND",
    "AUSTRALIAN",
    "CANADIAN DOLLAR",
    "SWISS FRANC",
    "POUND",
    "U.S. DOLLAR INDEX",
    "SILVER",
    "COPPER",
    "GOLD",
    "PLATINUM",
    "BITCOIN",
    "CRUDE OIL",
]

# --- signals -------------------------------------------------------------
# (code, interpretation) from change in net positions vs change in open interest
SIGNAL_NONE = (0, "No signal")
SIGNAL_BULLISH = (1, "Bullish")
SIGNAL_BEARISH = (2, "Bearish")
SIGNAL_BEARISH_REVERSAL = (3, "Bearish Reversal")
SIGNAL_BULLISH_REVERSAL = (4, "Bullish Reversal")

# --- positioning regimes (unsupervised clustering, scripts/gold_regimes.py) ---------------------
REGIME_SYMBOL = "GOLD"
# the main COMEX contract; the small CBOT 100 oz and IMM gold contracts would read as false extremes
REGIME_MARKET = "GOLD - COMMODITY EXCHANGE INC."
REGIME_REPORT_FILE = REPORT_DIR / "gold_regimes.md"
REGIME_FIGURE_DIR = REPORT_DIR / "figures" / "gold_regimes"
REGIME_LOG_FILE = PROJECT_ROOT / "logs" / "regimes.log"

# short names used by the analysis notebook (gold_df) and the regime code
ANALYSIS_COLUMN_NAMES = {
    MARKET_COL: "market",
    DATE_COL: "date",
    LONG_COL: "long",
    SHORT_COL: "short",
    "Change in Noncommercial-Long (All)": "change_long",
    "Change in Noncommercial-Short (All)": "change_short",
    "Open Interest (All)": "open_interest",
    OPEN_INTEREST_CHANGE_COL: "change_open_interest",
    NET_COL: "net_positions",
    NET_CHANGE_COL: "change_net_positions",
}

# COT index: where this week's net position sits between its min (0) and max (1) of the last 3 years
COT_INDEX_WINDOW_WEEKS = 156
COT_INDEX_MIN_WEEKS = 52
FLOW_WINDOW_WEEKS = 4  # smoothing window for the (noisy) weekly flow features
FORWARD_HORIZON_WEEKS = 8  # "what happens next": change in net position over the following weeks
CLIP_QUANTILES = (0.01, 0.99)  # tame extreme weeks before scaling

# slow-moving "where speculators stand" features: these define the regimes
STATE_FEATURES = ["long_share", "short_share", "cot_index"]
# fast "what they did lately" features: compared during model selection, not used for the regimes
FLOW_FEATURES = ["net_flow_4w", "oi_growth_4w"]

CANDIDATE_CLUSTER_COUNTS = (2, 3, 4, 5, 6, 7)
DBSCAN_EPS_VALUES = (0.3, 0.5, 0.8, 1.0, 1.5)
DBSCAN_MIN_SAMPLES = 10
N_REGIMES = 4  # chosen from the model-selection scorecard (see reports/gold_regimes.md)
# names in order of each regime's average net position (most short -> most long)
# (named from the regime profiles: 88% of "Net short / 3-yr low" weeks are net short, the rest sit near
# 3-year lows; "Long, off the highs" is net long but low in its 3-year range with more shorts active)
REGIME_NAMES = ("Net short / 3-yr low", "Low participation", "Long, off the highs", "Crowded long")
RANDOM_STATE = 0
KMEANS_N_INIT = 10
GMM_N_INIT = 5
BOOTSTRAP_ROUNDS = 20

# --- daily prices (Yahoo Finance; downloaded once by scripts/fetch_prices.py, then read from disk) ----
# COMEX gold futures (front month): the same contract the COT report covers; history from Aug 2000.
# GLD (the gold ETF) moves almost identically (weekly-return correlation 0.98) but only starts in Nov 2004.
PRICE_TICKER = "GC=F"
PRICE_START = "2000-01-01"
PRICE_DIR = DATA_DIR / "prices"
PRICE_FILE = PRICE_DIR / "GOLD_GC=F.csv"
PRICE_COLUMNS = ["date", "open", "high", "low", "close", "volume"]
PRICE_MATCH_TOLERANCE_DAYS = 5  # use the last close on or before the report date, at most this many days earlier
PRICE_TREND_WEEKS = 13  # "recent trend": gold's return over the last quarter
PRICE_FEATURES = ["price_pct_3y", "return_13w"]  # added to STATE_FEATURES for the "with price" model
LEAD_LAG_WEEKS = 8  # how far back / ahead to compare speculator moves with price moves

# "big moves": gold's move over the weeks after a report is published, ranked by size (up or down)
BIG_MOVE_WEEKS = 4
BIG_MOVE_QUANTILE = 0.8  # the largest 20% of moves count as "big"
VOLATILITY_WEEKS = 13  # how jumpy gold has been: spread of its weekly moves over the last quarter
CLUE_GROUPS = 5  # split each clue into fifths (calmest 20% ... jumpiest 20%)

# --- figure style (validated reference palette; 3 hues + neutral gray for the quiet regime) ------
# colours follow REGIME_NAMES; each regime also gets its own marker so colour is never the only cue
REGIME_COLORS = ("#eb6834", "#898781", "#1baf7a", "#2a78d6")
REGIME_MARKERS = ("D", "o", "^", "s")
SERIES_COLORS = ("#2a78d6", "#eb6834", "#1baf7a")  # model comparison lines, in fixed order
DIVERGING_COLORS = ("#2a78d6", "#f0efec", "#e34948")  # below average <- typical -> above average
SEQUENTIAL_COLORS = ("#f0efec", "#2a78d6", "#0d366b")
PLOT_SURFACE = "#fcfcfb"
PLOT_INK = "#0b0b0b"
PLOT_INK_SECONDARY = "#52514e"
PLOT_INK_MUTED = "#898781"
PLOT_GRID = "#e1e0d9"
PLOT_AXIS = "#c3c2b7"
FIGURE_DPI = 150
