# InvestPilot Architecture Rewrite Plan

## Target

Rebuild InvestPilot from a prompt-driven research harness into a contract-driven investment research operating system. The LLM should produce reasoning and structured inputs; deterministic services should own workflow state, artifact contracts, formula linkage, validation, simulation, report rendering, and post-research calibration.

## Design Principles

1. Single source of truth for step contracts, artifact names, dependencies, and validation gates.
2. Agents cannot advance by writing prose only; every step must satisfy its artifact contract.
3. Step 4 assumptions are the core asset: driver-level, evidence-linked, probability-calibrated, and user-reviewed.
4. Step 5 financial model outputs are deterministic from locked assumptions, not improvised markdown.
5. Step 6 simulations are reproducible from locked assumptions and versioned simulation parameters.
6. Reports render structured artifacts; they do not create new facts or valuation logic.
7. Failures create durable blocker artifacts instead of unbounded retry loops.

## Phase 1: Contract Foundation

Status: implemented.

Deliverables:

- `config/step_contracts.json` as the canonical 0-9 step registry.
- Python contract loader in `src/contracts/`.
- Workflow completion gated by required artifacts, not only markdown existence.
- Report and web step metadata derived from the same contract.
- Tests covering contract consistency and artifact contract enforcement.

Acceptance:

- A step cannot complete unless all required artifacts exist.
- Deprecated split/combined Step 4 artifacts are rejected instead of reused.
- Python tests, web tests, TypeScript checks, and compile checks pass.

## Phase 2: Evidence Registry

Status: implemented for Step 4 gating.

Deliverables:

- A normalized evidence registry that unifies annual reports, MD&A extraction, broker research, public filings, web sources, and raw data artifacts.
- Evidence IDs with source type, timestamp, page/URL, confidence, and extraction type.
- Bounded PDF read attempts, then official complete-report web recovery.
- Material coverage validator that blocks research when MD&A is missing.

Acceptance:

- Every Step 4 high-sensitivity assumption references evidence IDs.
- News, summaries, and broker excerpts cannot substitute for complete annual/interim reports.

## Phase 3: Assumption Lab

Status: partially implemented.

Deliverables:

- Driver-tree schema for segment revenues and margin/cost drivers.
- Validator for no bare growth rates, driver contribution sums, evidence coverage, P10/P50/P90 monotonicity, and P50 to P10 falsification paths.
- User-reviewed assumption lock that Step 5 and Step 6 must consume exactly.
- Calibration records for post-earnings actual-vs-forecast learning.

Acceptance:

- Step 4 fails if any segment uses a naked growth rate.
- Step 4 fails if probability tiers lack evidence or driver decomposition.
- Step 5/6 fail if they introduce assumptions absent from the reviewed lock.

## Phase 4: Formula Model Engine

Status: partially implemented.

Deliverables:

- Deterministic model graph derived from Step 4 assumptions.
- Canonical `forecast_model.json` with formulas, lineage, input assumption IDs, and outputs.
- Human-readable `forecast_model.html` and optional XLSX export.
- Formula audit: revenue sum, EPS bridge, tax/share-count treatment, valuation multiple linkage.

Acceptance:

- Every forecast output traces to a Step 4 assumption or raw data artifact.
- T+1/T+2/T+3 EPS bridges reconcile mechanically.
- Model generation blocks if Step 4 validation fails.

## Phase 5: Simulation And Decision Engine

Deliverables:

- Reproducible Monte Carlo engine with versioned config, seed, distribution family, and t-Copula parameters.
- Downside attribution and sensitivity reports.
- RRR and Kelly sizing derived from simulation outputs.
- Entry-price RRR recalculation and catalyst time-decay adjustment.

Acceptance:

- Simulation reruns with the same inputs produce the same results.
- RRR cannot be hand-entered without calculation lineage.
- Director review can veto decisions that violate RRR, Kelly, edge, or valuation rules.

## Phase 6: Research Memory

Deliverables:

- Thesis, catalyst, calibration, and knowledge-graph updates from structured outputs.
- Post-earnings actual-vs-forecast reviews.
- Cross-stock pattern retrieval for future research.

Acceptance:

- Each completed research initializes tracking artifacts.
- Forecast calibration improves or flags assumption bias over time.
