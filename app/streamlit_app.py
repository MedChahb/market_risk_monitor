"""Public app: the market risk of the reference book, of a book the visitor builds, and stress tests.

It reads the gold Parquet tables of the repository and recomputes VaR, ES, the backtest and the
stress losses of a custom book with pipeline/risk.py. Run from the repository root:
    streamlit run app/streamlit_app.py
"""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # Streamlit puts only app/ on the path

from app import ui

st.set_page_config(page_title="Market Risk Monitor", page_icon=":material/monitoring:", layout="wide")
ui.keep_book_state(ui.load_gold()["dim_position"].set_index("position_id"))
page = st.navigation(
    [
        st.Page("views/risk_today.py", title="Risk today", default=True),
        st.Page("views/build_book.py", title="Build your book", url_path="build"),
        st.Page("views/stress_tests.py", title="Stress tests", url_path="stress"),
    ],
    position="top",
)
page.run()
