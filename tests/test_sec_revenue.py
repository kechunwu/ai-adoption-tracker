import pandas as pd

from tracker.sec_revenue import (add_yoy, extract_revenue_facts, fiscal_labels, nearest_calendar_quarter,
                                 quarterly_revenue)


def test_q4_derivation_and_labels(load_fixture):
    facts = extract_revenue_facts(load_fixture("sec_companyfacts.json"))
    assert "8-K" not in set(facts["form"])
    q = quarterly_revenue(facts, "01-31").set_index("period_end")
    assert q.loc["2024-01-31", "revenue"] == 130          # 460 - 330
    assert q.loc["2024-01-31", "source"] == "derived_fy_minus_9m"
    assert q.loc["2024-01-31", "period_start"] == "2023-11-01"
    assert q.loc["2024-01-31", "fiscal_year"] == 2024 and q.loc["2024-01-31", "fiscal_quarter"] == 4
    assert q.loc["2023-04-30", "fiscal_quarter"] == 1
    # restatement: newest filing wins; lower-priority tag ignored
    assert q.loc["2024-04-30", "revenue"] == 141
    assert q.loc["2024-04-30", "fiscal_year"] == 2025
    # quarters add up to the full year
    fy24 = q[q["fiscal_year"] == 2024]["revenue"].sum()
    assert fy24 == 460


def test_yoy(load_fixture):
    q = add_yoy(quarterly_revenue(extract_revenue_facts(load_fixture("sec_companyfacts.json")), "01-31"))
    row = q[q["period_end"] == "2024-04-30"].iloc[0]
    assert abs(row["rev_yoy"] - __import__("math").log(141 / 100)) < 1e-12


def test_fiscal_labels_other_year_ends():
    # Elastic: FY ends Apr 30
    assert fiscal_labels(pd.Timestamp("2024-07-31"), "04-30") == (2025, 1)
    assert fiscal_labels(pd.Timestamp("2025-04-30"), "04-30") == (2025, 4)
    # calendar year
    assert fiscal_labels(pd.Timestamp("2024-09-30"), "12-31") == (2024, 3)
    assert fiscal_labels(pd.Timestamp("2024-12-31"), "12-31") == (2024, 4)


def test_calendar_snap():
    assert nearest_calendar_quarter(pd.Timestamp("2024-01-31")) == "2023Q4"
    assert nearest_calendar_quarter(pd.Timestamp("2024-04-30")) == "2024Q1"
    assert nearest_calendar_quarter(pd.Timestamp("2024-09-30")) == "2024Q3"
