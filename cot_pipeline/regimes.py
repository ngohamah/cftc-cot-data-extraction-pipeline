"""Positioning regimes (unsupervised): group weeks by where large speculators stand in a market.

Pure functions: features -> model-selection scorecard -> K-Means regimes -> profiles and
"what happens next". Plots live in regime_plots.py; scripts/gold_regimes.py runs everything.

Contract counts grow with the market (gold open interest is many times its 1986 level), so every
feature is scale-free: a share of open interest, a 3-year percentile, or a % change.
"""

import logging

import numpy as np
import pandas as pd
from scipy.stats import kruskal
from sklearn.cluster import DBSCAN, AgglomerativeClustering, KMeans
from sklearn.metrics import adjusted_rand_score, davies_bouldin_score, silhouette_score
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler

import config

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = ["market", "date", "long", "short", "open_interest", "net_positions"]
FEATURE_COLUMNS = ["long_share", "short_share", "net_share", "cot_index", "net_flow_4w", "oi_growth_4w"]
FORWARD_COLUMN = "forward_net_flow"
FORWARD_RETURN_COLUMN = "forward_return"  # added by prices.add_price_features
SUBSAMPLE_FRACTION = 0.8


# --- data and features ---------------------------------------------------


def prepare_market_frame(dataframe, market=config.REGIME_MARKET):
    """One market's rows, oldest-first with parsed dates; accepts raw CSV or notebook (short) column names."""
    renamed = dataframe.rename(columns=config.ANALYSIS_COLUMN_NAMES)
    missing = [c for c in REQUIRED_COLUMNS if c not in renamed.columns]
    if missing:
        raise ValueError(f"Frame is missing columns needed for regimes: {missing}")
    selected = renamed[renamed["market"] == market]
    if selected.empty:
        raise ValueError(f"No rows for market {market!r}")
    dropped = renamed.loc[renamed["market"] != market, "market"].value_counts()
    for name, count in dropped.items():
        logger.info("Dropped %d rows of %s (only %s is analysed)", count, name, market)
    ordered = selected.assign(date=pd.to_datetime(selected["date"])).sort_values("date", kind="stable")
    deduplicated = ordered.drop_duplicates(subset="date", keep="last")
    if len(deduplicated) < len(ordered):
        logger.warning("Dropped %d duplicate weeks for %s", len(ordered) - len(deduplicated), market)
    return deduplicated.reset_index(drop=True)


def build_features(frame, settings=None):
    """Scale-free positioning features for each week, plus the net-position change that followed.

    long_share / short_share / net_share: speculator longs, shorts and net as a share of open interest
    cot_index: this week's net position within its range of the last 3 years (0 = lowest, 1 = highest)
    net_flow_4w / oi_growth_4w: 4-week change in net position (share of OI) and in open interest (%)
    forward_net_flow: change in net position over the next FORWARD_HORIZON_WEEKS (share of OI today)
    """
    s = {
        "window": config.COT_INDEX_WINDOW_WEEKS,
        "min_weeks": config.COT_INDEX_MIN_WEEKS,
        "flow": config.FLOW_WINDOW_WEEKS,
        "horizon": config.FORWARD_HORIZON_WEEKS,
        **(settings or {}),
    }
    oi = frame["open_interest"].astype(float)
    net = frame["net_positions"].astype(float)
    rolling = net.rolling(s["window"], min_periods=s["min_weeks"])
    low, high = rolling.min(), rolling.max()
    features = pd.DataFrame(
        {
            "date": frame["date"],
            "long_share": frame["long"] / oi,
            "short_share": frame["short"] / oi,
            "net_share": net / oi,
            "cot_index": (net - low) / (high - low),
            "net_flow_4w": net.diff(s["flow"]) / oi.shift(s["flow"]),
            "oi_growth_4w": oi / oi.shift(s["flow"]) - 1,
            FORWARD_COLUMN: (net.shift(-s["horizon"]) - net) / oi,
        }
    )
    return features.replace([np.inf, -np.inf], np.nan)


def complete_rows(features, columns):
    """Rows with every column present (drops the warm-up weeks of the rolling features)."""
    complete = features.dropna(subset=columns).reset_index(drop=True)
    if len(complete) < len(features):
        logger.info(
            "Dropped %d weeks without a full set of %s (rolling warm-up)", len(features) - len(complete), columns
        )
    return complete


def scale_features(features, columns, clip=config.CLIP_QUANTILES):
    """Clip each column to its quantile range (tames extreme weeks), then standardise to mean 0, sd 1."""
    values = features[columns]
    clipped = values.clip(values.quantile(clip[0]), values.quantile(clip[1]), axis=1)
    return StandardScaler().fit_transform(clipped)


# --- models ----------------------------------------------------------------


def kmeans_labels(matrix, k):
    """Hard clusters: each week goes to its nearest of k centres."""
    return KMeans(n_clusters=k, n_init=config.KMEANS_N_INIT, random_state=config.RANDOM_STATE).fit_predict(matrix)


def gmm_labels(matrix, k):
    """Most likely component of a k-component Gaussian mixture (full covariance)."""
    model = GaussianMixture(
        n_components=k, covariance_type="full", n_init=config.GMM_N_INIT, random_state=config.RANDOM_STATE
    )
    return model.fit(matrix).predict(matrix)


def hierarchical_labels(matrix, k):
    """Ward agglomerative clustering cut at k groups."""
    return AgglomerativeClustering(n_clusters=k).fit_predict(matrix)


CLUSTERERS = {"K-Means": kmeans_labels, "Gaussian mixture": gmm_labels, "Hierarchical (Ward)": hierarchical_labels}


def mean_run_length(labels):
    """Average number of consecutive weeks spent in the same cluster before switching."""
    labels = np.asarray(labels)
    if labels.size == 0:
        return 0.0
    switches = np.r_[True, labels[1:] != labels[:-1]].sum()
    return labels.size / switches


def subsample_stability(cluster_fn, matrix, k, rounds=config.BOOTSTRAP_ROUNDS, seed=config.RANDOM_STATE):
    """Mean agreement (adjusted Rand index, 1 = identical) between the full-data clusters and
    clusters refit on random 80% subsamples. Near 1: the grouping is real, not an accident of the sample."""
    rng = np.random.default_rng(seed)
    reference = cluster_fn(matrix, k)
    size = int(SUBSAMPLE_FRACTION * len(matrix))
    indexes = [np.sort(rng.choice(len(matrix), size, replace=False)) for _ in range(rounds)]
    return float(np.mean([adjusted_rand_score(reference[idx], cluster_fn(matrix[idx], k)) for idx in indexes]))


def score_clustering(cluster_fn, matrix, k, rounds=config.BOOTSTRAP_ROUNDS):
    """Quality numbers for one model at one k."""
    labels = cluster_fn(matrix, k)
    return {
        "k": k,
        "silhouette": silhouette_score(matrix, labels),
        "davies_bouldin": davies_bouldin_score(matrix, labels),
        "stability": subsample_stability(cluster_fn, matrix, k, rounds),
        "avg_regime_weeks": mean_run_length(labels),
    }


def model_scorecard(matrix, counts=config.CANDIDATE_CLUSTER_COUNTS, clusterers=None, rounds=config.BOOTSTRAP_ROUNDS):
    """Silhouette (higher = better separated), Davies-Bouldin (lower = better), stability and average
    regime length for every model and cluster count."""
    rows = [
        {"model": name, **score_clustering(fn, matrix, k, rounds)}
        for name, fn in (clusterers or CLUSTERERS).items()
        for k in counts
    ]
    return pd.DataFrame(rows)


def gmm_bic(matrix, counts=config.CANDIDATE_CLUSTER_COUNTS):
    """Bayesian information criterion of a Gaussian mixture per k (lower = better fit after a complexity penalty)."""
    fits = {
        k: GaussianMixture(k, covariance_type="full", n_init=config.GMM_N_INIT, random_state=config.RANDOM_STATE).fit(
            matrix
        )
        for k in counts
    }
    return pd.Series({k: model.bic(matrix) for k, model in fits.items()}, name="bic")


def dbscan_summary(matrix, eps_values=config.DBSCAN_EPS_VALUES, min_samples=config.DBSCAN_MIN_SAMPLES):
    """How density clustering splits the weeks: cluster count, share left as noise, share in the biggest cluster."""

    def summarise(eps):
        labels = DBSCAN(eps=eps, min_samples=min_samples).fit_predict(matrix)
        clustered = labels[labels >= 0]
        largest = np.bincount(clustered).max() / len(labels) if clustered.size else 0.0
        return {
            "eps": eps,
            "clusters": len(np.unique(clustered)),
            "noise_share": float(np.mean(labels < 0)),
            "largest_share": float(largest),
        }

    return pd.DataFrame([summarise(eps) for eps in eps_values])


# --- regimes ---------------------------------------------------------------


def order_labels(labels, values):
    """Renumber clusters 0..k-1 in ascending order of their mean value (makes cluster ids reproducible)."""
    means = pd.Series(np.asarray(values, dtype=float)).groupby(np.asarray(labels)).mean().sort_values()
    mapping = {old: new for new, old in enumerate(means.index)}
    return pd.Series(labels).map(mapping).to_numpy()


def assign_regimes(features, n_regimes=config.N_REGIMES, names=config.REGIME_NAMES, columns=None):
    """Weeks with full state features, labelled with a K-Means regime ordered by average net position."""
    if len(names) != n_regimes:
        raise ValueError(f"Need {n_regimes} regime names, got {len(names)}")
    columns = columns or config.STATE_FEATURES
    complete = complete_rows(features, columns)
    labels = order_labels(kmeans_labels(scale_features(complete, columns), n_regimes), complete["net_share"])
    labelled = complete.assign(regime=labels, regime_name=[names[i] for i in labels])
    logger.info(
        "Assigned %d weeks to %d regimes: %s",
        len(labelled),
        n_regimes,
        labelled["regime_name"].value_counts().to_dict(),
    )
    return labelled


def run_lengths(labels):
    """(label, consecutive weeks) for each uninterrupted stay in a regime."""
    series = pd.Series(np.asarray(labels))
    run_id = (series != series.shift()).cumsum()
    runs = series.groupby(run_id).agg(["first", "size"])
    return runs.rename(columns={"first": "regime", "size": "weeks"}).reset_index(drop=True)


def regime_profile(labelled, names=config.REGIME_NAMES):
    """One row per regime: how often, how long it lasts, what it looks like and what tends to follow
    (including gold's return afterwards when price data has been added)."""
    forward = labelled[FORWARD_COLUMN]
    has_price = FORWARD_RETURN_COLUMN in labelled.columns
    extra = {}
    if has_price:
        future_return = labelled[FORWARD_RETURN_COLUMN]
        labelled = labelled.assign(rose=(future_return > 0).where(future_return.notna()))
        extra = {
            "forward_return": (FORWARD_RETURN_COLUMN, "mean"),
            "share_price_rose": ("rose", "mean"),
            "weeks_with_price": (FORWARD_RETURN_COLUMN, "count"),
        }
    grouped = labelled.assign(added=(forward > 0).where(forward.notna())).groupby("regime")
    profile = grouped.agg(
        weeks=("date", "size"),
        first_seen=("date", "min"),
        last_seen=("date", "max"),
        long_share=("long_share", "mean"),
        short_share=("short_share", "mean"),
        net_share=("net_share", "mean"),
        cot_index=("cot_index", "mean"),
        net_flow_4w=("net_flow_4w", "mean"),
        oi_growth_4w=("oi_growth_4w", "mean"),
        forward_net_flow=(FORWARD_COLUMN, "mean"),
        share_added_next=("added", "mean"),
        **extra,
    )
    typical_stay = run_lengths(labelled["regime"]).groupby("regime")["weeks"].mean()
    return profile.assign(
        name=[names[i] for i in profile.index],
        share_of_history=profile["weeks"] / profile["weeks"].sum(),
        typical_stay_weeks=typical_stay,
    )


def transition_matrix(labels, n_regimes=config.N_REGIMES):
    """Probability of being in each regime next week given this week's regime (rows sum to 1)."""
    labels = np.asarray(labels)
    counts = pd.crosstab(labels[:-1], labels[1:]).reindex(
        index=range(n_regimes), columns=range(n_regimes), fill_value=0
    )
    return counts.div(counts.sum(axis=1).replace(0, np.nan), axis=0)


def forward_flow_test(labelled, horizon=config.FORWARD_HORIZON_WEEKS, column=FORWARD_COLUMN):
    """Kruskal-Wallis test of H0: what happens over the next `horizon` weeks (by default the change in net
    position; pass column=FORWARD_RETURN_COLUMN for gold's return) has the same distribution in every regime.
    Uses every horizon-th week so the forward windows don't overlap."""
    sample = labelled.dropna(subset=[column]).iloc[::horizon]
    groups = [g[column].to_numpy() for _, g in sample.groupby("regime") if len(g) > 1]
    if len(groups) < 2:
        raise ValueError("Need at least two regimes with forward data to test")
    statistic, p_value = kruskal(*groups)
    return {"statistic": float(statistic), "p_value": float(p_value), "weeks_tested": int(len(sample))}


def feature_set_comparison(features, feature_sets, counts=config.CANDIDATE_CLUSTER_COUNTS, rounds=5):
    """K-Means on each feature set, all on the same weeks (those with every feature), with
    separation, repeatability and whether the groups differ in what speculators and gold did next."""
    every_column = sorted({c for columns in feature_sets.values() for c in columns})
    common = complete_rows(features, every_column)

    def score(name, columns, k):
        matrix = scale_features(common, columns)
        labelled = common.assign(regime=kmeans_labels(matrix, k))
        return {
            "features": name,
            "k": k,
            "weeks": len(common),
            "first_week": common["date"].min(),
            "silhouette": silhouette_score(matrix, labelled["regime"]),
            "stability": subsample_stability(kmeans_labels, matrix, k, rounds),
            "p_positioning_next": forward_flow_test(labelled)["p_value"],
            "p_gold_next": forward_flow_test(labelled, column=FORWARD_RETURN_COLUMN)["p_value"],
        }

    return pd.DataFrame([score(name, columns, k) for name, columns in feature_sets.items() for k in counts])
