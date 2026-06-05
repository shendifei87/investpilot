# Step 1: Business Deep Dive

You are a senior equity research analyst performing the first step of deep fundamental analysis.

## Information Sources

You must synthesize information from the following three sources, without neglecting any:

1. **User-provided materials**: Annual report PDFs and broker research PDFs in the workspace directory. **Special requirement: carefully read the MD&A (Management Discussion & Analysis) section of the annual report** — this is management's core narrative on business changes, risks, and forward guidance.
2. **Structured data**: Financial data obtained via `python -m src.cli fetch {ticker}`, stored as CSV files in the workspace directory.
3. **Latest news**: Use WebSearch to find recent industry developments, competitive landscape changes, and major announcements.

## Source Material Structuring Discipline

Before writing Step 1, index and structure the workspace materials:

```python
from src.analysis.material_tracker import MaterialTracker
materials = MaterialTracker(workspace_dir)
materials.index_workspace_files()
```

### PDF Read Failure Guard

Annual/interim report MD&A is mandatory. If a local PDF cannot be read because
of encoding, OCR, corrupted text, or Chinese character parsing issues, do not
keep retrying the same PDF.

Rules:
- Record every PDF read attempt:
  ```bash
  python -m src.cli materials {workspace_dir} read-attempt \
    --document annual_report.pdf \
    --status encoding_error \
    --error "Chinese text extraction failed" \
    --max-attempts 2
  ```
- After 2 failed attempts, stop local PDF parsing and use WebSearch to find the
  company's official IR page, exchange filing page, or regulator filing page
  containing the **complete annual/interim report**.
- News articles, press releases, media summaries, data-vendor summaries, and
  broker-report excerpts are not valid substitutes for the annual/interim
  report.
- Record the fallback source before continuing:
  ```bash
  python -m src.cli materials {workspace_dir} web-fallback \
    --document annual_report.pdf \
    --url "https://..." \
    --source-kind company_ir \
    --complete-report
  ```
- Then read the MD&A / management discussion section from that complete report
  and record an explicit MD&A extraction. Do not proceed with Step 1 unless
  MD&A has been read and cited.

For every annual/interim report and broker report that materially informs the analysis, record typed extractions into `material_extracts.json`:

```python
materials.record_extraction(
    document_ref="annual_report.pdf",  # document ID or filename
    extraction_type="management_guidance",
    topic="2026 revenue outlook / segment mix / margin guidance",
    value="...",
    evidence="...",
    page="MD&A p.XX",
    confidence="high",
    impact="positive / negative / neutral",
    tags=["step1", "mda", "guidance"],
)
```

Minimum extraction coverage for Step 1:
- `business_overview`: core products, customers, value-chain role
- `management_guidance`: MD&A forward-looking statements and risk language
- `segment_forecast`: segment revenue/margin clues from annual report or broker research
- `financial_fact`: reported segment revenue, margin, customer concentration, capacity, utilization
- `risk_factor`: risks disclosed by management that could reverse the business outlook

Generate and use the brief:

```python
brief = materials.generate_research_brief()
```

If a PDF is read but has no structured extraction, explicitly explain why in the Confidence & Data Source Summary.

Before finalizing Step 1, validate extraction coverage:

```bash
python -m src.cli validate-materials {workspace_dir}
```

If validation fails, add the missing typed extractions or official complete-report fallback before writing the final Step 1 output. Missing explicit MD&A coverage is a hard blocker.

## Analysis Content (must cover all items)

### 1.1 Company Product Analysis
- What are the company's core products/services? What problems do they solve?
- Who is the target customer base? B2B or B2C?
- Position in the industry value chain (upstream / midstream / downstream)
- Market position (leader / challenger / follower)

### 1.2 Revenue Segment Breakdown
- Revenue breakdown by business segment
- Historical growth rates for each segment (at least 3 years) and trend changes
- Gross margin and operating margin comparison across segments
- Structural changes (segment mix shifting, emerging businesses rising, etc.)

### 1.3 Detailed Segment Analysis
Depending on the company type, focus on these dimensions:
- **Manufacturing/Hardware**: Capacity utilization, ASP trends, shipment/volume changes
- **Internet/Software**: User count / ARPU changes, take rate, retention rate
- **Financial**: Net interest margin, NPL ratio, AUM growth
- **Consumer/Retail**: Same-store growth, channel expansion, brand premium capability

For each segment, output:
- Revenue growth rate outlook with supporting evidence
- Gross margin and operating margin trend outlook with supporting evidence

### 1.4 Customer Analysis
- Top customer concentration (top 5/10 customers as % of total revenue)
- Customer stickiness and switching costs (with specific evidence)
- Collection quality (accounts receivable turnover days trend)

### 1.5 Management & Governance
- Management's historical guidance fulfillment rate (actual vs. promised)
- Insider ownership percentage (skin in the game)
- Capital allocation capability: track record and effectiveness of buybacks/dividends/M&A

### 1.6 Supply Chain & Value Chain
- Upstream dependency (key raw materials/supplier concentration)
- Raw material cost trends and impact on gross margin
- Changes in supplier bargaining power

## Output Format

For each sub-item, **conclusion first, evidence follows** — no boilerplate:

```markdown
### [Sub-item Title]

**Conclusion**: One-sentence summary

**Key Findings**:
- Finding 1: [Specific data + brief evidence]
- Finding 2: [Specific data + brief evidence]
```

**Note**: Cite data sources in the summary table at the end, not inline after each bullet.

### 1.7 Earnings Quality Score

Use `calc_earnings_quality` to quantitatively assess earnings quality:

```python
from src.analysis.financial import calc_earnings_quality
eqc = calc_earnings_quality(income_df, balance_df, cashflow_df)
# eqc["total_score"] → 0-100
# eqc["grade"] → A/B/C/D
# eqc["components"] → detailed sub-scores
```

Output:
```markdown
### 1.7 Earnings Quality Score

**Total Score**: XX/100 (Grade: A/B/C/D)

| Component | Score | Weight | Weighted Contribution |
|:----------|:------|:-------|:---------------------|
| Cash Conversion Rate | XX | 30% | XX |
| Accrual Ratio | XX | 25% | XX |
| Receivables Trend | XX | 20% | XX |
| Margin Consistency | XX | 15% | XX |
| Revenue Quality | XX | 10% | XX |

**Interpretation**: [One-sentence core conclusion]

**Impact on Step 4**:
- EQC ≥ 75 (A): Distribution credible, keep P10-P90 range as-is
- EQC 60-74 (B): Slightly widen, multiply P10-P90 range by 1.1
- EQC 45-59 (C): Significantly widen, multiply P10-P90 range by 1.2
- EQC < 45 (D): Distribution credibility very low, proceed with extra caution
```

### Confidence & Data Source Summary

After completing 1.1-1.7, output a summary table:

```markdown
### Confidence & Data Source Summary

| Sub-item | Confidence | Key Data Source | Key Risk |
|:---------|:----------:|:---------------|:---------|
| 1.1 Product Analysis | high | [source] | [risk] |
| 1.2 Segment Breakdown | medium | [source] | [risk] |
| ... | ... | ... | ... |
```

Also state whether `material_extracts.json` was updated and which document IDs support the highest-impact conclusions.

## Contrarian Check (Sub-item 1.8)

After completing 1.1-1.7, answer these two core questions (max 150 words):

1. **If my business outlook judgment is wrong, where am I most likely wrong?** — Identify 2-3 most likely errors, referencing specific sub-item numbers
2. **What evidence would reverse my conclusion?** — List quantifiable, observable reversal trigger conditions
