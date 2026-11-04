import numpy as np
import pandas as pd

from tracker.analysis.leadlag import bh_qvalues, block_permute, company_tests, pooled_tests

CFG = {"lags_quarters": [0, 1, 2, 3, 4], "permutations": 300, "block_length": 4, "min_obs": 8,
       "primary_spec": "yoy", "robustness_specs": ["d_yoy"], "random_seed": 1}


def synthetic_panel(lead=2, noise=0.0, n=32, tickers=("AAA", "BBB", "CCC"), seed=0):
    """Method test only: revenue YoY = signal YoY shifted by `lead` quarters (+ noise)."""
    rng = np.random.default_rng(seed)
    rows = []
    for t in tickers:
        sig = np.cumsum(rng.normal(0, 0.1, n + lead))  # persistent, autocorrelated
        rev = sig[:n] + noise * rng.normal(0, 1, n)
        for i in range(n):
            fy, fq = 2016 + i // 4, i % 4 + 1
            rows.append({"ticker": t, "fiscal_year": fy, "fiscal_quarter": fq,
                         "calendar_quarter": f"{fy}Q{fq}",
                         "rev_yoy": rev[i], "hn_yoy": sig[i + lead], "npm_yoy": np.nan, "pypi_yoy": np.nan})
    # signal at t-lead must match revenue at t -> shift signal series so that x[t-lead] == rev[t]
    p = pd.DataFrame(rows)
    out = []
    for t, g in p.groupby("ticker"):
        g = g.copy()
        g["hn_yoy"] = g["rev_yoy"].shift(-lead) + noise * rng.normal(0, 0.05, len(g))
        out.append(g)
    return pd.concat(out)


def test_detects_planted_lead():
    res = company_tests(synthetic_panel(lead=2, noise=0.1), CFG)
    r = res[(res.signal == "hn") & (res.spec == "yoy") & (res.ticker == "AAA")].set_index("lag")
    assert r.loc[2, "r"] > 0.9
    assert r["r"].abs().idxmax() == 2
    assert r.loc[2, "ci_lo"] < r.loc[2, "r"] < r.loc[2, "ci_hi"]
    # signals with no data are reported as untestable, not dropped
    npm = res[(res.signal == "npm")]
    assert npm["r"].isna().all() and npm["status"].str.contains("insufficient").all()


def test_pooled_runs_and_finds_lead():
    pooled = pooled_tests(synthetic_panel(lead=1, noise=0.1), CFG)
    r = pooled[(pooled.signal == "hn") & (pooled.spec == "yoy") & (pooled.fe == "company")].set_index("lag")
    assert r["r"].idxmax() == 1 and r.loc[1, "p"] < 0.05 and r.loc[1, "p_lag_adj"] <= 1
    assert set(pooled["fe"]) == {"company", "company+time"}


def test_null_is_not_systematically_significant():
    rng = np.random.default_rng(7)
    rows = []
    for t in ("A", "B", "C", "D"):
        x = np.cumsum(rng.normal(0, .1, 30)); y = np.cumsum(rng.normal(0, .1, 30))
        for i in range(30):
            rows.append({"ticker": t, "fiscal_year": 2016 + i // 4, "fiscal_quarter": i % 4 + 1,
                         "calendar_quarter": f"{2016 + i // 4}Q{i % 4 + 1}", "rev_yoy": y[i], "hn_yoy": x[i],
                         "npm_yoy": np.nan, "pypi_yoy": np.nan})
    res = company_tests(pd.DataFrame(rows), CFG)
    ok = res[(res.spec == "yoy") & res.r.notna()]
    # independent random walks often show big |r| by chance; the autocorrelation-aware
    # p-values should not flag most of them
    assert (ok["p"] < 0.05).mean() < 0.25


def test_block_permute_keeps_nan_positions():
    x = np.array([np.nan, np.nan, 1, 2, 3, 4, 5, 6, 7, np.nan])
    y = block_permute(x, 4, np.random.default_rng(0))
    assert np.array_equal(np.isnan(x), np.isnan(y))
    assert sorted(y[~np.isnan(y)]) == [1, 2, 3, 4, 5, 6, 7]


def test_bh():
    q = bh_qvalues(pd.Series([0.01, 0.04, 0.03, np.nan, 0.5]))
    assert np.isnan(q[3])
    assert q[0] == 0.04 and abs(q[1] - 0.04 * 1) < 1e-9 or q[1] <= 0.0534
    assert (q.dropna() <= 1).all()
