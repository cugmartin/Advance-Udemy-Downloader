#!/usr/bin/env python3
"""Parse course report Markdown files and emit human-readable Markdown summaries."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any


SECTION_ALIASES = {
    "what_you_learn": ["what you'll learn"],
    "requirements": ["requirements"],
    "description": ["description"],
    "course_includes": ["this course includes"],
    "audience": ["who this course is for"],
}

MODULE_HEADING = re.compile(r"^\*\*(.+?)\*\*:?$")  # e.g. **DIGITAL MARKETING STRATEGY**
NUMBERED_ITEM = re.compile(r"^\s*\d{1,2}\.\s+(.*)")


def normalize_heading(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().strip(":").lower()


def collapse_lines(lines: list[str]) -> str:
    return "\n".join(line.rstrip() for line in lines).strip()


def extract_title_and_subtitle(lines: list[str]) -> tuple[str | None, str | None]:
    for idx, raw in enumerate(lines):
        stripped = raw.strip()
        if stripped.startswith("# "):
            title = stripped[2:].strip()
            subtitle = None
            for candidate in lines[idx + 1 :]:
                nxt = candidate.strip()
                if not nxt:
                    continue
                if nxt.startswith("#"):
                    break
                subtitle = nxt
                break
            return title, subtitle
    return None, None


def build_sections(lines: list[str]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw in lines:
        stripped = raw.rstrip()
        if stripped.startswith("## "):
            heading = normalize_heading(stripped[3:])
            current = heading
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(raw)
    return sections


def extract_bullets(lines: list[str]) -> list[str]:
    items: list[str] = []
    for raw in lines:
        stripped = raw.strip()
        if stripped.startswith("- "):
            value = stripped[2:].strip()
            if value:
                items.append(value)
    # preserve order but drop duplicates
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def extract_modules(description_lines: list[str]) -> list[dict[str, Any]]:
    modules: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw in description_lines:
        stripped = raw.strip()
        if not stripped:
            continue
        heading_match = MODULE_HEADING.match(stripped)
        if heading_match:
            title = heading_match.group(1).strip()
            if title:
                current = {"title": title, "items": []}
                modules.append(current)
            continue
        number_match = NUMBERED_ITEM.match(stripped)
        if number_match and current:
            current["items"].append(number_match.group(1).strip())
            continue
        if stripped.startswith("- ") and current:
            current["items"].append(stripped[2:].strip())
    return [module for module in modules if module["items"]]


def get_section_lines(sections: dict[str, list[str]], aliases: list[str]) -> list[str]:
    normalized_aliases = {normalize_heading(alias) for alias in aliases}
    for heading, lines in sections.items():
        if heading in normalized_aliases:
            return lines
    return []


def parse_course_report(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    title, subtitle = extract_title_and_subtitle(lines)
    sections = build_sections(lines)

    what_you_learn = extract_bullets(get_section_lines(sections, SECTION_ALIASES["what_you_learn"]))
    requirements = extract_bullets(get_section_lines(sections, SECTION_ALIASES["requirements"]))
    course_includes = extract_bullets(get_section_lines(sections, SECTION_ALIASES["course_includes"]))
    audience = extract_bullets(get_section_lines(sections, SECTION_ALIASES["audience"]))
    description_lines = get_section_lines(sections, SECTION_ALIASES["description"])

    description = collapse_lines(description_lines)
    modules = extract_modules(description_lines)

    return {
        "file": str(path),
        "title": title,
        "subtitle": subtitle,
        "what_you_learn": what_you_learn,
        "requirements": requirements,
        "course_includes": course_includes,
        "audience": audience,
        "description": description,
        "modules": modules,
    }


def format_bullet_list(items: list[str]) -> list[str]:
    return [f"- {item}" for item in items]


def append_list_section(lines: list[str], heading: str, items: list[str]) -> None:
    if not items:
        return
    lines.append(f"## {heading}")
    lines.extend(format_bullet_list(items))
    lines.append("")


def render_course_markdown(course: dict[str, Any]) -> str:
    lines: list[str] = []
    title = course.get("title") or Path(course.get("file", "")).stem or "Course Summary"
    subtitle = course.get("subtitle")

    lines.append(f"# {title}")
    if subtitle:
        lines.append(subtitle)
    lines.append("")

    append_list_section(lines, "What you'll learn", course.get("what_you_learn", []))
    append_list_section(lines, "Requirements", course.get("requirements", []))
    append_list_section(lines, "This course includes", course.get("course_includes", []))

    description = course.get("description")
    if description:
        lines.append("## Description")
        lines.append(description.strip())
        lines.append("")

    append_list_section(lines, "Who this course is for", course.get("audience", []))

    return "\n".join(line.rstrip() for line in lines).strip() + "\n"


def render_combined_markdown(courses: list[dict[str, Any]]) -> str:
    docs = [render_course_markdown(course).strip() for course in courses]
    return ("\n\n---\n\n".join(docs)).strip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract key sections from course report Markdown files and output Markdown summaries.",
    )
    parser.add_argument("files", nargs="+", help="One or more Markdown paths under course_reports/.")
    parser.add_argument(
        "-o",
        "--output",
        help="Optional Markdown output path that aggregates all inputs into a single file. If omitted, "
        "each input will emit <name>_summary.md next to the source file.",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="(Deprecated) preserved for backward compatibility; no effect when generating Markdown.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    paths = [Path(p) for p in args.files]
    courses = [parse_course_report(path) for path in paths]

    if args.output:
        output_text = render_combined_markdown(courses)
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output_text, encoding="utf-8")
        print(f"✓ Markdown 已保存: {out_path}")
        return

    for course, source in zip(courses, paths):
        markdown = render_course_markdown(course)
        out_path = source.with_name(f"{source.stem}_summary.md")
        out_path.write_text(markdown, encoding="utf-8")
        print(f"✓ Markdown 已保存: {out_path}")


if __name__ == "__main__":
    main()
