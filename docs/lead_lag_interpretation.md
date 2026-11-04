*Written 2026-11-04 on data through the week ending 2026-11-01 (SEC filings through 2026-09). The tables and
charts above regenerate weekly; this paragraph is updated by hand when the picture changes.*

**HN hiring-post share: a clean null.** Pooled correlations are small (between −0.01 and +0.11) at every lag, every
95% CI includes zero, and nothing survives the lag adjustment. Faster growth in how often job posts mention
Snowflake, Datadog, MongoDB, Kafka, Elastic or Cloudflare did not precede faster revenue growth, at least not by
enough to see in 19 to 36 quarters per company.

**npm downloads: a real co-movement, but not a lead.** With company fixed effects the pooled correlation is about
+0.5 at *every* lag, including lag 0, and it is flat across lags. A genuine leading indicator would peak at some
k ≥ 1. A flat profile is the signature of a shared slow trend: young products start with hyper-growth in both
their client library and their revenue, and both decelerate together. Three checks point the same way:

- removing anything common to all companies in a quarter (company + quarter fixed effects) shrinks r to
  +0.19 to +0.31, and no cell survives the lag adjustment (best lag-adjusted p = 0.09);
- switching to *acceleration* (change in YoY growth) on both sides removes slow trends, and all 30 pooled cells
  (including the post-hoc ones) then have p > 0.1;
- company by company, r is high (median +0.66) and positive in 25 of 25 cells, but each series has an
  effective sample of only about 3 to 11 independent observations, so none is significant on its own.

**Bottom line:** developer-adoption signals *track* the long arc of these companies' growth, but in this data they
do not *lead* revenue by a detectable margin, and they add nothing once the shared growth-decay trend is removed.
That is a useful negative result for anyone tempted to trade on download charts. It is also limited by small
samples, CI and bot noise in downloads, and only five public companies with an npm proxy. PyPI becomes testable
in late 2027.
