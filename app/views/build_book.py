"""Build your book: VaR, ES and the backtest of a book the visitor sets with sliders."""

import streamlit as st

from app import analysis, ui

gold = ui.load_gold()
positions = gold["dim_position"].set_index("position_id")
st.title("Build your book")
st.write(
    "Set the notional of each position in millions of euros (negative for a short position). VaR, "
    "Expected Shortfall and the backtest are recomputed on 18 years of daily returns."
)
notionals = ui.book_controls(positions)
gross = analysis.gross_notional(notionals)
if gross == 0:
    st.warning("Every position is at zero: set at least one notional.")
    st.stop()
pnl, estimates = ui.book_risk(tuple(notionals.items()))

st.subheader(f"VaR and ES for the session after {pnl.index.max():%d %b %Y}")
latest = analysis.latest(estimates).assign(var_share=lambda d: d["var"] / gross * 100)
latest[["var", "es"]] = latest[["var", "es"]].round()
st.dataframe(
    latest.rename(columns={"var": "VaR 99%", "es": "ES 97.5%", "var_share": "VaR, % of gross notional"}),
    width="stretch",
    column_config={
        "VaR 99%": st.column_config.NumberColumn(format="%,d €"),
        "ES 97.5%": st.column_config.NumberColumn(format="%,d €"),
        "VaR, % of gross notional": st.column_config.NumberColumn(format="%.2f%%"),
    },
)

first_year = int(estimates["fhs_ewma"].index.min().year) + 1
last_year = int(pnl.index.max().year)
start, end = st.select_slider(
    "Backtest period",
    options=list(range(first_year, last_year + 1)),
    value=(max(first_year, 2012), last_year),
)
table = analysis.backtest(pnl, estimates, f"{start}-01-01", f"{end}-12-31")
st.dataframe(
    table.rename(
        columns={
            "days": "Days",
            "exceptions": "Exceptions",
            "expected": "Expected",
            "kupiec_p": "Kupiec p",
            "christoffersen_p": "Christoffersen p",
            "zone": "Zone, last 250 days",
        }
    ),
    width="stretch",
    column_config={
        "Expected": st.column_config.NumberColumn(format="%.1f"),
        "Kupiec p": st.column_config.NumberColumn(format="%.3f"),
        "Christoffersen p": st.column_config.NumberColumn(format="%.3f"),
    },
)
period = pnl.loc[f"{start}-01-01" : f"{end}-12-31"]
fhs = estimates["fhs_ewma"]
covering = analysis.covering_var(pnl, fhs).loc[period.index]
exceptions = analysis.exception_days(pnl, fhs).loc[f"{start}-01-01" : f"{end}-12-31"]
st.plotly_chart(ui.pnl_chart(period, covering, exceptions, analysis.METHODS["fhs_ewma"]), width="stretch")
st.caption(
    "A custom book uses EWMA volatility (decay 0.94), computed instantly for any book. The reference "
    "book on the first page uses GJR-GARCH forecasts, refitted by the nightly pipeline."
)
ui.links()
