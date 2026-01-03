#!/usr/bin/env python3
"""Orchestrate Firecrawl scraping + Markdown parsing + local Chapter Overview injection."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv
from urllib.parse import urlparse

try:  # Support running from repo root or from scripts/ via PYTHONPATH tweaks
    from scripts.build_outline_from_outdir import DEFAULT_OUT_DIR, build_outline
except ModuleNotFoundError:  # pragma: no cover
    from build_outline_from_outdir import DEFAULT_OUT_DIR, build_outline


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOWNLOAD_SCRIPT = PROJECT_ROOT / "scripts" / "download_course_info.py"
PARSE_SCRIPT = PROJECT_ROOT / "scripts" / "parse_course_report.py"

ANSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def _strip_invalid_filename_chars(name: str) -> str:
    clean = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in name)
    return clean or "course_detail"


def _extract_course_slug(path: str) -> str | None:
    match = re.search(r"/course/([^/]+)/?", path)
    if match:
        return match.group(1)
    return None


def slug_from_url(url: str) -> str:
    parsed = urlparse(url)
    slug_source = _extract_course_slug(parsed.path)
    if not slug_source:
        slug_source = Path(parsed.path).stem or parsed.netloc or "course_detail"
    return _strip_invalid_filename_chars(slug_source)


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def _stream_process(cmd: list[str], cwd: Path | None = None) -> None:
    process = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    assert process.stdout is not None
    for line in process.stdout:
        sys.stdout.write(line)
    ret = process.wait()
    if ret != 0:
        raise RuntimeError(f"命令执行失败: {' '.join(cmd)}")


def run_download_script(course_url: str, output: Path, full_page: bool) -> None:
    cmd = [sys.executable, str(DOWNLOAD_SCRIPT), course_url, "--output", str(output)]
    if full_page:
        cmd.append("--full-page")
    _stream_process(cmd)


def run_parse_script(raw_path: Path, summary_path: Path) -> None:
    cmd = [
        sys.executable,
        str(PARSE_SCRIPT),
        str(raw_path),
        "--output",
        str(summary_path),
    ]
    _stream_process(cmd)


def resolve_local_course_dir(slug: str, override: str | None) -> Path:
    if override:
        candidate = Path(override)
        if not candidate.exists():
            raise FileNotFoundError(f"指定的 --course-dir 不存在: {candidate}")
        return candidate

    direct = DEFAULT_OUT_DIR / slug
    if direct.exists():
        return direct

    if DEFAULT_OUT_DIR.exists():
        slug_target = slugify(slug)
        for path in DEFAULT_OUT_DIR.iterdir():
            if path.is_dir() and slugify(path.name) == slug_target:
                return path

    raise FileNotFoundError(
        f"未在 {DEFAULT_OUT_DIR} 中找到课程目录（slug: {slug}）。"
        " 请先运行 main.py 下载课程或使用 --course-dir 指定目录。"
    )


def build_overview_markdown(course_dir: Path) -> str:
    overview = build_outline(course_dir, include_title=False).strip()
    if not overview:
        raise RuntimeError(f"目录 {course_dir} 未生成任何大纲内容。")
    return overview + "\n\n"


def insert_overview(summary_text: str, overview_md: str) -> str:
    overview_md = overview_md.strip()
    if not overview_md:
        return summary_text
    marker = "\n## Requirements"
    idx = summary_text.find(marker)
    if idx == -1:
        return summary_text.rstrip() + "\n\n" + overview_md + "\n"
    insertion_point = idx
    return (
        summary_text[:insertion_point].rstrip()
        + "\n\n"
        + overview_md
        + "\n"
        + summary_text[insertion_point:]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Firecrawl scrape + parse + local Chapter Overview injection.",
    )
    parser.add_argument("course_url", help="Udemy course URL（可为 lecture 链接）")
    parser.add_argument(
        "--full-page",
        action="store_true",
        help="传递 --full-page 给 download_course_info.py",
    )
    parser.add_argument(
        "--raw",
        help="原始 Firecrawl Markdown 路径（默认: course_reports/<slug>.md）",
    )
    parser.add_argument(
        "--summary",
        help="清洗后摘要路径（默认: course_reports/<slug>_summary.md）",
    )
    parser.add_argument(
        "--final",
        help="最终输出路径（默认: course_reports/<slug>_final.md）",
    )
    parser.add_argument(
        "--course-dir",
        help="已下载课程目录，若提供则直接使用，不再自动匹配 slug。",
    )
    return parser.parse_args()


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    args = parse_args()

    slug = slug_from_url(args.course_url)
    reports_dir = PROJECT_ROOT / "course_reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    raw_path = Path(args.raw) if args.raw else reports_dir / f"{slug}.md"
    summary_path = Path(args.summary) if args.summary else reports_dir / f"{slug}_summary.md"
    final_path = Path(args.final) if args.final else reports_dir / f"{slug}_final.md"

    print("▶️ 1/3 下载课程详情（Firecrawl）")
    run_download_script(args.course_url, raw_path, args.full_page)

    print("▶️ 2/3 生成清洗后的摘要")
    run_parse_script(raw_path, summary_path)

    print("▶️ 3/3 解析本地课程目录以生成 Chapter Overview")
    course_dir = resolve_local_course_dir(slug, args.course_dir)
    overview_md = build_overview_markdown(course_dir)

    summary_text = summary_path.read_text(encoding="utf-8")
    merged = insert_overview(summary_text, overview_md)
    final_path.write_text(merged, encoding="utf-8")

    print(f"✅ 最终文档已生成: {final_path}")


if __name__ == "__main__":
    main()
