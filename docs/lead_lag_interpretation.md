*Written 2026-11-04 on data through the week ending 2026-11-01 (SEC filings through 2026-09). The tables and
charts above regenerate weekly; this paragraph is updated by hand when the picture changes.*

**HN hiring-post share: a clean null.** Pooled correlations are small (between −0.01 and +0.11) at every lag, every
95% CI includes zero, and nothing survives the lag adjustment. Faster growth in how often job posts mention
Snowflake, Datadog, MongoDB, Kafka, Elastic or Cloudflare did not precede faster revenue growth, at least not by
enough to see in 19 to 36 quarters per company.

**npm downloads: a real co-movement, and at most a weak hint of a lead.** With company fixed effects the pooled
correlation is about +0.5 at *every* lag, including lag 0, and flat across lags. A flat profile is the signature of a
shared slow trend: young products start with hyper-growth in both their client library and their revenue, and both
decelerate together. Once that trend is stripped out, what is left is small and not statistically detectable:

- removing anything common to all companies in a quarter (company + quarter fixed effects) shrinks r to +0.19 at lag 0,
  but it *rises* with the lag, to +0.30 and +0.31 at lags 2 and 3, and lags 2 to 4 have p < 0.05 with 95% CIs above
  zero before any correction. That is the shape a lead would have, and at lags 2 and 3 the CIs clear zero in both
  fixed-effect versions. It does not survive the correction for trying five lags (best lag-adjusted p = 0.09), so it
  is a pattern to keep watching, not a finding;
- switching to *acceleration* (change in YoY growth) on both sides removes slow trends, and all 30 pooled cells
  (including the post-hoc ones) then have p > 0.1;
- company by company, r is high (median +0.66) and positive in 25 of 25 cells, but each series has an
  effective sample of only about 3 to 11 independent observations, so none is significant on its own.

**Bottom line:** developer-adoption signals *track* the long arc of these companies' growth. HN hiring share shows no
lead at all. npm downloads show no lead that survives the pre-registered correction, but the stricter specification
leaves a modest lead-shaped pattern (r ≈ +0.3 at two to three quarters) that this sample, five companies with an npm
proxy, is too small to confirm or rule out. So: no detectable lead, not evidence of no lead. The weekly rebuild will
firm the pattern up or erase it. The usual limits apply: small samples, CI and bot noise in downloads. PyPI becomes
testable in late 2027.
