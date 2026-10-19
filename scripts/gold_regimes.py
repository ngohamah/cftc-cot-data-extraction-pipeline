"""Find positioning regimes in gold with unsupervised clustering, show why the chosen model fits best, and
check them against the gold price.

Reads data/GOLD.csv (COMEX contract only) and, if saved, the daily prices in data/prices/ (run
scripts/fetch_prices.py first). Compares K-Means, Gaussian mixture, hierarchical and DBSCAN clustering, labels
every week with a K-Means regime and writes:
  reports/gold_regimes.md                 plain-language summary with the figures
  reports/gold_regimes_weekly.csv         every week's features, price and regime
  reports/figures/gold_regimes/*.png      the figures
Progress and dropped rows are logged to logs/regimes.log.

Usage: python scripts/gold_regimes.py [--rounds 20]
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # allow running from any folder

import matplotlib  # noqa: E402

matplotlib.use("Agg")  # figures go to files only (no windows, works on servers)

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

import config  # noqa: E402
from cot_pipeline import prices as price_data  # noqa: E402
from cot_pipeline import regime_plots as plots  # noqa: E402
from cot_pipeline import regimes  # noqa: E402
from cot_pipeline.logging_setup import LOGGER_NAME, configure_logging  # noqa: E402
from cot_pipeline.storage import write_csv, write_text  # noqa: E402

logger = logging.getLogger(f"{LOGGER_NAME}.regimes_script")

WEEKLY_CSV = config.REPORT_DIR / "gold_regimes_weekly.csv"
FEATURE_SETS = {
    "Positioning only (kept)": config.STATE_FEATURES,
    "Positioning + gold price": config.STATE_FEATURES + config.PRICE_FEATURES,
    "Gold price only": config.PRICE_FEATURES,
}

GLOSSARY = """## Words used in this report

**The data**
- **COT report**: a weekly report from the US regulator (CFTC) showing how many gold futures contracts
  different groups of traders hold. Here we follow the **large speculators** (funds and big traders betting on
  the price, called "non-commercials" in the report).
- **Long / short**: a long position profits if gold rises, a short position profits if it falls.
  **Net position** = longs minus shorts.
- **Open interest**: the total number of open contracts, a measure of how big the market is.
- **3-year percentile**: where this week's net position sits compared with the last 3 years (0% = the most
  short it has been, 100% = the most long).

**The method**
- **Unsupervised learning**: the computer is given the data but *no right answers*, and is asked to find
  structure by itself, here groups of weeks that look alike. (Supervised learning would instead be told what to
  predict, such as tomorrow's price.)
- **Clustering**: sorting things into groups so that members of a group are similar and different groups are
  not, like sorting a pile of photos into piles without being told what the piles should be.
- **Regime**: our name for one of these groups of weeks; a recurring "state" the market is in.
- **K-Means**: picks *k* centre points and puts every week with its nearest centre, then moves each centre to
  the middle of its group, and repeats until nothing changes. Simple, fast, and every group has a clear
  "average week".
- **Gaussian mixture**: like K-Means, but each group is a soft oval cloud and every week gets a probability of
  belonging to each group. More flexible, but needs more data and can over-split.
- **Hierarchical clustering (Ward)**: starts with every week on its own and keeps merging the two most similar
  groups, building a family tree; we cut the tree at *k* groups.
- **DBSCAN**: looks for crowded areas separated by empty space (like spotting towns on a map at night).
  Good when groups are islands; if the data is one continuous cloud it finds a single blob.
- **PCA (principal component analysis)**: not a clustering method. It squeezes many columns into a few that
  keep most of the variation, mainly to draw the data in 2-D. We plot real columns (long share vs short share)
  instead, because they are easier to read.

**How we judge the groups**
- **Silhouette score** (from -1 to 1): for each week, is it much closer to its own group than to the next
  group? Near 1 = clearly in its group, 0 = on the border, below 0 = probably in the wrong group.
- **Davies-Bouldin score**: how much the groups overlap. Lower is better.
- **Stability (adjusted Rand index)**: we refit the model on random 80% slices of history and check whether
  the same weeks end up together. 1 = identical groups every time, 0 = no better than chance.
- **BIC**: a score for the Gaussian mixture that rewards fitting the data but penalises extra groups. Lower is
  better; if it keeps falling as groups are added, the method never settles on a natural number.

**How we judge the results**
- **Kruskal-Wallis test**: checks whether several groups really differ (for example in what gold did next) or
  whether the differences could easily be luck. It compares rankings, so a few extreme weeks can't dominate.
- **p-value**: roughly, how likely differences this big would be if there were really no difference.
  Small (below 0.05, i.e. 5%) = probably a real difference; large = could easily be luck.
- **Correlation**: how closely two things move together, from -1 (always opposite) through 0 (unrelated) to 1
  (always together).
"""

REFERENCES = """## Further reading

Beginner-friendly first.

1. StatQuest with Josh Starmer (YouTube, short visual explainers). Search for "StatQuest K-means",
   "StatQuest PCA", "StatQuest DBSCAN" and "StatQuest p-values": https://www.youtube.com/@statquest
2. James, Witten, Hastie & Tibshirani, *An Introduction to Statistical Learning* (2nd ed., free PDF),
   chapter 12 "Unsupervised Learning": https://www.statlearning.com
3. scikit-learn user guide, "Clustering" (pictures of every method on example data):
   https://scikit-learn.org/stable/modules/clustering.html
4. scikit-learn example, "Selecting the number of clusters with silhouette analysis":
   https://scikit-learn.org/stable/auto_examples/cluster/plot_kmeans_silhouette_analysis.html
5. CFTC, "Commitments of Traders: explanatory notes":
   https://www.cftc.gov/MarketReports/CommitmentsofTraders/ExplanatoryNotes/index.htm
6. Briese, S. (2008). *The Commitments of Traders Bible*. Wiley. (How traders use COT data, including the
   3-year "COT index".)
7. Wang, C. (2003). The behavior and performance of major types of futures traders. *Journal of Futures
   Markets*, 23(1), 1-31.

Original papers behind the methods:

8. Lloyd, S. (1982). Least squares quantization in PCM. *IEEE Transactions on Information Theory*, 28(2),
   129-137. (K-Means)
9. Ester, M., Kriegel, H.-P., Sander, J. & Xu, X. (1996). A density-based algorithm for discovering clusters in
   large spatial databases with noise. *Proceedings of KDD-96*, 226-231. (DBSCAN)
10. Rousseeuw, P. J. (1987). Silhouettes: a graphical aid to the interpretation and validation of cluster
    analysis. *Journal of Computational and Applied Mathematics*, 20, 53-65.
11. Hubert, L. & Arabie, P. (1985). Comparing partitions. *Journal of Classification*, 2, 193-218.
    (Adjusted Rand index)
12. Schwarz, G. (1978). Estimating the dimension of a model. *Annals of Statistics*, 6(2), 461-464. (BIC)
13. Kruskal, W. H. & Wallis, W. A. (1952). Use of ranks in one-criterion variance analysis. *Journal of the
    American Statistical Association*, 47(260), 583-621.
"""


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rounds", type=int, default=config.BOOTSTRAP_ROUNDS, help="subsample rounds for stability")
    return parser.parse_args(argv)


def analyse(raw, prices=None, rounds=config.BOOTSTRAP_ROUNDS):
    """Everything the figures and report need (no file output). prices: saved daily prices, or None to skip
    the price checks."""
    frame = regimes.prepare_market_frame(raw)
    features = regimes.build_features(frame)
    if prices is not None:
        features = price_data.add_price_features(features, prices)
    state = regimes.complete_rows(features, config.STATE_FEATURES)
    state_matrix = regimes.scale_features(state, config.STATE_FEATURES)
    flow_columns = config.STATE_FEATURES + config.FLOW_FEATURES
    flow_matrix = regimes.scale_features(regimes.complete_rows(features, flow_columns), flow_columns)
    logger.info("Scoring models on %d weeks (%d subsample rounds each)", len(state_matrix), rounds)
    labelled = regimes.assign_regimes(features)
    result = {
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
        "profile": regimes.regime_profile(labelled),
        "transitions": regimes.transition_matrix(labelled["regime"]),
        "test": regimes.forward_flow_test(labelled),
    }
    if prices is None:
        return result
    logger.info("Comparing feature sets with and without gold price features")
    return {
        **result,
        "price_test": regimes.forward_flow_test(labelled, column=regimes.FORWARD_RETURN_COLUMN),
        "lead_lag": price_data.lead_lag_correlations(features),
        "feature_sets": regimes.feature_set_comparison(features, FEATURE_SETS, rounds=max(2, rounds // 4)),
    }


def build_figures(result):
    """(file name, figure) pairs in the order the report shows them."""
    labelled, profile = result["labelled"], result["profile"]
    figures = [
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
    if "price_test" not in result:
        return figures
    return figures + [
        ("9_price_timeline.png", plots.price_timeline_figure(labelled)),
        ("10_speculators_follow_price.png", plots.lead_lag_figure(result["lead_lag"])),
        ("11_gold_after_regime.png", plots.gold_after_regime_figure(labelled, profile, result["price_test"])),
        ("12_with_and_without_price.png", plots.feature_set_figure(result["feature_sets"])),
    ]


FIGURE_CAPTIONS = {
    "1_scale_free_features.png": "Why we use shares of the market instead of raw contract counts.",
    "2_model_selection.png": "The evidence for K-Means with 4 regimes (each panel answers one question).",
    "3_regime_map.png": "Every week placed by speculators' longs and shorts, coloured by regime.",
    "4_regime_fingerprint.png": "The average week in each regime.",
    "5_regime_timeline.png": "Which regime each week was in, over 38 years.",
    "6_what_happens_next.png": "What speculators did over the 8 weeks after each regime.",
    "7_regime_transitions.png": "How likely each regime is to switch to another the following week.",
    "8_silhouette_by_week.png": "How clearly each week belongs to its regime.",
    "9_price_timeline.png": "The regimes drawn on the gold price chart.",
    "10_speculators_follow_price.png": "Do speculators move before, with or after the price?",
    "11_gold_after_regime.png": "What gold did over the 8 weeks after each regime was published.",
    "12_with_and_without_price.png": "Re-running the clustering with gold price features added.",
}


def _table(frame):
    header = "| " + " | ".join(frame.columns) + " |"
    divider = "|" + "---|" * len(frame.columns)
    rows = ["| " + " | ".join(str(v) for v in row) + " |" for row in frame.itertuples(index=False)]
    return "\n".join([header, divider, *rows])


def _p_text(test):
    return "less than 0.001" if test["p_value"] < 0.001 else f"{test['p_value']:.2f}"


def _price_section(result):
    """The gold price findings, in plain language (empty if prices weren't available)."""
    if "price_test" not in result:
        return "## Gold price\n\nNo saved prices were found; run `python scripts/fetch_prices.py` and re-run.\n"
    profile, labelled, lead_lag = result["profile"], result["labelled"], result["lead_lag"]
    horizon = config.FORWARD_HORIZON_WEEKS
    priced = labelled.dropna(subset=[regimes.FORWARD_RETURN_COLUMN])
    past = lead_lag.loc[lead_lag["lag_weeks"] == 0, "correlation"].iloc[0]
    after = lead_lag.loc[lead_lag["lag_weeks"] == 1, "correlation"].iloc[0]
    largest_after = lead_lag.loc[lead_lag["lag_weeks"] > 0, "correlation"].abs().max()
    comparison = result["feature_sets"]
    at_k = comparison[comparison["k"] == config.N_REGIMES].set_index("features")
    table = pd.DataFrame(
        {
            "Regime": profile["name"],
            f"Gold's avg. return next {horizon} wks": profile["forward_return"].map("{:+.1%}".format),
            "Gold rose afterwards": profile["share_price_rose"].map("{:.0%}".format),
            "Weeks with a price": profile["weeks_with_price"].astype(int),
        }
    )
    compare_table = pd.DataFrame(
        {
            "Inputs": at_k.index,
            "Separation (silhouette)": at_k["silhouette"].round(2).to_numpy(),
            "Stability": at_k["stability"].round(2).to_numpy(),
            "p-value: speculators next": at_k["p_positioning_next"].map("{:.3f}".format).to_numpy(),
            "p-value: gold next": at_k["p_gold_next"].map("{:.2f}".format).to_numpy(),
        }
    )
    return f"""## Gold price: do the regimes tell us where gold goes next?

Daily COMEX gold futures prices (`{config.PRICE_TICKER}` from Yahoo Finance, {priced["date"].min():%Y} onwards)
were matched to each report. Gold's "next {horizon} weeks" are measured from the first close **after the
report is published** (Friday afternoon), so nothing is used before it was public.

**Short answer: no.** Gold's average return over the next {horizon} weeks was
{priced[regimes.FORWARD_RETURN_COLUMN].mean():+.1%} overall and was positive after every regime; the differences
between regimes are small and could easily be luck (Kruskal-Wallis p-value {_p_text(result["price_test"])}).

{_table(table)}

**Why: speculators move with the price, not ahead of it.** In weeks when gold rises, speculators buy, and in
weeks when it falls they sell (correlation {past:.2f} in the same week). But their buying or selling says
almost nothing about gold's *next* week ({after:+.2f}) or any of the following {config.LEAD_LAG_WEEKS} weeks (all
within ±{largest_after:.2f}). Positioning mirrors the trend that has already happened; it is not a forecast.

**Re-running the clustering with price data.** We added gold's 3-year price percentile and its last-13-week
return to the inputs and re-ran K-Means on the same weeks. The groups became *less* clearly separated, and
still did not forecast gold. Price and positioning largely carry the same information (they move together), so
we keep the positioning-only regimes and use the price as the yardstick instead.

{_table(compare_table)}
"""


def render_report(result, figure_names):
    """Plain-language markdown summary for readers without a statistics background."""
    profile, scorecard, test = result["profile"], result["scorecard"], result["test"]
    labelled = result["labelled"]
    chosen = scorecard[(scorecard["model"] == "K-Means") & (scorecard["k"] == config.N_REGIMES)].iloc[0]
    latest = labelled.iloc[-1]
    open_interest = result["frame"]["open_interest"]
    growth, peak = open_interest.iloc[-1] / open_interest.iloc[0], open_interest.max() / open_interest.iloc[0]
    has_price = "price_test" in result
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
    figures = "\n\n".join(
        f"**{FIGURE_CAPTIONS.get(name, name)}**\n\n![{name}](figures/gold_regimes/{name})" for name in figure_names
    )
    price_bullet = (
        f"- **They do not forecast gold's price.** Gold rose about as often after every regime (p-value "
        f"{_p_text(result['price_test'])}): speculators *follow* the price rather than lead it. Adding price "
        "data to the clustering made the groups blurrier, so the positioning-only regimes are kept.\n"
        if has_price
        else ""
    )
    return f"""# Gold positioning regimes

_Generated by `scripts/gold_regimes.py` from {len(labelled)} weekly COT reports
({labelled["date"].min():%Y-%m-%d} to {labelled["date"].max():%Y-%m-%d}), COMEX gold only._

## In short

- Large speculators in gold move between **{config.N_REGIMES} positioning regimes**, found by K-Means clustering
  without being told what to look for.
- The regime **tells you what speculators tend to do next**: crowded longs tend to be trimmed and net-short
  positions tend to be bought back (p-value {_p_text(test)}).
{price_bullet}- Latest report ({latest["date"]:%Y-%m-%d}): **{latest["regime_name"]}**.

These are descriptions of past positioning, not trading recommendations.

{GLOSSARY}
## The regimes

{_table(regime_table)}

{_price_section(result)}
## Why K-Means with {config.N_REGIMES} regimes

Positions are measured as a share of open interest because the market is about {growth:.0f}x its 1986 size
(peaking at {peak:.0f}x), so raw contract counts mostly measure market size.
Only the slow-moving "where speculators stand" features are used (long share, short share and the 3-year
percentile of the net position). Adding the noisy 4-week flows made every model's groups blurrier.

- **DBSCAN** puts nearly all weeks in one blob: positioning is one continuous cloud, not separate islands.
- **Gaussian mixture** improves its fit with every extra group (BIC never bottoms out), so it gives no natural
  count, and its groups are less clearly separated.
- **Hierarchical (Ward)** groups change a lot when part of the history is left out.
- **K-Means** separates the groups most clearly at every group count, and refitting it on random 80% slices
  of history gives almost the same groups (agreement {chosen["stability"]:.2f} out of 1, level with the
  Gaussian mixture), with regimes lasting {chosen["avg_regime_weeks"]:.0f} weeks on average.
  With 2 groups separation is slightly higher, but that only splits "long-heavy" from "not".

{_table(score_table)}

## Figures

{figures}

## Caveats

- The model is fitted on the full history, so it describes the past; it is not a forecast tested out-of-sample.
- The "Low participation" regime is mostly the 1988-2007 era, when speculators held a smaller share of the
  market; it partly reflects a different market structure rather than a state that recurs today.
- Tests use one week in every {config.FORWARD_HORIZON_WEEKS} so their windows don't overlap
  ({test["weeks_tested"]} weeks tested for positioning).
- Gold prices are the continuous front-month futures contract, which switches to the next contract each
  delivery month; for gold these switches are small.

{REFERENCES}"""


def load_prices():
    """Saved daily prices, or None (with a warning) if they haven't been downloaded."""
    try:
        return price_data.read_saved_prices()
    except FileNotFoundError:
        logger.warning("No saved prices at %s; run scripts/fetch_prices.py. Skipping price checks.", config.PRICE_FILE)
        return None


def main(argv=None):
    args = parse_args(argv)
    configure_logging(config.REGIME_LOG_FILE)
    source = config.DATA_DIR / f"{config.REGIME_SYMBOL}.csv"
    try:
        raw = pd.read_csv(source)
        result = analyse(raw, prices=load_prices(), rounds=args.rounds)
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
