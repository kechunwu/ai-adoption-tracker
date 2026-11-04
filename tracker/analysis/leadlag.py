"""Lead/lag study: do developer-adoption signals lead reported revenue growth?

Design (fixed in config/tracked.yaml `analysis:` before any data was pulled):

* Unit: company x fiscal quarter (actual fiscal-quarter dates from the SEC).
* Variables: log YoY growth of revenue, and of each signal aggregated over the
  same fiscal quarter (HN hiring-post share excl. the company's own posts;
  npm and PyPI average daily downloads of the company's proxy packages).
* For lag k in {0,1,2,3,4}: corr(signal_yoy[t-k], revenue_yoy[t]).
  Positive k = the signal LEADS revenue by k quarters.
* Primary spec: YoY levels. Robustness: first difference of YoY
  ("acceleration"), which removes shared slow-moving trends.
* Every (company, signal, spec, lag) is reported -- no lag is selected.

Statistical honesty:
* 95% CIs use the Fisher z-transform with an *effective* sample size
  corrected for autocorrelation (Bartlett / Pyper & Peterman 1998):
      n_eff = n / (1 + 2 * sum_j rho_x(j) * rho_y(j))
  YoY growth series are highly autocorrelated, so n_eff << n.
* The headline p-value (`p`) is a t-test on r using that same n_eff. We chose
  it after a calibration simulation (scripts/null_calibration.py, run before
  any real data was pulled): on independent persistent series the n_eff test
  keeps its false-positive rate near 5%, while a 4-quarter block permutation
  test rejected 10-32% of the time. The block-permutation p (`p_perm`) is
  still reported as a secondary column, with that caveat.
* Lag selection: `p_lag_adj` = Bonferroni over the five lags tried for that
  company/signal (so reading off the "best" lag is paid for). Across all
  company tests we also report Benjamini-Hochberg q-values (`q_bh`).
* Pooled panel: within-company demeaned (company fixed effects), and also
  two-way demeaned (company + calendar-quarter fixed effects, so a common
  macro/rate cycle cannot drive the result).
"""
from __future__ import annotations

import json
import logging

import numpy as np
import pandas as pd

from tracker.config import PROCESSED, analysis_settings

log = logging.getLogger(__name__)

SIGNALS = {"hn": "HN hiring-post share", "npm": "npm downloads", "pypi": "PyPI downloads",
           # post-hoc (added after seeing registry-wide download inflation in the raw data):
           "npm_rel": "npm downloads vs registry baseline", "pypi_rel": "PyPI downloads vs registry baseline"}
POST_HOC = {"npm_rel", "pypi_rel"}


# ------------------------------------------------------------- utilities --
def pearson(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 3:
        return np.nan
    x = x - x.mean()
    y = y - y.mean()
    d = np.sqrt((x * x).sum() * (y * y).sum())
    return float((x * y).sum() / d) if d > 0 else np.nan


def acf(x: np.ndarray, j: int) -> float:
    if len(x) <= j + 2:
        return 0.0
    return pearson(x[:-j], x[j:]) if j > 0 else 1.0


def effective_n(x: np.ndarray, y: np.ndarray) -> float:
    n = len(x)
    J = max(1, n // 5)
    s = sum((acf(x, j) or 0.0) * (acf(y, j) or 0.0) for j in range(1, J + 1))
    ne = n / (1 + 2 * s) if (1 + 2 * s) > 0 else n
    return float(min(max(ne, 3.0), n))


def fisher_ci(r: float, n_eff: float, z=1.959964) -> tuple[float, float]:
    if not np.isfinite(r) or n_eff <= 3.5 or abs(r) >= 1:
        return (np.nan, np.nan)
    zr = np.arctanh(r)
    se = 1 / np.sqrt(n_eff - 3)
    return float(np.tanh(zr - z * se)), float(np.tanh(zr + z * se))


def neff_pvalue(r: float, n_eff: float) -> float:
    """Two-sided t-test of r with the autocorrelation-adjusted sample size."""
    from scipy import stats

    if not np.isfinite(r) or not np.isfinite(n_eff) or n_eff <= 3 or abs(r) >= 1:
        return np.nan
    df = n_eff - 2
    t = r * np.sqrt(df / (1 - r * r))
    return float(2 * stats.t.sf(abs(t), df))


def block_permute(x: np.ndarray, block: int, rng: np.random.Generator) -> np.ndarray:
    """Shuffle contiguous blocks of the *observed* values, keeping NaN positions fixed."""
    out = x.copy()
    idx = np.flatnonzero(np.isfinite(x))
    vals = x[idx]
    blocks = [vals[i:i + block] for i in range(0, len(vals), block)]
    order = rng.permutation(len(blocks))
    out[idx] = np.concatenate([blocks[i] for i in order]) if blocks else vals
    return out


def bh_qvalues(p: pd.Series) -> pd.Series:
    """Benjamini-Hochberg q-values (NaN-aware)."""
    mask = p.notna()
    pv = p[mask].to_numpy()
    n = len(pv)
    if n == 0:
        return pd.Series(np.nan, index=p.index)
    order = np.argsort(pv)
    ranked = pv[order] * n / (np.arange(n) + 1)
    q = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(n)
    out[order] = np.minimum(q, 1.0)
    res = pd.Series(np.nan, index=p.index)
    res[mask] = out
    return res


# ------------------------------------------------------- series building --
def company_arrays(panel: pd.DataFrame, ticker: str, signal: str, spec: str):
    """Regular quarterly grid for one company -> (x, y, calendar_quarter labels)."""
    p = panel[panel["ticker"] == ticker].copy()
    p["qidx"] = p["fiscal_year"] * 4 + p["fiscal_quarter"]
    grid = pd.DataFrame({"qidx": np.arange(p["qidx"].min(), p["qidx"].max() + 1)})
    g = grid.merge(p, on="qidx", how="left")
    x = g[f"{signal}_yoy"].to_numpy(dtype=float)
    y = g["rev_yoy"].to_numpy(dtype=float)
    if spec == "d_yoy":
        x = np.r_[np.nan, np.diff(x)]
        y = np.r_[np.nan, np.diff(y)]
    return x, y, g["calendar_quarter"].to_numpy()


def lagged_pairs(x: np.ndarray, y: np.ndarray, k: int):
    """Pairs (x[t-k], y[t]) where both are observed."""
    if k > 0:
        xs, ys = x[:-k], y[k:]
    else:
        xs, ys = x, y
    m = np.isfinite(xs) & np.isfinite(ys)
    return xs[m], ys[m], m, k


# --------------------------------------------------------- per company --
def company_tests(panel: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    lags, B, L = cfg["lags_quarters"], int(cfg["permutations"]), int(cfg["block_length"])
    min_obs = int(cfg["min_obs"])
    specs = [cfg["primary_spec"], *cfg.get("robustness_specs", [])]
    rng = np.random.default_rng(cfg["random_seed"])
    rows = []
    for ticker in sorted(panel["ticker"].unique()):
        for sig in SIGNALS:
            if f"{sig}_yoy" not in panel:
                continue
            for spec in specs:
                x, y, _ = company_arrays(panel, ticker, sig, spec)
                obs = {}
                for k in lags:
                    xs, ys, _, _ = lagged_pairs(x, y, k)
                    r = pearson(xs, ys) if len(xs) >= min_obs else np.nan
                    ne = effective_n(xs, ys) if len(xs) >= min_obs else np.nan
                    obs[k] = (len(xs), r, ne)
                testable = [k for k in lags if np.isfinite(obs[k][1])]
                exceed = {k: 0 for k in lags}
                exceed_max = 0
                if testable:
                    best = max(abs(obs[k][1]) for k in testable)
                    for _ in range(B):
                        xp = block_permute(x, L, rng)
                        rs = {}
                        for k in testable:
                            a, b, _, _ = lagged_pairs(xp, y, k)
                            rs[k] = pearson(a, b) if len(a) >= 3 else 0.0
                            if abs(rs[k]) >= abs(obs[k][1]) - 1e-12:
                                exceed[k] += 1
                        if max(abs(v) for v in rs.values() if np.isfinite(v)) >= best - 1e-12:
                            exceed_max += 1
                for k in lags:
                    n, r, ne = obs[k]
                    lo, hi = fisher_ci(r, ne) if np.isfinite(r) else (np.nan, np.nan)
                    rows.append({
                        "ticker": ticker, "signal": sig, "spec": spec, "lag": k, "n": n,
                        "r": r, "n_eff": ne, "ci_lo": lo, "ci_hi": hi,
                        "p": neff_pvalue(r, ne),
                        "p_perm": (exceed[k] + 1) / (B + 1) if np.isfinite(r) else np.nan,
                        "p_perm_maxlag": (exceed_max + 1) / (B + 1) if testable else np.nan,
                        "status": "ok" if np.isfinite(r) else f"insufficient data (n={n} < {min_obs})",
                    })
    df = pd.DataFrame(rows)
    return _family_adjust(df, ["ticker", "signal", "spec"])


# --------------------------------------------------------------- pooled --
def _demean_np(x: np.ndarray, groups: list[np.ndarray], iters: int) -> np.ndarray:
    """Remove group means (alternating projections for >1 grouping)."""
    x = x.copy()
    for _ in range(iters):
        for g in groups:
            sums = np.bincount(g, weights=x)
            cnt = np.bincount(g)
            x = x - (sums / np.maximum(cnt, 1))[g]
    return x


def pooled_tests(panel: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    lags, B, L = cfg["lags_quarters"], int(cfg["permutations"]), int(cfg["block_length"])
    min_obs = int(cfg["min_obs"])
    specs = [cfg["primary_spec"], *cfg.get("robustness_specs", [])]
    rng = np.random.default_rng(cfg["random_seed"] + 1)
    tickers = sorted(panel["ticker"].unique())
    rows = []
    for sig in SIGNALS:
        if f"{sig}_yoy" not in panel:
            continue
        for spec in specs:
            arrays = {t: company_arrays(panel, t, sig, spec) for t in tickers}
            # For each lag, precompute which (company, t) pairs are observed. Because
            # block_permute keeps NaN positions fixed, these masks hold under the null.
            layout = {}
            for k in lags:
                parts = []
                for ci, (t, (x, y, cq)) in enumerate(arrays.items()):
                    xs = x[:-k] if k > 0 else x
                    ys = y[k:] if k > 0 else y
                    cqs = cq[k:] if k > 0 else cq
                    m = np.isfinite(xs) & np.isfinite(ys)
                    if m.sum() >= 4:
                        parts.append((t, np.flatnonzero(m), ys[m], cqs[m]))
                layout[k] = parts

            def stacked(xmap, k):
                parts = layout[k]
                xs = np.concatenate([xmap[t][idx] for t, idx, _, _ in parts]) if parts else np.array([])
                return xs

            for fe in ("company", "company+time"):
                two_way = fe == "company+time"
                iters = 20 if two_way else 1
                obs, prepared = {}, {}
                for k in lags:
                    parts = layout[k]
                    n = int(sum(len(idx) for _, idx, _, _ in parts))
                    if n < min_obs or len(parts) < 2:
                        obs[k] = (n, len(parts), np.nan, np.nan)
                        continue
                    comp = np.concatenate([np.full(len(idx), i) for i, (_, idx, _, _) in enumerate(parts)])
                    groups = [comp]
                    if two_way:
                        cq_all = np.concatenate([c for _, _, _, c in parts]).astype(str)
                        groups.append(pd.factorize(cq_all)[0])
                    y_all = _demean_np(np.concatenate([y for _, _, y, _ in parts]), groups, iters)
                    x_all = _demean_np(stacked({t: a[0] for t, a in arrays.items()}, k), groups, iters)
                    ne = 0.0
                    for i in range(len(parts)):
                        sel = comp == i
                        ne += effective_n(x_all[sel], y_all[sel])
                    prepared[k] = (groups, y_all)
                    obs[k] = (n, len(parts), pearson(x_all, y_all), ne)
                testable = [k for k in lags if np.isfinite(obs[k][2])]
                exceed = {k: 0 for k in lags}
                exceed_max = 0
                if testable:
                    best = max(abs(obs[k][2]) for k in testable)
                    for _ in range(B):
                        xperm = {t: block_permute(a[0], L, rng) for t, a in arrays.items()}
                        rs = []
                        for k in testable:
                            groups, y_all = prepared[k]
                            xp = _demean_np(stacked(xperm, k), groups, iters)
                            r = pearson(xp, y_all)
                            r = 0.0 if not np.isfinite(r) else r
                            if abs(r) >= abs(obs[k][2]) - 1e-12:
                                exceed[k] += 1
                            rs.append(abs(r))
                        if max(rs) >= best - 1e-12:
                            exceed_max += 1
                for k in lags:
                    n, nc, r, ne = obs[k]
                    lo, hi = fisher_ci(r, ne) if np.isfinite(r) else (np.nan, np.nan)
                    rows.append({
                        "signal": sig, "spec": spec, "fe": fe, "lag": k, "n": n, "n_companies": nc,
                        "r": r, "n_eff": ne, "ci_lo": lo, "ci_hi": hi,
                        "p": neff_pvalue(r, ne),
                        "p_perm": (exceed[k] + 1) / (B + 1) if np.isfinite(r) else np.nan,
                        "p_perm_maxlag": (exceed_max + 1) / (B + 1) if testable else np.nan,
                        "status": "ok" if np.isfinite(r) else f"insufficient data (n={n})",
                    })
    return _family_adjust(pd.DataFrame(rows), ["signal", "spec", "fe"])


def _family_adjust(df: pd.DataFrame, family: list[str]) -> pd.DataFrame:
    """p_any_lag: Bonferroni over the lags tried within a family (no lag picking).
    q_bh: Benjamini-Hochberg across every test of the same spec."""
    if df.empty:
        return df
    df["post_hoc"] = df["signal"].isin(POST_HOC)
    n_tested = df.groupby(family)["p"].transform(lambda s: s.notna().sum())
    df["p_lag_adj"] = np.minimum(1.0, df["p"] * n_tested)
    df["q_bh"] = np.nan
    for _, idx in df.groupby(["spec", "post_hoc"]).groups.items():
        df.loc[idx, "q_bh"] = bh_qvalues(df.loc[idx, "p"])
    return df


def summarize(company: pd.DataFrame, pooled: pd.DataFrame, cfg: dict) -> dict:
    prim = cfg["primary_spec"]
    c = company[(company["spec"] == prim) & company["r"].notna() & ~company["post_hoc"]]
    p = pooled[(pooled["spec"] == prim) & pooled["r"].notna() & ~pooled["post_hoc"]]
    ch = company[(company["spec"] == prim) & company["r"].notna() & company["post_hoc"]]
    return {
        "note": "counts cover pre-registered signals (hn, npm, pypi) only; post-hoc signals listed separately",
        "posthoc_company_tests_run": int(len(ch)),
        "posthoc_company_tests_p_lt_05": int((ch["p"] < 0.05).sum()),
        "primary_spec": prim,
        "company_tests_run": int(len(c)),
        "company_tests_p_lt_05": int((c["p"] < 0.05).sum()),
        "expected_false_positives_at_05": round(0.05 * len(c), 1),
        "company_tests_q_lt_10": int((c["q_bh"] < 0.10).sum()),
        "pooled_tests_run": int(len(p)),
        "pooled_tests_p_lt_05": int((p["p"] < 0.05).sum()),
        "pooled_min_p_lag_adj": float(p["p_lag_adj"].min()) if len(p) else None,
        "untestable_cells": int(company.loc[~company["post_hoc"], "r"].isna().sum()),
    }


def run(panel: pd.DataFrame | None = None, cfg: dict | None = None, write=True):
    cfg = cfg or analysis_settings()
    if panel is None:
        path = PROCESSED / "quarterly_panel.csv"
        if not path.exists():
            log.warning("no quarterly panel yet; skipping lead/lag")
            return None
        panel = pd.read_csv(path)
    company = company_tests(panel, cfg)
    pooled = pooled_tests(panel, cfg)
    summary = summarize(company, pooled, cfg)
    if write:
        company.to_csv(PROCESSED / "leadlag_company.csv", index=False)
        pooled.to_csv(PROCESSED / "leadlag_pooled.csv", index=False)
        (PROCESSED / "leadlag_summary.json").write_text(json.dumps(summary, indent=2))
        from tracker.analysis.findings import write as write_findings
        write_findings(company, pooled, summary)
    log.info("lead/lag summary: %s", summary)
    return company, pooled, summary
