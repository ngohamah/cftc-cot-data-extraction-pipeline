"""Download daily gold prices from Yahoo Finance once and save them to data/prices/.

Later steps (scripts/gold_regimes.py, the notebook) read the saved file, so Yahoo is only contacted when the
file is missing or --refresh is given. Progress is logged to logs/regimes.log.

Usage: python scripts/fetch_prices.py [--refresh] [--ticker GC=F]
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # allow running from any folder

import config  # noqa: E402
from cot_pipeline.logging_setup import LOGGER_NAME, configure_logging  # noqa: E402
from cot_pipeline.prices import PriceDownloadError, download_prices, tidy_prices  # noqa: E402
from cot_pipeline.storage import write_csv  # noqa: E402

logger = logging.getLogger(f"{LOGGER_NAME}.fetch_prices")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--refresh", action="store_true", help="download again even if the file exists")
    parser.add_argument("--ticker", default=config.PRICE_TICKER, help=f"Yahoo ticker (default {config.PRICE_TICKER})")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    configure_logging(config.REGIME_LOG_FILE)
    path = config.PRICE_FILE if args.ticker == config.PRICE_TICKER else config.PRICE_DIR / f"GOLD_{args.ticker}.csv"
    if path.exists() and not args.refresh:
        logger.info("Prices already saved at %s; not downloading (use --refresh to update)", path)
        return 0
    try:
        prices = tidy_prices(download_prices(args.ticker))
    except (PriceDownloadError, ValueError) as error:
        logger.error("Could not get prices: %s", error)
        return 1
    write_csv(prices, path)
    logger.info(
        "Saved %d daily prices for %s (%s to %s) to %s",
        len(prices),
        args.ticker,
        prices["date"].min().date(),
        prices["date"].max().date(),
        path,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
