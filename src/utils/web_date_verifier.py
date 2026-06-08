"""Web Date Verifier — 程序化验证 WebSearch 结果的实际发布日期。

解决的问题：WebSearch 工具可能返回 1-3 年前的旧文章，搜索引擎将历史热门内容
错误匹配为近期结果。本模块通过抓取源页面提取实际日期，防止过期信息被误引。

用法：
    from src.utils.web_date_verifier import verify_evidence_list

    evidence = [
        {"url": "https://...", "claim": "高盛下调至卖出", "source": "WebSearch"},
        {"url": "https://...", "claim": "董事长减持633万股", "source": "WebSearch"},
    ]
    results = verify_evidence_list(evidence, max_age_days=90)

    # results[i] 包含:
    #   - url, claim, source (原样保留)
    #   - actual_date: str|None  (页面提取的实际日期)
    #   - status: "ok" | "outdated" | "no_date" | "fetch_error"
    #   - message: str (human-readable 说明)

CLI:
    python -m src.cli verify-news <json_file>
    python -m src.cli verify-news --url "https://..." --max-age 90
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlparse

import requests

# ---------------------------------------------------------------------------
# Date extraction patterns
# ---------------------------------------------------------------------------

# ISO / numeric: 2026-06-08, 2026/06/08, 2026.06.08, 20260608
# Also handles Chinese: 2026年06月08日, 2026年6月8日
_RE_ISO = re.compile(
    r"(20\d{2})[/\-.年](0?[1-9]|1[0-2])[/\-.月](0?[1-9]|[12]\d|3[01])日?"
)

# Chinese relative dates
_RE_RELATIVE_CN = re.compile(
    r"(\d+)\s*(分钟|小时|天|周|个月|年)\s*前"
)

# Common news site meta tags
_META_DATE_PATTERNS = [
    # <meta property="article:published_time" content="2026-06-08T...">
    re.compile(r'property=["\']article:published_time["\'][^>]*content=["\']([^"\']+)["\']', re.I),
    # <meta name="publish_date" content="2026-06-08">
    re.compile(r'name=["\']publish_date["\'][^>]*content=["\']([^"\']+)["\']', re.I),
    # <meta name="date" content="2026-06-08">
    re.compile(r'name=["\']date["\'][^>]*content=["\']([^"\']+)["\']', re.I),
    # <meta itemprop="datePublished" content="2026-06-08">
    re.compile(r'itemprop=["\']datePublished["\'][^>]*content=["\']([^"\']+)["\']', re.I),
    # <time datetime="2026-06-08">
    re.compile(r'<time[^>]*datetime=["\']([^"\']+)["\']', re.I),
    # data-publishtime="2026-05-27 10:05:00" (Sina Finance)
    re.compile(r'data-publishtime=["\']([^"\']+)["\']', re.I),
    # <span class="date">2026年06月08日</span>  (common on Chinese sites)
    re.compile(r'class=["\'][^"\']*date[^"\']*["\'][^>]*>([^<]*20\d{2}[/\-.年]\d{1,2}[/\-.月]\d{1,2}[^<]*)', re.I),
]


@dataclass
class VerifyResult:
    url: str
    claim: str = ""
    source: str = ""
    actual_date: Optional[str] = None
    status: str = "unknown"  # ok | outdated | no_date | fetch_error
    message: str = ""
    fetched_at: str = ""
    raw_snippet: str = ""  # date 周围的上下文，用于人工复核


def _extract_date_from_url(url: str) -> Optional[str]:
    """从 URL 路径中提取日期（很多新闻 URL 包含日期，如 /2026-05-27/）。"""
    # Common URL date patterns: /2026-05-27/, /2026/05/27/, /20260527/
    m = re.search(r"/(20\d{2})[/\-](\d{1,2})[/\-](\d{1,2})/", url)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r"/(20\d{2})(\d{2})(\d{2})/", url)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


def _extract_date_from_html(html: str, url: str = "") -> Optional[str]:
    """从 HTML 中提取发布日期。优先级：meta标签 > URL日期 > 正文前部日期。"""
    candidates: list[str] = []

    # 1. Try meta tags first (most reliable)
    for pattern in _META_DATE_PATTERNS:
        for m in pattern.finditer(html):
            raw = m.group(1).strip()
            normalized = _normalize_date_str(raw)
            if normalized:
                candidates.append(("meta", normalized))

    # 2. Try URL extraction (very reliable for news sites)
    if url:
        url_date = _extract_date_from_url(url)
        if url_date:
            candidates.append(("url", url_date))

    # 3. Try ISO patterns in body text (first 3000 chars to avoid comments/ads)
    head = html[:3000]
    for m in _RE_ISO.finditer(head):
        raw = m.group(0)
        normalized = _normalize_date_str(raw)
        if normalized:
            candidates.append(("body", normalized))

    if not candidates:
        return None

    # Priority: meta > url > body
    priority = {"meta": 0, "url": 1, "body": 2}
    candidates.sort(key=lambda x: (priority.get(x[0], 99), x[1]))

    return candidates[0][1]


def _normalize_date_str(raw: str) -> Optional[str]:
    """将各种日期格式统一为 YYYY-MM-DD。"""
    raw = raw.strip()

    # ISO format: 2026-06-08 or 2026-06-08T12:00:00
    m = re.match(r"(20\d{2})[/\-.](\d{1,2})[/\-.](\d{1,2})", raw)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    # Chinese: 2026年06月08日 or 2026年6月8日
    m = re.match(r"(20\d{2})年(\d{1,2})月(\d{1,2})日?", raw)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    # Chinese with time: 2023年07月06日 20:41:04
    m = re.match(r"(20\d{2})年(\d{1,2})月(\d{1,2})日\s+\d{1,2}:\d{1,2}", raw)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    # Compact: 20260608
    m = re.match(r"(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])$", raw)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    return None


def _extract_context(html: str, date_str: str, window: int = 80) -> str:
    """提取日期在原文中的上下文，用于人工复核。"""
    idx = html.find(date_str)
    if idx < 0:
        # Try without leading zeros
        for m in _RE_ISO.finditer(html):
            if _normalize_date_str(m.group(0)) == date_str:
                idx = m.start()
                break
    if idx < 0:
        return ""
    start = max(0, idx - window)
    end = min(len(html), idx + len(date_str) + window)
    snippet = html[start:end].replace("\n", " ").strip()
    return f"...{snippet}..."


def verify_url(
    url: str,
    claim: str = "",
    source: str = "",
    max_age_days: int = 90,
    timeout: int = 15,
) -> VerifyResult:
    """验证单个 URL 的发布日期。

    Args:
        url: 要验证的网页 URL
        claim: 该条证据的描述（原样保留）
        source: 来源标注（原样保留）
        max_age_days: 最大允许天数，超过视为 outdated
        timeout: HTTP 请求超时秒数

    Returns:
        VerifyResult 包含验证状态和提取的日期
    """
    result = VerifyResult(
        url=url,
        claim=claim,
        source=source,
        fetched_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/131.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        result.status = "fetch_error"
        result.message = f"抓取失败: {e}"
        return result

    actual_date = _extract_date_from_html(html, url=url)

    if actual_date is None:
        result.status = "no_date"
        result.message = "页面中未找到明确的发布日期"
        return result

    result.actual_date = actual_date
    result.raw_snippet = _extract_context(html, actual_date)

    # Check age
    try:
        pub_dt = datetime.strptime(actual_date, "%Y-%m-%d")
        age_days = (datetime.now() - pub_dt).days
        if age_days > max_age_days:
            result.status = "outdated"
            result.message = (
                f"⚠️ 过期新闻！发布于 {actual_date}（{age_days} 天前），"
                f"超过 {max_age_days} 天窗口。不得作为最新证据引用。"
            )
        elif age_days < 0:
            result.status = "no_date"
            result.message = f"提取的日期 {actual_date} 在未来，可能为误提取"
        else:
            result.status = "ok"
            result.message = f"✅ 发布于 {actual_date}（{age_days} 天前），在有效窗口内"
    except ValueError:
        result.status = "no_date"
        result.message = f"日期格式无法解析: {actual_date}"

    return result


def verify_evidence_list(
    evidence: list[dict],
    max_age_days: int = 90,
    timeout: int = 15,
    fail_on_outdated: bool = False,
) -> list[dict]:
    """批量验证证据列表的发布日期。

    Args:
        evidence: 证据列表，每项至少包含 "url"，可选 "claim"、"source"
        max_age_days: 最大允许天数
        timeout: 每个 URL 的超时秒数
        fail_on_outdated: 如果为 True，遇到 outdated 则抛出异常

    Returns:
        验证结果列表（dict），包含原字段 + actual_date / status / message

    Raises:
        OutdatedEvidenceError: 当 fail_on_outdated=True 且存在过期证据时
    """
    results = []
    outdated_items = []

    for item in evidence:
        url = item.get("url", "")
        if not url:
            results.append({**item, "status": "no_url", "message": "缺少 URL", "actual_date": None})
            continue

        vr = verify_url(
            url=url,
            claim=item.get("claim", ""),
            source=item.get("source", ""),
            max_age_days=max_age_days,
            timeout=timeout,
        )
        results.append(asdict(vr))

        if vr.status == "outdated":
            outdated_items.append(vr)

    if fail_on_outdated and outdated_items:
        msgs = [f"  - {r.claim}: {r.message}" for r in outdated_items]
        raise OutdatedEvidenceError(
            f"发现 {len(outdated_items)} 条过期证据：\n" + "\n".join(msgs)
        )

    return results


def print_verification_report(results: list[dict], file=None) -> None:
    """打印人类可读的验证报告。"""
    out = file or sys.stdout

    ok_count = sum(1 for r in results if r.get("status") == "ok")
    outdated_count = sum(1 for r in results if r.get("status") == "outdated")
    no_date_count = sum(1 for r in results if r.get("status") == "no_date")
    error_count = sum(1 for r in results if r.get("status") == "fetch_error")

    print("=" * 60, file=out)
    print("Web Date Verification Report", file=out)
    print("=" * 60, file=out)
    print(f"Total: {len(results)} | ✅ OK: {ok_count} | ⚠️ Outdated: {outdated_count} "
          f"| ❓ No Date: {no_date_count} | ❌ Error: {error_count}", file=out)
    print("-" * 60, file=out)

    for i, r in enumerate(results, 1):
        status_icon = {
            "ok": "✅", "outdated": "⚠️", "no_date": "❓",
            "fetch_error": "❌", "no_url": "🚫",
        }.get(r.get("status"), "?")

        claim = r.get("claim", "")[:50]
        print(f"\n[{i}] {status_icon} {claim}", file=out)
        print(f"    URL: {r.get('url', '')[:80]}", file=out)
        print(f"    Date: {r.get('actual_date', 'N/A')}", file=out)
        print(f"    {r.get('message', '')}", file=out)

    if outdated_count > 0:
        print("\n" + "=" * 60, file=out)
        print("🚨 以下证据已过期，不得在报告中引用为最新信息：", file=out)
        for r in results:
            if r.get("status") == "outdated":
                print(f"  - {r.get('claim', 'N/A')}: {r.get('message', '')}", file=out)

    print(file=out)


class OutdatedEvidenceError(Exception):
    """当发现过期证据时抛出。"""
    pass


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    """CLI: python -m src.utils.web_date_verifier <args>"""
    import argparse

    parser = argparse.ArgumentParser(description="验证 WebSearch 结果的发布日期")
    parser.add_argument("input", nargs="?", help="JSON 文件路径（证据列表）")
    parser.add_argument("--url", help="单个 URL 验证")
    parser.add_argument("--max-age", type=int, default=90, help="最大允许天数 (default: 90)")
    parser.add_argument("--timeout", type=int, default=15, help="HTTP 超时秒数")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    args = parser.parse_args()

    if args.url:
        # Single URL mode
        result = verify_url(args.url, max_age_days=args.max_age, timeout=args.timeout)
        if args.json:
            print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        else:
            print_verification_report([asdict(result)])
    elif args.input:
        # Batch mode from JSON file
        with open(args.input, "r", encoding="utf-8") as f:
            evidence = json.load(f)
        results = verify_evidence_list(evidence, max_age_days=args.max_age, timeout=args.timeout)
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            print_verification_report(results)
    else:
        # Read from stdin
        evidence = json.load(sys.stdin)
        results = verify_evidence_list(evidence, max_age_days=args.max_age, timeout=args.timeout)
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            print_verification_report(results)


if __name__ == "__main__":
    main()
