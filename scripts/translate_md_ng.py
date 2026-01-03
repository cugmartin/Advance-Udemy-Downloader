#!/usr/bin/env python3
"""
使用吴恩达“三步翻译法”将 Markdown 英文文档翻译成中文。

脚本会：
1. 读取 .env 中的模型、API Key（命令行可覆盖）
2. 读取 Markdown（文件或目录）
3. 对长文本自动分段，逐段请求 LLM 翻译
4. 仅输出最终的优化译文，保留 Markdown 结构
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path
from textwrap import dedent
from typing import Iterable, List, Optional

from dotenv import load_dotenv

try:
    from openai import (
        APIConnectionError,
        APIError,
        APITimeoutError,
        OpenAI,
        RateLimitError,
    )
except ImportError:  # pragma: no cover - 明确提示缺失依赖
    print("错误: 缺少 openai 依赖，请先运行 `pip install openai`", file=sys.stderr)
    sys.exit(1)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_PROVIDER = os.getenv("TRANSLATE_PROVIDER", "openai")
DEFAULT_MODEL = os.getenv("TRANSLATE_MODEL", "gpt-4o-mini")
DEFAULT_API_KEY = os.getenv("TRANSLATE_API_KEY") or os.getenv("OPENAI_API_KEY")
DEFAULT_BASE_URL = os.getenv("TRANSLATE_BASE_URL") or os.getenv("OPENAI_BASE_URL")
DEFAULT_CHUNK_SIZE = int(os.getenv("TRANSLATE_CHUNK_SIZE", "2800"))
DEFAULT_REQUEST_TIMEOUT = float(os.getenv("TRANSLATE_REQUEST_TIMEOUT", "60"))
DEFAULT_MAX_RETRIES = int(os.getenv("TRANSLATE_MAX_RETRIES", "3"))
DEFAULT_RETRY_DELAY = float(os.getenv("TRANSLATE_RETRY_DELAY", "5"))

CHINESE_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")


def is_probably_chinese(text: str, threshold: float = 0.25) -> bool:
    if not text:
        return False
    total = len(text)
    hits = len(CHINESE_CHAR_RE.findall(text))
    return (hits / max(total, 1)) >= threshold


def chunk_markdown(text: str, chunk_size: int) -> Iterable[str]:
    if len(text) <= chunk_size:
        yield text
        return
    buffer: List[str] = []
    current_len = 0
    for paragraph in text.split("\n\n"):
        paragraph_block = paragraph + "\n\n"
        if current_len + len(paragraph_block) > chunk_size and buffer:
            yield "".join(buffer).rstrip()
            buffer = [paragraph_block]
            current_len = len(paragraph_block)
        else:
            buffer.append(paragraph_block)
            current_len += len(paragraph_block)
    if buffer:
        yield "".join(buffer).rstrip()


def create_client(
    api_key: str | None,
    base_url: str | None,
    timeout: float | None,
) -> OpenAI:
    if not api_key:
        raise SystemExit(
            "错误: 未提供翻译 API Key。请在 .env 中设置 TRANSLATE_API_KEY/OPENAI_API_KEY，或使用 --api-key 参数。"
        )
    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    if timeout:
        kwargs["timeout"] = timeout
    return OpenAI(**kwargs)


def translate_chunk(
    client: OpenAI,
    model: str,
    chunk: str,
    source_lang: str,
    target_lang: str,
    max_retries: int,
    retry_delay: float,
    show_stage_logs: bool,
) -> str:
    retryable_errors = (
        APITimeoutError,
        APIConnectionError,
        RateLimitError,
        APIError,
    )
    stage_total = 3

    def log_stage(message: str) -> None:
        if show_stage_logs:
            print(message, flush=True)

    def run_stage(
        stage_index: int,
        stage_name: str,
        description: str,
        messages_builder,
        temperature: float = 0.2,
    ) -> str:
        last_error: Exception | None = None
        log_stage(f"    🟡 阶段 {stage_index}/{stage_total}：{stage_name}（{description}）")
        for attempt in range(1, max_retries + 1):
            try:
                response = client.chat.completions.create(
                    model=model,
                    temperature=temperature,
                    messages=messages_builder(),
                )
                content = response.choices[0].message.content.strip()
                log_stage(f"    ✅ 阶段 {stage_index}/{stage_total} 完成")
                return content
            except retryable_errors as err:
                last_error = err
                if attempt == max_retries:
                    break
                delay = retry_delay * attempt
                log_stage(
                    f"    ⚠️ 阶段 {stage_index}/{stage_total} 失败（第 {attempt}/{max_retries} 次）：{err}. {delay:.1f}s 后重试..."
                )
                time.sleep(delay)
        assert last_error is not None
        raise last_error

    # 阶段 1：初步翻译
    def stage1_messages():
        return [
            {
                "role": "system",
                "content": "You are a meticulous bilingual translator. Produce a faithful Markdown translation from "
                f"{source_lang} to {target_lang}, preserving structure, code blocks, inline math, and links.",
            },
            {
                "role": "user",
                "content": dedent(
                    f"""
                    请将以下 Markdown 段落从 {source_lang} 翻译成 {target_lang}。务必忠实传达含义，不要润色：
                    ```markdown
                    {chunk}
                    ```
                    """
                ).strip(),
            },
        ]

    initial_translation = run_stage(
        stage_index=1,
        stage_name="初步翻译",
        description="忠实保留 Markdown 结构",
        messages_builder=stage1_messages,
        temperature=0.1,
    )

    # 阶段 2：反思评估
    def stage2_messages():
        return [
            {
                "role": "system",
                "content": "You are a bilingual reviewer. Compare the source and translation, then list concrete improvement points covering accuracy, terminology, tone, and formatting. Keep it concise.",
            },
            {
                "role": "user",
                "content": dedent(
                    f"""
                    原文 Markdown：
                    ```markdown
                    {chunk}
                    ```

                    初步译文：
                    ```markdown
                    {initial_translation}
                    ```

                    请用 3-6 条要点列出可以改进的地方，每条开头使用 `-`。
                    """
                ).strip(),
            },
        ]

    review_notes = run_stage(
        stage_index=2,
        stage_name="反思评估",
        description="列出改进要点",
        messages_builder=stage2_messages,
        temperature=0.0,
    )

    if show_stage_logs and review_notes:
        log_stage("      📋 改进要点：")
        for line in review_notes.splitlines():
            log_stage(f"        {line}")

    # 阶段 3：优化润色
    def stage3_messages():
        return [
            {
                "role": "system",
                "content": "You are a senior bilingual technical editor. Apply the improvement notes and produce a polished Markdown translation. Only output the final Markdown, no explanations.",
            },
            {
                "role": "user",
                "content": dedent(
                    f"""
                    原文 Markdown：
                    ```markdown
                    {chunk}
                    ```

                    初步译文：
                    ```markdown
                    {initial_translation}
                    ```

                    改进要点：
                    {review_notes}

                    请根据改进要点输出润色后的最终译文，仅输出 Markdown。
                    """
                ).strip(),
            },
        ]

    final_translation = run_stage(
        stage_index=3,
        stage_name="优化润色",
        description="落实改进要点并输出最终译文",
        messages_builder=stage3_messages,
        temperature=0.2,
    )

    return final_translation


def translate_text(
    client: OpenAI,
    model: str,
    text: str,
    source_lang: str,
    target_lang: str,
    chunk_size: int,
    max_retries: int,
    retry_delay: float,
    show_progress: bool,
    show_stage_logs: bool,
) -> str:
    translated_chunks: List[str] = []
    chunks = list(chunk_markdown(text, chunk_size))
    total = len(chunks)
    for index, chunk in enumerate(chunks, start=1):
        if show_progress:
            print(f"⏳ 翻译进度: {index}/{total}（本段 {len(chunk)} 字符）", flush=True)
        translated_chunks.append(
            translate_chunk(
                client,
                model,
                chunk,
                source_lang,
                target_lang,
                max_retries,
                retry_delay,
                show_stage_logs,
            )
        )
    return "\n\n".join(translated_chunks).strip() + "\n"


def translate_file(
    client: OpenAI,
    model: str,
    input_file: Path,
    output_file: Optional[Path],
    source_lang: str,
    target_lang: str,
    chunk_size: int,
    max_retries: int,
    retry_delay: float,
    show_progress: bool,
    show_stage_logs: bool,
    overwrite: bool,
    skip_if_chinese: bool,
) -> None:
    if not input_file.exists():
        raise FileNotFoundError(f"输入文件不存在: {input_file}")
    if input_file.suffix.lower() != ".md":
        raise ValueError(f"仅支持 .md 文件: {input_file}")

    text = input_file.read_text(encoding="utf-8")
    if skip_if_chinese and is_probably_chinese(text):
        print(f"⚠️  跳过 {input_file.name}（检测为中文）")
        return

    destination = output_file or input_file.with_name(f"{input_file.stem}_zh{input_file.suffix}")
    if destination.exists() and not overwrite:
        print(f"⚠️  目标文件已存在，使用 --overwrite 可覆盖: {destination}")
        return

    print(
        f"\n{'='*60}\n翻译文件: {input_file}\n输出文件: {destination}\n{'='*60}",
        flush=True,
    )
    translation = translate_text(
        client=client,
        model=model,
        text=text,
        source_lang=source_lang,
        target_lang=target_lang,
        chunk_size=chunk_size,
        max_retries=max_retries,
        retry_delay=retry_delay,
        show_progress=show_progress,
        show_stage_logs=show_stage_logs,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(translation, encoding="utf-8")
    print(f"✅ 已生成: {destination}", flush=True)


def translate_directory(
    client: OpenAI,
    model: str,
    input_dir: Path,
    output_dir: Optional[Path],
    source_lang: str,
    target_lang: str,
    chunk_size: int,
    max_retries: int,
    retry_delay: float,
    show_progress: bool,
    show_stage_logs: bool,
    overwrite: bool,
    skip_if_chinese: bool,
    recursive: bool,
) -> None:
    if not input_dir.is_dir():
        raise FileNotFoundError(f"输入目录不存在: {input_dir}")

    md_files = sorted(
        input_dir.rglob("*.md") if recursive else input_dir.glob("*.md"),
        key=lambda p: str(p),
    )
    if not md_files:
        print(f"⚠️  目录中未找到 Markdown 文件: {input_dir}")
        return

    for path in md_files:
        relative = path.relative_to(input_dir)
        target_file = (
            (output_dir / relative).with_name(f"{relative.stem}_zh{relative.suffix}")
            if output_dir
            else path.with_name(f"{path.stem}_zh{path.suffix}")
        )
        translate_file(
            client=client,
            model=model,
            input_file=path,
            output_file=target_file,
            source_lang=source_lang,
            target_lang=target_lang,
            chunk_size=chunk_size,
            max_retries=max_retries,
            retry_delay=retry_delay,
            show_progress=show_progress,
            show_stage_logs=show_stage_logs,
            overwrite=overwrite,
            skip_if_chinese=skip_if_chinese,
        )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="使用吴恩达三步法翻译 Markdown 文档（支持文件或目录）。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=dedent(
            """
            示例：
              python scripts/translate_md_ng.py docs/course.md
              python scripts/translate_md_ng.py docs/ --output docs/zh/ --recursive
              python scripts/translate_md_ng.py docs/course.md --model gpt-4o-mini --chunk-size 2000
            """
        ),
    )
    parser.add_argument("input", type=Path, help="输入 Markdown 文件或目录")
    parser.add_argument("--output", "-o", type=Path, help="输出文件或目录（默认与输入同目录，追加 _zh）")
    parser.add_argument("--model", type=str, default=None, help="覆盖 .env 中的 TRANSLATE_MODEL")
    parser.add_argument("--api-key", type=str, default=None, help="覆盖 .env 中的 TRANSLATE_API_KEY/OPENAI_API_KEY")
    parser.add_argument("--base-url", type=str, default=None, help="覆盖 .env 中的 TRANSLATE_BASE_URL/OPENAI_BASE_URL")
    parser.add_argument("--source-lang", type=str, default="English", help="源语言描述（默认 English）")
    parser.add_argument("--target-lang", type=str, default="Chinese", help="目标语言描述（默认 Chinese）")
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        help=f"分段大小（字符数，默认 {DEFAULT_CHUNK_SIZE}）",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=DEFAULT_REQUEST_TIMEOUT,
        help=f"单次请求超时时间（秒，默认 {DEFAULT_REQUEST_TIMEOUT}）",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        help=f"请求失败重试次数（默认 {DEFAULT_MAX_RETRIES}）",
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=DEFAULT_RETRY_DELAY,
        help=(
            "首次重试等待秒数（随后按尝试次数线性递增，"
            f"默认 {DEFAULT_RETRY_DELAY}）"
        ),
    )
    parser.add_argument(
        "--progress",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="输出按分段（chunk）的翻译进度日志（默认开启）",
    )
    parser.add_argument(
        "--stage-logs",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="打印吴恩达三步法各阶段的详细日志（默认开启）",
    )
    parser.add_argument("--overwrite", action="store_true", help="覆盖已存在的 _zh 文件")
    parser.add_argument("--recursive", "-r", action="store_true", help="递归翻译子目录（仅输入为目录时生效）")
    parser.add_argument(
        "--skip-if-chinese",
        action="store_true",
        default=True,
        help="检测到已为中文时跳过（默认开启）",
    )
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    model = args.model or DEFAULT_MODEL
    api_key = args.api_key or DEFAULT_API_KEY
    base_url = args.base_url or DEFAULT_BASE_URL
    request_timeout = args.request_timeout
    max_retries = args.max_retries
    retry_delay = args.retry_delay
    show_progress = args.progress
    show_stage_logs = args.stage_logs

    client = create_client(api_key, base_url, request_timeout)

    input_path = args.input.resolve()
    if input_path.is_file():
        translate_file(
            client=client,
            model=model,
            input_file=input_path,
            output_file=args.output,
            source_lang=args.source_lang,
            target_lang=args.target_lang,
            chunk_size=args.chunk_size,
            max_retries=max_retries,
            retry_delay=retry_delay,
            show_progress=show_progress,
            show_stage_logs=show_stage_logs,
            overwrite=args.overwrite,
            skip_if_chinese=args.skip_if_chinese,
        )
    elif input_path.is_dir():
        translate_directory(
            client=client,
            model=model,
            input_dir=input_path,
            output_dir=args.output,
            source_lang=args.source_lang,
            target_lang=args.target_lang,
            chunk_size=args.chunk_size,
            max_retries=max_retries,
            retry_delay=retry_delay,
            show_progress=show_progress,
            show_stage_logs=show_stage_logs,
            overwrite=args.overwrite,
            skip_if_chinese=args.skip_if_chinese,
            recursive=args.recursive,
        )
    else:
        parser.error(f"输入路径不存在: {input_path}")


if __name__ == "__main__":
    main()
