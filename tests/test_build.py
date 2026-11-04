import pandas as pd

from tracker.build import weekly_downloads


def test_weekly_drops_partial_weeks_and_yoy():
    days = pd.date_range("2023-01-02", "2024-03-06", freq="D")  # Monday start; ends mid-week
    daily = pd.DataFrame({"date": days, "package": "x", "registry": "npm", "entity": "e",
                          "downloads": 10_000})
    w = weekly_downloads(daily)
    assert (w["downloads"] == 70_000).all()           # only complete weeks
    assert w["week"].dt.day_of_week.eq(6).all()     # weeks end Sunday
    assert w["yoy"].dropna().abs().max() < 1e-12  # flat series -> 0% YoY


def test_spans_break(monkeypatch):
    from tracker import build
    monkeypatch.setattr(build, "known_breaks", lambda: [{"registry": "pypi", "date": "2026-08-25"}])
    reg = pd.Series(["pypi", "pypi", "npm"])
    start = pd.Series(pd.to_datetime(["2025-08-01", "2026-09-01", "2025-08-01"]))
    end = pd.Series(pd.to_datetime(["2026-09-01", "2027-09-01", "2026-09-01"]))
    assert build.spans_break(reg, start, end).tolist() == [True, False, False]
