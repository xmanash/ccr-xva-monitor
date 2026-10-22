# CCR-XVA Monitor

## The problem

A risk analyst asks a simple question: if this counterparty defaults, how much could we lose, and what does the collateral agreement change? A chat model will answer in fluent sentences and can invent the figure. That number cannot go into a risk report.

This desk separates the two jobs. QuantLib and a NumPy Monte Carlo simulation compute expected exposure (EE), potential future exposure (PFE), and approximate unilateral CVA, DVA, and a teaching FVA. The language model only chooses which specialist to call and phrases an answer whose numbers already exist in the engine, in SQLite, or in a cited methodology note. A sentence that adds any other number is withheld.

v0.1 prices USD interest rate swaps and USD-settled FX forwards and applies a simple cash collateral agreement (CSA). It does not calculate SA-CCR or IMM capital. Live equity and index levels come from Yahoo Finance and are not used to price the credit book.

## Architecture

A question enters through Streamlit, the FastAPI API, or the local MCP server. A guardrail runs first. `desk_coordinator` delegates to `methodology_agent`, `exposure_agent`, `cva_agent`, `dva_agent`, `fva_agent`, `csa_agent`, `trends_agent`, `xva_agent`, or `memory_agent` when `CCR_GOOGLE_API_KEY` is set. Otherwise the LangGraph router selects the same agent. `market` is reached only by the router. The numeric critic checks the sentence, and an optional rewrite from Groq, Google Gemini, or Ollama may rephrase it only when every number still matches a claim. SQLite stores the calculation. Langfuse receives a copy when `CCR_LANGFUSE_HOST` is set.

```mermaid
flowchart TD
  ask[Question or trade upload] --> edge[Streamlit, FastAPI, or MCP]
  edge --> guard[Input guardrail]
  guard --> adk[desk_coordinator]
  guard --> graph[LangGraph router]
  adk --> named
  graph --> named
  graph --> market
  subgraph named [desk_coordinator sub-agents]
    methodology_agent
    exposure_agent
    cva_agent
    dva_agent
    fva_agent
    csa_agent
    trends_agent
    xva_agent
    memory_agent
  end
  methodology_agent --> notes[BM25 plus Chroma or Pinecone]
  exposure_agent --> quantlib[QuantLib and NumPy Monte Carlo]
  cva_agent --> quantlib
  dva_agent --> quantlib
  fva_agent --> quantlib
  trends_agent --> quantlib
  xva_agent --> quantlib
  csa_agent --> sqlite[(SQLite)]
  memory_agent --> sqlite
  market --> yahoo[Yahoo Finance]
  quantlib --> critic[Numeric critic]
  notes --> critic
  yahoo --> critic
  sqlite --> critic
  critic --> rewrite[Groq, Gemini, or Ollama]
  critic --> sqlite
  sqlite --> langfuse[Langfuse]
```

The agent names and the tool each one may call:

| Agent name | Tool |
| --- | --- |
| `desk_coordinator` | none; it only delegates |
| `methodology_agent` | `search_methodology` |
| `exposure_agent` | `peak_pfe` |
| `cva_agent` | `calculate_cva` |
| `dva_agent` | `calculate_dva` |
| `fva_agent` | `calculate_fva` |
| `csa_agent` | `read_csa` |
| `trends_agent` | `graph_trends` |
| `xva_agent` | `approximate_xva`, `what_if_cva` |
| `memory_agent` | `recall_memory` |
| `market` | Yahoo Finance chart API. Router only; no ADK agent. |

## Tools

These are the products and libraries the running desk uses:

- **QuantLib** prices the interest rate swap checks. **NumPy** runs the Hull-White and FX Monte Carlo paths.
- **LangGraph** is the offline router: `guard_input`, `planner`, `execute`, `critic`, `guard_output`.
- **Google ADK** is the coordinator when a Google key is set. The model is `gemini-2.5-flash`.
- **Groq** (`llama-3.1-8b-instant`), **Google Gemini** (`gemini-2.5-flash`), and **Ollama** (`llama3.1:8b`) only rewrite a finished answer. They do not calculate.
- **rank-bm25** ranks methodology notes. **Chroma** stores a local mirror. **Pinecone** (`llama-text-embed-v2`) embeds those notes when `CCR_PINECONE_API_KEY` is set.
- **SQLite**, through SQLAlchemy, stores counterparties, trades, CSAs, exposures, XVA results, episodes, messages, and traces.
- **Langfuse** receives traces when its host and both keys are set.
- **Yahoo Finance** supplies live equity and index quotes.
- **FastAPI** serves the API. **Streamlit** and **Plotly** are the desk UI.

Cursor can call the same engines through the stdio MCP server `ccr-xva` (`python -m ccr_xva.mcp.server` or the `ccr-mcp` command). Its tools are `list_agents`, `recall_memory`, `search_methodology`, `list_book`, `load_sample_book`, `calculate_exposure`, `calculate_xva`, and `ask_risk`.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
pytest -q
uvicorn ccr_xva.api.main:app --reload
```

The API is `http://localhost:8000/api/v1`. Interactive docs are at `http://localhost:8000/docs`.

In a second terminal:

```bash
streamlit run src/ccr_xva/ui/app.py
```

Docker, with Ollama already running on the host if you want model rewrites:

```bash
docker compose up --build
```

`docker compose --profile obs up` also starts Langfuse. Calculations are stored in SQLite even when Langfuse is down.

Copy `.env.example` to `.env`. Set `CCR_LLM_ENABLED=true` after `ollama pull llama3.1:8b` to allow rewrites. An 8B model is the laptop default. A 70B model is optional and will miss the interactive latency target.

Optional clients:

```bash
pip install -e ".[adk]"
pip install -e ".[pinecone]"
```

Pinecone index settings are `CCR_PINECONE_INDEX`, `CCR_PINECONE_CLOUD`, `CCR_PINECONE_REGION`, `CCR_PINECONE_EMBED_MODEL`, and `CCR_PINECONE_NAMESPACE`.

## What a number means

Expected exposure is the pathwise average of positive collateralized mark-to-market. PFE95 and PFE99 are the matching quantiles. CVA is loss given default times the discounted default-probability bucket sum of expected exposure. DVA uses expected negative exposure and an own-credit probability. FVA is a funding-spread integral. None of these is a regulatory capital number.

Sample trades and CSAs are written by:

```bash
python scripts/seed_data.py
```

## Evaluation

```bash
python scripts/run_eval.py
```

That command writes `data/eval_report.json`. The latest local run passed the short suite and the FX accuracy check. For one EURUSD forward, 8,000 Monte Carlo paths, seed 11, and a one-year horizon, the closed-form GBM positive-exposure formula is **312,342.32 USD**. The Monte Carlo engine on the same trade is **312,322.85 USD**. The relative error is **0.000062** (0.0062 percent). The pass bar is 0.02 (2 percent).

The same report rejects a planted number. The sentence "CVA is 99999.00 USD" is compared with an engine claim of 10.00, and 99999 is recorded as ungrounded, so the critic withholds that draft.

CI runs these deterministic checks, including the QuantLib cross-check. It does not call Groq, Gemini, or Ollama. RAGAS faithfulness is not part of that job. See [docs/evaluation_report.md](docs/evaluation_report.md).

## Layout

- `src/ccr_xva/engines` pricing, collateral, exposure, XVA
- `src/ccr_xva/agents` Google ADK coordinator, LangGraph router, specialist tools, and numeric critic
- `src/ccr_xva/api` FastAPI
- `src/ccr_xva/mcp` MCP tools for Cursor
- `src/ccr_xva/ui` Streamlit
- `src/shared` settings and id helpers
- `data/docs` methodology notes used by retrieval

European options, wrong-way-risk flags, and revaluation surrogates are typed extension points in `src/ccr_xva/engines/extensions.py` and are not implemented.
