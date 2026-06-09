"""Known-working IR / financial data domains for WebFetch and WebSearch.

When a primary IR page (e.g. company.com/investor) is blocked by security policy,
use these alternative domains.  Grouped by market.
"""

# HK stock filing & data sources
HK_IR_DOMAINS = {
    "hkex_news": "https://www1.hkexnews.hk/search/titlesearch.xhtml",
    "aastocks": "https://www.aastocks.com/en/stocks/analysis/company-fundamental/",
    "etnet": "https://warrants.etnet.com.hk/www/sc/stocks/realtime/quote_ci_pl.php",
    "futunn": "https://www.futunn.com/en/stock/{ticker}-HK/financials-income-statement",
    "stockanalysis": "https://stockanalysis.com/quote/hkg/{ticker}/financials/",
    "investing": "https://uk.investing.com/equities/{name}-financial-summary",
    "marketscreener": "https://in.marketscreener.com/quote/stock/{name}/finances/",
    "yahoo": "https://finance.yahoo.com/quote/{ticker}.HK/key-statistics/",
}

# US stock filing & data sources
US_IR_DOMAINS = {
    "sec_edgar": "https://www.sec.gov/cgi-bin/browse-edgar",
    "stockanalysis": "https://stockanalysis.com/stocks/{ticker}/financials/",
    "yahoo": "https://finance.yahoo.com/quote/{ticker}/key-statistics/",
    "investing": "https://www.investing.com/equities/{name}-financial-summary",
    "marketscreener": "https://www.marketscreener.com/quote/stock/{name}/finances/",
    "roic_ai": "https://roic.ai/quote/{ticker}",
}

# Chinese financial data portals (for A-share / HK Chinese-language reports)
CN_FINANCIAL_DOMAINS = {
    "eastmoney": "https://finance.eastmoney.com/",
    "10jqka": "https://stock.10jqka.com.cn/",
    "hexun": "https://stock.hexun.com/",
    "gelonghui": "https://www.gelonghui.com/",
    "xueqiu": "https://xueqiu.com/S/{ticker}/",
    "futunn_cn": "https://news.futunn.com/post/{post_id}",
}

# Domains known to work with mcp__web-reader__webReader MCP tool
WEBREADER_FRIENDLY_DOMAINS = [
    "finance.yahoo.com",
    "www.investing.com",
    "stockanalysis.com",
    "www.marketscreener.com",
    "www.aastocks.com",
]
