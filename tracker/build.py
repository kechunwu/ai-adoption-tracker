"""Clean raw pulls into the tidy tables the app and the study read.

Outputs (data/processed/):
  downloads_weekly.csv   week x registry x package (complete weeks only)
  entity_weekly.csv      week x entity x registry (sum over the entity's packages)
  hn_share.csv           month x entity HN hiring-post share (+3-month avg)
  what_moved.csv         latest-week movers table
  quarterly_panel.csv    company x fiscal quarter: revenue + signals + YoY
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from tracker.config import PROCESSED, RAW, entities, package_map, public_companies
from tracker.storage import read_csv

log = logging.getLogger(__name__)


# --------------------------------------------------------------- downloads --
def load_daily() -> pd.DataFrame:
    frames = []
    for reg in ("npm", "pypi"):
        df = read_csv(RAW / f"{reg}_daily.csv")
        if not df.empty:
            df["registry"] = reg
            frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["date", "package", "downloads", "registry", "entity"])
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    pm = package_map()
    df["entity"] = [pm.get((r, p)) for r, p in zip(df["registry"], df["package"])]
    return df.dropna(subset=["entity"])


def weekly_downloads(daily: pd.DataFrame) -> pd.DataFrame:
    """Sum to weeks ending Sunday; drop partial weeks; add 4-wk avg and YoY."""
    if daily.empty:
        return pd.DataFrame()
    d = daily.copy()
    d["week"] = d["date"].dt.to_period("W-SUN").dt.end_time.dt.normalize()
    g = d.groupby(["registry", "package", "entity", "week"], as_index=False).agg(
        downloads=("downloads", "sum"), days=("date", "nunique"))
    g = g[g["days"] == 7].drop(columns="days")
    g = g.sort_values(["registry", "package", "week"])
    out = []
    for _, s in g.groupby(["registry", "package"], sort=False):
        s = s.set_index("week").asfreq("W-SUN")
        s[["registry", "package", "entity"]] = s[["registry", "package", "entity"]].ffill().bfill()
        s["ma4"] = s["downloads"].rolling(4, min_periods=4).mean()
        lag = s["ma4"].shift(52)
        s["yoy"] = np.where(lag > 0, s["ma4"] / lag - 1, np.nan)
        out.append(s.reset_index())
    return pd.concat(out, ignore_index=True)


def entity_weekly(weekly: pd.DataFrame) -> pd.DataFrame:
    if weekly.empty:
        return pd.DataFrame()
    g = weekly.groupby(["entity", "registry", "week"], as_index=False)["downloads"].sum(min_count=1)
    out = []
    for _, s in g.groupby(["entity", "registry"], sort=False):
        s = s.sort_values("week").set_index("week").asfreq("W-SUN")
        s[["entity", "registry"]] = s[["entity", "registry"]].ffill().bfill()
        s["ma4"] = s["downloads"].rolling(4, min_periods=4).mean()
        lag = s["ma4"].shift(52)
        s["yoy"] = np.where(lag > 0, s["ma4"] / lag - 1, np.nan)
        out.append(s.reset_index())
    return pd.concat(out, ignore_index=True)


# ---------------------------------------------------------------------- HN --
def hn_share() -> pd.DataFrame:
    df = read_csv(RAW / "hn_monthly.csv")
    if df.empty:
        return df
    df = df.sort_values(["entity", "month"])
    df["share_3m"] = df.groupby("entity")["share_ex_employer"].transform(lambda s: s.rolling(3, min_periods=3).mean())
    df["share_yoy"] = df.groupby("entity")["share_3m"].transform(lambda s: np.where(s.shift(12) > 0, s / s.shift(12) - 1, np.nan))
    return df


# --------------------------------------------------------------- movers --
def what_moved(weekly: pd.DataFrame, hn: pd.DataFrame) -> pd.DataFrame:
    """One row per package: last complete week vs prior week / prior 4 weeks / last year."""
    if weekly.empty:
        return pd.DataFrame()
    names = {e.id: e.name for e in entities()}
    rows = []
    for (reg, pkg), s in weekly.groupby(["registry", "package"]):
        s = s.dropna(subset=["downloads"]).sort_values("week")
        if len(s) < 2:
            continue
        last, prev = s.iloc[-1], s.iloc[-2]
        prior4 = s["downloads"].iloc[-5:-1].mean() if len(s) >= 5 else np.nan
        rows.append({
            "entity": last["entity"], "name": names.get(last["entity"], last["entity"]),
            "registry": reg, "package": pkg, "week": last["week"].date().isoformat(),
            "downloads": int(last["downloads"]),
            "wow": last["downloads"] / prev["downloads"] - 1 if prev["downloads"] else np.nan,
            "vs_prior4": last["downloads"] / prior4 - 1 if prior4 else np.nan,
            "yoy_4wk": last.get("yoy", np.nan),
        })
    out = pd.DataFrame(rows)
    if not hn.empty:
        latest = hn.sort_values("month").groupby("entity").tail(2)
        chg = latest.groupby("entity").agg(hn_month=("month", "last"), hn_share=("share_ex_employer", "last"),
                                           hn_share_prev=("share_ex_employer", "first")).reset_index()
        out = out.merge(chg, on="entity", how="left")
    out["abs_move"] = out["vs_prior4"].abs()
    return out.sort_values("abs_move", ascending=False).drop(columns="abs_move")


# ------------------------------------------------------- quarterly panel --
def _window_mean_daily(daily: pd.DataFrame, start, end, min_coverage=0.9) -> float:
    """Average daily downloads (summed over packages) inside [start, end]."""
    m = daily[(daily["date"] >= start) & (daily["date"] <= end)]
    n_days = (end - start).days + 1
    if m.empty:
        return np.nan
    by_day = m.groupby("date")["downloads"].sum()
    if len(by_day) < min_coverage * n_days:
        return np.nan
    return float(by_day.mean())


def quarterly_panel() -> pd.DataFrame:
    rev = read_csv(PROCESSED / "revenue_quarterly.csv")
    if rev.empty:
        return pd.DataFrame()
    daily = load_daily()
    hn = read_csv(RAW / "hn_monthly.csv")
    if not hn.empty:
        hn["month_start"] = pd.to_datetime(hn["month"] + "-01")
    rows = []
    for c in public_companies():
        r = rev[rev["ticker"] == c.ticker]
        dc = daily[daily["entity"] == c.id] if not daily.empty else daily
        hc = hn[hn["entity"] == c.id] if not hn.empty else hn
        for q in r.itertuples():
            s, e = pd.Timestamp(q.period_start), pd.Timestamp(q.period_end)
            row = {"ticker": c.ticker, "period_start": q.period_start, "period_end": q.period_end,
                   "fiscal_year": q.fiscal_year, "fiscal_quarter": q.fiscal_quarter,
                   "calendar_quarter": q.calendar_quarter, "revenue": q.revenue}
            for reg in ("npm", "pypi"):
                sub = dc[dc["registry"] == reg] if not dc.empty else dc
                row[f"{reg}_daily"] = _window_mean_daily(sub, s, e) if not sub.empty else np.nan
            if not hc.empty:
                hq = hc[(hc["month_start"] >= s) & (hc["month_start"] <= e)]
                posts = hq["total_posts"].sum()
                row["hn_share"] = hq["mentions_ex_employer"].sum() / posts if posts else np.nan
                row["hn_months"] = len(hq)
            rows.append(row)
    p = pd.DataFrame(rows)
    # log YoY vs the same fiscal quarter a year earlier
    for col, out in [("revenue", "rev_yoy"), ("hn_share", "hn_yoy"), ("npm_daily", "npm_yoy"), ("pypi_daily", "pypi_yoy")]:
        if col not in p:
            p[col] = np.nan
        key = p.set_index(["ticker", "fiscal_year", "fiscal_quarter"])[col]
        prev = [key.get((t, fy - 1, fq), np.nan) for t, fy, fq in zip(p["ticker"], p["fiscal_year"], p["fiscal_quarter"])]
        prev = pd.to_numeric(pd.Series(prev, index=p.index), errors="coerce")
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = p[col] / prev
        p[out] = np.where((ratio > 0) & np.isfinite(ratio), np.log(ratio.where(ratio > 0)), np.nan)
    return p.sort_values(["ticker", "period_end"]).reset_index(drop=True)


def run() -> dict[str, pd.DataFrame]:
    PROCESSED.mkdir(parents=True, exist_ok=True)
    daily = load_daily()
    weekly = weekly_downloads(daily)
    ew = entity_weekly(weekly)
    hn = hn_share()
    moved = what_moved(weekly, hn)
    panel = quarterly_panel()
    outs = {"downloads_weekly": weekly, "entity_weekly": ew, "hn_share": hn,
            "what_moved": moved, "quarterly_panel": panel}
    for name, df in outs.items():
        if not df.empty:
            df.to_csv(PROCESSED / f"{name}.csv", index=False)
            log.info("wrote %s (%d rows)", name, len(df))
    return outs
