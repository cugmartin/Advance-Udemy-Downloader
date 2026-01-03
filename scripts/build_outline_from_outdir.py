#!/usr/bin/env python3
"""Generate Chapter Overview markdown from locally downloaded course directories (out_dir)."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = PROJECT_ROOT / "out_dir"

IGNORED_SUFFIXES = {
    ".srt",
    ".vtt",
    ".json",
    ".url",
    ".txt",
    ".log",
    ".tmp",
}


def _is_placeholder(entry: Path) -> bool:
    if entry.name.startswith("."):
        return True
    if entry.is_file() and entry.suffix.lower() in IGNORED_SUFFIXES:
        return True
    return False


def _collect_chapter_items(chapter_path: Path) -> list[str]:
    entries: list[str] = []
    for child in sorted(chapter_path.iterdir()):
        if child.is_dir():
            nested_files = [f.stem for f in child.iterdir() if f.is_file() and not _is_placeholder(f)]
            if nested_files:
                entries.append(f"{child.name}/")
            continue
        if _is_placeholder(child):
            continue
        entries.append(child.stem)
    return entries


def build_outline(course_dir: Path, course_title: str | None = None, include_title: bool = True) -> str:
    if not course_dir.exists() or not course_dir.is_dir():
        raise ValueError(f"目录不存在: {course_dir}")

    chapter_dirs: Iterable[Path] = sorted(
        [p for p in course_dir.iterdir() if p.is_dir()],
        key=lambda p: p.name,
    )
    chapters = []
    for chapter_path in chapter_dirs:
        items = _collect_chapter_items(chapter_path)
        chapters.append((chapter_path.name, items))

    content_lines: list[str] = []
    if include_title:
        title = course_title or course_dir.name
        content_lines.append(f"# {title} — Outline")
        content_lines.append("")
    content_lines.append("## Chapter Overview")
    content_lines.append("")

    has_content = False
    for idx, (chapter_name, items) in enumerate(chapters, start=1):
        content_lines.append(f"### {idx:02d} — {chapter_name} ({len(items)} items)")
        if not items:
            content_lines.append("_No lecture files found in this chapter._")
        else:
            for item_idx, item in enumerate(items, start=1):
                content_lines.append(f"{item_idx}. {item}")
        content_lines.append("")
        has_content = True

    if not has_content:
        content_lines.append("_No chapters detected in local directory._\n")

    return "\n".join(content_lines).strip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="从 out_dir 生成课程大纲 Markdown")
    parser.add_argument(
        "course_dir",
        help="课程根目录 (例如 out_dir/<course_name>)",
    )
    parser.add_argument(
        "--course-title",
        help="自定义标题（默认使用目录名）",
    )
    parser.add_argument(
        "--output",
        help="输出 Markdown 文件路径（默认打印到 stdout）",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    course_dir = Path(args.course_dir)
    outline_md = build_outline(course_dir, args.course_title, include_title=True)
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(outline_md, encoding="utf-8")
        print(f"✓ 章节大纲已写入: {out_path}")
    else:
        print(outline_md)


if __name__ == "__main__":
    main()
