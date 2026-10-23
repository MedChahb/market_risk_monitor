# Market regimes (hidden Markov model)

**Purpose.** Label each day as calm, normal or stress, to analyse the VaR and volatility models by regime ([`notebooks/06_regimes.ipynb`](../../notebooks/06_regimes.ipynb)).

**Data.** At each reporting day since February 2008: the log of the mean 22-day volatility of the CAC 40, Euro Stoxx 50 and S&P 500, their mean 22-day return, the mean pairwise 63-day correlation of their daily returns, and the log of the VIX.

**Method.** Three-state Gaussian HMM with full covariance, states ordered by mean volatility. EM starts from k-means means and a transition matrix with 0.95 on its diagonal: random starts gave different labellings, and the best of ten changed when one day of data was added. Two fits: on the whole history with smoothed probabilities (descriptive, uses later data), and refitted every January from 2012 on past data with standardisation on past statistics and a forward filter (known at each close). A Gaussian mixture on the same features is kept for comparison.

**Validation.** Known episodes, persistence, agreement between the two fits, and the concentration of VaR exceptions by regime.

**Results.** Calm on 42% of days (volatility 11.5%, VIX 14.6), normal on 40% (19.0%, 20.1), stress on 18% (31.3%, 31.2); average spells of 81, 57 and 41 days, against 10 to 17 for the mixture. 78% of 2008 in stress, the 2020 crash from 27 February (28 February in the walk-forward fit), 73% of 2022 in the walk-forward fit. Since 2012 the two fits make the same stress call on 85.3% of days. Adding a day of data leaves 99.96% of the full-history labels unchanged.

**Limits.** Three states imposed (BIC keeps falling with more states); the fixed start does not reach the highest likelihood found (over fifty random starts, a fit whose stress state isolates crisis peaks); equity features only; Gaussian emissions. The walk-forward stress state is less distinct (20.4% mean volatility against 18.5% on normal days) and holds long spells of low equity correlation (59% of 2021 and 51% of 2024 in stress, against none and 5% with hindsight). The yield-curve slope was left out: it produced a steep-curve era rather than a market condition.

**Monitoring.** Regime probabilities at each close on the Market page; QLIKE by regime on the Models page. Not used as a model input.
