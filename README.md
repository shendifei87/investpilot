# InvestPilot

基于 Claude Code 的深度基本面投研框架。寻找估值被显著低估的股票（高赔率 + 高胜率），核心是识别预期差并在 0-3 个月内兑现。

## 特性

- **七步深度投研流程** — 业务分析 → 护城河 → 边际变化 → 量化建模 → 交易策略 → 审计 → 研究总监审核
- **蒙特卡洛模拟** — t-Copula 依赖结构 + Kelly 仓位管理
- **多市场支持** — A 股、港股、美股（数据源：Tushare Pro）
- **预期差驱动** — Edge 分类评分 + 催化剂时间衰减追踪
- **知识图谱** — 跨股票研究经验积累与模式匹配
- **自包含 HTML 报告** — 内联 CSS + base64 图表嵌入

## 安装

```bash
# 需要 Python 3.9+
pip install -e ".[dev]"
```

或手动安装依赖：

```bash
pip install tushare pandas numpy scipy matplotlib requests tabulate pytest
```

## 配置

设置 Tushare Pro API Token：

```bash
export TUSHARE_TOKEN="your_token_here"
```

在 [tushare.pro](https://tushare.pro) 注册获取 Token。

## 快速开始

### 1. 创建 Workspace

```bash
mkdir -p workspaces/AAPL
# 将年报 PDF 和券商研报放入该目录
```

### 2. 数据抓取

```bash
# 检测市场
python -m src.cli detect AAPL
# → {"market": "US", "normalized": "AAPL"}

# 抓取数据到 workspace
python -m src.cli fetch AAPL -o workspaces/AAPL
```

### 3. 启动投研

在 Claude Code 中输入股票代码即可触发七步分析流程：

```
> 研究 AAPL
```

详细流程参见 [CLAUDE.md](CLAUDE.md)。

## CLI 命令

| 命令 | 说明 |
|:-----|:-----|
| `detect <ticker>` | 检测股票市场（A股/港股/美股） |
| `fetch <ticker>` | 抓取数据到 workspace |
| `fetch-peers <ticker>` | 抓取同业数据 |
| `analyze <ticker>` | 技术指标分析（MA/RSI/MACD） |
| `thesis <action>` | 管理 investment thesis |
| `catalyst <action>` | 催化剂追踪 |
| `knowledge <action>` | 知识图谱操作 |
| `report <workspace>` | 生成 HTML 研报 |

## 项目结构

```
investpilot/
├── CLAUDE.md              # 投研框架主 prompt（七步流程定义）
├── config/                # 配置（市场规则、阈值、权重）
├── prompts/               # 七步 prompt 模板
├── src/
│   ├── cli.py             # CLI 入口
│   ├── storage.py         # 原子化 JSON 存储
│   ├── analysis/          # 分析引擎
│   │   ├── financial.py   # 财务分析（PE/PB/PS/EV, 盈余质量评分）
│   │   ├── monte_carlo.py # 蒙特卡洛模拟 + Kelly
│   │   ├── valuation.py   # DCF / Reverse DCF / PE Band
│   │   ├── step4_validate.py  # Step 4 预检（15 项验证）
│   │   ├── thesis_tracker.py  # Thesis 生命周期管理
│   │   ├── catalyst_tracker.py # 催化剂追踪 + 时间衰减
│   │   ├── edge_scorer.py     # Edge 四维评分
│   │   └── knowledge_graph.py # 跨股票知识图谱
│   ├── data/              # 数据抓取层
│   │   ├── ashare_fetcher.py  # A 股（Tushare）
│   │   ├── hk_fetcher.py      # 港股（Tushare）
│   │   ├── us_fetcher.py      # 美股（Tushare）
│   │   └── tushare_client.py  # Tushare API 统一客户端
│   └── report/            # 报告生成（HTML + Markdown）
├── tests/                 # 测试套件（172 项测试）
└── workspaces/            # 按股票代码组织的研究数据
```

## 运行测试

```bash
python -m pytest tests/ -v
```

## 市场规则

| 市场 | 报告语言 | Ticker 格式 | 示例 |
|:-----|:---------|:-----------|:-----|
| A 股 | 中文 | `600xxx.SS` / `000xxx.SZ` | `600519`, `000001.SZ` |
| 港股 | 中文 | `xxxx.HK` | `0700.HK`, `9988.HK` |
| 美股 | 英文 | `XXXX` | `AAPL`, `TSLA` |

## License

Private — for personal research use only.
