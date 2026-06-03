# InvestPilot

A deep fundamental investment research harness built on Claude Code. Seeks significantly undervalued stocks (high reward-to-risk + high probability), with the core thesis of identifying expectation gaps that materialize within 0–3 months.

## Features

- **Quick Triage Gate + 7-Step Deep Research Pipeline** — PASS / WATCH / FULL_RESEARCH screening before full research
- **Monte Carlo Simulation** — t-Copula dependency structure + Kelly criterion position sizing
- **Multi-Market Support** — A-share, Hong Kong, US stocks (data source: Tushare Pro)
- **Expectation Gap Driven** — 4-dimension Edge classification scoring + catalyst time-decay tracking
- **Knowledge Graph** — Cross-stock research experience accumulation and pattern matching
- **Self-Contained HTML Reports** — Inline CSS + base64-embedded charts

## Installation

```bash
# Requires Python 3.9+
pip install -e ".[dev]"
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

Enter a stock ticker in Claude Code to trigger Quick Triage before the 7-step analysis pipeline:

```
> Research AAPL
```

Quick Triage writes `workspaces/AAPL/step0_quick_triage.md` and returns one of:

- `PASS`: stop unless explicitly overridden
- `WATCH`: monitor defined triggers before full research
- `FULL_RESEARCH`: continue Business Analysis → Competitive Moat → Marginal Changes → Quantitative Modeling → Trading Strategy → Auditing → Research Director Review

See [CLAUDE.md](CLAUDE.md) for the full workflow details.

## CLI Commands

| Command | Description |
|:--------|:------------|
| `detect <ticker>` | Detect stock market (A-share / HK / US) |
| `fetch <ticker>` | Fetch data into workspace |
| `fetch-peers <ticker>` | Fetch peer company data |
| `analyze <ticker>` | Technical analysis (MA / RSI / MACD) |
| `thesis <action>` | Manage investment thesis lifecycle |
| `catalyst <action>` | Track catalysts with time decay |
| `consensus <action>` | Track market consensus, revisions, and expectation gaps |
| `materials <action>` | Track structured extraction from annual reports and broker PDFs |
| `knowledge <action>` | Knowledge graph operations |
| `report <workspace>` | Generate HTML research report |

## Project Structure

```
investpilot/
├── CLAUDE.md              # Master prompt (7-step workflow definition)
├── config/                # Configuration (market rules, thresholds, weights)
├── prompts/               # 7-step prompt templates
├── src/
│   ├── cli.py             # CLI entry point
│   ├── storage.py         # Atomic JSON storage (crash-safe)
│   ├── analysis/          # Analysis engine
│   │   ├── financial.py   # Financial analysis (PE/PB/PS/EV, earnings quality)
│   │   ├── monte_carlo.py # Monte Carlo simulation + Kelly criterion
│   │   ├── valuation.py   # DCF / Reverse DCF / Forward PE Band
│   │   ├── step4_validate.py  # Step 4 pre-flight validator (15 checks)
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
├── tests/                 # Test suite (172 tests)
└── workspaces/            # Per-stock research data and outputs
```

## Running Tests

```bash
python -m pytest tests/ -v
```

## Market Rules

| Market | Report Language | Ticker Format | Examples |
|:-------|:----------------|:--------------|:---------|
| A-share | Chinese | `600xxx.SS` / `000xxx.SZ` | `600519`, `000001.SZ` |
| Hong Kong | Chinese | `xxxx.HK` | `0700.HK`, `9988.HK` |
| US | English | `XXXX` | `AAPL`, `TSLA` |

## License

Private — for personal research use only.
