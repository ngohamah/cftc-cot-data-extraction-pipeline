"""Backfill (or re-ingest) price bars by calling the ingest-price-bars Supabase Edge Function.

The Edge Function (supabase/functions/ingest-price-bars) downloads daily price bars from Yahoo
Finance and stores them in the price_bars table. This script asks it to do that for the full
history, one asset per request so each call stays small, and reports what happened.

Reads two environment variables (never put their values in the code):
  INGEST_PRICE_BARS_URL     https://<project-ref>.supabase.co/functions/v1/ingest-price-bars
  INGEST_PRICE_BARS_SECRET  the function's CRON_SECRET

Usage:
  python scripts/backfill_price_bars.py                 # every enabled asset, range=max
  python scripts/backfill_price_bars.py --assets GOLD   # one asset
  python scripts/backfill_price_bars.py --range 1y      # smaller re-ingest

Exit code 1 if any asset failed; details are printed and logged to logs/price_backfill.log.
"""

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # allow running from any folder

import requests  # noqa: E402

import config  # noqa: E402
from cot_pipeline.logging_setup import LOGGER_NAME, configure_logging  # noqa: E402

logger = logging.getLogger(f"{LOGGER_NAME}.price_backfill")

# the function answers 207 when it ran but at least one asset failed; the body says which
ACCEPTED_STATUS_CODES = (200, 207)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--assets", nargs="*", help="asset names, e.g. GOLD JPYUSD (default: all enabled)")
    parser.add_argument(
        "--range",
        default=config.PRICE_DEFAULT_RANGE,
        choices=config.PRICE_RANGES,
        help=f"how much history to (re)load (default: {config.PRICE_DEFAULT_RANGE})",
    )
    parser.add_argument("--log-file", type=Path, default=config.PRICE_LOG_FILE, help="where to write the log")
    return parser.parse_args(argv)


def read_settings(env):
    """Return (url, secret) from the environment, or raise with the names that are missing."""
    missing = [name for name in (config.PRICE_INGEST_URL_ENV, config.PRICE_INGEST_SECRET_ENV) if not env.get(name)]
    if missing:
        raise ValueError(f"missing environment variable(s): {', '.join(missing)}")
    return env[config.PRICE_INGEST_URL_ENV], env[config.PRICE_INGEST_SECRET_ENV]


def summarize(results):
    """Split per-asset results into (ok lines, failed lines) for the run summary."""
    ok, failed = [], []
    for item in results:
        if item.get("error"):
            failed.append(f"{item['asset']}: {item['error']}")
        else:
            ok.append(f"{item['asset']}: {item.get('bars', 0)} bars")
    return ok, failed


def list_assets(session, url, secret):
    """Ask the function which assets are enabled in the price_assets table."""
    response = session.get(url, headers={"x-cron-secret": secret}, timeout=config.PRICE_INGEST_LIST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()["assets"]


def ingest(session, url, secret, asset, range_):
    """Ingest one asset and return the function's summary for it ({asset, bars} or {asset, error})."""
    response = session.post(
        url,
        json={"assets": [asset], "range": range_},
        headers={"x-cron-secret": secret},
        timeout=config.PRICE_INGEST_TIMEOUT_SECONDS,
    )
    if response.status_code not in ACCEPTED_STATUS_CODES:
        response.raise_for_status()
    summary = response.json().get("summary", [])
    if not summary:
        return {"asset": asset, "error": "not an enabled asset (no summary returned)"}
    return summary[0]


def ingest_all(session, url, secret, assets, range_):
    """Ingest every asset in turn; a failed request is recorded as that asset's error, not raised."""
    results = []
    for asset in assets:
        logger.info("ingesting %s (range=%s)", asset, range_)
        try:
            result = ingest(session, url, secret, asset, range_)
        except (requests.RequestException, ValueError, KeyError) as exc:
            result = {"asset": asset, "error": f"request failed: {exc}"}
        if result.get("error"):
            logger.error("%s failed: %s", asset, result["error"])
        else:
            logger.info("%s: %s bars upserted", asset, result.get("bars", 0))
        results.append(result)
    return results


def main(argv=None, env=None):
    args = parse_args(argv)
    configure_logging(args.log_file)
    try:
        url, secret = read_settings(env if env is not None else os.environ)
    except ValueError as exc:
        logger.error("%s", exc)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    with requests.Session() as session:  # one connection for every request, closed when done
        try:
            assets = args.assets or list_assets(session, url, secret)
        except (requests.RequestException, ValueError, KeyError) as exc:
            logger.error("could not list enabled assets: %s", exc)
            print(f"ERROR: could not list enabled assets: {exc}", file=sys.stderr)
            return 2
        logger.info("backfilling %d asset(s) with range=%s", len(assets), args.range)
        results = ingest_all(session, url, secret, assets, args.range)

    ok, failed = summarize(results)
    print("\n".join(ok))
    if failed:
        print("\nFAILED:\n" + "\n".join(failed), file=sys.stderr)
        logger.error("%d of %d asset(s) failed", len(failed), len(results))
        return 1
    logger.info("all %d asset(s) ingested", len(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
