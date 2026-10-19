"""Find positioning regimes in gold with unsupervised clustering, and show why the chosen model fits best.

Reads data/GOLD.csv (COMEX contract only), compares K-Means, Gaussian mixture, hierarchical and DBSCAN
clustering, labels every week with a K-Means regime and writes:
  reports/gold_regimes.md                 plain-language summary with the figures
  reports/gold_regimes_weekly.csv         every week's features and regime
  reports/figures/gold_regimes/*.png      the figures
Progress and dropped rows are logged to logs/regimes.log.

Usage: python scripts/gold_regimes.py [--rounds 20]
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # allow running from any folder

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

import config  # noqa: E402
from cot_pipeline import regime_plots as plots  # noqa: E402
from cot_pipeline import regimes  # noqa: E402
from cot_pipeline.logging_setup import LOGGER_NAME, configure_logging  # noqa: E402
from cot_pipeline.storage import write_csv, write_text  # noqa: E402

logger = logging.getLogger(f"{LOGGER_NAME}.regimes_script")

WEEKLY_CSV = config.REPORT_DIR / "gold_regimes_weekly.csv"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rounds", type=int, default=config.BOOTSTRAP_ROUNDS, help="subsample rounds for stability")
    return parser.parse_args(argv)


def analyse(raw, rounds=config.BOOTSTRAP_ROUNDS):
    """Everything the figures and report need, computed from the raw symbol CSV (no file output)."""
    frame = regimes.prepare_market_frame(raw)
    features = regimes.build_features(frame)
    state = regimes.complete_rows(features, config.STATE_FEATURES)
    state_matrix = regimes.scale_features(state, config.STATE_FEATURES)
    flow_columns = config.STATE_FEATURES + config.FLOW_FEATURES
    flow_matrix = regimes.scale_features(regimes.complete_rows(features, flow_columns), flow_columns)
    logger.info("Scoring models on %d weeks (%d subsample rounds each)", len(state_matrix), rounds)
    labelled = regimes.assign_regimes(features)
    profile = regimes.regime_profile(labelled)
    return {
        "frame": frame,
        "features": features,
        "state_matrix": state_matrix,
        "scorecard": regimes.model_scorecard(state_matrix, rounds=rounds),
        "flow_scorecard": regimes.model_scorecard(
            flow_matrix, clusterers={"K-Means": regimes.kmeans_labels}, rounds=rounds
        ),
        "bic": regimes.gmm_bic(state_matrix),
        "dbscan": regimes.dbscan_summary(state_matrix),
        "labelled": labelled,
        "profile": profile,
        "transitions": regimes.transition_matrix(labelled["regime"]),
        "test": regimes.forward_flow_test(labelled),
    }


def build_figures(result):
    """(file name, figure) pairs in the order the report shows them."""
    labelled, profile = result["labelled"], result["profile"]
    return [
        ("1_scale_free_features.png", plots.scale_free_figure(result["frame"], result["features"])),
        (
            "2_model_selection.png",
            plots.model_selection_figure(
                result["scorecard"], result["flow_scorecard"], result["bic"], result["dbscan"]
            ),
        ),
        ("3_regime_map.png", plots.regime_map_figure(labelled, profile)),
        ("4_regime_fingerprint.png", plots.fingerprint_figure(labelled, profile)),
        ("5_regime_timeline.png", plots.regime_timeline_figure(labelled)),
        ("6_what_happens_next.png", plots.what_happens_next_figure(labelled, profile, result["test"])),
        ("7_regime_transitions.png", plots.transition_figure(result["transitions"])),
        ("8_silhouette_by_week.png", plots.silhouette_figure(result["state_matrix"], labelled["regime"].to_numpy())),
    ]


def _table(frame):
    header = "| " + " | ".join(frame.columns) + " |"
    divider = "|" + "---|" * len(frame.columns)
    rows = ["| " + " | ".join(str(v) for v in row) + " |" for row in frame.itertuples(index=False)]
    return "\n".join([header, divider, *rows])


def render_report(result, figure_names):
    """Plain-language markdown summary for readers without a statistics background."""
    profile, scorecard, test = result["profile"], result["scorecard"], result["test"]
    labelled = result["labelled"]
    chosen = scorecard[(scorecard["model"] == "K-Means") & (scorecard["k"] == config.N_REGIMES)].iloc[0]
    latest = labelled.iloc[-1]
    regime_table = pd.DataFrame(
        {
            "Regime": profile["name"],
            "Share of weeks": profile["share_of_history"].map("{:.0%}".format),
            "Typical stay": profile["typical_stay_weeks"].map("{:.0f} weeks".format),
            "Net position (share of OI)": profile["net_share"].map("{:+.0%}".format),
            f"Avg. net change next {config.FORWARD_HORIZON_WEEKS} wks": profile["forward_net_flow"].map(
                "{:+.1%}".format
            ),
            "Speculators added afterwards": profile["share_added_next"].map("{:.0%}".format),
            "Seen": profile["first_seen"].dt.year.astype(str) + "-" + profile["last_seen"].dt.year.astype(str),
        }
    )
    score_table = (
        scorecard[scorecard["k"] == config.N_REGIMES][
            ["model", "silhouette", "davies_bouldin", "stability", "avg_regime_weeks"]
        ]
        .round(2)
        .rename(
            columns={
                "model": "Model",
                "silhouette": "Separation (silhouette, higher better)",
                "davies_bouldin": "Overlap (Davies-Bouldin, lower better)",
                "stability": "Repeatability (1 = identical)",
                "avg_regime_weeks": "Avg. weeks per regime",
            }
        )
    )
    figures = "\n\n".join(f"![{name}](figures/gold_regimes/{name})" for name in figure_names)
    p_text = "less than 0.001" if test["p_value"] < 0.001 else f"{test['p_value']:.3f}"
    return f"""# Gold positioning regimes

_Generated by `scripts/gold_regimes.py` from {len(labelled)} weekly COT reports
({labelled["date"].min():%Y-%m-%d} to {labelled["date"].max():%Y-%m-%d}), COMEX gold only._

## In short

- Large speculators in gold move between **{config.N_REGIMES} positioning regimes**, found by K-Means clustering
  without being told what to look for.
- The regime **tells you something about what speculators do next**: crowded longs tend to be trimmed and
  net-short positions tend to be covered (short covering) (statistical test p-value {p_text}).
- Latest report ({latest["date"]:%Y-%m-%d}): **{latest["regime_name"]}**.

These are descriptions of past positioning, not trading recommendations.

## The regimes

{_table(regime_table)}

## Why K-Means with {config.N_REGIMES} regimes

Positions are measured as a share of open interest because the market today is many times bigger than in 1986.
Only the slow-moving "where speculators stand" features are used (long share, short share and the 3-year
percentile of the net position). Adding the noisy 4-week flows made every model's groups blurrier.

- **DBSCAN** (density) puts nearly all weeks in one blob or calls them noise: there are no isolated islands.
- **Gaussian mixture** improves its fit with every extra group (BIC never bottoms out), so it gives no natural
  count, and its groups are less clearly separated.
- **Hierarchical (Ward)** groups change a lot when part of the history is left out.
- **K-Means** gives the clearest separation of the multi-group options and the same groups on
  {chosen["stability"]:.0%}-similar subsamples, with regimes lasting {chosen["avg_regime_weeks"]:.0f} weeks on average.
  With 2 groups separation is slightly higher, but that only splits "long-heavy" from "not".

{_table(score_table)}

## Figures

{figures}

## Caveats

- The model is fitted on the full history, so it describes the past; it is not a forecast tested out-of-sample.
- The "Low participation" regime is mostly the 1988-2007 era, when speculators held a smaller share of the
  market; it partly reflects a different market structure rather than a state that recurs today.
- The test uses one week in every {config.FORWARD_HORIZON_WEEKS} so its windows don't overlap
  ({test["weeks_tested"]} weeks tested).
"""


def main(argv=None):
    args = parse_args(argv)
    configure_logging(config.REGIME_LOG_FILE)
    source = config.DATA_DIR / f"{config.REGIME_SYMBOL}.csv"
    try:
        raw = pd.read_csv(source)
        result = analyse(raw, rounds=args.rounds)
    except (FileNotFoundError, pd.errors.EmptyDataError) as error:
        logger.error("Could not read %s: %s", source, error)
        return 1
    except ValueError as error:
        logger.error("Regime analysis failed: %s", error)
        return 1
    config.REGIME_FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    figures = build_figures(result)
    for name, figure in figures:
        figure.savefig(config.REGIME_FIGURE_DIR / name, dpi=config.FIGURE_DPI, facecolor=config.PLOT_SURFACE)
        plt.close(figure)
        logger.info("Saved figure %s", config.REGIME_FIGURE_DIR / name)
    write_csv(result["labelled"], WEEKLY_CSV)
    write_text(render_report(result, [name for name, _ in figures]), config.REGIME_REPORT_FILE)
    logger.info("Wrote %s and %s", config.REGIME_REPORT_FILE, WEEKLY_CSV)
    return 0


if __name__ == "__main__":
    sys.exit(main())
