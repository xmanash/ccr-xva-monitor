# Evaluation report

v0.1 targets for the checks this repository can run locally:

- FX-forward expected exposure within 2% of the GBM positive-exposure formula
- Zero-volatility IRS and FX expected exposure within 1% of deterministic full revaluation, and in practice a much tighter tolerance in the unit tests
- Par IRS value near zero, and off-market IRS value aligned with QuantLib
- Hull-White zero bond aligned with QuantLib
- CVA is zero when the one-year default probability is zero, and it scales with loss given default
- A higher collateral threshold does not reduce positive exposure on the same mark-to-market
- Answers either refuse or contain only numbers present in engine, memory, or retrieved notes
- A methodology question retrieves the unilateral CVA note
- The desk roster contains methodology, exposure, XVA, memory, and the coordinator, and every router path has an owner

RAGAS faithfulness is not run in GitHub Actions because that job would need a local or hosted model. `scripts/run_eval.py` writes `data/eval_report.json` with the short suite and an 8,000-path FX comparison. Run it on a laptop before quoting a latency or faithfulness number.

## Handoff failures

The fixed set in `src/ccr_xva/evals/failures.py` scores eight questions. Three definitional notes used to miss methodology: a collateral-threshold question and a recovery-rate definition went to what-if, and a formula comparison went to compare. Five controls stay put: a formula that already reached methodology, the current peak PFE for ABC Bank, two explicit shocks, and a snapshot recall.

The committed baseline in `src/ccr_xva/evals/baseline.json` is 3 misroutes and handoff accuracy 0.625. After definitions are routed to methodology before the what-if and compare branches, the same eight questions score 0 misroutes and handoff accuracy 1.0. `POST /api/v1/eval/run` returns that score as `failure_set`. The short suite `passed` flag is unchanged.

Two items stay open and are not a pass: one false policy refusal, because the output guard sees "waive collateral" inside a correct methodology note, and one resimulated snapshot drift, because a new exposure draw does not reuse the stored seed and path count. An ungrounded number is still withheld by the existing planted `99999` check.

These checks do not validate a regulatory capital model.
