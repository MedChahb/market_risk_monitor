# Market regimes (hidden Markov model)

**Purpose.** Label each day as calm, normal or stress, to analyse the VaR and volatility models by regime ([`notebooks/06_regimes.ipynb`](../../notebooks/06_regimes.ipynb)).

**Data.** At each reporting day since February 2008: the log of the mean 22-day volatility of the CAC 40, Euro Stoxx 50 and S&P 500, their mean 22-day return, the mean pairwise 63-day correlation of their daily returns, and the log of the VIX.

**Method.** Three-state Gaussian HMM with full covariance (best of 10 EM starts), states ordered by mean volatility. Two fits: on the whole history with smoothed probabilities (descriptive, uses later data), and refitted every January from 2012 on past data with standardisation on past statistics and a forward filter (known at each close). A Gaussian mixture on the same features is kept for comparison.

**Validation.** Known episodes, persistence, agreement between the two fits, and the concentration of VaR exceptions by regime.

**Results.** Calm on 39% of days (volatility 12.5%, VIX 15.2), normal on 36% (17.0%, 19.8), stress on 25% (28.1%, 26.7); average spells of 69, 67 and 41 days, against 10 to 17 for the mixture. 83% of 2008 in stress, the 2020 crash from 27 February in both fits, 80% of 2022 in the walk-forward fit. The two fits agree on 79.9% of days on the stress call.

**Limits.** Three states imposed (BIC keeps falling with more states); equity features only; Gaussian emissions; labels relative to the history seen (2015: 54% stress with hindsight, 2% for the walk-forward fit). The yield-curve slope was left out: it produced a steep-curve era rather than a market condition.

**Monitoring.** Regime probabilities at each close on the Market page; QLIKE by regime on the Models page. Not used as a model input.
