# Step 0: Quick Triage

## 目标

在投入完整七步深研之前，用 30-60 分钟判断这只股票是否值得进入 full research。Quick Triage 的任务不是证明 thesis，而是快速排除低赔率、无催化剂、无预期差或数据不足的标的。

输出必须写入：

`workspaces/{workspace_dir}/step0_quick_triage.md`

## 输入

- 用户提供的 ticker、触发新闻、URL 或笔记
- workspace 中已有的 PDF、CSV、JSON、user_notes.md
- `python -m src.cli detect {ticker}` 的市场识别结果
- 如 workspace 缺少基础行情和财务数据，先运行：
  `python -m src.cli fetch {ticker} -o workspaces/{workspace_dir}`
- WebSearch 获取最近 1-3 个月公司和行业变化
- 知识图谱 brief（如有）：
  ```python
  from src.analysis.knowledge_graph import KnowledgeGraph
  kg = KnowledgeGraph()
  brief = kg.generate_research_brief(ticker, industry, themes)
  ```
- 如果已经能识别明确市场共识或初步预期差，使用 `ConsensusTracker` 记录结构化线索，供 Step 3 继承：
  ```python
  from src.analysis.consensus_tracker import ConsensusTracker
  tracker = ConsensusTracker(workspace_dir)
  tracker.record_snapshot(source="...", metrics={...}, confidence="low")
  tracker.add_expectation_gap(metric="...", period="...", consensus_value=..., our_value=...)
  ```
- 对 workspace 中已有 PDF/报告先做材料索引；若触发线索来自某份材料，记录一条最小 extraction：
  ```python
  from src.analysis.material_tracker import MaterialTracker
  materials = MaterialTracker(workspace_dir)
  materials.index_workspace_files()
  materials.record_extraction(document_ref="...", extraction_type="broker_assumption", topic="...", value="...", evidence="...")
  ```

## 决策原则

Quick Triage 只允许三种结论：

| 结论 | 定义 | 后续动作 |
|:--|:--|:--|
| PASS | 没有清晰预期差、催化剂弱、估值不便宜，或存在重大不可验证风险 | 停止，不进入七步深研，除非用户明确 override |
| WATCH | 有潜在线索，但关键证据不足或催化剂窗口未到 | 不进入深研，列出触发重启研究的监控条件 |
| FULL_RESEARCH | 存在可检验预期差、0-3 个月催化剂、初步赔率合理，且资料足够 | 继续 Step 1-7 |

## 输出模板

# Step 0: Quick Triage - {ticker}

## 0.1 One-Line Setup

用一句话说明：
- 这家公司是什么
- 市场可能错在哪里
- 为什么现在看

## 0.2 Initial Evidence

| 证据 | 来源 | 对 thesis 的影响 | 可信度 |
|:--|:--|:--|:--|
| ... | ... | positive / negative / neutral | high / medium / low |

要求：
- 区分事实、管理层口径、卖方观点和我们的推断
- 对所有数字标注来源
- 不得引用未经核实的估值倍数作为结论

## 0.3 Preliminary Expectation Gap

回答：
1. 当前市场显性共识是什么？
2. 我们可能不同意的地方是什么？
3. 这个差异是否能在 0-3 个月内被验证？
4. 如果市场共识是对的，最可能体现在哪个指标？
5. 是否已经更新 `consensus_snapshot.json`？如果没有，说明缺失原因。
6. 是否已经更新 `material_extracts.json`？如果没有，说明缺失原因。

## 0.4 Catalyst Window

| 催化剂 | 预计时间 | 方向 | 可验证指标 | 失败信号 |
|:--|:--|:--|:--|:--|
| ... | YYYY-MM-DD / range | positive / negative | ... | ... |

若 0-3 个月内没有明确催化剂，默认不得给 FULL_RESEARCH，除非存在极端估值错杀或结构性机会。

## 0.5 Valuation Sanity Check

只做粗筛，不做完整估值。

必须回答：
- 当前价格和日期是什么？
- 是否已有 `calculated_valuation.json`？
- 初步看估值是便宜、合理、偏贵，还是无法判断？
- 如果认为便宜，便宜相对于什么口径？必须说明 trailing / forward / historical / peer basis，不可混比。

禁止：
- 直接使用新闻、研报或第三方 API 的 PE/PB/PS 作为结论
- 将 trailing PE 与 forward PE 直接比较
- 将 T+1 与 T+2 forward PE 混比

## 0.6 Fatal Flaws and Missing Data

列出可能直接导致 PASS 的问题：

| 问题 | 为什么重要 | 如何验证 | 是否阻断 |
|:--|:--|:--|:--|
| ... | ... | ... | yes / no |

## 0.7 Triage Scorecard

每项 0-3 分：

| 维度 | 分数 | 理由 |
|:--|:--:|:--|
| 预期差清晰度 | 0-3 | ... |
| 0-3 个月催化剂强度 | 0-3 | ... |
| 初步赔率/估值吸引力 | 0-3 | ... |
| 业务质量/财务质量底线 | 0-3 | ... |
| 数据可得性与可验证性 | 0-3 | ... |
| **合计** | **0-15** | ... |

参考阈值：
- 0-5：PASS
- 6-9：WATCH
- 10-15：FULL_RESEARCH 候选，但若存在阻断性 fatal flaw，仍必须 PASS 或 WATCH

## 0.8 Decision

最终结论只能为：

**Decision: PASS / WATCH / FULL_RESEARCH**

必须附：
- 3 条最重要理由
- 若 PASS：说明什么新信息会让它重新进入 watchlist
- 若 WATCH：列出重启 full research 的触发条件和监控日期
- 若 FULL_RESEARCH：列出 Step 1-3 必须优先验证的 5 个问题

## 0.9 Contrarian Check

回答：

“我是否只是因为一个有趣新闻或便宜表象而想深研？如果不做这只股票，机会成本是什么？”

如果该问题揭示重大动机偏差，必须下调 Decision。

## Appendix A: Pre-Research Brief

Before starting Step 0, check for historical research that could inform the triage:

```python
from src.analysis.knowledge_graph import KnowledgeGraph

kg = KnowledgeGraph()
brief = kg.generate_research_brief(ticker, industry, themes)
```

If the workspace already has an open thesis (`thesis.json` exists and status is `open`), enter **incremental update mode** instead of a fresh triage:

```python
from src.analysis.thesis_tracker import ThesisTracker

tracker = ThesisTracker(workspace_dir)
brief = tracker.generate_update_brief()
# Returns: thesis summary, hypothesis status, catalyst decay, time since last update
```

In incremental update mode, only update what changed (new data, new catalysts, hypothesis validation). Do not redo the full 7-step pipeline unless the thesis has been invalidated.
