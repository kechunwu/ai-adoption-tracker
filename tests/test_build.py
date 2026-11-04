import pandas as pd

from tracker.build import weekly_downloads


def test_weekly_drops_partial_weeks_and_yoy():
    days = pd.date_range("2023-01-02", "2024-03-06", freq="D")  # Monday start; ends mid-week
    daily = pd.DataFrame({"date": days, "package": "x", "registry": "npm", "entity": "e",
                          "downloads": 10})
    w = weekly_downloads(daily)
    assert (w["downloads"] == 70).all()           # only complete weeks
    assert w["week"].dt.dayofweek.eq(6).all()     # weeks end Sunday
    assert w["yoy"].dropna().abs().max() < 1e-12  # flat series -> 0% YoY
