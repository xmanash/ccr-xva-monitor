# Exposure and XVA methodology

This note is the retrieval corpus for v0.1. It describes what the engines calculate. It is not a regulatory capital manual.

## Expected exposure

Expected exposure at a future date is the average, across Monte Carlo paths, of the positive netting-set mark-to-market after collateral. Expected positive exposure, also called EPE, is the time average of that expected-exposure curve.

Potential future exposure at the ninety-five percentile is the path quantile of positive exposure. The ninety-nine percentile is stored beside it. Peak PFE in the assistant answers means the maximum of the ninety-five percentile curve.

Effective EPE follows the running maximum of expected exposure and averages that running maximum over the first year. The implementation is a teaching version of the Basel effective-EPE idea, not a certified regulatory calculator.

## Unilateral CVA

The unilateral CVA formula is loss given default times a sum over exposure dates of the discount factor, the marginal default probability, and expected exposure.

Loss given default is one minus the recovery rate. The default recovery assumption is 0.40. A flat one-year default probability is converted to a constant hazard rate. Survival to a date is the exponential of minus hazard times year fraction.

DVA uses the same bucket sum on expected negative exposure and the firm's own default probability. FVA is a teaching approximation: a funding spread times the discounted time integral of expected exposure minus expected negative exposure.

Total XVA reported by the API is CVA minus DVA plus FVA. These numbers are not IMM, not SA-CCR, and not an accounting close-out adjustment.

## CSA parameters

A cash CSA in this version has a threshold, a minimum transfer amount, and an independent amount. Variation margin is the positive part of mark-to-market minus threshold minus independent amount. A call smaller than the minimum transfer amount is skipped. Independent amount is treated as already held. Weekly frequency keeps a collateral balance for seven days between calls.

Raising the threshold cannot reduce uncollateralized positive exposure. The assistant refuses requests to waive collateral or to increase an exposure limit.

## Pricing models

Interest rate swaps are annual fixed versus annual floating on one USD curve. Future values use Hull-White discount bonds and full cashflow revaluation, including a locked floating fixing after a reset date. FX forwards are revalued in closed form on a geometric Brownian spot with deterministic domestic and foreign rates. The domestic value is foreign notional times spot times the foreign discount factor minus strike times the domestic discount factor.

European options, wrong-way-risk scores, and machine-learned revaluation surrogates are extension points and are not calculated in v0.1.

## Limits

Market data are scenario inputs, not a live feed. The book is single-currency USD for discounting. Every number in an answer must match the calculation engine, stored memory, or a cited note. If a draft number fails that check, the assistant withholds it.
