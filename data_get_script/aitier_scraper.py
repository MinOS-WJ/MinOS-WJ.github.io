#!/usr/bin/env python3
"""Low-dependency scraper for AITier ranking pages.

The site is a Next.js application.  The ranking and model data are embedded in
the server-rendered RSC payload, so a browser or JavaScript runtime is not
required.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener


DEFAULT_CONFIG = Path(__file__).with_name("config.json")
DEFAULT_OUTPUT_DIR = Path(__file__).with_name("data")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36 "
    "AITierRankingCollector/1.0"
)
NEXT_PUSH_MARKER = "self.__next_f.push([1,"


class ScrapeError(RuntimeError):
    """Raised when a page cannot be fetched or parsed."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def timestamp(value: datetime | None = None) -> str:
    value = value or utc_now()
    return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8", newline="")
    os.replace(temporary, path)


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def load_config(path: Path) -> dict[str, Any]:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ScrapeError(f"配置文件不存在: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ScrapeError(f"配置文件不是有效 JSON: {path}: {exc}") from exc
    if not isinstance(config, dict) or not isinstance(config.get("domains"), dict):
        raise ScrapeError("配置文件必须包含 domains 对象")
    return config


def fetch_html(
    url: str,
    timeout: float,
    retries: int,
    opener: Any,
) -> tuple[str, dict[str, str]]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        "Accept-Encoding": "identity",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Referer": "https://aitier.net/zh/rankings",
    }
    last_error: Exception | None = None
    for attempt in range(1, retries + 2):
        try:
            request = Request(url, headers=headers, method="GET")
            with opener.open(request, timeout=timeout) as response:
                raw = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
                try:
                    html = raw.decode(charset)
                except (LookupError, UnicodeDecodeError):
                    html = raw.decode("utf-8", errors="replace")
                return html, {key: value for key, value in response.headers.items()}
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt <= retries:
                wait_seconds = min(30.0, 1.5 * (2 ** (attempt - 1)))
                logging.warning("请求失败，第 %s/%s 次重试，%.1f 秒后继续: %s", attempt, retries + 1, wait_seconds, exc)
                time.sleep(wait_seconds)
    raise ScrapeError(f"请求失败: {url}: {last_error}") from last_error


def _iter_next_payload_strings(html: str) -> Iterable[str]:
    decoder = json.JSONDecoder()
    start = 0
    while True:
        marker_index = html.find(NEXT_PUSH_MARKER, start)
        if marker_index < 0:
            return
        value_start = marker_index + len(NEXT_PUSH_MARKER)
        try:
            value, _ = decoder.raw_decode(html[value_start:])
        except json.JSONDecodeError:
            start = value_start
            continue
        if isinstance(value, str):
            yield value
        start = value_start + 1


def parse_rsc_data(html: str) -> dict[str, Any]:
    """Extract the page props containing initialRankings and initialModels."""
    for payload in _iter_next_payload_strings(html):
        if "initialRankings" not in payload:
            continue
        separator = payload.find(":")
        if separator < 0:
            continue
        try:
            tree = json.loads(payload[separator + 1 :])
        except json.JSONDecodeError:
            continue
        if not isinstance(tree, list) or len(tree) < 4 or not isinstance(tree[3], dict):
            continue
        props = tree[3]
        if isinstance(props.get("initialRankings"), list):
            return props
    raise ScrapeError("页面中未找到 initialRankings 数据，站点结构可能已变化")


def normalize_result(domain: str, url: str, props: dict[str, Any], fetched_at: str) -> dict[str, Any]:
    rankings = props.get("initialRankings")
    models = props.get("initialModels")
    if not isinstance(rankings, list):
        raise ScrapeError(f"{domain}: initialRankings 不是数组")
    if not isinstance(models, list):
        models = []
    models_by_id = {
        item.get("id"): item
        for item in models
        if isinstance(item, dict) and item.get("id") is not None
    }
    rows: list[dict[str, Any]] = []
    for ranking in rankings:
        if not isinstance(ranking, dict):
            continue
        row = dict(ranking)
        model_id = row.get("modelId")
        row["model"] = models_by_id.get(model_id)
        rows.append(row)
    return {
        "schema_version": 1,
        "fetched_at": fetched_at,
        "domain": domain,
        "url": url,
        "count": len(rows),
        "model_count": len(models),
        "rankings": rows,
        "models": models,
        "page_error": props.get("initialError"),
    }


def write_domain_files(
    output_dir: Path,
    result: dict[str, Any],
    raw_html: str | None = None,
    raw_suffix: str | None = None,
) -> None:
    domain = result["domain"]
    atomic_write_json(output_dir / f"{domain}.json", result)
    if raw_html is not None and raw_suffix is not None:
        raw_dir = output_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(raw_dir / f"{domain}_{raw_suffix}.html", raw_html)


def write_latest_files(output_dir: Path, run: dict[str, Any]) -> None:
    atomic_write_json(output_dir / "latest.json", run)


def scrape_once(
    config: dict[str, Any],
    output_dir: Path,
    selected_domains: list[str] | None,
    timeout: float,
    retries: int,
    delay: float,
    keep_raw: bool,
) -> dict[str, Any]:
    started_at = timestamp()
    configured_domains = config["domains"]
    names = selected_domains or list(configured_domains)
    unknown = [name for name in names if name not in configured_domains]
    if unknown:
        raise ScrapeError(f"配置中不存在的 domain: {', '.join(unknown)}")
    output_dir.mkdir(parents=True, exist_ok=True)
    opener = build_opener()
    domain_results: dict[str, dict[str, Any]] = {}
    success_count = 0
    for index, domain in enumerate(names):
        url = str(configured_domains[domain])
        if index:
            time.sleep(max(0.0, delay))
        logging.info("抓取 %s: %s", domain, url)
        try:
            html, headers = fetch_html(url, timeout, retries, opener)
            props = parse_rsc_data(unescape(html))
            result = normalize_result(domain, url, props, started_at)
            result["status"] = "ok"
            result["http_headers"] = {
                key.lower(): value
                for key, value in headers.items()
                if key.lower() in {"etag", "last-modified", "content-type", "cache-control"}
            }
            domain_results[domain] = result
            raw_name = started_at.replace(":", "").replace("-", "") if keep_raw else None
            write_domain_files(output_dir, result, html if raw_name else None, raw_name)
            success_count += 1
            logging.info("%s 完成：%s 条排行，%s 个模型", domain, result["count"], result["model_count"])
        except ScrapeError as exc:
            logging.error("%s 失败: %s", domain, exc)
            domain_results[domain] = {
                "status": "error",
                "domain": domain,
                "url": url,
                "count": 0,
                "model_count": 0,
                "error": str(exc),
            }
    run = {
        "schema_version": 1,
        "fetched_at": started_at,
        "status": "ok" if success_count == len(names) else ("partial" if success_count else "error"),
        "success_count": success_count,
        "domain_count": len(names),
        "domains": domain_results,
    }
    write_latest_files(output_dir, run)
    return run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="抓取 aitier.net 的全部排行榜数据")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="排行榜配置 JSON")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="输出目录，默认 data")
    parser.add_argument("--domain", nargs="+", dest="domains", help="只抓取指定 domain，可传多个")
    parser.add_argument("--interval-minutes", type=float, default=0, help="大于 0 时按间隔持续运行")
    parser.add_argument("--timeout", type=float, default=45, help="单次 HTTP 请求超时秒数")
    parser.add_argument("--retries", type=int, default=2, help="失败后的重试次数")
    parser.add_argument("--delay", type=float, default=1.0, help="domain 之间的间隔秒数")
    parser.add_argument("--keep-raw", action="store_true", help="额外保存每次抓到的原始 HTML")
    parser.add_argument("--verbose", action="store_true", help="输出调试日志")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    if args.timeout <= 0 or args.retries < 0 or args.delay < 0:
        parser.error("timeout 必须大于 0，retries 和 delay 不能为负数")
    try:
        config = load_config(args.config)
    except ScrapeError as exc:
        logging.error("%s", exc)
        return 2
    while True:
        try:
            run = scrape_once(
                config,
                args.output_dir,
                args.domains,
                args.timeout,
                args.retries,
                args.delay,
                args.keep_raw,
            )
        except ScrapeError as exc:
            logging.error("本轮采集失败: %s", exc)
            return 1
        logging.info("本轮结束：%s，成功 %s/%s", run["status"], run["success_count"], run["domain_count"])
        if args.interval_minutes <= 0:
            return 0 if run["success_count"] else 1
        wait_seconds = args.interval_minutes * 60
        logging.info("下一轮将在 %.1f 分钟后开始，按 Ctrl+C 停止", args.interval_minutes)
        try:
            time.sleep(wait_seconds)
        except KeyboardInterrupt:
            logging.info("已停止")
            return 0


if __name__ == "__main__":
    sys.exit(main())
