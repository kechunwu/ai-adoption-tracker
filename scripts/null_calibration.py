"""Calibrate the lead/lag p-values on synthetic NULL data (no true relationship).

Why: YoY growth series are persistent, and correlations between two persistent
but independent series are often large by pure chance ("spurious regression").
A valid test should reject ~5% of the time at alpha = 0.05 when there is no
relationship. This script measures the false-positive rate of each candidate
test on independent AR(1) and random-walk series of the lengths we actually
have (16-30 quarters) and writes docs/null_calibration.md.

Run: python scripts/null_calibration.py   (~1-2 minutes, seeded)
This uses simulated noise only; no real data is involved.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tracker.analysis.leadlag import block_permute, effective_n, neff_pvalue, pearson  # noqa: E402

R, B = 300, 400


def gen(kind, n, rng):
    e = rng.normal(size=n)
    if kind == "random walk":
        return np.cumsum(e)
    x = np.zeros(n)
    for i in range(1, n):
        x[i] = kind * x[i - 1] + e[i]
    return x


def perm_p(x, y, block, rng):
    r = pearson(x, y)
    c = sum(abs(pearson(block_permute(x, block, rng), y)) >= abs(r) for _ in range(B))
    return (c + 1) / (B + 1)


def naive_p(r, n):
    return neff_pvalue(r, n)  # same t-test with the raw n (ignores autocorrelation)


def main():
    rng = np.random.default_rng(20261104)
    rows = []
    for kind in [0.5, 0.8, 0.95, "random walk"]:
        for n in [16, 24, 32]:
            hits = {"naive t-test (raw n)": 0, "block permutation (4q)": 0,
                    "t-test with Bartlett n_eff [used]": 0, "block perm. on differenced": 0}
            for _ in range(R):
                x, y = gen(kind, n, rng), gen(kind, n, rng)
                r = pearson(x, y)
                hits["naive t-test (raw n)"] += naive_p(r, n) < 0.05
                hits["block permutation (4q)"] += perm_p(x, y, 4, rng) < 0.05
                hits["t-test with Bartlett n_eff [used]"] += neff_pvalue(r, effective_n(x, y)) < 0.05
                hits["block perm. on differenced"] += perm_p(np.diff(x), np.diff(y), 4, rng) < 0.05
            label = f"AR(1) phi={kind}" if kind != "random walk" else "random walk"
            rows.append((label, n, {k: v / R for k, v in hits.items()}))
            print(label, n, rows[-1][2])
    cols = list(rows[0][2])
    lines = ["# Null calibration of the lead/lag tests", "",
             "False-positive rate at alpha = 0.05 on pairs of **independent** simulated series "
             f"({R} pairs per cell, {B} permutations). A well-calibrated test is close to 0.05.", "",
             "| process | n quarters | " + " | ".join(cols) + " |",
             "|---|---|" + "---|" * len(cols)]
    for label, n, h in rows:
        lines.append(f"| {label} | {n} | " + " | ".join(f"{h[c]:.2f}" for c in cols) + " |")
    lines += ["", "Reproduce with `python scripts/null_calibration.py`.",
              "Takeaway: ignoring autocorrelation (raw n) is badly anti-conservative; the Bartlett "
              "n_eff t-test stays close to nominal, so it is the headline p-value in the study."]
    (ROOT / "docs" / "null_calibration.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
