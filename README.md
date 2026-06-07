# InvestPilot

A deep fundamental investment research harness built on Claude Code. Seeks significantly undervalued stocks (high reward-to-risk + high probability), with the core thesis of identifying expectation gaps that materialize within 0–3 months.

## Features

- **Quick Triage Gate + 9-Step Deep Research Pipeline** — PASS / WATCH / FULL_RESEARCH screening before full research
- **Sequential Workflow Guard** — State machine enforces step-by-step progression with dependency checks, blocking, and artifact tracking
- **Formula-Linked Financial Forecast Model** — Three-statement model (income, cash flow, balance sheet) with segment-level revenue build, valuation bridge, and built-in consistency checks
- **Step 4 Structured Assumptions + Validation** — Pre-flight 15-check validator with guard state, retry limits, and blocker escalation before Monte Carlo simulation
- **Probabilistic Simulation** — t-Copula dependency structure + Kelly criterion position sizing + assumption consistency verification
- **Forward PE Band** — Point-in-time vs constant-EPS proxy distinction with 5-year historical percentile bands
- **Multi-Market Support** — A-share, Hong Kong, US stocks (data source: Tushare Pro)
- **Expectation Gap Driven** — 4-dimension Edge classification scoring + catalyst time-decay tracking
- **Knowledge Graph** — Cross-stock research experience accumulation and pattern matching
- **PDF Read Failure Guard** — Material coverage validation with web fallback; rejects news/summaries as annual report substitutes
- **Self-Contained HTML Reports** — Inline CSS + base64-embedded charts with collapsible step navigation and metric cards
- **Web Dashboard** — TypeScript (Hono) server with real-time workspace status, file upload, step content retrieval, and Bearer token auth

## Installation

```bash
# Requires Python 3.9+
pip install -e ".[dev]"

# Web dashboard (TypeScript)
cd web && npm install
```

Or install dependencies manually:

```bash
pip install tushare pandas numpy scipy matplotlib requests tabulate pytest
```

## Configuration

Set your Tushare Pro API token:

```bash
export TUSHARE_TOKEN="your_token_here"
```

Register at [tushare.pro](https://tushare.pro) to get a token.

## Quick Start

### 1. Create a Workspace

```bash
mkdir -p workspaces/AAPL
# Place annual report PDFs and broker research into this directory
```

### 2. Fetch Data

```bash
# Detect market
python -m src.cli detect AAPL
# → {"market": "US", "normalized": "AAPL"}

# Fetch data into workspace
python -m src.cli fetch AAPL -o workspaces/AAPL
```

### 3. Launch Research

Enter a stock ticker in Claude Code to trigger Quick Triage before the 9-step analysis pipeline:

```
> Research AAPL
```

Quick Triage writes `workspaces/AAPL/step0_quick_triage.md` and returns one of:

- `PASS`: stop unless explicitly overridden
- `WATCH`: monitor defined triggers before full research
- `FULL_RESEARCH`: continue Business Analysis → Competitive Moat → Marginal Changes → Assumption Research → Financial Model Build → Monte Carlo Simulation → RRR & Trading Strategy → Auditing → Research Director Review

See [CLAUDE.md](CLAUDE.md) for the full workflow details.

For the contract-driven rewrite roadmap, see [docs/architecture_rewrite_plan.md](docs/architecture_rewrite_plan.md).

### 4. Start the Web Dashboard

```bash
cd web
npm start            # Production: http://localhost:8080
npm run dev          # Dev mode with auto-reload

# With authentication
INVESTPILOT_TOKEN="your_token" npm start

# Custom port
npm start -- 3000
```

## CLI Commands

| Command | Description |
|:--------|:------------|
| `detect <ticker>` | Detect stock market (A-share / HK / US) |
| `fetch <ticker>` | Fetch data into workspace |
| `fetch-peers <ticker>` | Fetch peer company data |
| `analyze <ticker>` | Technical analysis (MA / RSI / MACD) |
| `workflow <workspace> <action>` | Manage sequential research workflow state for steps 0–9 |
| `validate-step4 <workspace>` | Run Step 4 assumption validation with guard state |
| `validate-materials <workspace>` | Verify material coverage (annual report + MD&A extraction) |
| `model <workspace>` | Generate formula-linked financial forecast model (JSON + HTML) |
| `thesis <action>` | Manage investment thesis lifecycle |
| `catalyst <action>` | Track catalysts with time decay |
| `consensus <action>` | Track market consensus, revisions, and expectation gaps |
| `materials <action>` | Track structured extraction from annual reports and broker PDFs |
| `knowledge <action>` | Knowledge graph operations |
| `report <workspace>` | Generate HTML research report |

## Project Structure

```
investpilot/
├── CLAUDE.md              # Master prompt (9-step workflow definition)
├── config/                # Configuration (market rules, thresholds, weights)
├── prompts/               # 9-step prompt templates (00–09)
├── web/                   # TypeScript web layer (Hono)
│   ├── src/
│   │   ├── index.ts       # Entry point — Hono app + @hono/node-server
│   │   ├── config.ts      # Constants, env vars, step definitions
│   │   ├── routes/        # API route handlers
│   │   ├── middleware/    # Auth, CORS, upload limit
│   │   └── services/     # Workspace status, multipart parsing
│   ├── public/
│   │   └── index.html     # Dashboard SPA
│   ├── tests/             # Vitest test suite
│   └── package.json
├── src/
│   ├── cli.py             # CLI entry point
│   ├── storage.py         # Atomic JSON storage (crash-safe)
│   ├── analysis/          # Analysis engine
│   │   ├── financial.py   # Financial analysis (PE/PB/PS/EV, earnings quality)
│   │   ├── monte_carlo.py # Probabilistic simulation + Kelly criterion
│   │   ├── valuation.py   # DCF / Reverse DCF / Forward PE Band
│   │   ├── step4_validate.py  # Step 4 assumption validator and guard
│   │   ├── step4_schema.py    # Step 4 structured assumption schema + persistence
│   │   ├── financial_model.py # Formula-linked three-statement forecast model
│   │   ├── research_workflow.py # Sequential workflow state machine
│   │   ├── thesis_tracker.py  # Thesis lifecycle management
│   │   ├── catalyst_tracker.py # Catalyst tracking + time decay
│   │   ├── consensus_tracker.py # Structured consensus + expectation gap tracking
│   │   ├── material_tracker.py  # Structured extraction from reports/PDFs
│   │   ├── edge_scorer.py     # 4-dimension Edge scoring
│   │   └── knowledge_graph.py # Cross-stock knowledge graph
│   ├── data/              # Data fetching layer
│   │   ├── ashare_fetcher.py  # A-share (Tushare)
│   │   ├── hk_fetcher.py      # Hong Kong (Tushare)
│   │   ├── us_fetcher.py      # US (Tushare)
│   │   └── tushare_client.py  # Unified Tushare API client
│   └── report/            # Report generation (HTML + Markdown)
├── tests/                 # Python test suite
└── workspaces/            # Per-stock research data and outputs
```

## Running Tests

```bash
# Python tests (analysis engine, CLI, data fetchers)
python -m pytest tests/ -v

# TypeScript tests (web layer)
cd web && npm test
```

## Market Rules

| Market | Report Language | Ticker Format | Examples |
|:-------|:----------------|:--------------|:---------|
| A-share | Chinese | `600xxx.SS` / `000xxx.SZ` | `600519`, `000001.SZ` |
| Hong Kong | Chinese | `xxxx.HK` | `0700.HK`, `9988.HK` |
| US | English | `XXXX` | `AAPL`, `TSLA` |

## License

Private — for personal research use only.
