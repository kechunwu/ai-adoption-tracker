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

from tracker.config import PROCESSED, RAW, entities, known_breaks, package_map, public_companies
from tracker.storage import read_csv

log = logging.getLogger(__name__)


# --------------------------------------------------------------- downloads --
REF_MIN_DAILY = 1000   # "established" package: median >= 1,000/day over the prior 28 days
MAX_IMPUTED_DAYS = 2
MIN_YOY_BASE = 10_000  # weekly downloads a year earlier; YoY from a tinier base is not meaningful (display only)   # a week with more filled-in days than this is left blank


def mark_missing(df: pd.DataFrame) -> pd.DataFrame:
    """Turn reporting artefacts into missing values (NaN) instead of real zeros.

    1. Pre-launch zeros: npm reports 0 for every day before a package existed.
       These are dropped (`prelaunch`), not imputed.
    2. Registry outages (`outage`): days on which >= 50% of established packages
       report exactly 0 (e.g. npm returned 0 for everything on 2026-10-13..15).
    3. A 0 for an established package on any other day is also treated as missing
       (a package with millions of daily installs does not drop to zero).
    """
    if df.empty:
        return df.assign(missing=pd.Series(dtype=bool), prelaunch=pd.Series(dtype=bool),
                         outage=pd.Series(dtype=bool))
    df = df.sort_values(["package", "date"]).copy()
    df["downloads"] = df["downloads"].astype(float)
    started = df.groupby("package")["downloads"].transform(lambda s: (s > 0).cummax()).astype(bool)
    ref = df.groupby("package")["downloads"].transform(lambda s: s.shift(1).rolling(28, min_periods=14).median())
    established = ref >= REF_MIN_DAILY
    zero = df["downloads"] == 0
    n_est = established.groupby(df["date"]).transform("sum")
    n_zero = (zero & established).groupby(df["date"]).transform("sum")
    df["outage"] = (n_est > 0) & (n_zero >= 0.5 * n_est)
    df["prelaunch"] = ~started
    df["missing"] = started & zero & (df["outage"] | established)
    df.loc[df["missing"] | df["prelaunch"], "downloads"] = np.nan
    return df


def outage_days(df: pd.DataFrame) -> list[str]:
    """Dates treated as registry-wide outages (listed on the methodology page)."""
    if df.empty or "outage" not in df:
        return []
    return sorted(pd.to_datetime(df.loc[df["outage"], "date"]).dt.strftime("%Y-%m-%d").unique())


def impute_same_weekday(s: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Fill missing days with the mean of the same weekday 1 week before/after
    (falling back to 2 weeks). Keeps weekday seasonality, unlike a plain mean."""
    s = s.asfreq("D")
    filled = s.copy()
    for k in (7, 14):
        cand = pd.concat([s.shift(k), s.shift(-k)], axis=1).mean(axis=1)
        filled = filled.fillna(cand)
    return filled, s.isna() & filled.notna()


def load_daily(drop_missing: bool = True) -> pd.DataFrame:
    """Daily downloads for both registries with artefacts handled.

    Pre-launch rows are dropped; missing (outage) days are imputed from the same
    weekday and flagged `imputed` so weekly sums stay comparable."""
    frames = []
    for reg in ("npm", "pypi"):
        df = read_csv(RAW / f"{reg}_daily.csv")
        if df.empty:
            continue
        df["date"] = pd.to_datetime(df["date"])
        df = mark_missing(df)
        df = df[~df["prelaunch"]]
        parts = []
        for pkg, g in df.groupby("package"):
            vals, imp = impute_same_weekday(g.set_index("date")["downloads"])
            parts.append(pd.DataFrame({"date": vals.index, "package": pkg, "downloads": vals.values,
                                       "imputed": imp.values}))
        df = pd.concat(parts, ignore_index=True)
        if drop_missing:
            df = df.dropna(subset=["downloads"])
        df["registry"] = reg
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["date", "package", "downloads", "registry", "entity", "imputed"])
    df = pd.concat(frames, ignore_index=True)
    pm = package_map()
    df["entity"] = [pm.get((r, p)) for r, p in zip(df["registry"], df["package"])]
    return df.dropna(subset=["entity"])


def weekly_downloads(daily: pd.DataFrame) -> pd.DataFrame:
    """Weeks ending Sunday; complete weeks only, at most MAX_IMPUTED_DAYS filled
    in from the same weekday; 4-week average and YoY of the 4-week average."""
    if daily.empty:
        return pd.DataFrame()
    d = daily.dropna(subset=["downloads"]).copy()
    if "imputed" not in d:
        d["imputed"] = False
    d["week"] = d["date"].dt.to_period("W-SUN").dt.end_time.dt.normalize()
    g = d.groupby(["registry", "package", "entity", "week"], as_index=False).agg(
        downloads=("downloads", "sum"), days=("date", "nunique"), imputed_days=("imputed", "sum"))
    g = g[(g["days"] == 7) & (g["imputed_days"] <= MAX_IMPUTED_DAYS)].drop(columns="days")
    # 4-week average from the gap-filled DAILY series (rolling 28 days), so one bad
    # week doesn't blank the average; blank if > 7 of the 28 days were filled in.
    roll = []
    for (reg, pkg), s in d.groupby(["registry", "package"]):
        s = s.set_index("date").sort_index()
        r = pd.DataFrame({"sum28": s["downloads"].rolling("28D", min_periods=28).sum(),
                          "imp28": s["imputed"].astype(float).rolling("28D", min_periods=28).sum()})
        r = r[r.index.dayofweek == 6]
        r["ma4"] = np.where(r["imp28"] <= 7, r["sum28"] / 4, np.nan)
        roll.append(r[["ma4"]].assign(registry=reg, package=pkg).rename_axis("week").reset_index())
    roll = pd.concat(roll, ignore_index=True)
    out = []
    for (reg, pkg), s in g.groupby(["registry", "package"], sort=False):
        s = s.set_index("week").asfreq("W-SUN")
        s[["registry", "package", "entity"]] = s[["registry", "package", "entity"]].ffill().bfill()
        out.append(s.reset_index())
    w = pd.concat(out, ignore_index=True)
    w = w.merge(roll, on=["registry", "package", "week"], how="left")
    w = w.sort_values(["registry", "package", "week"])
    lag = w.groupby(["registry", "package"])["ma4"].shift(52)
    w["yoy"] = np.where(lag >= MIN_YOY_BASE, w["ma4"] / lag - 1, np.nan)
    w.loc[spans_break(w["registry"], w["week"] - pd.Timedelta(weeks=52) - pd.Timedelta(days=27), w["week"]), "yoy"] = np.nan
    return w.reset_index(drop=True)


def spans_break(registry: pd.Series, start: pd.Series, end: pd.Series) -> pd.Series:
    """True where the window [start, end] (YoY comparison span) contains a known registry break."""
    out = pd.Series(False, index=registry.index)
    for b in known_breaks():
        d = pd.Timestamp(b["date"])
        out |= (registry == b["registry"]) & (pd.to_datetime(start) < d) & (pd.to_datetime(end) >= d)
    return out


def entity_weekly(weekly: pd.DataFrame) -> pd.DataFrame:
    if weekly.empty:
        return pd.DataFrame()
    w = weekly.copy()
    span = w.dropna(subset=["ma4"]).groupby(["entity", "registry", "package"])["week"].agg(["min", "max"]).reset_index()
    g = w.groupby(["entity", "registry", "week"], as_index=False).agg(
        downloads=("downloads", lambda x: x.sum(min_count=1)), ma4=("ma4", lambda x: x.sum(min_count=1)),
        n_dl=("downloads", "count"), n_ma=("ma4", "count"))
    # expected = packages of this entity that existed that week; a missing one -> blank, not a fake dip
    exp = []
    for r in g.itertuples():
        sp = span[(span["entity"] == r.entity) & (span["registry"] == r.registry)]
        exp.append(int(((sp["min"] <= r.week) & (sp["max"] >= r.week)).sum()))
    g["expected"] = exp
    g.loc[g["n_dl"] < g["expected"], "downloads"] = np.nan
    g.loc[g["n_ma"] < g["expected"], "ma4"] = np.nan
    g = g.drop(columns=["expected", "n_dl", "n_ma"]).sort_values(["entity", "registry", "week"])
    lag = g.groupby(["entity", "registry"])["ma4"].shift(52)
    g["yoy"] = np.where(lag >= MIN_YOY_BASE, g["ma4"] / lag - 1, np.nan)
    # yoy_raw is kept so the baseline-relative ratio survives registry breaks
    brk = spans_break(g["registry"], g["week"] - pd.Timedelta(weeks=52) - pd.Timedelta(days=27), g["week"])
    lag_raw = g.groupby(["entity", "registry"])["ma4"].shift(52)
    g["yoy_raw"] = np.where(lag_raw >= MIN_YOY_BASE, g["ma4"] / lag_raw - 1, np.nan)
    g.loc[brk, "yoy"] = np.nan
    return add_baseline(g.reset_index(drop=True))


BASELINE = "_baseline"


def add_baseline(df: pd.DataFrame, keys=("registry", "week")) -> pd.DataFrame:
    """Add YoY relative to the registry control basket: (1+yoy)/(1+yoy_baseline) - 1."""
    ycol = "yoy_raw" if "yoy_raw" in df else "yoy"
    base = df[df["entity"] == BASELINE][[*keys, "ma4", ycol]].rename(
        columns={"ma4": "baseline_ma4", ycol: "baseline_yoy"})
    if base.empty:
        df["baseline_yoy"] = np.nan
        df["yoy_rel"] = np.nan
        return df
    df = df.drop(columns=[c for c in ("baseline_ma4", "baseline_yoy", "yoy_rel") if c in df]).merge(
        base, on=list(keys), how="left")
    df["yoy_rel"] = (1 + df[ycol]) / (1 + df["baseline_yoy"]) - 1
    return df


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
    base = weekly[weekly["entity"] == BASELINE].groupby(["registry", "week"])["ma4"].sum(min_count=1)
    base_yoy = (base / base.groupby(level=0).shift(52) - 1).rename("baseline_yoy")
    weekly = weekly[weekly["entity"] != BASELINE]
    last_week = weekly.dropna(subset=["downloads"])["week"].max()
    for (reg, pkg), s in weekly.groupby(["registry", "package"]):
        s = s.set_index("week").sort_index()
        if last_week not in s.index or pd.isna(s.at[last_week, "downloads"]):
            continue
        last = s.loc[last_week]
        prev_w = last_week - pd.Timedelta(weeks=1)
        prev = s["downloads"].get(prev_w, np.nan)
        prior4 = s["downloads"].reindex(pd.date_range(end=prev_w, periods=4, freq="W-SUN"))
        prior4 = prior4.mean() if prior4.notna().sum() >= 3 else np.nan
        rows.append({
            "entity": last["entity"], "name": names.get(last["entity"], last["entity"]),
            "registry": reg, "package": pkg, "week": last_week.date().isoformat(),
            "downloads": int(last["downloads"]),
            "wow": last["downloads"] / prev - 1 if prev and pd.notna(prev) else np.nan,
            "vs_prior4": last["downloads"] / prior4 - 1 if prior4 and pd.notna(prior4) else np.nan,
            "yoy_4wk": last.get("yoy", np.nan),
            "yoy_vs_baseline": (1 + last.get("yoy", np.nan)) / (1 + base_yoy.get((reg, last_week), np.nan)) - 1,
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
    # registry baseline over the same fiscal window (for the post-hoc "relative" signals)
    if not daily.empty and (daily["entity"] == BASELINE).any():
        bd = daily[daily["entity"] == BASELINE]
        for reg in ("npm", "pypi"):
            sub = bd[bd["registry"] == reg]
            p[f"{reg}_base_daily"] = [
                _window_mean_daily(sub, pd.Timestamp(a), pd.Timestamp(b)) if not sub.empty else np.nan
                for a, b in zip(p["period_start"], p["period_end"])]
    pairs = [("revenue", "rev_yoy"), ("hn_share", "hn_yoy"), ("npm_daily", "npm_yoy"), ("pypi_daily", "pypi_yoy"),
             ("npm_base_daily", "npm_base_yoy"), ("pypi_base_daily", "pypi_base_yoy")]
    for col, out in pairs:
        if col not in p:
            p[col] = np.nan
        key = p.set_index(["ticker", "fiscal_year", "fiscal_quarter"])[col]
        prev = [key.get((t, fy - 1, fq), np.nan) for t, fy, fq in zip(p["ticker"], p["fiscal_year"], p["fiscal_quarter"])]
        prev = pd.to_numeric(pd.Series(prev, index=p.index), errors="coerce")
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = p[col] / prev
        p[out] = np.where((ratio > 0) & np.isfinite(ratio), np.log(ratio.where(ratio > 0)), np.nan)
    p["npm_rel_yoy"] = p["npm_yoy"] - p["npm_base_yoy"]
    p["pypi_rel_yoy"] = p["pypi_yoy"] - p["pypi_base_yoy"]
    # raw YoY spanning a registry break is not comparable -> blank (relative versions stay)
    prev_start = pd.to_datetime(p["period_start"]) - pd.DateOffset(years=1)
    for reg in ("npm", "pypi"):
        brk = spans_break(pd.Series(reg, index=p.index), prev_start, pd.to_datetime(p["period_end"]))
        p.loc[brk, f"{reg}_yoy"] = np.nan
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
