import importlib.util
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no windows during tests

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402
from helpers import GOLD  # noqa: E402

import config  # noqa: E402
from cot_pipeline import regimes  # noqa: E402

# (long share, short share) of open interest for four clearly different positioning states
STATES = [(0.10, 0.35), (0.20, 0.12), (0.45, 0.20), (0.55, 0.08)]


def load_script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "gold_regimes.py"
    spec = importlib.util.spec_from_file_location("gold_regimes", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def synthetic_gold(weeks=320, block=20, seed=0):
    """Weekly gold rows (short column names) cycling through STATES in blocks, with a little noise."""
    rng = np.random.default_rng(seed)
    state = [STATES[(i // block) % len(STATES)] for i in range(weeks)]
    open_interest = np.full(weeks, 100_000)
    long = np.array([s[0] for s in state]) * open_interest * (1 + rng.normal(0, 0.03, weeks))
    short = np.array([s[1] for s in state]) * open_interest * (1 + rng.normal(0, 0.03, weeks))
    return pd.DataFrame(
        {
            "market": GOLD,
            "date": pd.date_range("2000-01-04", periods=weeks, freq="7D").strftime("%Y-%m-%d"),
            "long": long.round(),
            "short": short.round(),
            "open_interest": open_interest,
            "net_positions": (long - short).round(),
        }
    )


@pytest.fixture(scope="module")
def features():
    return regimes.build_features(regimes.prepare_market_frame(synthetic_gold()))


def test_prepare_market_frame_filters_sorts_and_renames():
    """Raw CSV names are accepted, other contracts dropped, and weeks put oldest-first."""
    raw = synthetic_gold(weeks=5).iloc[::-1].rename(columns={v: k for k, v in config.ANALYSIS_COLUMN_NAMES.items()})
    other = raw.head(2).assign(**{config.MARKET_COL: "GOLD - INTERNATIONAL MONETARY MARKET"})
    result = regimes.prepare_market_frame(pd.concat([raw, other]))
    assert len(result) == 5
    assert result["date"].is_monotonic_increasing
    assert (result["market"] == GOLD).all()


def test_prepare_market_frame_drops_duplicate_weeks():
    frame = synthetic_gold(weeks=4)
    assert len(regimes.prepare_market_frame(pd.concat([frame, frame.tail(1)]))) == 4


@pytest.mark.parametrize(
    "frame, message",
    [(synthetic_gold(weeks=3).drop(columns="open_interest"), "missing"), (synthetic_gold(weeks=3), "No rows")],
)
def test_prepare_market_frame_errors(frame, message):
    market = GOLD if message == "missing" else "SILVER - COMMODITY EXCHANGE INC."
    with pytest.raises(ValueError, match=message):
        regimes.prepare_market_frame(frame, market=market)


def test_build_features_are_scale_free(features):
    """Shares match long/OI, the COT index stays in 0..1 and the forward flow looks ahead."""
    frame = regimes.prepare_market_frame(synthetic_gold())
    assert features["long_share"].iloc[0] == pytest.approx(frame["long"].iloc[0] / 100_000)
    assert features["cot_index"].dropna().between(0, 1).all()
    horizon = config.FORWARD_HORIZON_WEEKS
    expected = (frame["net_positions"].iloc[horizon] - frame["net_positions"].iloc[0]) / 100_000
    assert features["forward_net_flow"].iloc[0] == pytest.approx(expected)
    assert features["forward_net_flow"].tail(horizon).isna().all()


def test_build_features_handles_zero_open_interest():
    frame = regimes.prepare_market_frame(synthetic_gold(weeks=3).assign(open_interest=0))
    assert not np.isinf(regimes.build_features(frame)[regimes.FEATURE_COLUMNS].to_numpy(dtype=float)).any()


@pytest.mark.parametrize("labels, expected", [([0, 0, 1, 1, 1, 0], 2.0), ([3, 3, 3], 3.0), ([], 0.0)])
def test_mean_run_length(labels, expected):
    assert regimes.mean_run_length(labels) == expected


def test_order_labels_sorts_clusters_by_mean_value():
    assert list(regimes.order_labels([5, 5, 2, 9], [10, 12, -3, 4])) == [2, 2, 0, 1]


def test_assign_regimes_recovers_planted_states(features):
    """Four planted states come back as four regimes, numbered from most short to most long."""
    labelled = regimes.assign_regimes(features)
    means = labelled.groupby("regime")["net_share"].mean()
    assert means.is_monotonic_increasing
    week_number = (labelled["date"] - labelled["date"].min()).dt.days // 7 + (len(features) - len(labelled))
    planted_state = (week_number // 20) % len(STATES)
    assert (labelled.groupby(planted_state)["regime"].nunique() == 1).all()
    assert set(labelled["regime_name"]) == set(config.REGIME_NAMES)


def test_assign_regimes_needs_one_name_per_regime(features):
    with pytest.raises(ValueError, match="names"):
        regimes.assign_regimes(features, n_regimes=3)


def test_profile_and_transitions(features):
    labelled = regimes.assign_regimes(features)
    profile = regimes.regime_profile(labelled)
    assert profile["share_of_history"].sum() == pytest.approx(1)
    assert profile["typical_stay_weeks"].min() > 1
    transitions = regimes.transition_matrix(labelled["regime"])
    assert np.allclose(transitions.sum(axis=1), 1)


def test_forward_flow_test_detects_difference_and_needs_two_groups():
    rng = np.random.default_rng(1)
    labelled = pd.DataFrame(
        {"regime": np.repeat([0, 1], 200), "forward_net_flow": np.r_[rng.normal(-1, 0.2, 200), rng.normal(1, 0.2, 200)]}
    )
    assert regimes.forward_flow_test(labelled, horizon=2)["p_value"] < 0.001
    with pytest.raises(ValueError, match="two regimes"):
        regimes.forward_flow_test(labelled[labelled["regime"] == 0], horizon=2)


def test_scorecard_dbscan_and_bic_shapes(features):
    complete = regimes.complete_rows(features, config.STATE_FEATURES)
    matrix = regimes.scale_features(complete, config.STATE_FEATURES)
    scorecard = regimes.model_scorecard(matrix, counts=(2, 4), rounds=2)
    assert len(scorecard) == 2 * len(regimes.CLUSTERERS)
    kmeans_four = scorecard[(scorecard["model"] == "K-Means") & (scorecard["k"] == 4)].iloc[0]
    assert kmeans_four["stability"] > 0.9
    assert list(regimes.gmm_bic(matrix, counts=(2, 3)).index) == [2, 3]
    assert set(regimes.dbscan_summary(matrix, eps_values=(0.5,)).columns) == {
        "eps",
        "clusters",
        "noise_share",
        "largest_share",
    }


def test_script_builds_every_figure_and_report():
    """End to end on synthetic data: analysis, all figures and the markdown report (nothing written to disk)."""
    script = load_script()
    result = script.analyse(synthetic_gold(), rounds=2)
    figures = script.build_figures(result)
    assert len(figures) == 8
    report = script.render_report(result, [name for name, _ in figures])
    assert "## The regimes" in report and "figures/gold_regimes/2_model_selection.png" in report
    for _, figure in figures:
        plt.close(figure)


def test_script_adds_price_figures_and_section_when_prices_are_saved():
    from test_prices import daily_prices

    script = load_script()
    result = script.analyse(synthetic_gold(), prices=daily_prices(), rounds=2)
    figures = script.build_figures(result)
    assert len(figures) == 13
    report = script.render_report(result, [name for name, _ in figures])
    assert (
        "## Gold price" in report and "## Can we see a big price move coming?" in report and "## Words used" in report
    )
    for _, figure in figures:
        plt.close(figure)
