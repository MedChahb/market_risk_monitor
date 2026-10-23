from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from app import analysis

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def app() -> AppTest:
    app = AppTest.from_file(str(ROOT / "app" / "streamlit_app.py"), default_timeout=60)
    app.run()
    return app


def test_risk_today_shows_the_published_var_of_the_reference_book(app):
    fact_var = pd.read_parquet(ROOT / "data" / "gold" / "fact_var.parquet")
    latest = fact_var[(fact_var["for_date"] == fact_var["for_date"].max()) & (fact_var["method_id"] == "fhs")]
    assert not app.exception
    assert app.metric[0].value == f"{latest['var_99_eur'].iloc[0]:,.0f} €"


def test_moving_a_slider_recomputes_the_var_and_the_stress_page_keeps_the_book(app):
    app.switch_page("views/build_book.py").run()
    before = app.dataframe[0].value["VaR 99%"]
    app.slider(key="notional_CAC40").set_value(4.0).run()
    after = app.dataframe[0].value["VaR 99%"]
    assert not app.exception and (after > before).all()
    app.switch_page("views/stress_tests.py").run()
    assert app.slider(key="notional_CAC40").value == 4.0
    assert app.metric[0].value == f"{after['Filtered historical simulation (EWMA)']:,.0f} €"


def test_a_book_with_every_position_at_zero_asks_for_a_notional(app):
    app.switch_page("views/build_book.py").run()
    for slider in app.slider:
        slider.set_value(0.0)
    app.run()
    assert not app.exception and app.warning[0].value.startswith("Every position is at zero")


def test_the_stress_page_replays_every_scenario(app):
    app.switch_page("views/stress_tests.py").run()
    table = app.dataframe[0].value
    assert not app.exception
    assert table["Scenario"].tolist() == [scenario.name for scenario in analysis.SCENARIOS]
