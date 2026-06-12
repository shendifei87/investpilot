#!/usr/bin/env python3
"""Tushare MCP Proxy — exposes only whitelisted tools via tushare SDK.

Reduces tool count from 255 to ~30, saving ~40K+ tokens of system prompt.
Runs as a stdio MCP server; forwards tool calls to tushare.pro_api().
"""

from __future__ import annotations

import os
from typing import Any

import mcp.types as types
import tushare as ts
from mcp.server import Server
from mcp.server.stdio import stdio_server

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TUSHARE_TOKEN = os.environ.get(
    "TUSHARE_TOKEN",
    "0c6d2b8dbc4f7ff8380db634dd51098a22102df0cde48e14d1235e32",
)

# 23 tools actually referenced in prompt files + a few useful extras.
# Key = tushare API method name, value = (description, param_schema).
WHITELIST: dict[str, tuple[str, dict[str, dict[str, str]]]] = {
    # ── 行情数据 ──
    "daily": (
        "股票日线行情",
        {
            "ts_code": "股票代码(支持多代码逗号分隔)",
            "trade_date": "交易日期YYYYMMDD",
            "start_date": "开始日期YYYYMMDD",
            "end_date": "结束日期YYYYMMDD",
        },
    ),
    "daily_basic": (
        "每日指标(PE/PB/PS/市值/换手率等)",
        {
            "ts_code": "股票代码",
            "trade_date": "交易日期YYYYMMDD",
            "start_date": "开始日期YYYYMMDD",
            "end_date": "结束日期YYYYMMDD",
        },
    ),
    "adj_factor": (
        "复权因子",
        {
            "ts_code": "股票代码",
            "trade_date": "交易日期YYYYMMDD",
            "start_date": "开始日期YYYYMMDD",
            "end_date": "结束日期YYYYMMDD",
        },
    ),
    "stk_limit": (
        "每日涨跌停价格",
        {
            "ts_code": "股票代码",
            "trade_date": "交易日期YYYYMMDD",
            "start_date": "开始日期YYYYMMDD",
            "end_date": "结束日期YYYYMMDD",
        },
    ),
    # ── 财务数据 ──
    "income": (
        "利润表",
        {
            "ts_code": "股票代码",
            "ann_date": "公告日期YYYYMMDD",
            "start_date": "公告开始日期YYYYMMDD",
            "end_date": "公告结束日期YYYYMMDD",
            "period": "报告期(如20241231)",
            "report_type": "报告类型",
        },
    ),
    "balancesheet": (
        "资产负债表",
        {
            "ts_code": "股票代码",
            "ann_date": "公告日期YYYYMMDD",
            "start_date": "公告开始日期YYYYMMDD",
            "end_date": "公告结束日期YYYYMMDD",
            "period": "报告期(如20241231)",
        },
    ),
    "cashflow": (
        "现金流量表",
        {
            "ts_code": "股票代码",
            "ann_date": "公告日期YYYYMMDD",
            "start_date": "公告开始日期YYYYMMDD",
            "end_date": "公告结束日期YYYYMMDD",
            "period": "报告期(如20241231)",
        },
    ),
    "fina_indicator": (
        "财务指标(EPS/ROE/毛利率/负债率等)",
        {
            "ts_code": "股票代码",
            "ann_date": "公告日期YYYYMMDD",
            "start_date": "公告开始日期YYYYMMDD",
            "end_date": "公告结束日期YYYYMMDD",
            "period": "报告期(如20241231)",
        },
    ),
    "fina_mainbz": (
        "主营业务构成(按产品/地区/行业)",
        {
            "ts_code": "股票代码",
            "period": "报告期(如20241231)",
            "type": "类型:P产品 D地区 I行业",
        },
    ),
    "forecast": (
        "业绩预告",
        {
            "ts_code": "股票代码",
            "ann_date": "公告日期YYYYMMDD",
            "start_date": "公告开始日期YYYYMMDD",
            "end_date": "公告结束日期YYYYMMDD",
            "period": "报告期(如20241231)",
        },
    ),
    "express": (
        "业绩快报",
        {
            "ts_code": "股票代码",
            "ann_date": "公告日期YYYYMMDD",
            "start_date": "公告开始日期YYYYMMDD",
            "end_date": "公告结束日期YYYYMMDD",
            "period": "报告期(如20241231)",
        },
    ),
    "dividend": (
        "分红送股数据",
        {
            "ts_code": "股票代码",
            "ann_date": "公告日期YYYYMMDD",
            "record_date": "股权登记日YYYYMMDD",
            "ex_date": "除权除息日YYYYMMDD",
        },
    ),
    # ── 基础数据 ──
    "stock_basic": (
        "股票列表(代码/名称/行业/上市日期等)",
        {
            "ts_code": "股票代码",
            "name": "名称",
            "exchange": "交易所:SSE/SZSE/BSE",
            "market": "市场类别",
            "list_status": "上市状态:L上市 D退市",
        },
    ),
    "stock_company": (
        "上市公司基本信息(法人/注册资本/地址等)",
        {
            "ts_code": "股票代码",
            "exchange": "交易所:SSE/SZSE/BSE",
        },
    ),
    "top10_holders": (
        "前十大股东",
        {
            "ts_code": "股票代码",
            "period": "报告期(如20241231)",
            "ann_date": "公告日期YYYYMMDD",
            "start_date": "公告开始日期YYYYMMDD",
            "end_date": "公告结束日期YYYYMMDD",
        },
    ),
    "top10_floatholders": (
        "前十大流通股东",
        {
            "ts_code": "股票代码",
            "period": "报告期(如20241231)",
            "ann_date": "公告日期YYYYMMDD",
            "start_date": "公告开始日期YYYYMMDD",
            "end_date": "公告结束日期YYYYMMDD",
        },
    ),
    "stk_holdernumber": (
        "股东人数",
        {
            "ts_code": "股票代码",
            "ann_date": "公告日期YYYYMMDD",
            "start_date": "公告开始日期YYYYMMDD",
            "end_date": "公告结束日期YYYYMMDD",
        },
    ),
    # ── 资金流向 ──
    "moneyflow_dc": (
        "个股资金流向(东方财富)",
        {
            "ts_code": "股票代码",
            "trade_date": "交易日期YYYYMMDD",
            "start_date": "开始日期YYYYMMDD",
            "end_date": "结束日期YYYYMMDD",
        },
    ),
    "moneyflow": (
        "个股资金流向(Tushare)",
        {
            "ts_code": "股票代码",
            "trade_date": "交易日期YYYYMMDD",
            "start_date": "开始日期YYYYMMDD",
            "end_date": "结束日期YYYYMMDD",
        },
    ),
    "moneyflow_hsgt": (
        "沪深港通资金流向",
        {
            "trade_date": "交易日期YYYYMMDD",
            "start_date": "开始日期YYYYMMDD",
            "end_date": "结束日期YYYYMMDD",
        },
    ),
    "hk_hold": (
        "沪深股通持股明细",
        {
            "ts_code": "股票代码",
            "trade_date": "交易日期YYYYMMDD",
            "start_date": "开始日期YYYYMMDD",
            "end_date": "结束日期YYYYMMDD",
            "exchange": "类型:SH/SZ/HK",
        },
    ),
    "margin_detail": (
        "融资融券交易明细",
        {
            "ts_code": "股票代码",
            "trade_date": "交易日期YYYYMMDD",
            "start_date": "开始日期YYYYMMDD",
            "end_date": "结束日期YYYYMMDD",
        },
    ),
    # ── 公司行为 ──
    "block_trade": (
        "大宗交易",
        {
            "ts_code": "股票代码",
            "trade_date": "交易日期YYYYMMDD",
            "start_date": "开始日期YYYYMMDD",
            "end_date": "结束日期YYYYMMDD",
        },
    ),
    "repurchase": (
        "股票回购",
        {
            "ann_date": "公告日期YYYYMMDD",
            "start_date": "公告开始日期YYYYMMDD",
            "end_date": "公告结束日期YYYYMMDD",
        },
    ),
    "stk_holdertrade": (
        "股东增减持",
        {
            "ts_code": "股票代码",
            "ann_date": "公告日期YYYYMMDD",
            "start_date": "公告开始日期YYYYMMDD",
            "end_date": "公告结束日期YYYYMMDD",
        },
    ),
    "pledge_detail": (
        "股权质押明细",
        {
            "ts_code": "股票代码",
        },
    ),
    # ── 行业/指数 ──
    "sw_daily": (
        "申万行业指数日行情",
        {
            "ts_code": "行业代码",
            "trade_date": "交易日期YYYYMMDD",
            "start_date": "开始日期YYYYMMDD",
            "end_date": "结束日期YYYYMMDD",
        },
    ),
    "index_member_all": (
        "申万行业成分(分级)",
        {
            "ts_code": "股票代码",
            "l1_code": "一级行业代码",
            "l2_code": "二级行业代码",
            "l3_code": "三级行业代码",
            "is_new": "是否最新(Y/N)",
        },
    ),
    "index_daily": (
        "指数日线行情",
        {
            "ts_code": "指数代码",
            "trade_date": "交易日期YYYYMMDD",
            "start_date": "开始日期YYYYMMDD",
            "end_date": "结束日期YYYYMMDD",
        },
    ),
    # ── 龙虎榜 ──
    "top_list": (
        "龙虎榜每日交易明细",
        {
            "trade_date": "交易日期YYYYMMDD",
            "ts_code": "股票代码",
        },
    ),
    "top_inst": (
        "龙虎榜机构交易明细",
        {
            "trade_date": "交易日期YYYYMMDD",
            "ts_code": "股票代码",
        },
    ),
    # ── 港股(补充) ──
    "hk_basic": (
        "港股列表信息",
        {
            "ts_code": "股票代码",
            "list_status": "上市状态:L/D",
        },
    ),
    "hk_daily": (
        "港股日线行情",
        {
            "ts_code": "股票代码(如0700.HK)",
            "start_date": "开始日期YYYYMMDD",
            "end_date": "结束日期YYYYMMDD",
        },
    ),
    "hk_fina_indicator": (
        "港股财务指标",
        {
            "ts_code": "股票代码",
            "start_date": "开始日期YYYYMMDD",
            "end_date": "结束日期YYYYMMDD",
        },
    ),
}

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

server = Server("tushare-proxy")
pro = ts.pro_api(TUSHARE_TOKEN)


def _build_tool_schemas() -> list[types.Tool]:
    """Build tool definitions from whitelist."""
    tools: list[types.Tool] = []
    for name, (desc, params) in WHITELIST.items():
        properties: dict[str, dict[str, str]] = {}
        for pname, pdesc in params.items():
            properties[pname] = {"type": "string", "description": pdesc}
        tools.append(
            types.Tool(
                name=name,
                description=desc,
                inputSchema={
                    "type": "object",
                    "properties": properties,
                },
            )
        )
    return tools


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return _build_tool_schemas()


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    if name not in WHITELIST:
        return [types.TextContent(type="text", text=f"Error: tool '{name}' not in whitelist")]

    # Filter out None / empty-string args — tushare rejects them
    clean_args = {k: v for k, v in (arguments or {}).items() if v is not None and v != ""}

    try:
        func = getattr(pro, name)
        df = func(**clean_args)

        if df is None or df.empty:
            return [types.TextContent(type="text", text="[]")]

        result = df.to_json(orient="records", force_ascii=False)
        return [types.TextContent(type="text", text=result)]

    except Exception as e:
        return [types.TextContent(type="text", text=f"Error calling tushare {name}: {e}")]


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        init_options = server.create_initialization_options()
        await server.run(read_stream, write_stream, init_options)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
