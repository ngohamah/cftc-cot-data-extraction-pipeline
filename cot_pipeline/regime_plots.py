"""Figures for the positioning-regime analysis, written for a non-technical reader.

Every function takes ready-made data and returns a matplotlib Figure (nothing is saved or shown here).
"""

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.ticker import NullFormatter, PercentFormatter, StrMethodFormatter
from sklearn.metrics import silhouette_samples

import config

STYLE = {
    "figure.facecolor": config.PLOT_SURFACE,
    "axes.facecolor": config.PLOT_SURFACE,
    "axes.edgecolor": config.PLOT_AXIS,
    "axes.labelcolor": config.PLOT_INK_SECONDARY,
    "axes.titlecolor": config.PLOT_INK,
    "axes.titlesize": 11,
    "axes.titleweight": "bold",
    "axes.titlelocation": "left",
    "axes.labelsize": 9.5,
    "axes.grid": True,
    "axes.axisbelow": True,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "grid.color": config.PLOT_GRID,
    "grid.linewidth": 0.6,
    "xtick.color": config.PLOT_INK_MUTED,
    "ytick.color": config.PLOT_INK_MUTED,
    "xtick.labelsize": 8.5,
    "ytick.labelsize": 8.5,
    "legend.frameon": False,
    "legend.fontsize": 8.5,
    "font.family": ["Arial", "Helvetica Neue", "DejaVu Sans"],
    "lines.linewidth": 2,
}
PERCENT = PercentFormatter(1.0, decimals=0)


def _figure(*args, **kwargs):
    with plt.rc_context(STYLE):
        return plt.subplots(*args, **kwargs)


def _finish(fig, title, subtitle):
    """Headline (the takeaway) plus a one-line plain-language explanation, spaced in inches so they never
    overlap whatever the figure height, then lay out the panels below them."""
    height = fig.get_figheight()
    fig.text(
        0.01, 1 - 0.3 / height, title, ha="left", va="baseline", fontsize=14, fontweight="bold", color=config.PLOT_INK
    )
    fig.text(0.01, 1 - 0.58 / height, subtitle, ha="left", va="baseline", fontsize=10, color=config.PLOT_INK_SECONDARY)
    fig.tight_layout(rect=(0, 0, 1, 1 - 0.8 / height))


def _regime_style(regime):
    return {"color": config.REGIME_COLORS[regime], "marker": config.REGIME_MARKERS[regime]}


def scale_free_figure(frame, features):
    """Why the model uses shares of open interest rather than raw contract counts."""
    with plt.rc_context(STYLE):
        fig, (top, bottom) = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
        growth = frame["open_interest"].iloc[-1] / frame["open_interest"].iloc[0]
        peak = frame["open_interest"].max() / frame["open_interest"].iloc[0]
        top.plot(frame["date"], frame["open_interest"] / 1000, color=config.SERIES_COLORS[0], linewidth=1.5)
        top.set_title("Total open contracts (open interest)")
        top.set_ylabel("Thousand contracts")
        bottom.plot(features["date"], features["net_share"], color=config.SERIES_COLORS[0], linewidth=1.2)
        bottom.axhline(0, color=config.PLOT_AXIS, linewidth=1)
        bottom.set_title("Speculators' net position as a share of open interest")
        bottom.set_ylabel("Net long (+) / net short (-)")
        bottom.set_xlabel("Report date")
        bottom.yaxis.set_major_formatter(PERCENT)
        _finish(
            fig,
            f"The gold futures market is about {growth:.0f}x its 1986 size (and peaked at {peak:.0f}x)",
            "Raw contract counts mostly measure market size, so the model compares positions as a share of the "
            "market instead.",
        )
    return fig


def _mark_choice(ax, x, y):
    ax.scatter([x], [y], s=180, facecolors="none", edgecolors=config.PLOT_INK, linewidths=1.5, zorder=5)
    ax.annotate("chosen", (x, y), xytext=(8, 8), textcoords="offset points", fontsize=8.5, color=config.PLOT_INK)


def _model_lines(ax, scorecard, metric, chosen_k):
    for color, (name, rows) in zip(config.SERIES_COLORS, scorecard.groupby("model", sort=False), strict=False):
        ax.plot(rows["k"], rows[metric], color=color, marker="o", markersize=5, label=name)
    chosen = scorecard[(scorecard["model"] == "K-Means") & (scorecard["k"] == chosen_k)]
    _mark_choice(ax, chosen_k, chosen[metric].iloc[0])
    ax.set_xlabel("Number of groups (k)")


def model_selection_figure(scorecard, flow_scorecard, bic, dbscan, chosen_k=config.N_REGIMES):
    """Six panels comparing models, cluster counts and feature sets - the case for the chosen model."""
    with plt.rc_context(STYLE):
        fig, axes = plt.subplots(2, 3, figsize=(15, 9))
        (sil, stab, length), (feat, bic_ax, dens) = axes

        _model_lines(sil, scorecard, "silhouette", chosen_k)
        sil.set_title("1. How clearly separated are the groups?")
        sil.set_ylabel("Silhouette score (higher = clearer)")
        sil.legend(loc="upper right")

        _model_lines(stab, scorecard, "stability", chosen_k)
        stab.set_title("2. Do the same groups come back on new samples?")
        stab.set_ylabel("Agreement with 80% subsamples (1 = identical)")
        stab.set_ylim(0, 1.05)

        _model_lines(length, scorecard, "avg_regime_weeks", chosen_k)
        length.set_title("3. How long does a regime typically last?")
        length.set_ylabel("Average weeks before switching")

        kmeans = scorecard[scorecard["model"] == "K-Means"]
        flow_kmeans = flow_scorecard[flow_scorecard["model"] == "K-Means"]
        feat.plot(
            kmeans["k"],
            kmeans["silhouette"],
            color=config.SERIES_COLORS[0],
            marker="o",
            markersize=5,
            label="Positioning only (long, short, 3-yr percentile)",
        )
        feat.plot(
            flow_kmeans["k"],
            flow_kmeans["silhouette"],
            color=config.SERIES_COLORS[1],
            marker="o",
            markersize=5,
            label="+ recent 4-week flows",
        )
        _mark_choice(feat, chosen_k, kmeans.loc[kmeans["k"] == chosen_k, "silhouette"].iloc[0])
        feat.set_title("4. Adding noisy weekly flows blurs the groups")
        feat.set_xlabel("Number of groups (k)")
        feat.set_ylabel("K-Means silhouette score")
        feat.legend(loc="upper right")

        bic_ax.plot(bic.index, bic.values / 1000, color=config.SERIES_COLORS[1], marker="o", markersize=5)
        bic_ax.set_title("5. Gaussian mixture never settles on a k")
        bic_ax.set_xlabel("Number of groups (k)")
        bic_ax.set_ylabel("BIC, thousands (lower = better)")

        dens.plot(
            dbscan["eps"],
            dbscan["largest_share"],
            color=config.SERIES_COLORS[0],
            marker="o",
            markersize=5,
            label="Weeks in the single biggest group",
        )
        dens.plot(
            dbscan["eps"],
            dbscan["noise_share"],
            color=config.SERIES_COLORS[1],
            marker="o",
            markersize=5,
            label="Weeks left unassigned (noise)",
        )
        dens.set_title("6. Density clustering (DBSCAN): one blob or noise")
        dens.set_xlabel("Neighbourhood radius (eps, standardised units)")
        dens.set_ylabel("Share of weeks")
        dens.yaxis.set_major_formatter(PERCENT)
        dens.legend(loc="center right")

        _finish(
            fig,
            f"Why K-Means with {chosen_k} regimes on positioning features",
            "K-Means separates the groups most clearly at every k and is as repeatable as a Gaussian mixture at k=4; "
            "density clustering finds no natural islands, and the mixture keeps asking for more groups.",
        )
    return fig


def silhouette_figure(matrix, labels, names=config.REGIME_NAMES):
    """How well each week fits its own regime versus the nearest other regime."""
    values = silhouette_samples(matrix, labels)
    with plt.rc_context(STYLE):
        fig, ax = plt.subplots(figsize=(11, 6.5))
        bottom = 0
        for regime, name in enumerate(names):
            regime_values = np.sort(values[labels == regime])
            top = bottom + len(regime_values)
            ax.fill_betweenx(np.arange(bottom, top), 0, regime_values, color=config.REGIME_COLORS[regime], linewidth=0)
            ax.text(0.98, (bottom + top) / 2, name, ha="right", va="center", fontsize=9, color=config.PLOT_INK)
            bottom = top + 25
        ax.axvline(values.mean(), color=config.PLOT_INK, linewidth=1)
        ax.annotate(
            f"average {values.mean():.2f}",
            (values.mean(), bottom),
            xytext=(4, -12),
            textcoords="offset points",
            fontsize=8.5,
            color=config.PLOT_INK,
        )
        ax.axvline(0, color=config.PLOT_AXIS, linewidth=1)
        ax.set_yticks([])
        ax.grid(axis="y", visible=False)
        ax.set_xlabel("Silhouette per week (1 = sits squarely in its regime, below 0 = closer to another regime)")
        _finish(
            fig,
            "Most weeks sit clearly inside their regime",
            "Each sliver is one week; long bars to the right mean a confident assignment.",
        )
        ax.set_xlim(min(-0.1, values.min() - 0.05), 1)
    return fig


def regime_map_figure(labelled, profile):
    """Every week placed by speculator longs vs shorts (share of open interest), coloured by regime."""
    with plt.rc_context(STYLE):
        fig, ax = plt.subplots(figsize=(11, 7.5))
        for regime, rows in labelled.groupby("regime"):
            ax.scatter(
                rows["long_share"],
                rows["short_share"],
                s=16,
                alpha=0.45,
                linewidths=0,
                label=profile.loc[regime, "name"],
                **_regime_style(regime),
            )
        for regime, row in profile.iterrows():
            ax.scatter(
                row["long_share"],
                row["short_share"],
                s=140,
                edgecolors=config.PLOT_SURFACE,
                linewidths=2,
                zorder=5,
                **_regime_style(regime),
            )
            ax.annotate(
                row["name"],
                (row["long_share"], row["short_share"]),
                xytext=(10, 6),
                textcoords="offset points",
                fontsize=10,
                fontweight="bold",
                color=config.PLOT_INK,
            )
        limit = max(labelled["long_share"].max(), labelled["short_share"].max()) * 1.02
        ax.plot([0, limit], [0, limit], color=config.PLOT_INK_MUTED, linewidth=1)
        ax.annotate(
            "longs = shorts (net zero)",
            (limit * 0.55, limit * 0.55),
            rotation=0,
            xytext=(6, -14),
            textcoords="offset points",
            fontsize=8.5,
            color=config.PLOT_INK_MUTED,
        )
        ax.set_xlim(0, limit)
        ax.set_ylim(0, labelled["short_share"].max() * 1.05)
        ax.xaxis.set_major_formatter(PERCENT)
        ax.yaxis.set_major_formatter(PERCENT)
        ax.set_xlabel("Speculator long contracts, share of open interest")
        ax.set_ylabel("Speculator short contracts, share of open interest")
        ax.legend(title="Regime (large marker = average week)", loc="upper right", markerscale=1.6)
        _finish(
            fig,
            "Four distinct positioning regimes in gold",
            "Each dot is one weekly report; regimes were found by K-Means without being told what to look for.",
        )
    return fig


def regime_timeline_figure(labelled, names=config.REGIME_NAMES):
    """Net positioning through time with the regime of every week."""
    with plt.rc_context(STYLE):
        fig, (top, strip) = plt.subplots(2, 1, figsize=(13, 7.5), sharex=True, gridspec_kw={"height_ratios": [4, 1.3]})
        top.plot(labelled["date"], labelled["net_share"], color=config.PLOT_AXIS, linewidth=0.8, zorder=1)
        for regime, rows in labelled.groupby("regime"):
            top.scatter(
                rows["date"],
                rows["net_share"],
                s=10,
                linewidths=0,
                label=names[regime],
                zorder=2,
                **_regime_style(regime),
            )
            strip.scatter(
                rows["date"],
                np.full(len(rows), regime),
                marker="|",
                s=120,
                linewidths=1.2,
                color=config.REGIME_COLORS[regime],
            )
        top.axhline(0, color=config.PLOT_INK_MUTED, linewidth=1)
        top.yaxis.set_major_formatter(PERCENT)
        top.set_ylabel("Net position, share of open interest")
        top.set_title("Speculators' net position, coloured by regime")
        top.legend(loc="upper left", ncols=4, markerscale=2)
        strip.set_yticks(range(len(names)), names)
        strip.set_ylim(-0.7, len(names) - 0.3)
        strip.grid(axis="y", visible=False)
        strip.set_title("Regime each week")
        strip.set_xlabel("Report date")
        _finish(
            fig,
            "Regimes last for weeks to months, and the mix has shifted over time",
            "Net-short spells fill the 1990s and early 2000s; since then the same regime marks 3-year lows "
            "(2013-2019) even while still slightly net long. Crowded longs dominate since the mid-2000s.",
        )
    return fig


FINGERPRINT_COLUMNS = {
    "long_share": ("Longs, share of OI", "{:.0%}"),
    "short_share": ("Shorts, share of OI", "{:.0%}"),
    "net_share": ("Net, share of OI", "{:+.0%}"),
    "cot_index": ("3-yr percentile of net", "{:.0%}"),
    "net_flow_4w": ("Net change, last 4 wks", "{:+.1%}"),
    "oi_growth_4w": ("Open interest change, last 4 wks", "{:+.1%}"),
}


def fingerprint_figure(labelled, profile):
    """Average of each feature per regime, shaded by how unusual it is versus all weeks."""
    columns = list(FINGERPRINT_COLUMNS)
    means = profile[columns]
    z_scores = (means - labelled[columns].mean()) / labelled[columns].std()
    cmap = LinearSegmentedColormap.from_list("diverging", config.DIVERGING_COLORS)
    with plt.rc_context(STYLE):
        fig, ax = plt.subplots(figsize=(12, 4.8))
        image = ax.imshow(z_scores.to_numpy(), cmap=cmap, vmin=-1.5, vmax=1.5, aspect="auto")
        for (row, col), value in np.ndenumerate(means.to_numpy()):
            ax.text(
                col,
                row,
                FINGERPRINT_COLUMNS[columns[col]][1].format(value),
                ha="center",
                va="center",
                fontsize=10,
                color=config.PLOT_INK,
            )
        ax.set_xticks(range(len(columns)), [FINGERPRINT_COLUMNS[c][0] for c in columns], rotation=15, ha="right")
        ax.set_yticks(range(len(profile)), profile["name"])
        ax.grid(visible=False)
        ax.tick_params(colors=config.PLOT_INK_SECONDARY, length=0)
        colorbar = fig.colorbar(image, ax=ax, shrink=0.85)
        colorbar.set_label("Below typical  <->  above typical (std. devs)", color=config.PLOT_INK_SECONDARY)
        colorbar.outline.set_visible(False)
        _finish(
            fig,
            "What each regime looks like",
            "Numbers are regime averages; colour shows how far each sits from a typical week.",
        )
    return fig


def _p_text(test):
    return "p < 0.001" if test["p_value"] < 0.001 else f"p = {test['p_value']:.2f}"


def _outcome_figure(labelled, profile, column, share_column, text):
    """Box plot of what followed each regime (left) and how often it was positive (right)."""
    names = profile["name"].tolist()
    data = [labelled.loc[labelled["regime"] == r, column].dropna().to_numpy() for r in profile.index]
    with plt.rc_context(STYLE):
        fig, (box, bars) = plt.subplots(1, 2, figsize=(14, 6), gridspec_kw={"width_ratios": [1.6, 1]}, sharey=True)
        parts = box.boxplot(
            data,
            vert=False,
            widths=0.55,
            showfliers=False,
            patch_artist=True,
            medianprops={"color": config.PLOT_INK, "linewidth": 1.5},
            whiskerprops={"color": config.PLOT_INK_MUTED},
            capprops={"color": config.PLOT_INK_MUTED},
        )
        for regime, patch in enumerate(parts["boxes"]):
            patch.set(facecolor=config.REGIME_COLORS[regime], alpha=0.55, edgecolor=config.REGIME_COLORS[regime])
        box.axvline(0, color=config.PLOT_INK_MUTED, linewidth=1)
        box.set_yticks(range(1, len(names) + 1), names)
        box.xaxis.set_major_formatter(PERCENT)
        box.set_xlabel(text["box_xlabel"])
        box.set_title("Spread of what followed (box = middle half of weeks)")
        for label, offset, align in ((text["down"] + " <-", -6, "right"), ("-> " + text["up"], 6, "left")):
            box.annotate(
                label,
                (0, 0.45),
                xytext=(offset, 0),
                textcoords="offset points",
                ha=align,
                fontsize=8.5,
                color=config.PLOT_INK_MUTED,
            )

        shares = profile[share_column].to_numpy()
        bars.barh(range(1, len(names) + 1), shares, height=0.55, color=list(config.REGIME_COLORS))
        bars.axvline(0.5, color=config.PLOT_INK_MUTED, linewidth=1)
        counts = profile[text["count_column"]].to_numpy() if "count_column" in text else [None] * len(shares)
        for y, (share, count) in enumerate(zip(shares, counts, strict=True), start=1):
            label = f"{share:.0%}" + (f"  ({count:.0f} weeks)" if count is not None else "")
            bars.text(share + 0.01, y, label, va="center", fontsize=10, color=config.PLOT_INK)
        bars.set_xlim(0, 1)
        bars.xaxis.set_major_formatter(PERCENT)
        bars.set_xlabel(text["bar_xlabel"])
        bars.set_title(text["bar_title"])
        _finish(fig, text["title"], text["subtitle"])
    return fig


def what_happens_next_figure(labelled, profile, test, horizon=config.FORWARD_HORIZON_WEEKS):
    """The relationship: the regime today vs how speculators change their net position next."""
    return _outcome_figure(
        labelled,
        profile,
        "forward_net_flow",
        "share_added_next",
        {
            "box_xlabel": f"Change in net position over the next {horizon} weeks (share of open interest)",
            "down": "speculators sold",
            "up": "speculators bought",
            "bar_xlabel": f"Share of weeks where net position was higher {horizon} weeks later",
            "bar_title": "How often speculators added (50% = coin flip)",
            "title": "Positioning tends to revert: crowded longs get trimmed, net shorts get covered",
            "subtitle": f"Kruskal-Wallis test on {test['weeks_tested']} non-overlapping {horizon}-week windows: "
            f"regimes differ in what follows ({_p_text(test)}).",
        },
    )


def gold_after_regime_figure(labelled, profile, test, horizon=config.FORWARD_HORIZON_WEEKS):
    """The price question: the regime today vs gold's return over the following weeks."""
    verdict = "differ" if test["p_value"] < 0.05 else "do not clearly differ"
    return _outcome_figure(
        labelled,
        profile,
        "forward_return",
        "share_price_rose",
        {
            "box_xlabel": f"Gold's return over the {horizon} weeks after the report is published",
            "down": "gold fell",
            "up": "gold rose",
            "bar_xlabel": f"Share of weeks where gold was higher {horizon} weeks later",
            "bar_title": "How often gold rose (50% = coin flip)",
            "count_column": "weeks_with_price",
            "title": "The regimes do not forecast gold's price",
            "subtitle": f"Gold's average return was positive after every regime, and the gaps between regimes could "
            f"easily be luck (Kruskal-Wallis test on {test['weeks_tested']} non-overlapping windows: regimes "
            f"{verdict}, {_p_text(test)}).",
        },
    )


def lead_lag_figure(lead_lag):
    """Do speculators move before or after the price? Correlation between their weekly change and gold's
    weekly return, with gold's week shifted earlier or later."""
    lags = lead_lag["lag_weeks"]
    colors = [
        config.SERIES_COLORS[1] if lag < 0 else config.PLOT_INK_MUTED if lag == 0 else config.SERIES_COLORS[0]
        for lag in lags
    ]
    with plt.rc_context(STYLE):
        fig, ax = plt.subplots(figsize=(12, 6))
        ax.bar(lags, lead_lag["correlation"], width=0.7, color=colors)
        ax.axhline(0, color=config.PLOT_AXIS, linewidth=1)
        top = max(lead_lag["correlation"].max(), 0.1)
        for x, label in ((-4.5, "<- gold's week came first"), (4.5, "gold's week came after ->")):
            ax.text(x, top * 1.08, label, ha="center", fontsize=9.5, color=config.PLOT_INK)
        same_week = lead_lag.loc[lags == 0, "correlation"].iloc[0]
        ax.annotate(
            f"same week: {same_week:.2f}",
            (0, same_week),
            xytext=(0, 4),
            textcoords="offset points",
            ha="center",
            fontsize=9.5,
            color=config.PLOT_INK,
        )
        ax.set_ylim(min(-0.15, lead_lag["correlation"].min() - 0.05), top * 1.2)
        ax.set_xticks(lags)
        ax.set_xlabel("Weeks between speculators' weekly change and gold's weekly move (negative = gold moved first)")
        ax.set_ylabel("Correlation (1 = always together, 0 = unrelated)")
        _finish(
            fig,
            "Speculators move with the price in the same week; they don't move ahead of it",
            "Weeks when gold rises are weeks when speculators buy (grey). Their buying says nothing about gold's "
            "following weeks (blue bars near zero).",
        )
    return fig


def price_timeline_figure(labelled, names=config.REGIME_NAMES):
    """Gold's price with each week's regime, so regimes can be read against the familiar price chart."""
    priced = labelled.dropna(subset=["close"])
    with plt.rc_context(STYLE):
        fig, ax = plt.subplots(figsize=(13, 6.5))
        ax.plot(priced["date"], priced["close"], color=config.PLOT_AXIS, linewidth=0.8, zorder=1)
        for regime, rows in priced.groupby("regime"):
            ax.scatter(
                rows["date"], rows["close"], s=12, linewidths=0, label=names[regime], zorder=2, **_regime_style(regime)
            )
        ax.set_yscale("log")
        ax.yaxis.set_major_formatter(StrMethodFormatter("${x:,.0f}"))
        ax.yaxis.set_minor_formatter(NullFormatter())
        ax.set_yticks([250, 500, 1000, 2000, 4000])
        ax.set_ylabel("Gold futures price, US$ per ounce (log scale)")
        ax.set_xlabel("Report date")
        ax.legend(loc="upper left", markerscale=2)
        _finish(
            fig,
            "Regimes on the gold price chart",
            "Crowded longs come with strong rallies and net-short spells with weak prices: positioning mirrors "
            "the trend that has already happened.",
        )
    return fig


def feature_set_figure(comparison, chosen_k=config.N_REGIMES):
    """Positioning only vs adding price features: separation and whether groups predict what comes next."""
    panels = [
        ("silhouette", "1. How clearly separated are the groups?", "Silhouette score (higher = clearer)"),
        ("p_positioning_next", "2. Do groups differ in what speculators do next?", "p-value (below line = yes)"),
        ("p_gold_next", "3. Do groups differ in what gold does next?", "p-value (below line = yes)"),
    ]
    with plt.rc_context(STYLE):
        fig, axes = plt.subplots(1, 3, figsize=(16, 5.8))
        for ax, (metric, title, ylabel) in zip(axes, panels, strict=True):
            for color, (name, rows) in zip(
                config.SERIES_COLORS, comparison.groupby("features", sort=False), strict=False
            ):
                ax.plot(rows["k"], rows[metric], color=color, marker="o", markersize=5, label=name)
            if metric != "silhouette":
                ax.set_yscale("log")
                ax.yaxis.set_major_formatter(StrMethodFormatter("{x:g}"))
                ax.yaxis.set_minor_formatter(NullFormatter())
                ax.set_yticks([0.001, 0.01, 0.05, 0.2, 1])
                ax.axhline(0.05, color=config.PLOT_INK, linewidth=1)
                ax.annotate(
                    "0.05: convincing below this line",
                    (comparison["k"].min(), 0.05),
                    xytext=(0, 5),
                    textcoords="offset points",
                    fontsize=8.5,
                    color=config.PLOT_INK,
                )
            ax.set_title(title)
            ax.set_ylabel(ylabel)
            ax.set_xlabel("Number of groups (k)")
        axes[0].legend(loc="upper right")
        _finish(
            fig,
            "Adding gold's price doesn't help: no version forecasts gold",
            f"K-Means on the same {comparison['weeks'].iloc[0]} weeks "
            f"({comparison['first_week'].iloc[0]:%Y} onwards) with three choices of inputs. Price-only groups are "
            "cleaner but just sort price trends; positioning-only is kept.",
        )
    return fig


def transition_figure(transitions, names=config.REGIME_NAMES):
    """Chance of moving from this week's regime (row) to next week's (column)."""
    cmap = LinearSegmentedColormap.from_list("sequential", config.SEQUENTIAL_COLORS)
    with plt.rc_context(STYLE):
        fig, ax = plt.subplots(figsize=(9, 6.5))
        image = ax.imshow(transitions.to_numpy(), cmap=cmap, vmin=0, vmax=1)
        for (row, col), value in np.ndenumerate(transitions.to_numpy()):
            ink = config.PLOT_SURFACE if value > 0.55 else config.PLOT_INK
            ax.text(col, row, f"{value:.0%}", ha="center", va="center", fontsize=11, color=ink)
        ax.set_xticks(range(len(names)), names, rotation=15, ha="right")
        ax.set_yticks(range(len(names)), names)
        ax.set_xlabel("Regime next week")
        ax.set_ylabel("Regime this week")
        ax.grid(visible=False)
        ax.tick_params(colors=config.PLOT_INK_SECONDARY, length=0)
        colorbar = fig.colorbar(image, ax=ax, shrink=0.8, format=PERCENT)
        colorbar.set_label("Chance of the move", color=config.PLOT_INK_SECONDARY)
        colorbar.outline.set_visible(False)
        _finish(
            fig,
            "Regimes are sticky, and moves go to neighbours",
            "Net-short rarely jumps straight to crowded-long: positioning shifts gradually.",
        )
    return fig


def big_move_figure(volatility_table, summary, positioning_table, threshold, base_rate):
    """Can a big gold move be seen coming? (1) jumpiness, (2) direction of big moves, (3) every clue."""
    with plt.rc_context(STYLE):
        fig = plt.figure(figsize=(15, 11))
        grid = fig.add_gridspec(2, 2, height_ratios=[1, 0.9])
        jumpy, direction = fig.add_subplot(grid[0, 0]), fig.add_subplot(grid[0, 1])
        clues = fig.add_subplot(grid[1, :])

        chances = volatility_table["big_move_chance"].to_numpy()
        jumpy.bar(range(len(chances)), chances, width=0.65, color=config.SERIES_COLORS[0])
        for x, chance in enumerate(chances):
            jumpy.text(x, chance + 0.006, f"{chance:.0%}", ha="center", fontsize=10, color=config.PLOT_INK)
        jumpy.axhline(base_rate, color=config.PLOT_INK_MUTED, linewidth=1)
        jumpy.set_xticks(range(len(chances)), ["Calmest\nfifth", "2nd", "3rd", "4th", "Jumpiest\nfifth"])
        jumpy.set_ylim(0, max(chances) * 1.25)
        jumpy.yaxis.set_major_formatter(PERCENT)
        jumpy.set_ylabel("Chance of a big move in the next 4 weeks")
        jumpy.set_xlabel(f"How jumpy gold was over the last 13 weeks\n(grey line = normal chance, {base_rate:.0%})")
        jumpy.set_title("1. After jumpy weeks, big moves are about twice as likely")

        shares = positioning_table["share_up"].to_numpy()
        direction.bar(range(len(shares)), shares, width=0.65, color=config.SERIES_COLORS[0])
        for x, share in enumerate(shares):
            direction.text(x, share + 0.01, f"{share:.0%}", ha="center", fontsize=10, color=config.PLOT_INK)
        direction.axhline(0.5, color=config.PLOT_INK_MUTED, linewidth=1)
        direction.set_xticks(range(len(shares)), ["Most\nshort", "2nd", "3rd", "4th", "Most\nlong"])
        direction.set_ylim(0, 1)
        direction.yaxis.set_major_formatter(PERCENT)
        direction.set_ylabel("Share of big moves that were UP")
        direction.set_xlabel(
            "Speculators' positioning on report day, in fifths of its 3-year range\n(grey line = coin flip, 50%)"
        )
        direction.set_title("2. Up or down? Speculators' positioning gives no hint")

        rows = summary.iloc[::-1].reset_index(drop=True)
        for y, row in rows.iterrows():
            color = config.SERIES_COLORS[0] if row["reliable"] else config.PLOT_INK_MUTED
            clues.plot([row["chance_lowest_fifth"], row["chance_highest_fifth"]], [y, y], color=color, linewidth=2)
            clues.scatter(
                row["chance_lowest_fifth"],
                y,
                s=70,
                facecolors=config.PLOT_SURFACE,
                edgecolors=color,
                linewidths=2,
                zorder=3,
            )
            clues.scatter(row["chance_highest_fifth"], y, s=70, color=color, zorder=3)
            p_label = "p < 0.001" if row["p_value"] < 0.001 else f"p = {row['p_value']:.2f}"
            verdict = "reliable" if row["reliable"] else "could be luck"
            clues.text(0.345, y, f"{verdict} ({p_label})", va="center", fontsize=9.5, color=config.PLOT_INK)
        clues.axvline(base_rate, color=config.PLOT_INK_MUTED, linewidth=1)
        clues.set_yticks(range(len(rows)), rows["clue"])
        clues.set_xlim(0.1, 0.42)
        clues.set_ylim(-0.6, len(rows) - 0.4)
        clues.xaxis.set_major_formatter(PERCENT)
        clues.set_xlabel(
            "Chance of a big move in the next 4 weeks: open dot = clue in its lowest fifth, filled dot = highest "
            f"fifth (grey line = normal, {base_rate:.0%})"
        )
        clues.set_title("3. Which clues on report day raise the odds of a big move?")
        clues.grid(axis="y", visible=False)
        _finish(
            fig,
            "Can we see a big gold move coming? Its size a little, its direction no",
            f"A big move = gold up or down by {threshold:.1%} or more in the 4 weeks after a report is published "
            "(the largest 20% of moves; normally 1 week in 5). Only gold's own recent jumpiness is a reliable clue.",
        )
    return fig
