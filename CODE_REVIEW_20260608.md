# InvestPilot 深度 Code Review 报告

**日期**: 2026-06-08
**范围**: 全部源代码、测试、配置、Web 层
**代码库规模**: ~15,000 行 Python + ~2,000 行 TypeScript + 10 个 Prompt 模板

---

## 严重程度定义

| 级别 | 定义 |
|------|------|
| **P0 — Critical** | 数据错误、资金损失风险、数据丢失 |
| **P1 — High** | 逻辑错误导致分析偏差、安全漏洞 |
| **P2 — Medium** | 代码质量、性能、可维护性 |
| **P3 — Low** | 风格、文档、命名 |

---

## 一、P0 — Critical Bugs (必须修复)

### 1. `total_liab` 误用为 `total_debt` — EV 严重高估

**影响范围**: 3 个 fetcher, 影响所有 EV/EBITDA 估值

| 文件 | 行号 | 问题 |
|------|------|------|
| `src/data/ashare_fetcher.py` | L155 | `total_liab` (总负债) 当 `total_debt` (有息负债) 用 |
| `src/data/hk_fetcher.py` | L157 | 同上 |
| `src/data/us_fetcher.py` | L327-329, L358 | `Liabilities` (总负债) 当 `total_debt` |

**后果**: EV = market_cap + total_debt - cash。把总负债（含应付账款、预收款项等经营性负债）当有息负债，导致 EV 虚高 30-200%，EV/EBITDA 严重失真。

**修复**: 有息负债 = 短期借款 + 长期借款 + 应付债券 + 一年内到期的非流动负债。A-share 从 `balancesheet` 取 `st_borr + lt_borr + bond_payable + non_cur_liab_due_1y`；US 从 SEC filings 的 long-term debt + short-term debt borrowings。

---

### 2. `eps` 标注为 `eps_ttm` — TTM vs Period EPS 混淆

**文件**: `src/data/ashare_fetcher.py` L136

```python
"eps_ttm": row.get("eps"),  # 实际是单季度 EPS, 不是 TTM
```

**后果**: 下游估值（Forward PE = price / eps_ttm）使用单季度 EPS 当 TTM，导致 PE 偏高或偏低（取决于该季度 vs 全年平均利润）。所有 A-share 的 Forward PE 计算都可能出错。

**修复**: 用 `fina_indicator.eps` (TTM EPS) 或自行计算 TTM = Q1+Q2+Q3+Q4 rolling sum。

---

### 3. HK 销售净利率误标为 gross_margin

**文件**: `src/data/hk_fetcher.py` L163

```python
raw.get("销售净利率", ...),  # 这是 net margin, 不是 gross margin
```

**后果**: 所有港股的毛利率数据实际是净利率，导致毛利率分析（竞争力判断、同行比较）全部失真。

**修复**: AKShare 的 `stock_hk_financial_indicator_em` 返回的 `销售毛利率` 字段才是正确值。

---

### 4. Monte Carlo 顺序 Python 循环 — 性能 P0

**文件**: `src/analysis/monte_carlo.py` L334-338

100,000 次迭代用 `for i in range(n_sims)` 逐行执行，耗时 30-60 秒。

**修复**: 改为 NumPy 向量化：
```python
# 生成全部随机数 → t-Copula 变换 → 计算 EPS → 计算 target_price
# 预计从 30-60s 降至 ~0.5s
z = np.random.standard_t(df=6, size=(n_sims, n_vars))
# ... 一次性计算所有模拟路径
```

**注意**: 数学实现（t-Copula, BSM 反函数）经测试验证正确，只需向量化循环。

---

### 5. Workflow 版本迁移删除当前 Steps 4-7 数据

**文件**: `src/analysis/research_workflow.py` L73-80

```python
if previous_version < 3:
    obsolete.update({"4", "5", "6", "7"})  # 这些是当前步骤!
```

**后果**: 任何 `version < 3` 的 workspace 升级时，Steps 4-7 的完成状态被删除。已完成的财务模型、蒙特卡洛模拟结果将丢失。

**修复**: 确认旧版本 step ID 映射，将废弃步骤映射到新 ID 而非直接删除。

---

### 6. Thesis 历史版本共享引用导致数据篡改

**文件**: `src/analysis/thesis_tracker.py` L130-131

```python
"hypotheses": list(current.get("hypotheses", [])),  # 浅拷贝!
```

**后果**: `revise_thesis` 创建新版本时，hypotheses 列表内的 dict 是共享引用。修改新版本的 hypothesis 会同步修改旧版本的同名字段（如 `resolve_hypothesis` 修改 status）。

**修复**: `copy.deepcopy(current.get("hypotheses", []))`

---

## 二、P1 — High Severity

### 7. `sync_from_files` 可跳过 `in_progress` 状态

**文件**: `src/analysis/research_workflow.py` L107-129

`sync_from_files` 跳过 `completed`/`blocked`/`skipped` 状态，但**不跳过 `in_progress`**。如果一个 in_progress 的 step 的 artifact 文件已存在（上次运行残留），会被静默标记为 completed，绕过 workflow guard。

**修复**: 添加 `status == "in_progress"` 到跳过条件。

---

### 8. Knowledge Graph `record_outcome` 篡改历史记录

**文件**: `src/analysis/knowledge_graph.py` L257-260

```python
current["outcome"] = outcome       # current 是 history 中最后一项的引用
current["return_pct"] = return_pct  # 同时修改了历史记录
```

**修复**: `record_outcome` 时对 `current` 做 deep copy 再修改。

---

### 9. Catalyst time_decay 日期代理逻辑错误

**文件**: `src/analysis/catalyst_tracker.py` L153-156

用最早催化剂日期 `min(dates)` 代替 thesis 创建日期计算 `days_elapsed`。如果第一个催化剂是 60 天前的，decay modifier 会显示 "active_decay" 即使 thesis 昨天才创建。

**修复**: 从 `thesis.json` 读取 `created_at` 字段。

---

### 10. Consensus Tracker `snapshot()` 返回可变内部引用

**文件**: `src/analysis/consensus_tracker.py` L293

```python
def snapshot(self) -> dict:
    return self._data  # 直接返回内部可变对象
```

**修复**: `return copy.deepcopy(self._data)`

---

### 11. Web 前端 XSS — 未转义文件名

**文件**: `web/public/index.html` L265, L329

```html
<img ... alt="${img}">          <!-- XSS if filename contains " -->
<a href=".../${r}">             <!-- XSS if filename contains " or > -->
```

**修复**: 对文件名做 `encodeURIComponent()` 和 HTML entity 转义。

---

### 12. SEC EDGAR 无速率限制

**文件**: `src/data/us_fetcher.py` L60

SEC EDGAR 要求 10 requests/second，代码未实现任何速率限制。高频调用会触发 403 封禁。

**修复**: 添加 `time.sleep(0.1)` 间隔，设置 `User-Agent` header。

---

### 13. `config/settings.py` HK/US primary_source 配置错误

**文件**: `config/settings.py` L18, L24

```python
"HK": {"primary_source": "tushare"},  # 应为 "akshare"
"US": {"primary_source": "tushare"},  # 应为 "akshare" 或 "websearch"
```

与 CLAUDE.md 文档和实际代码路径矛盾。

---

### 14. Report Generator 硬编码年份 `"t1_2026E"`

**文件**: `src/report/generator.py` L434

```python
t1 = bridge.get('t1_2026E', {})  # 2027 年运行时 key 不匹配
```

**修复**: 动态计算 forward year: `f"t1_{current_year + 1}E"`。

---

## 三、P2 — Medium Severity

| # | 文件 | 行号 | 问题 |
|---|------|------|------|
| 15 | `src/analysis/valuation.py` | L167 | `except Exception` 返回空 dict，静默失败无日志 |
| 16 | `src/analysis/financial.py` | L798 | EBITDA 硬编码 1.2x 乘数 |
| 17 | `src/analysis/financial.py` | L993 | `acceleration` 变量计算但未返回（dead code） |
| 18 | `src/analysis/financial.py` | L829 | 现金流代理 `CA - CL` 过于粗糙 |
| 19 | `src/analysis/financial_model.py` | L505 | `paid_in_capital = equity * 0.5` 硬编码启发式 |
| 20 | `src/analysis/financial_model.py` | L498 | `prepaid_other_ca = revenue * 0.02` 硬编码 |
| 21 | `src/data/base.py` | L106 | `_compute_ev` 中 0 值 market_cap/debt 被当 None (falsy check) |
| 22 | `src/data/cache.py` | L43-46 | 子串匹配缓存失效可能命中错误文件 |
| 23 | `src/data/cache.py` | L34-38 | 空 DataFrame 被缓存，浪费空间 |
| 24 | `src/data/tushare_client.py` | L72 | Token 在 import 时读取 |
| 25 | `src/data/tushare_client.py` | L68-83 | 对不可重试异常做重试 |
| 26 | `src/storage.py` | L75,79 | `_atomic_write` 异常路径双重 `os.close(fd)` |
| 27 | `src/storage.py` | L36,88 | `filename` 参数无路径遍历验证 |
| 28 | `src/report/generator.py` | L1028-1033 | 货币检测逻辑脆弱（靠字符剥离判断市场） |
| 29 | `web/src/routes/files.ts` | L33,65 | `readFileSync` 无大小限制 — 大文件 DoS 风险 |
| 30 | `web/src/services/multipart.ts` | — | 手写 multipart 解析器无单元测试 |
| 31 | `web/src/routes/health.ts` | L7 | Health endpoint 泄露文件系统路径 |
| 32 | `web/src/routes/research.ts` | L36-43 | 重建 workspace 会覆盖 `user_notes.md` |
| 33 | `thesis_tracker.py` | L205 | 预确认守卫用 `notes='force'` 魔术字符串绕过 |
| 34 | `consensus_tracker.py` | L293 | `snapshot()` 返回内部可变引用 (同 #10) |
| 35 | `material_tracker.py` | L328-334 | 文件类型检测用子串匹配，误分类风险 |
| 36 | `edge_scorer.py` | L252-256 | 损坏的 `edge_score.json` 静默丢弃全部历史 |
| 37 | `config/ir_domains.py` | L12 | etnet 域名用 HTTP 而非 HTTPS |
| 38 | `_base.py` | L43-44 | 类属性 `_default_state` 共享可变状态风险 |
| 39 | `catalyst_tracker.py` | L147 | 直接读取 `thesis.json` — 跨模块耦合 |
| 40 | 全局 | — | 所有 `datetime.now()` 无时区，跨时区不一致 |

---

## 四、P3 — Low / Info

| # | 问题 |
|---|------|
| 41 | `thesis_tracker.py` L341: 错误消息说 "6-step"，实际是 9-step + Step 0 |
| 42 | `knowledge_graph.py` L313: `min_rrr` 参数标记 deprecated 但从未使用 (dead parameter) |
| 43 | `step_contracts.py` L55-60: `_load_raw_contracts` 被调用 3 次（未缓存） |
| 44 | `conftest.py`: 2 个 fixture 存在但 0 个测试文件使用（每个 test 文件自建 helper） |
| 45 | `config/settings.py` L10-11: import 时创建目录（副作用） |
| 46 | `report/_html_templates.py` L183: Font Awesome CDN 依赖 — 离线报告图标丢失 |
| 47 | `ticker_rules.py` L36: `.SH` 后缀被接受但从不被任何代码路径生成 |
| 48 | UUID 碰撞空间：6 hex chars = 16.7M，当前使用量 <100/类型，风险可忽略 |

---

## 五、测试覆盖率分析

### 统计

| 指标 | 值 |
|------|-----|
| 源代码行数 | ~15,000 (Python) + ~2,000 (TypeScript) |
| 测试代码行数 | 8,459 (Python) |
| 测试-代码比 | 0.56:1 |
| 总断言数 | ~1,330 |
| 零测试覆盖模块 | 7/33 (21%) |
| 参数化测试 | 1 个 (整个测试套件) |
| 集成测试 | 0 |

### 亮点

- **核心财务计算测试优秀**: DCF 手工验证、DuPont ROE 交叉验证、Monte Carlo BSM 反函数对比 scipy
- **Step 4 验证覆盖全面**: 25+ 验证规则全部有测试
- **测试隔离良好**: 全部使用 `tmp_path`，无共享状态

### 零覆盖关键模块 (P0 测试缺口)

| 模块 | 行数 | 风险 |
|------|------|------|
| `src/utils/web_date_verifier.py` | 347 | **安全关键** — 防止过期新闻污染研究 |
| `src/cli_post_research.py` | 580 | **每次研究后运行** — 报告生成失败 = 研究不完整 |
| `src/data/hk_fetcher.py` | ~250 | **主要市场** — AKShare API 变化无法提前发现 |
| `src/analysis/_utils.py` | ~50 | `coerce_float` 和 `is_pct_variable` 决定 pct→decimal 转换 |

### 建议的测试改进优先级

1. **P0**: 为 `web_date_verifier.py` 添加 ~30 个测试（各种日期格式、过期/新鲜/无日期页面）
2. **P0**: 为 `cli_post_research.py` 添加集成测试（完整 workspace → HTML 报告）
3. **P1**: 为 `hk_fetcher.py` 添加 mock AKShare 测试
4. **P1**: 将 6 个文件的 `_make_tracker()` helper 合并到 `conftest.py`
5. **P2**: 添加至少 1 个端到端测试（fetch → model → monte carlo → report）

---

## 六、修复优先级路线图

### 阶段 1: 数据正确性 (1-2 天)

1. **修复 `total_debt` 计算** (#1) — 所有 fetcher 的 EV 依赖此项
2. **修复 `eps_ttm` 标签** (#2) — 影响 Forward PE
3. **修复 HK gross_margin 标签** (#3) — 影响港股竞争力分析
4. **修复 `config/settings.py` primary_source** (#13) — 配置与代码不一致

### 阶段 2: 数据完整性 (1-2 天)

5. **修复 thesis 浅拷贝** (#6) — `deepcopy` 替代 `list()`
6. **修复 knowledge_graph 共享引用** (#8) — 同上
7. **修复 workflow 迁移逻辑** (#5) — 确认旧 step ID 映射
8. **修复 `sync_from_files` in_progress 跳过** (#7)
9. **修复 `snapshot()` 返回 deep copy** (#10)

### 阶段 3: 性能与安全 (2-3 天)

10. **Monte Carlo 向量化** (#4) — NumPy 批量计算，预计 60x 提速
11. **Web XSS 修复** (#11) — HTML entity 转义 + `encodeURIComponent`
12. **SEC EDGAR 速率限制** (#12) — 添加 100ms 间隔
13. **Report generator 硬编码年份** (#14) — 动态 forward year

### 阶段 4: 测试补充 (2-3 天)

14. `web_date_verifier.py` 测试 (30+ cases)
15. `cli_post_research.py` 集成测试
16. `hk_fetcher.py` mock 测试
17. 合并 `conftest.py` 共享 fixture

### 阶段 5: 代码质量 (持续)

18. P2 级别的 26 个中等严重度问题
19. 添加 parametrized tests
20. 1 个端到端集成测试

---

## 七、架构级观察

1. **fetcher 层的数据质量是最大风险点**: 3 个 fetcher 都有 `total_debt` 错误，说明数据映射缺乏验证。建议添加 `validate_fetch_result()` 方法，在 fetch 后自动校验关键字段范围（如 `total_debt < total_liab`）。

2. **908 行 `build_financial_model()` 函数**: 单一函数过长，硬编码启发式（`equity * 0.5`、`revenue * 0.02`）没有注释说明假设依据。建议拆分为子函数 + 配置化假设。

3. **tracker 层的深拷贝问题普遍存在**: `thesis_tracker`、`knowledge_graph`、`consensus_tracker` 都有浅拷贝/共享引用问题。建议在 `_base.py` 添加 `_deep_copy_state()` 工具方法。

4. **Web 层的 TypeScript 测试缺口**: 3 个测试文件 vs 14 个源文件，覆盖率远低于 Python 层。multipart parser 零测试尤其值得关注。

5. **无集成测试**: 全部 1,330 个断言都是单元测试。`fetch → model → monte_carlo → report` 这条关键路径从未被端到端验证过。

---

*Report generated by deep code review on 2026-06-08. Total findings: 48 (6 Critical, 8 High, 26 Medium, 8 Low/Info).*
