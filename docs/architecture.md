# InvestPilot Architecture

## Component Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                          InvestPilot                            │
├──────────────────────┬───────────────────────────────────────────┤
│  Python Backend      │  TypeScript Web Layer                    │
│                      │                                          │
│  src/cli.py          │  web/src/index.ts  (Hono server)         │
│  ├─ detect           │  ├─ GET  /api/workspaces                 │
│  ├─ fetch            │  ├─ GET  /api/workspaces/:ticker         │
│  ├─ workflow         │  ├─ POST /api/upload                     │
│  ├─ report           │  ├─ GET  /api/step/:ticker/:step         │
│  ├─ thesis           │  └─ Static file serving                  │
│  ├─ catalyst         │                                          │
│  └─ ...              │  web/public/  (HTML dashboard)           │
│                      │                                          │
│  src/data/           │  web/src/middleware/auth.ts               │
│  ├─ ashare_fetcher   │  web/src/services/workspace.ts           │
│  ├─ hk_fetcher       │  web/src/config.ts                       │
│  └─ us_fetcher       │                                          │
│                      │                                          │
│  src/analysis/       │  Tests: vitest                           │
│  ├─ financial_model  │                                          │
│  ├─ monte_carlo      ├───────────────────────────────────────────┤
│  ├─ valuation        │  Config                                  │
│  └─ edge_scorer      │                                          │
│                      │  config/settings.py   (env vars)         │
│  src/report/         │  config/step_contracts.json              │
│  └─ html templates   │  config/ticker_rules.py                  │
│                      │  .env                                  │
│  Tests: pytest       │                                          │
└──────────────────────┴───────────────────────────────────────────┘
         │                          │
         ▼                          ▼
┌──────────────────┐   ┌───────────────────────────┐
│  Data Sources    │   │  Workspace Storage         │
│                  │   │                             │
│  Tushare Pro API │   │  workspaces/{TICKER}/       │
│  AKShare (free)  │   │  ├─ *.pdf  (annual reports) │
│  SEC EDGAR       │   │  ├─ stepN_*.md (analysis)  │
│  WebSearch       │   │  ├─ forecast_model.json     │
│                  │   │  └─ *.html (reports)        │
└──────────────────┘   └───────────────────────────┘
```

## 9-Step Research Pipeline

InvestPilot runs a strict sequential research pipeline. Each step produces an artifact and must pass a workflow guard before the next step starts.

```
Step 0: Quick Triage ──── PASS/WATCH/FULL_RESEARCH
        │                      │           │
        │                      │           ▼
        │                   (stop)    Step 1: Business Deep Dive
        │                                   │
        │                              Step 2: Competitive Moat
        │                                   │
        │                              Step 3: Marginal Changes
        │                                   │
        │                              Step 4: Assumptions ──► step4_structured_assumptions.json
        │                                   │
        │                              Step 5: Financial Model ──► forecast_model.json + .html
        │                                   │
        │                              Step 6: Monte Carlo ──► distribution_chart.png
        │                                   │
        │                              Step 7: RRR & Strategy
        │                                   │
        │                              Step 8: Auditing
        │                                   │
        │                              Step 9: Director Review ──► Auto-generate reports
        │                                   │
        └──────────────────────────── Post-research: ThesisTracker, CatalystTracker, KnowledgeGraph
```

### Workflow Guard

Every step transition is enforced by `src/cli.py workflow`:

```bash
python -m src.cli workflow {dir} start    --step N   # Mark step N in-progress
python -m src.cli workflow {dir} complete --step N   # Mark step N completed + record artifact
python -m src.cli workflow {dir} block    --step N   # Block with a reason
```

Step N requires all prior steps completed. State is persisted in `workflow_state.json` per workspace.

## Data Flow

```
1. User provides ticker
2. CLI detects market (A-share / HK / US)
3. Fetcher downloads data → data_cache/*.csv
4. Claude reads prompts/NN_*.md + workspace data
5. Claude produces step artifacts → workspaces/{TICKER}/stepN_*.md
6. Workflow guard validates transitions
7. Step 9 auto-generates HTML + MD reports
8. Post-research: thesis/catalyst/edge/knowledge-graph trackers initialized
```

## Key Design Decisions

| Decision | Rationale |
|:---------|:----------|
| Contract-driven step system | `step_contracts.json` defines step IDs, names, and artifacts — both Python and TypeScript read the same source of truth |
| Atomic JSON storage | `src/storage.py` uses write-to-temp + rename for crash-safe persistence |
| Formula-linked financial model | `forecast_model.json` stores inputs + formula conventions; validation checks consistency between income/cash-flow/balance-sheet |
| Evidence registry | Every claim in the analysis is tagged with `evidence_id` linking to source data |
| Market-specific fetchers | Separate fetchers per market (AshareFetcher, HKFetcher, USFetcher) with different primary data sources |
| MCP real-time data layer | Tushare MCP tools supplement batch data during analysis steps |

## Market Data Sources

| Market | Primary | Supplement | Financials |
|:-------|:--------|:-----------|:-----------|
| A-share | Tushare Pro | AKShare, MCP tools | Tushare income/balance/cashflow |
| HK | AKShare | Tushare southbound flow | WebSearch for MD&A (PDFs are scanned) |
| US | AKShare (price) | WebSearch, SEC EDGAR | SEC EDGAR filings |
