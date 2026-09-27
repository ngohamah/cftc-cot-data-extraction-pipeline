"""Plain-language run summary for non-technical readers (pure)."""

import pandas as pd

import config


def summarise_symbol(symbol, signals, new_weeks):
    """One plain-language row describing a symbol's latest week (signals are oldest-first)."""
    latest = signals.iloc[-1]
    return {
        "Market": symbol,
        "Week of": latest[config.DATE_COL],
        "Large speculators net position (contracts)": f"{int(latest[config.NET_COL]):,}",
        "Change vs previous week": "n/a"
        if pd.isna(latest[config.NET_CHANGE_COL])
        else f"{int(latest[config.NET_CHANGE_COL]):+,}",
        "Reading": latest["Interpretation"],
        "New weeks added this run": new_weeks,
    }


def render_report(rows, run_time, problems):
    """Markdown summary for non-technical readers."""
    table = pd.DataFrame(rows)
    header = "| " + " | ".join(table.columns) + " |\n|" + "---|" * len(table.columns) + "\n" if rows else ""
    body = "".join("| " + " | ".join(str(v) for v in row) + " |\n" for row in table.itertuples(index=False))
    issues = "".join(f"- {p}\n" for p in problems) or "- None\n"
    return (
        "# Commitments of Traders - weekly summary\n\n"
        f"_Generated {run_time:%Y-%m-%d %H:%M}_\n\n"
        "**What this shows:** each week the CFTC reports how many futures contracts large "
        "speculators (hedge funds, money managers) hold betting on prices rising (long) or "
        "falling (short). The *net position* is longs minus shorts. The *reading* combines the "
        "weekly change in that net position with the change in open interest (total contracts "
        "outstanding):\n\n"
        "- **Bullish** - speculators added to bets on rising prices while new money entered.\n"
        "- **Bearish** - speculators cut bets on rising prices while new money entered.\n"
        "- **Bullish / Bearish Reversal** - the same moves but with money leaving the market, "
        "which often comes before a change in direction.\n\n"
        "This is an indicator, not a trading recommendation.\n\n"
        "## Latest week by market\n\n"
        f"{header}{body}\n"
        "## Issues during this run\n\n"
        f"{issues}"
    )
