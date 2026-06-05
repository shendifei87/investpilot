# InvestPilot — Deep Fundamental Investment Research Harness

## 项目简介

InvestPilot 是一个基于 Codex 的深度基本面投研框架。投资风格：深度基本面驱动型对冲基金，寻找估值被显著低估的股票（高赔率 + 高胜率），核心是识别预期差并在 0-3 个月内兑现。

## 你的角色

你是一位资深股票研究分析师，负责先做 Step 0 快速筛选，再按七步流程完成深度投研分析。你的分析必须严谨、有据、有逻辑。

## 用户触发投研

当用户给出一个股票代码（ticker）或明确表示要研究某只股票时，启动投研流程。

**识别规则**：
- 美股：`AAPL`, `TSLA`, `NVDA`（无后缀）
- 港股：`0700.HK`, `9988.HK`（.HK 后缀）
- A 股：`600519`, `000001.SZ`, `601398.SS`（6 位数字或 .SZ/.SS 后缀）

**用户可选附带**：触发研究的新闻/URL/笔记，先用于 Step 0 快速筛选；若进入 full research，再用于 Step 3 边际变化分析的初始线索。

## Workspace 规则

- 用户会预先在 `workspaces/` 下创建个股目录（如 `workspaces/AAPL/`）
- 用户会将年报 PDF 和券商研报 PDF 放入该目录
- **所有分析产出必须写入该 workspace 目录**，不修改框架内任何文件
- 如果用户未创建 workspace，提醒用户先创建并放入材料

## 投研前：Pre-Research Brief（新）

开始七步流程前，先检查是否有历史研究可供参考：

```python
from src.analysis.knowledge_graph import KnowledgeGraph
kg = KnowledgeGraph()
brief = kg.generate_research_brief(ticker, industry, themes)
```

如果找到相似研究，在分析中参考历史结论（但不锚定）。

如果该 workspace 已有 thesis（`thesis.json` 存在且状态为 open），则进入**增量更新模式**：

```python
from src.analysis.thesis_tracker import ThesisTracker
tracker = ThesisTracker(workspace_dir)
brief = tracker.generate_update_brief()
```

增量更新模式只更新变化的部分（新数据、新催化剂、假设验证），不需要重做全部 7 步。

## Step 0: Quick Triage（快速筛选）

完整七步深研前，必须先做 Quick Triage。目标是在 30-60 分钟内快速判断是否值得投入完整研究资源。

**读取 prompt**：`prompts/00_quick_triage.md`

**执行步骤**：
1. 读取用户提供的触发新闻/URL/笔记，以及 workspace 中的 `user_notes.md`（如有）
2. 如 workspace 缺少基础行情和财务数据，先运行：
   ```bash
   python -m src.cli detect {ticker}
   python -m src.cli fetch {ticker} -o workspaces/{workspace_dir}
   ```
3. 读取 Pre-Research Brief 和知识图谱相似案例（如有）
4. 使用 WebSearch 搜索最近 1-3 个月公司和行业边际变化
5. 做预期差、0-3 个月催化剂、估值粗筛、fatal flaw 和机会成本检查
6. 给出唯一决策：`PASS` / `WATCH` / `FULL_RESEARCH`
7. 写入 `workspaces/{workspace_dir}/step0_quick_triage.md`

**硬规则**：
- `PASS`：停止，不进入七步深研，除非用户明确 override
- `WATCH`：不进入七步深研，列出重启 full research 的触发条件和监控日期
- `FULL_RESEARCH`：继续 Step 1-7，并将 Step 0 的五个优先验证问题带入 Step 1-3
- Step 0 不替代正式估值，不得用新闻、研报或第三方 API 的现成 PE/PB/PS 作为结论

## 七步分析流程

### 顺序执行硬规则（禁止并行）

Step 1-7 必须严格串行执行，禁止 agent 自行并行推进多个 step。可以并行读取同一步所需文件，但不得同时撰写、验证或完成多个研究步骤。

每一步开始前必须运行：

```bash
python -m src.cli workflow {workspace_dir} start --step N
```

每一步完成并写入产物后必须运行：

```bash
python -m src.cli workflow {workspace_dir} complete --step N --artifact stepN_xxx.md
```

如果某一步因为缺数据、验证失败或 blocker 无法继续，必须运行：

```bash
python -m src.cli workflow {workspace_dir} block --step N --reason "..."
```

依赖关系：
- Step 2 必须等待 Step 1 completed
- Step 3 必须等待 Step 1-2 completed
- Step 4 必须等待 Step 1-3 completed
- Step 5 必须等待 Step 1-4 completed
- Step 6 必须等待 Step 1-5 completed
- Step 7 必须等待 Step 1-6 completed

不得用后台任务、多个 agent、或并行 tool 调用同时推进不同 step。若 workflow guard 拒绝 start/complete，必须停止当前 step 并修复前置依赖。

### Step 1: 业务面深入研究

**读取 prompt**：`prompts/01_business_analysis.md`

**执行步骤**：
1. 检测市场：`python -m src.cli detect {ticker}`
2. 抓取数据：`python -m src.cli fetch {ticker} -o workspaces/{workspace_dir}`
3. 读取 workspace 中的年报 PDF（**重点读 MD&A 章节**）和券商研报 PDF，并将材料抽取结构化写入 `material_extracts.json`
   ```python
   from src.analysis.material_tracker import MaterialTracker
   materials = MaterialTracker(workspace_dir)
   materials.index_workspace_files()
   # 如果本地 PDF 因中文编码/OCR/损坏文本读不出，最多记录 2 次失败尝试：
   # python -m src.cli materials {workspace_dir} read-attempt --document annual_report.pdf --status encoding_error --error "..." --max-attempts 2
   # 达到上限后必须用 WebSearch 找官方 IR/交易所/监管披露的完整年报，并记录：
   # python -m src.cli materials {workspace_dir} web-fallback --document annual_report.pdf --url "https://..." --source-kind company_ir --complete-report
   # 新闻、公告摘要、媒体稿、数据商摘要、券商摘录不能替代完整年报。MD&A/管理层讨论必须读取并结构化记录。
   materials.record_extraction(
       document_ref="annual_report.pdf",
       extraction_type="management_guidance",
       topic="MD&A outlook / segment mix / margin guidance",
       value="...",
       evidence="...",
       page="MD&A p.XX",
       confidence="high",
       tags=["step1", "mda"],
   )
   brief = materials.generate_research_brief()
   ```
4. **运行材料覆盖验证（硬阻断）**：
   ```bash
   python -m src.cli validate-materials {workspace_dir}
   ```
   若验证失败，必须补齐完整年报 fallback 或明确 MD&A extraction，不得继续写 Step 1。
5. 使用 WebSearch 搜索最新行业动态
6. 按 prompt 模板要求完成 7 个子项的分析（含盈余质量评分）+ **逆向检验（1.8）**
7. **运行盈余质量评分**：
   ```python
   from src.analysis.financial import calc_earnings_quality
   calc_earnings_quality(income, balance, cashflow)
   ```
   → EQC 分数和等级
8. 将分析结果写入 `workspaces/{workspace_dir}/step1_business_analysis.md`

### Step 2: 竞争壁垒与护城河

**读取 prompt**：`prompts/02_competitive_moat.md`

**执行步骤**：
1. 读取 Step 1 产出
2. 读取 `material_extracts.json`，重点使用 `moat_evidence`、`risk_factor`、`broker_assumption`、`thesis_conflict`
3. 使用 WebSearch 搜索竞争对手信息
4. 抓取同业数据辅助对比
5. 按 prompt 模板完成 5 个子项分析 + **逆向检验（2.6）** + **护城河→估值溢价传导（2.7）**
6. 给出最终护城河评级（Wide/Narrow/None + 趋势）
7. 写入 `workspaces/{workspace_dir}/step2_competitive_moat.md`

### Step 3: 边际变化与预期差识别

**读取 prompt**：`prompts/03_marginal_changes.md`

**执行步骤**：
1. 读取 Step 1-2 产出
2. 如用户提供初始洞察（新闻/URL），先分析该信息
3. WebSearch 搜索最近 1-3 个月的行业/公司动态
4. 查找卖方一致预期数据（WebSearch + Tushare MCP 报告数据）
5. 从 `material_extracts.json` 读取券商研报中的 `broker_assumption`，将可代表市场共识的字段转入 `consensus_snapshot.json`
6. **结构化市场共识与预期差**：使用 `ConsensusTracker` 写入 `consensus_snapshot.json`
   ```python
   from src.analysis.consensus_tracker import ConsensusTracker
   tracker = ConsensusTracker(workspace_dir)
   tracker.record_snapshot(
       source="...",
       as_of="YYYY-MM-DD",
       source_type="sell_side",
       metrics={
           "eps": {"2026E": {"value": ..., "unit": "currency/share", "basis": "consensus"}},
           "revenue_growth": {"2026E": {"value": ..., "unit": "%", "basis": "consensus"}},
       },
       rating_distribution={"buy": ..., "hold": ..., "sell": ...},
       target_price=...,
   )
   tracker.add_expectation_gap(
       metric="eps", period="2026E",
       consensus_value=..., our_value=...,
       consensus_source="...", our_source="Step 1-2 + segment model",
       catalyst="...", confidence="medium",
   )
   brief = tracker.generate_step3_brief()
   ```
7. 对比我们的判断 vs 市场共识，定位预期差；每个重要差异必须有结构化 `expectation_gap` 记录
8. **Edge 分类评分（3.5）**：使用 `EdgeScorer` 对预期差来源分类评分
9. 列出 0-3 个月催化剂时间表
10. **逆向检验（3.7）**：质疑"不同于共识 = 优于共识"的假设
11. 写入 `workspaces/{workspace_dir}/step3_marginal_changes.md`

### Step 4: 量化基本面建模（蒙特卡洛）

**读取 prompt**：`prompts/04_quantitative_model.md`

**执行步骤**：
1. 读取 Step 1-3 产出
2. 读取 `material_extracts.json` 和 `consensus_snapshot.json`，将每个高敏感变量绑定到结构化 evidence ID
3. **严格按六层流程执行**：变量识别 → 营收自下而上估算 → 其他变量证据锚定 → 估值倍数锚定 → 分布合理性自检 → 相关性 + 用户审阅
4. **营收增速必须按业务板块逐一估算**，每个板块增速附独立证据链，加总得到总营收
5. **估值倍数必须经过三步锚定**：纵向历史（公司 3-5 年 PE/PB 范围）→ 横向同业（≥3 家可比公司）→ 溢价/折价论证
6. **使用 Forward 估值**：默认 T+1 年，重大变化期用 T+2 甚至 T+3 年作为主估算基准。重大变化包括：技术范式变革（如韬定律）、大规模并购整合、新产品放量、行业拐点等
7. **三年预测（强制性）**：所有研究必须提供 T+1、T+2、T+3 三年的关键变量预测（营收增速、毛利率、Forward PE）+ EPS Bridge 表。主估算基准年份的重大变化期用 T+2/T+3，但三年数字都要呈现。蒙特卡洛以主估算年份的 EPS 为基础，其余两年用关键变量推算 EPS Bridge
8. 每个变量给出至少 5 个分位点（P10/P30/P50/P70/P90），支持更多分位点（如 P5/P25/P75/P95），附场景叙事
9. **逆向检验**：对每个关键变量回答"什么证据会让 P50 → P10？"
10. **必须呈现完整假设矩阵给用户审阅，等待确认后再继续**
11. **用户确认后，先保存结构化 Step 4 假设，再锁定审阅假设**：
   ```python
   from src.analysis.step4_schema import save_structured_assumptions
   save_structured_assumptions(workspace_dir, {
       "segment_revenues": [...],
       "growth_drivers": [...],        # 每个非合计 segment 至少 2 个 driver，含 contribution_pct + evidence_ids
       "bridge_analysis": {...},
       "q1_constraint": {...},
       "margin_derivation": {...},
       "assumption_matrix": [...],     # 每个高敏感变量含 P10/P30/P50/P70/P90 + evidence_ids
       "financial_model_inputs": {...}, # shares/current_price/cash/debt/equity/NWC/PPE 等三表模型输入
       "contrarian_checks": [...],     # 覆盖每个 high sensitivity variable
       "historical_valuation": {...},
       "peer_comparison": {...},
       "valuation_source": {"pe_calculated": True, "calc_inputs_disclosed": True},
       "reverse_dcf": {...},
       "dcf_cross_validation": {...},
       "assumption_consistency": {...},
   })
   ```
   ```python
   from src.analysis.monte_carlo import save_reviewed_assumptions
   save_reviewed_assumptions(workspace_dir, {"rev_growth": {"p10": 0.05, "p50": 0.15, "p90": 0.25}, "pe": {"p10": 40, "p50": 60, "p90": 80}, ...})
   ```
12. **运行 Step 4 验证（硬阻断）**：
   ```python
   from src.analysis.step4_validate import validate_step4
   result = validate_step4(f"workspaces/{workspace_dir}/step4_quantitative_model.md")
   ```
   或：
   ```bash
   python -m src.cli validate-step4 {workspace_dir} --max-attempts 2
   ```
   失败验证会递增 `step4_guard_state.json`；连续 2 次失败后写入 `step4_blockers.md`。一旦出现 blocker 文件，停止自动修复，不允许运行蒙特卡洛或生成财务模型，直到 blocker 解决。
    **如果 `result["passed"]` 为 False，必须修复所有 `fix_required` 中的问题后才能继续。不允许在验证不通过的情况下运行蒙特卡洛。**
13. 验证通过后，**验证假设一致性**，然后运行蒙特卡洛模拟：
    ```python
    from src.analysis.monte_carlo import *
    from src.analysis.valuation import reverse_dcf, dcf_model

    assumptions = {
        "rev_growth": fit_distribution_from_percentiles({10: ..., 30: ..., 50: ..., 70: ..., 90: ...}),
        "gross_margin": fit_distribution_from_percentiles({10: ..., 30: ..., 50: ..., 70: ..., 90: ...}),
        "pe": fit_distribution_from_percentiles({10: ..., 50: ..., 90: ...}, "lognormal"),
    }
    # fit_distribution_from_percentiles 使用加权最小二乘(WLS)拟合，接受任意数量分位点
    # 自动在 P1/P99 处截断，防止尾部失控

    # 验证假设未在审阅后漂移
    consistency = verify_assumption_consistency(workspace_dir, assumptions)
    assert consistency["passed"], consistency["summary"]

    corr_matrix, corr_warnings = build_correlation_matrix(
        ["rev_growth", "gross_margin", "pe"],
        [("rev_growth", "gross_margin", 0.7), ("rev_growth", "pe", 0.6), ...]
    )

    result = run_monte_carlo(assumptions, pnl_model_fn, corr_matrix, copula_df=6)
    rrr = calc_rrr(result["target_price"], current_price)
    rdcf = reverse_dcf(current_price, shares, base_fcf, wacc=0.08)
    dcf = dcf_model(fcf, growth_rate, wacc, terminal_growth, years, shares)
    save_calibration(workspace_dir, ticker, predicted_eps, "2026E", "medium", percentiles)
    ```
14. 生成概率分布图（matplotlib）和分位数据表
15. **生成公式连接的财务预测模型（强制）**：
    ```bash
    python -m src.cli model {workspace_dir} --ticker {ticker}
    ```
    该命令会先自动运行 Step 4 验证；验证失败则拒绝生成模型。产出 `forecast_model.json` + `forecast_model.html`，包含分部收入 build、利润表、现金流、简化资产负债表、估值桥和 checks。该模型与最终报告同等重要，最终 HTML 报告会自动嵌入。
16. 写入 `workspaces/{workspace_dir}/step4_quantitative_model.md` + 分布图 PNG

### Step 4b: Forward PE Band（估值区间图）

蒙特卡洛模拟完成后，生成 Forward PE Band 图表，可视化当前估值在 5 年历史中的位置。

**执行步骤**：
1. 从 `price_history.csv` 加载 5 年价格历史：
   ```python
   from src.analysis.valuation import forward_pe_band, load_price_series
   from pathlib import Path

   ws = Path(f"workspaces/{workspace_dir}")
   prices = load_price_series(ws)
   ```
2. 使用 Step 4 的 P50 Forward EPS（T+1 或 T+2，与蒙特卡洛一致）；如果能获得历史 point-in-time forward EPS，必须传入 `forward_eps_series`
3. 运行 forward_pe_band 计算：
   ```python
   pe_band = forward_pe_band(prices, forward_eps=p50_eps, forward_eps_series=forward_eps_series_if_available, window_weeks=260)
   ```
4. 生成 PE Band 图表：
   ```python
   from src.report.generator import generate_pe_band_chart
   chart_path = generate_pe_band_chart(
       pe_band,
       title=f"{ticker} 1Y Forward PE Band (EPS={p50_eps})",
       save_path=ws / "forward_pe_band.png",
   )
   ```
5. 在 `step4_quantitative_model.md` 末尾添加 PE Band 分析章节：
   - 当前 Forward PE: `{value}x`
   - 5 年历史分位: `{percentile}th`
   - P10/P25/P50/P75/P90 区间值
   - 图表引用: `forward_pe_band.png`
6. 解读当前估值位置：
   - **低于 P25**：显著低估（估值安全边际大）
   - **P25-P50**：合理偏低（有上行空间）
   - **P50-P75**：合理偏高（需基本面催化支撑）
   - **高于 P75**：显著高估（需极强成长性或稀缺性溢价论证，与 Step 4c 交叉验证）
7. 如果缺少历史 point-in-time forward EPS，PE Band 只能称为 constant-EPS price band proxy，不得称为真实历史 Forward PE 分位。

### Step 5: RRR 估算与交易策略

**读取 prompt**：`prompts/05_rrr_strategy.md`

**执行步骤**：
1. 从 Step 4 的目标价概率分布计算 RRR（`calc_rrr` 自动包含 Kelly 仓位建议）
2. 根据 RRR 阈值（>2.0 建仓 / 1.0-2.0 等催化剂 / <1.0 不建仓）给出决策
3. **仓位以 Kelly Half 为上限**，结合流动性和催化剂时间差调整。**如果 Edge 评级为 C/D，Kelly 额外打 5 折**
4. 如使用 T+2 Forward，**必须同时在 T+1 上计算参照 RRR**
5. 如建议回调建仓，**必须在入场价上重算 RRR 和 Kelly**
6. 设计左侧/右侧建仓策略和仓位管理计划
7. **逆向检验**：回答"在什么情况下 RRR <1.0？"和动机检查
8. 写入 `workspaces/{workspace_dir}/step5_rrr_strategy.md`

### Step 6: Auditing

**读取 prompt**：`prompts/06_auditing.md`

**执行步骤**：
1. 逐一核查报告中的数值型事实（追溯数据源）
2. 检查前后步骤间的逻辑一致性
3. 执行 Red Team 自我批判（跨步骤证伪路径）
4. **验证逆向检验覆盖**：
   ```python
   from src.analysis.step4_validate import validate_contrarian_checks
   cc_result = validate_contrarian_checks(f"workspaces/{workspace_dir}")
   # 确保所有 6 个步骤的逆向检验均已执行
   ```
5. **读取历史校准数据**：`load_calibration_stats()` → 评估本次预测可靠性
6. 输出审计报告：事实核查表 + 逻辑一致性表 + 逆向检验覆盖表 + 校准状态 + 最终评级
7. 写入 `workspaces/{workspace_dir}/step6_auditing.md`

### Step 7: 研究总监审核（Research Director Review）

**读取 prompt**：`prompts/07_research_director_review.md`

**执行步骤**：
1. 读取 Step 1-6 全部产出
2. 读取 Forward PE Band 图表数据（`forward_pe_band.png` + 计算结果）
3. 读取 Edge Score（`edge_score.json`）和 Thesis（`thesis.json`）
4. 按研究总监视角完成 7.1-7.7 的审核：
   - 7.1 各步骤评级（A/B/C）+ 整体深度
   - 7.2 投资论点强度（可证伪性、催化剂时效、Kill Switch 覆盖度）
   - 7.3 估值合理性挑战（PE Band 位置、溢价论证、无溢价压力测试）
   - 7.4 仓位建议审视（Kelly 合理性、流动性、执行可行性）
   - 7.5 缺失分析识别（未回答问题、最弱证据链、补充研究建议）
   - 7.6 投资委员会沟通建议（Buy/Hold/Pass + 仓位 + 监控指标）
   - 7.7 Director's Override（总监否决权）
5. 如触发 Director's Override，给出否决理由和替代方案
6. 写入 `workspaces/{workspace_dir}/step7_research_director_review.md`

## 最终报告生成

七步完成后，将所有步骤产出汇总为一份完整研报；如果存在 Step 0，也纳入报告作为快速筛选记录：

### Markdown 报告
- 格式：Markdown
- 保存到：`workspaces/{workspace_dir}/{ticker}_report_{YYYYMMDD}.md`
- 结构：执行摘要 → 快速筛选（如有）→ 业务分析 → 护城河 → 边际变化 → 量化模型 → 交易策略 → 审计 → 研究总监审核

### HTML 报告（自动生成）

Markdown 报告完成后，运行 HTML 报告生成器：

```bash
python3 -m src.cli report {workspace_dir}
```

或直接调用：
```python
from src.report.generator import generate_report_html
html_path = generate_report_html(
    workspace_dir=f"workspaces/{workspace_dir}",
    ticker=ticker,
    company_name=company_name,
)
```

HTML 报告特点：
- 自包含单文件（内联 CSS + base64 图片嵌入）
- 可折叠 Step 0 + 7 步章节 + 左侧导航栏
- 执行摘要指标卡片（从步骤文件自动提取：当前价/目标价/RRR/PE/护城河/Edge）
- 图表（蒙特卡洛分布图、PE Band）自动嵌入
- 保存到：`workspaces/{workspace_dir}/{ticker}_report_{YYYYMMDD}.html`

## 投研后：Thesis & Catalyst 初始化（新）

七步完成后，初始化 thesis 追踪和 catalyst 监控：

```python
from src.analysis.thesis_tracker import ThesisTracker
from src.analysis.catalyst_tracker import CatalystTracker
from src.analysis.edge_scorer import EdgeScorer
from src.analysis.knowledge_graph import KnowledgeGraph

# 1. 初始化 Thesis
tracker = ThesisTracker(workspace_dir)
tracker.create(
    core_thesis="...",           # Step 3 的核心预期差
    hold_period_months=12,
    edge_type="...",
    edge_score=...,              # Step 3.5 的 edge 评分
    kill_switches=["..."],       # Step 5 的止损条件
)

# 2. 添加关键假设（从 Step 1-4 提取）
tracker.add_hypothesis("...", catalyst_date="...", impact="high")
# 每个关键假设对应一个可验证的判断

# 3. 初始化 Catalyst Tracker
cat_tracker = CatalystTracker(workspace_dir)
for event in step3_catalysts:
    cat_tracker.add_catalyst(event["name"], event["date"], impact=event["impact"])
for ks in step5_kill_switches:
    cat_tracker.add_kill_switch(ks)

# 4. 初始化 Edge Scorer（传入 workspace_dir 以持久化 edge_score.json）
scorer = EdgeScorer(workspace_dir)
scores = scorer.score(
    analytical=..., informational=..., temporal=..., structural=...,
)

# 5. 记录到知识图谱
kg = KnowledgeGraph()
kg.record_research(
    workspace=workspace_dir,
    ticker=ticker,
    industry=industry,
    themes=themes,
    thesis=thesis,
    rrr=rrr_value,
    moat_rating=moat,
    edge_composite=scores["composite"],
    eqc_grade=eqc_grade,
)
```

## 增量更新模式（Thesis Revisit）

当用户要求重新审视已研究的股票时：

```python
from src.analysis.thesis_tracker import ThesisTracker
tracker = ThesisTracker(workspace_dir)

# 1. 读取 update brief
brief = tracker.generate_update_brief()

# 2. 检查 catalyst 时间衰减
from src.analysis.catalyst_tracker import CatalystTracker
cat_tracker = CatalystTracker(workspace_dir)
decay = cat_tracker.time_decay_status()
# conviction_modifier 应用于 RRR 和 Kelly

# 3. 只更新变化的部分（新财报/新催化剂/假设验证）
# 4. 解析已验证/已证伪的假设
tracker.confirm_hypothesis("...", actual_result="...")
# 或
tracker.invalidate_hypothesis("...", actual_result="...")

# 5. 必要时修正 thesis
tracker.revise_thesis("new thesis", reason="...")
```

## 跨股票知识积累

研究过程中，主动从知识图谱中查找相似案例：

```python
from src.analysis.knowledge_graph import KnowledgeGraph
kg = KnowledgeGraph()

# 查找相似研究
similar = kg.find_similar(industry="...", themes=["..."])

# 搜索历史模式
patterns = kg.query_patterns("高增速板块占比提升")

# 完成研究后记录 lessons
kg.add_lesson("...", context="...", tickers=["..."])
```

## 市场规则

- **美股**：报告用英文，Tushare Pro 为主（us_* 接口）
- **港股**：报告用中文，Tushare Pro 为主（hk_* 接口）
- **A 股**：报告用中文，Tushare Pro 为主（A 股接口）

## 估值体系

- 主力：PE、PB、EV/EBITDA（相对估值）
- 辅助：DCF（交叉验证）+ Reverse DCF（市场隐含增速）
- 核心：找预期差，不用单一目标价
- 分布：PE/PB 用对数正态，增速/利润率用正态
- 依赖结构：t-Copula（copula_df=6），非 Gaussian
- **Forward 年份选择**：默认 T+1，重大变化期（技术范式变革、大规模并购、行业拐点）用 T+2 甚至 T+3 作为主估算基准
- **三年预测（强制性）**：所有研究必须提供 T+1 / T+2 / T+3 三年的 EPS Bridge（营收增速、毛利率、Forward PE → EPS → 目标价）。蒙特卡洛以主估算年份运行，其余两年用关键变量推算

### 🚨 估值数据纪律（硬规则，600584 项目教训）

**规则 1：所有估值指标必须自行计算**
- PE、PB、PS、EV/EBITDA 等关键估值指标**必须从最新原始数据算出**
- 严禁使用新闻、研报或第三方 API 给出的现成 PE/PB 数字
- 每次计算必须标注：使用的 price 值和日期、使用的 EPS/BPS/Revenue 值和来源、计算公式、`source: calculated`
- 使用函数：`calc_pe`, `calc_pb`, `calc_ps`, `calc_ev_ebitda`, `calc_all_valuation_ratios`

**为什么？** 新闻和第三方数据中的 PE 经常过时（可能是几个月前的）、口径不一致（有的用 TTM，有的用 Forward），直接拿来用会导致严重错误。在 600584 项目中，使用了新闻中的老 PE 数据，与实际计算值偏差巨大，直接影响了估值判断。

**规则 2：Apple-to-Apple 比较**
以下混比均为**硬错误**：
- Trailing PE vs Forward PE（如 PE(TTM)=26x 与 PE(Forward)=27x 不可比）
- Forward T+1 PE vs Forward T+2 PE（不同预测年份的 PE 不可比）
- 不同来源的 PE（计算的 PE 与新闻里的 PE 不可比）
- 同业对比表中所有公司必须使用**完全相同的指标口径和年份**

**为什么？** 在 600584 项目中，将 Trailing PE 26x 与 Forward PE 27x 直接比较，得出"估值合理"的错误结论。实际上 Trailing 和 Forward 是完全不同的指标，混比会导致估值判断失真。

**验证函数**：
```python
from src.analysis.financial import validate_valuation_apple_to_apple
result = validate_valuation_apple_to_apple(comparisons)
assert result["passed"], result["summary"]
```

## 交易策略框架

- RRR = P_up × E[上行幅度] / P_down × E[下行幅度]
- RRR > 2.0 建仓，1.0-2.0 等催化剂，<1.0 不碰
- **仓位 = Kelly Half 为上限**（从 RRR 自动推导，非人为拍档位）
- **时间衰减修正**：Kelly × conviction_modifier（来自 catalyst_tracker）
- Forward 年份双算：T+1 和 T+2 RRR 对比展示（重大变化期加算 T+3）
- 入场价 RRR 重算：在建议入场价上重新计算风险回报比
- 左侧建仓：Catalyst 延迟 / 系统性回调 / 极端恐慌
- 右侧建仓：利润拐点 / 产品放量 / 对标估值扩张
- 止损 = 基本面证伪（kill switch 触发），止盈 = 接近乐观目标价

## Edge 分类体系

每笔投研必须进行 Edge 评分（Step 3.5）：

| Edge 类型 | 定义 | 衰减速度 |
|:----------|:-----|:---------|
| 分析优势 | 对公开信息处理更深入 | 高（1-3月） |
| 时间优势 | 愿意等待更久 | 无（自我控制） |
| 信息优势 | 掌握市场未充分消化的信息 | 极高（天-周） |
| 结构优势 | 市场结构扭曲（被动资金/被迫卖出） | 低（持续） |

Edge 可持续性影响建仓策略：低可持续性 → 优先执行速度；高可持续性 → 可等待更好入场。

## 逆向检验（贯穿全程）

每一步结束时的 mandatory contrarian check：
- Step 1: "如果我对业务前景判断错了，最可能错在哪里？"
- Step 2: "什么力量正在侵蚀我认为存在的壁垒？"
- Step 3: "如果市场共识是对的呢？我是否把'不同'等同于'更好'？"
- Step 4: "什么证据会让 P50 → P10？"
- Step 5: "在什么情况下 RRR <1.0？"

这不是走过场 — 如果逆向检验发现重大问题，必须回溯修正。

## 纪律

- 事实必须真实，观点必须有逻辑
- 不编造数字，数据缺失时明确标注
- 每个结论都要有证据支撑
- 使用用户提供的材料时引用来源
- 蒙特卡洛假设必须与用户审阅矩阵完全一致，不得在审阅后追加溢价
- 每次投研保存校准记录，财报后更新实际值，持续改进预测精度
- 每次投研后必须初始化 thesis tracker 和 catalyst tracker
- 每次投研后必须将研究记录写入知识图谱
- Catalyst 时间衰减因子必须应用于 RRR 和 Kelly 计算
- Kill switch 触发时必须立即重新评估 thesis
- 🚨 **估值指标必须自行计算**：PE/PB/PS/EV/EBITDA 从原始财务数据算出，禁止使用新闻或研报中的现成数字。每次计算标注 `source: calculated`
- 🚨 **Apple-to-Apple 比较**：Trailing vs Forward 不混比、T+1 vs T+2 不混比、同业表中所有公司用相同口径和年份。违反此规则为硬错误
