"""End-to-end build on synthetic files in a temp dir (method test, not data)."""
import numpy as np
import pandas as pd

from tracker import build


def test_quarterly_panel_end_to_end(tmp_path, monkeypatch):
    raw, proc = tmp_path / "raw", tmp_path / "processed"
    raw.mkdir(); proc.mkdir()
    monkeypatch.setattr(build, "RAW", raw)
    monkeypatch.setattr(build, "PROCESSED", proc)
    days = pd.date_range("2016-01-01", "2024-12-31", freq="D")
    growth = np.exp(np.arange(len(days)) * 0.0005)
    pd.DataFrame({"date": days.strftime("%Y-%m-%d"), "package": "snowflake-sdk",
                  "downloads": (1000 * growth).astype(int)}).to_csv(raw / "npm_daily.csv", index=False)
    months = pd.period_range("2016-01", "2024-12", freq="M").astype(str)
    pd.DataFrame({"month": months, "entity": "SNOW", "total_posts": 500, "mentions": 20,
                  "mentions_ex_employer": 20, "employer_posts": 0, "share": 0.04,
                  "share_ex_employer": 0.04}).to_csv(raw / "hn_monthly.csv", index=False)
    # Snowflake-style fiscal quarters (FY ends Jan 31)
    rows = []
    for fy in range(2018, 2025):
        starts = [f"{fy-1}-02-01", f"{fy-1}-05-01", f"{fy-1}-08-01", f"{fy-1}-11-01"]
        ends = [f"{fy-1}-04-30", f"{fy-1}-07-31", f"{fy-1}-10-31", f"{fy}-01-31"]
        for q, (s, e) in enumerate(zip(starts, ends), 1):
            rows.append({"ticker": "SNOW", "period_start": s, "period_end": e, "revenue": 100 * 1.3 ** (fy - 2018),
                         "fiscal_year": fy, "fiscal_quarter": q, "calendar_quarter": "x"})
    pd.DataFrame(rows).to_csv(proc / "revenue_quarterly.csv", index=False)

    p = build.quarterly_panel()
    snow = p[p["ticker"] == "SNOW"].set_index(["fiscal_year", "fiscal_quarter"])
    assert snow["hn_months"].dropna().eq(3).all()
    assert abs(snow.loc[(2020, 2), "rev_yoy"] - np.log(1.3)) < 1e-9
    assert abs(snow.loc[(2020, 2), "hn_yoy"]) < 1e-9          # flat share -> 0 growth
    assert 0.15 < snow.loc[(2020, 2), "npm_yoy"] < 0.2          # 0.0005/day * ~365
    assert snow["pypi_yoy"].isna().all()

    outs = build.run()
    assert not outs["entity_weekly"].empty and not outs["what_moved"].empty
