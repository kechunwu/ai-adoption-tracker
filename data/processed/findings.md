**Pre-registered verdicts (pooled, primary spec = YoY growth):**

- **HN hiring-post share: NULL**. no cell reaches p < 0.05; strongest cell: lag 1q, company FE, r = +0.11 [-0.05, +0.27], p = 0.172, lag-adjusted p = 0.862, n = 163 quarter-obs across 6 companies.
- **npm downloads: MIXED/WEAK**. some cells have p < 0.05 but none survive lag adjustment under both FE variants; strongest cell: lag 0q, company FE, r = +0.51 [+0.18, +0.73], p = 0.004, lag-adjusted p = 0.021, n = 144 quarter-obs across 5 companies.
- **PyPI downloads: UNTESTABLE**. not enough overlapping quarters yet.
- **npm downloads vs registry baseline (post-hoc): MIXED/WEAK**. some cells have p < 0.05 but none survive lag adjustment under both FE variants; strongest cell: lag 0q, company FE, r = +0.43 [+0.11, +0.66], p = 0.010, lag-adjusted p = 0.051, n = 144 quarter-obs across 5 companies.
- **PyPI downloads vs registry baseline (post-hoc): UNTESTABLE**. not enough overlapping quarters yet.

Company-level: 0 of 55 tests have p < 0.05 (≈2.8 expected by chance); 0 survive Benjamini-Hochberg at q < 0.10.
Share of company-level correlations that are positive: 88% (50% expected under no relationship).

_Verdict rules were fixed in code before data was pulled (tracker/analysis/findings.py)._
