"""Turn SEC XBRL companyfacts revenue facts into a clean quarterly series.

Rules (unit-tested in tests/test_sec_revenue.py):
* Candidate tags in priority order (companies switch tags over time; ASC 606
  moved most filers to RevenueFromContractWithCustomer... in 2018).
* Only 10-K / 10-Q (and amendments). For each (start, end) period we keep the
  highest-priority tag, then the most recently *filed* value, so restatements
  and later comparatives win.
* Quarters (80-100 day durations) are taken as reported. 10-Ks do not report
  Q4 on its own, so Q4 = full year (350-380 days) - nine-month YTD
  (260-285 days) with the same start date; if the 9M fact is missing we fall
  back to FY - (Q1 + Q2 + Q3).
* Non-calendar fiscal years (Snowflake/MongoDB end Jan 31, Elastic Apr 30)
  are labelled with the fiscal year in which they END (company convention),
  and each quarter is also snapped to the nearest calendar quarter-end for
  display. Signals are always aggregated over the company's *actual* fiscal
  quarter dates, so no calendar approximation enters the lead/lag study.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd

REVENUE_TAGS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "SalesRevenueNet",
]
FORMS = {"10-K", "10-Q", "10-K/A", "10-Q/A"}


def extract_revenue_facts(companyfacts: dict) -> pd.DataFrame:
    gaap = companyfacts.get("facts", {}).get("us-gaap", {})
    rows = []
    for prio, tag in enumerate(REVENUE_TAGS):
        for f in gaap.get(tag, {}).get("units", {}).get("USD", []):
            if f.get("form") not in FORMS or "start" not in f:
                continue
            rows.append({
                "tag": tag, "tag_priority": prio, "start": f["start"], "end": f["end"],
                "val": float(f["val"]), "form": f["form"], "filed": f.get("filed", ""),
                "accn": f.get("accn", ""), "fy": f.get("fy"), "fp": f.get("fp"),
            })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["days"] = (pd.to_datetime(df["end"]) - pd.to_datetime(df["start"])).dt.days
    return df


def _dedupe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["start", "end", "tag_priority", "filed"], ascending=[True, True, True, False])
    return df.drop_duplicates(["start", "end"], keep="first")


def fiscal_labels(end: pd.Timestamp, fy_end_mmdd: str) -> tuple[int, int]:
    """Return (fiscal_year, fiscal_quarter) for a quarter ending on `end`."""
    mm, dd = (int(x) for x in fy_end_mmdd.split("-"))
    cand = pd.Timestamp(dt.date(end.year, mm, dd))
    if cand < end - pd.Timedelta(days=10):
        cand = pd.Timestamp(dt.date(end.year + 1, mm, dd))
    quarters_to_go = round((cand - end).days / 91.3)
    return cand.year, 4 - quarters_to_go


def nearest_calendar_quarter(end: pd.Timestamp) -> str:
    """Snap a period end to the nearest calendar quarter end, e.g. 2024-01-31 -> 2023Q4."""
    cands = []
    for y in (end.year - 1, end.year):
        for q, (m, d) in enumerate([(3, 31), (6, 30), (9, 30), (12, 31)], start=1):
            cands.append((abs((pd.Timestamp(dt.date(y, m, d)) - end).days), y, q))
    _, y, q = min(cands)
    return f"{y}Q{q}"


def quarterly_revenue(facts: pd.DataFrame, fy_end_mmdd: str) -> pd.DataFrame:
    if facts.empty:
        return pd.DataFrame()
    f = _dedupe(facts)
    q = f[(f["days"] >= 80) & (f["days"] <= 100)]
    ytd9 = f[(f["days"] >= 260) & (f["days"] <= 285)]
    fy = f[(f["days"] >= 350) & (f["days"] <= 380)]

    out = {(r.start, r.end): {"period_start": r.start, "period_end": r.end, "revenue": r.val,
                               "source": "reported_quarter", "filed": r.filed}
           for r in q.itertuples()}
    q_by_end = {r.end for r in q.itertuples()}

    for r in fy.itertuples():
        if r.end in q_by_end:
            continue
        nine = ytd9[ytd9["start"] == r.start]
        if not nine.empty:
            n = nine.sort_values("end").iloc[-1]
            q4_start = (pd.Timestamp(n["end"]) + pd.Timedelta(days=1)).date().isoformat()
            out[(q4_start, r.end)] = {"period_start": q4_start, "period_end": r.end,
                                      "revenue": r.val - n["val"], "source": "derived_fy_minus_9m",
                                      "filed": r.filed}
            continue
        inside = q[(q["start"] >= r.start) & (q["end"] < r.end)].sort_values("end")
        if len(inside) == 3:
            q4_start = (pd.Timestamp(inside["end"].iloc[-1]) + pd.Timedelta(days=1)).date().isoformat()
            out[(q4_start, r.end)] = {"period_start": q4_start, "period_end": r.end,
                                      "revenue": r.val - inside["val"].sum(),
                                      "source": "derived_fy_minus_q1q3", "filed": r.filed}

    df = pd.DataFrame(out.values()).sort_values("period_end").reset_index(drop=True)
    # if overlapping quarters exist (e.g. restated period with shifted start), keep one per end date
    df = df.drop_duplicates("period_end", keep="last")
    ends = pd.to_datetime(df["period_end"])
    labels = [fiscal_labels(e, fy_end_mmdd) for e in ends]
    df["fiscal_year"] = [a for a, _ in labels]
    df["fiscal_quarter"] = [b for _, b in labels]
    df["calendar_quarter"] = [nearest_calendar_quarter(e) for e in ends]
    return df.reset_index(drop=True)


def add_yoy(df: pd.DataFrame) -> pd.DataFrame:
    """Log YoY growth vs. the same fiscal quarter one year earlier."""
    import numpy as np

    df = df.copy()
    key = df.set_index(["fiscal_year", "fiscal_quarter"])["revenue"]
    prev = [key.get((fy - 1, fq)) for fy, fq in zip(df["fiscal_year"], df["fiscal_quarter"])]
    prev = pd.to_numeric(pd.Series(prev, index=df.index), errors="coerce")
    df["revenue_prev_year"] = prev
    df["rev_yoy"] = np.log(df["revenue"] / prev)
    return df
