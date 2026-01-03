#!/usr/bin/env python3
"""
Auto-rewrite the intro paragraph below the first H1 of a Markdown file
using an LLM (pain-point + solution tone).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from textwrap import dedent
from typing import List, Tuple

from dotenv import load_dotenv

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    print("错误: 缺少 openai 依赖，请先执行 `pip install openai`", file=sys.stderr)
    sys.exit(1)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_MODEL = os.getenv("TRANSLATE_MODEL", "gpt-4o-mini")
DEFAULT_API_KEY = os.getenv("TRANSLATE_API_KEY") or os.getenv("OPENAI_API_KEY")
DEFAULT_BASE_URL = os.getenv("TRANSLATE_BASE_URL") or os.getenv("OPENAI_BASE_URL")
DEFAULT_TIMEOUT = float(os.getenv("TRANSLATE_REQUEST_TIMEOUT", "60"))


def create_client(api_key: str | None, base_url: str | None, timeout: float | None) -> OpenAI:
    if not api_key:
        raise SystemExit("错误: 未提供 API Key，请在 .env 中配置 TRANSLATE_API_KEY/OPENAI_API_KEY。")
    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    if timeout:
        kwargs["timeout"] = timeout
    return OpenAI(**kwargs)


def find_intro_block(lines: List[str]) -> Tuple[int, int]:
    """Return (start_idx, end_idx) of the intro paragraph after first H1."""
    title_idx = next((i for i, line in enumerate(lines) if line.startswith("# ")), None)
    if title_idx is None:
        raise ValueError("未找到一级标题 (# )，无法定位导语。")
    start = None
    for idx in range(title_idx + 1, len(lines)):
        stripped = lines[idx].strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            # 下一个标题，说明原文件没有导语
            start = idx
            break
        start = idx
        break
    if start is None:
        # 附加在标题后面
        start = title_idx + 1
        lines.insert(start, "")
    end = start
    while end < len(lines) and lines[end].strip():
        if lines[end].startswith("## "):
            break
        if lines[end].startswith("# "):
            break
        end += 1
    return start, end


def build_prompt(title: str, old_intro: str, extra_context: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": "You are a bilingual SaaS copywriter. Draft concise Mandarin intros that hook readers with pain points plus the course's solution/value.",
        },
        {
            "role": "user",
            "content": dedent(
                f"""
                课程标题：{title}
                现有导语：{old_intro or '（空）'}
                课程要点示例：
                {extra_context.strip()}

                请写 4-5 句中文导语，格式要求：
                - 先点出受众常见痛点（如 24/7 响应、成本、体验不一致）
                - 再说明课程的 解决方案/收益
                - 语气务实有画面感，可直接放在 Markdown 标题下方
                - 不要使用营销口号或夸张标点
                """
            ).strip(),
        },
    ]


def rewrite_intro(
    path: Path,
    client: OpenAI,
    model: str,
) -> None:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    start_idx, end_idx = find_intro_block(lines)
    old_intro = "\n".join(lines[start_idx:end_idx]).strip()

    # gather extra context：取“你将学到什么”部分的前 3 bullet
    extra_context = []
    capture = False
    for line in lines:
        if line.startswith("## ") and "你将学到什么" in line:
            capture = True
            continue
        if capture:
            if line.startswith("## "):
                break
            if line.strip().startswith("- "):
                extra_context.append(line.strip()[2:])
            if len(extra_context) >= 4:
                break
    context_text = "\n".join(f"- {item}" for item in extra_context) or "（暂无额外要点）"
    title = next((line[2:].strip() for line in lines if line.startswith("# ")), "课程")

    response = client.chat.completions.create(
        model=model,
        temperature=0.4,
        messages=build_prompt(title, old_intro, context_text),
    )
    new_intro = response.choices[0].message.content.strip()

    new_lines = lines[:start_idx] + [new_intro, ""] + lines[end_idx:]
    path.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")
    print("✅ 导语已更新。")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="用 LLM 重写 Markdown 一级标题下的导语。")
    parser.add_argument("input", type=Path, help="目标 Markdown 文件路径")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"使用的模型（默认 {DEFAULT_MODEL}）")
    parser.add_argument("--api-key", default=None, help="可覆盖 TRANSLATE_API_KEY/OPENAI_API_KEY")
    parser.add_argument("--base-url", default=None, help="可覆盖 TRANSLATE_BASE_URL/OPENAI_BASE_URL")
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"请求超时时间（秒，默认 {DEFAULT_TIMEOUT}）",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    md_path = args.input.resolve()
    if not md_path.exists():
        raise SystemExit(f"错误: 文件不存在 {md_path}")

    client = create_client(args.api_key or DEFAULT_API_KEY, args.base_url or DEFAULT_BASE_URL, args.timeout)
    rewrite_intro(md_path, client, args.model)


if __name__ == "__main__":
    main()
