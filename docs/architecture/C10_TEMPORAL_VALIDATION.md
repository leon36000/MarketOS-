# C10 — Temporal Validation and Selection Bias Controls

Validation follows event and knowledge time. Training, calibration, parameter selection and evaluation windows are disjoint according to explicit purge and embargo rules. Overlapping labels, delayed filings, late revisions and future memory/model artifacts are removed from earlier contexts.

Candidate selection reports the full search, not only the winner. Required evidence includes number of trials, parameter-space coverage, correlation among trials, walk-forward paths, holdout uses and discarded results.

Candidate metrics include distribution of outcomes, drawdown and tail behavior, calibration, turnover, implementation cost, capacity and uncertainty. Sharpe-like summaries are adjusted for non-normality, sample length and selection. Probability-of-overfitting and deflated-performance diagnostics are candidates, not automatic acceptance rules.

Robustness tests include alternate start dates, universes, regimes, costs, delays, missing data, source versions and plausible parameter perturbations. A result that depends on one narrow path is classified as fragile.

A hidden final temporal holdout is used once for a promotion decision. Failure returns the candidate to research; the holdout is not converted into another tuning set.
