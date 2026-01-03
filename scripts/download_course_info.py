"""Fetch Udemy course detail page via Firecrawl and store as Markdown."""

from __future__ import annotations

import argparse
import os
import sys
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from urllib.parse import urlparse, urlunparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


def _strip_invalid_filename_chars(name: str) -> str:
    clean = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in name)
    return clean or "course_detail"


def _extract_title(response: Any) -> str | None:
    candidates = []
    if hasattr(response, "title"):
        candidates.append(response.title)
    if isinstance(response, dict):
        candidates.append(response.get("title"))
        for key in ("data", "result", "post", "metadata"):
            value = response.get(key)
            if isinstance(value, dict):
                candidates.append(value.get("title"))
    if hasattr(response, "metadata") and isinstance(response.metadata, dict):
        candidates.append(response.metadata.get("title"))
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def _extract_markdown(response: Any) -> str:
    if hasattr(response, "markdown"):
        return response.markdown
    if isinstance(response, dict):
        if "markdown" in response:
            return response["markdown"]
        data = response.get("data")
        if isinstance(data, dict) and "markdown" in data:
            return data["markdown"]
        if isinstance(data, str):
            return data
        if "content" in response:
            return response["content"]
    if hasattr(response, "data"):
        data = response.data
        if isinstance(data, dict) and "markdown" in data:
            return data["markdown"]
        if hasattr(data, "markdown"):
            return data.markdown
        if isinstance(data, str):
            return data
    if isinstance(response, str):
        return response
    return ""


def _normalize_course_url(url: str) -> str:
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    target = None
    if netloc == "udemy.com":
        target = "www.udemy.com"
    elif netloc.endswith(".udemy.com") and netloc != "www.udemy.com":
        target = "www.udemy.com"
    if target:
        parsed = parsed._replace(netloc=target)
    course_match = re.search(r"(/course/[^/]+)", parsed.path)
    if course_match:
        new_path = course_match.group(1) + "/"
        parsed = parsed._replace(path=new_path, params="", query="", fragment="")
    return urlunparse(parsed)


def fetch_course_detail(url: str, output: Path | None, main_only: bool) -> Path:
    try:
        from firecrawl import Firecrawl
    except ImportError:  # pragma: no cover
        print("需要安装 firecrawl-py，请运行: python -m pip install firecrawl-py")
        sys.exit(1)

    api_key = os.getenv("FIRECRAWL_API_KEY")
    if not api_key:
        print("错误: .env 中缺少 FIRECRAWL_API_KEY")
        sys.exit(1)

    client = Firecrawl(api_key=api_key)

    try:
        response = client.scrape(
            url,
            formats=["markdown"],
            only_main_content=main_only,
        )
    except TypeError:
        response = client.scrape(
            url,
            formats=["markdown"],
            onlyMainContent=main_only,
        )

    markdown = _extract_markdown(response)
    if not markdown:
        print("错误: Firecrawl 没有返回任何内容")
        sys.exit(1)

    title = _extract_title(response)
    if title and not markdown.lstrip().startswith("#"):
        markdown = f"# {title}\n\n{markdown}"

    output_dir = PROJECT_ROOT / "course_reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    if output is None:
        parsed = urlparse(url)
        slug_source = Path(parsed.path).stem or parsed.netloc or "course_detail"
        slug = _strip_invalid_filename_chars(slug_source)
        output = output_dir / f"{slug}.md"
    else:
        output = output if output.is_absolute() else (PROJECT_ROOT / output)
        output.parent.mkdir(parents=True, exist_ok=True)

    output.write_text(markdown, encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="使用 Firecrawl 抓取 Udemy 课程详情并输出 Markdown",
    )
    parser.add_argument("course_url", help="Udemy 课程详情页 URL")
    parser.add_argument(
        "--output",
        help="自定义输出路径（默认为 course_reports/<slug>.md）",
    )
    parser.add_argument(
        "--full-page",
        action="store_true",
        help="抓取完整页面（默认只抓取主体内容）",
    )
    args = parser.parse_args()

    if not args.course_url.startswith(("http://", "https://")):
        parser.error("URL 必须以 http:// 或 https:// 开头")

    normalized_url = _normalize_course_url(args.course_url)
    if normalized_url != args.course_url:
        print(f"提示: 已将 URL 标准化为 {normalized_url}")

    output_path = fetch_course_detail(
        url=normalized_url,
        output=Path(args.output) if args.output else None,
        main_only=not args.full_page,
    )
    print(f"✓ 课程详情已保存到: {output_path}")


if __name__ == "__main__":
    main()
