"""Constants for the COT pipeline: paths, source URLs, markets and column names."""

from pathlib import Path

# --- paths ---------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
SIGNAL_DIR = PROJECT_ROOT / "signal"
RAW_DIR = PROJECT_ROOT / "raw"
REPORT_DIR = PROJECT_ROOT / "reports"
LOG_FILE = PROJECT_ROOT / "logs" / "pipeline.log"

# legacy futures 1986-2016, downloaded once with cot.cot_hist(store_txt=True)
HISTORICAL_FILE = PROJECT_ROOT / "old_data" / "FUT86_16.txt"

# --- CFTC source ---------------------------------------------------------
# yearly legacy futures report (same file cot_reports.cot_year downloads)
CFTC_YEAR_URL = "https://cftc.gov/files/dea/history/deacot{year}.zip"
FIRST_API_YEAR = 2017
REQUEST_TIMEOUT_SECONDS = 60
REQUEST_RETRIES = 3

# --- column names --------------------------------------------------------
MARKET_COL = "Market and Exchange Names"
DATE_COL = "As of Date in Form YYYY-MM-DD"
LONG_COL = "Noncommercial Positions-Long (All)"
SHORT_COL = "Noncommercial Positions-Short (All)"
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
    "Open Interest (All)",
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
