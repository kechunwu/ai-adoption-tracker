"""Template the headline findings from the result tables (no hand-written claims).

The wording is mechanical: it reports every pooled test for the primary spec
and classifies the overall result with rules fixed in advance:
  * "supported"      -> a pooled test with lag >= 1 has p_lag_adj < 0.05 under BOTH
                         fixed-effects variants, with a positive r
  * "mixed/weak"     -> some test has p < 0.05 but the above bar isn't met
  * "null"           -> nothing reaches p < 0.05
"""
from __future__ import annotations

import json

import pandas as pd

from tracker.config import PROCESSED

SIG = {"hn": "HN hiring-post share", "npm": "npm downloads", "pypi": "PyPI downloads",
       "npm_rel": "npm downloads vs registry baseline (post-hoc)",
       "pypi_rel": "PyPI downloads vs registry baseline (post-hoc)"}


def classify(pooled: pd.DataFrame, sig: str, spec: str = "yoy") -> tuple[str, str]:
    p = pooled[(pooled["signal"] == sig) & (pooled["spec"] == spec) & pooled["r"].notna()]
    if p.empty:
        return "untestable", "not enough overlapping quarters yet"
    strong = []
    for k in range(1, 5):
        rows = p[p["lag"] == k]
        if len(rows) == 2 and (rows["p_lag_adj"] < 0.05).all() and (rows["r"] > 0).all():
            strong.append(k)
    best = p.loc[p["p"].idxmin()]
    desc = (f"strongest cell: lag {int(best['lag'])}q, {best['fe']} FE, r = {best['r']:+.2f} "
            f"[{best['ci_lo']:+.2f}, {best['ci_hi']:+.2f}], p = {best['p']:.3f}, lag-adjusted p = {best['p_lag_adj']:.3f}, "
            f"n = {int(best['n'])} quarter-obs across {int(best['n_companies'])} companies")
    if strong:
        return "supported", f"positive lead at lag(s) {strong} survives lag adjustment under both FE variants; {desc}"
    if (p["p"] < 0.05).any():
        return "mixed/weak", f"some cells have p < 0.05 but none survive lag adjustment under both FE variants; {desc}"
    return "null", f"no cell reaches p < 0.05; {desc}"


def write(company: pd.DataFrame, pooled: pd.DataFrame, summary: dict) -> str:
    lines = ["**Pre-registered verdicts (pooled, primary spec = YoY growth):**", ""]
    verdicts = {}
    for sig in SIG:
        v, d = classify(pooled, sig)
        verdicts[sig] = v
        lines.append(f"- **{SIG[sig]}: {v.upper()}**. {d}.")
    c = company[(company["spec"] == "yoy") & company["r"].notna()]
    lines += ["", f"Company-level: {summary.get('company_tests_p_lt_05', 0)} of {summary.get('company_tests_run', 0)} "
              f"tests have p < 0.05 (≈{summary.get('expected_false_positives_at_05', 0)} expected by chance); "
              f"{summary.get('company_tests_q_lt_10', 0)} survive Benjamini-Hochberg at q < 0.10."]
    if not c.empty:
        frac_pos = (c["r"] > 0).mean()
        lines.append(f"Share of company-level correlations that are positive: {frac_pos:.0%} (50% expected under no relationship).")
    lines += ["", "_Verdict rules were fixed in code before data was pulled (tracker/analysis/findings.py)._"]
    text = "\n".join(lines) + "\n"
    (PROCESSED / "findings.md").write_text(text)
    (PROCESSED / "verdicts.json").write_text(json.dumps(verdicts, indent=2))
    return text
