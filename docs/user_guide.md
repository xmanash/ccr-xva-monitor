# User guide

## Load a book

Upload a CSV to `POST /api/v1/trades/upload` or use the Upload page. Required columns are `trade_id`, `counterparty_id`, `product_type`, `notional`, `currency`, `start_date`, `maturity`, `direction`, and `netting_set_id`. Optional columns include `fixed_rate`, `strike`, `underlying`, `counterparty_name`, `pd`, and `recovery_rate`.

`product_type` is `IRS` or `FX_Forward`. FX notionals are foreign-currency units. `underlying` is a pair such as `EURUSD`, and `currency` stays `USD`. `strike` is USD per foreign unit. `Buy` means buy the foreign currency.

Create a CSA with structured JSON or a sentence such as `daily cash collateral, 0 threshold, 10% MTA`. A percent minimum transfer amount is converted with the notional you pass in, or with the stored gross notional when you save the CSA through the service.

## Calculate

`POST /api/v1/calculate/exposure` and `POST /api/v1/calculate/xva` take a netting set id and an optional market scenario (`as_of`, `usd_rate`, `n_paths`, `hw_sigma`, FX spots and vols). The response includes `calculation_id`. Fetch the trace with `GET /api/v1/traces/{calculation_id}`.

What-if threshold and recovery overrides are on the XVA request and in chat, for example: what happens to CVA if we increase the collateral threshold by $5m or change the recovery rate to 40%.

## Ask

`POST /api/v1/query` returns an answer, citations, numeric claims, a calculation id, and a Plotly chart when the question is about exposure. If the assistant cannot ground a number, it withholds the draft. Requests to raise limits, waive collateral, or hide a breach are refused.

Set `CCR_LLM_ENABLED=true` to let Ollama or Groq rewrite the wording. The rewrite is kept only when it still matches the same claims. With the flag off, the answer is the grounded template.
