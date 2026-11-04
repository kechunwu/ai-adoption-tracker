# Null calibration of the lead/lag tests

False-positive rate at alpha = 0.05 on pairs of **independent** simulated series (300 pairs per cell, 400 permutations). A well-calibrated test is close to 0.05.

| process | n quarters | naive t-test (raw n) | block permutation (4q) | t-test with Bartlett n_eff [used] | block perm. on differenced |
|---|---|---|---|---|---|
| AR(1) phi=0.5 | 16 | 0.10 | 0.04 | 0.05 | 0.03 |
| AR(1) phi=0.5 | 24 | 0.10 | 0.06 | 0.04 | 0.06 |
| AR(1) phi=0.5 | 32 | 0.16 | 0.07 | 0.06 | 0.06 |
| AR(1) phi=0.8 | 16 | 0.21 | 0.05 | 0.05 | 0.04 |
| AR(1) phi=0.8 | 24 | 0.21 | 0.08 | 0.04 | 0.05 |
| AR(1) phi=0.8 | 32 | 0.31 | 0.12 | 0.05 | 0.05 |
| AR(1) phi=0.95 | 16 | 0.30 | 0.04 | 0.01 | 0.02 |
| AR(1) phi=0.95 | 24 | 0.45 | 0.16 | 0.03 | 0.07 |
| AR(1) phi=0.95 | 32 | 0.46 | 0.16 | 0.04 | 0.05 |
| random walk | 16 | 0.41 | 0.09 | 0.02 | 0.02 |
| random walk | 24 | 0.56 | 0.25 | 0.03 | 0.06 |
| random walk | 32 | 0.58 | 0.27 | 0.02 | 0.06 |

Reproduce with `python scripts/null_calibration.py`.
Takeaway: ignoring autocorrelation (raw n) is badly anti-conservative; the Bartlett n_eff t-test stays close to nominal, so it is the headline p-value in the study.
