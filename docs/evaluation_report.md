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

These checks do not validate a regulatory capital model.
