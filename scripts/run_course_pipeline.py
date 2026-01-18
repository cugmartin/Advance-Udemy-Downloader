#!/usr/bin/env python3
"""
End-to-end pipeline:
1. Firecrawl download + summary generation
2. Markdown → 中文翻译
3. 导语重写（痛点 + 解决方案）
4. Markdown → HTML（内联样式）
5. 上传到 WordPress
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
REPORTS_DIR = PROJECT_ROOT / "course_reports"


def slug_from_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if "/course/" in path:
        slug = path.split("/course/", 1)[1].split("/")[0]
    else:
        slug = Path(path).stem or parsed.netloc or "course"
    return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in slug) or "course"


def run_step(cmd: list[str], title: str) -> None:
    print(f"\n{'=' * 60}\n▶️  {title}\n{'=' * 60}")
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"❌ 步骤失败：{title}\n命令: {' '.join(cmd)}\n退出码: {exc.returncode}") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="一条命令跑完整的课程抓取→翻译→发布流程。")
    parser.add_argument("course_url", help="Udemy 课程 URL（lecture 链接也可）")
    parser.add_argument(
        "--status",
        choices=["draft", "publish", "pending", "private"],
        default="draft",
        help="WordPress 文章状态（默认 draft）",
    )
    parser.add_argument("--full-page", action="store_true", help="传递 --full-page 给 generate_course_summary.py")
    parser.add_argument("--course-dir", help="传给 generate_course_summary.py 的 --course-dir")
    parser.add_argument("--skip-download", action="store_true", help="跳过下载/生成摘要（直接使用现有 *_final.md）")
    parser.add_argument("--skip-translate", action="store_true", help="跳过翻译（需已有 *_final_zh.md）")
    parser.add_argument("--skip-intro", action="store_true", help="跳过导语重写")
    parser.add_argument("--skip-upload", action="store_true", help="跳过上传到 WordPress")
    parser.add_argument("--dry-run", action="store_true", help="执行到 HTML 转换为止，不上传 WordPress")
    parser.add_argument("--keep-output", action="store_true", help="保留 course_reports 下的生成文件")
    return parser.parse_args()


def cleanup_generated_files(slug: str) -> None:
    targets = [
        REPORTS_DIR / f"{slug}.md",
        REPORTS_DIR / f"{slug}_summary.md",
        REPORTS_DIR / f"{slug}_final.md",
        REPORTS_DIR / f"{slug}_final_zh.md",
        REPORTS_DIR / f"{slug}_final_zh.html",
    ]
    removed = []
    for path in targets:
        if path.exists():
            try:
                path.unlink()
                removed.append(path.name)
            except OSError as exc:
                print(f"⚠️ 无法删除 {path.name}: {exc}")
    if removed:
        print(f"\n🧹 已清理 course_reports 中的文件: {', '.join(removed)}")


def main() -> None:
    args = parse_args()
    slug = slug_from_url(args.course_url)

    final_md = REPORTS_DIR / f"{slug}_final.md"
    final_zh_md = REPORTS_DIR / f"{slug}_final_zh.md"
    final_zh_html = REPORTS_DIR / f"{slug}_final_zh.html"

    if not args.skip_download:
        cmd = [
            sys.executable,
            str(SCRIPTS_DIR / "generate_course_summary.py"),
            args.course_url,
        ]
        if args.full_page:
            cmd.append("--full-page")
        if args.course_dir:
            cmd.extend(["--course-dir", args.course_dir])
        run_step(cmd, "下载课程并生成最终 Markdown")
    elif not final_md.exists():
        raise SystemExit(f"❌ 跳过下载但未找到 {final_md}")

    if not args.skip_translate:
        cmd = [
            sys.executable,
            str(SCRIPTS_DIR / "translate_md_ng.py"),
            str(final_md),
            "--overwrite",
        ]
        run_step(cmd, "翻译 Markdown 为中文")
    elif not final_zh_md.exists():
        raise SystemExit(f"❌ 跳过翻译但未找到 {final_zh_md}")

    if not args.skip_intro:
        run_step(
            [
                sys.executable,
                str(SCRIPTS_DIR / "rewrite_intro.py"),
                str(final_zh_md),
            ],
            "重写导语（痛点 + 解决方案）",
        )

    run_step(
        [
            sys.executable,
            str(SCRIPTS_DIR / "md_to_html_converter.py"),
            str(final_zh_md),
            str(final_zh_html),
        ],
        "Markdown 转 HTML（内联样式）",
    )

    if not final_zh_html.exists():
        raise SystemExit(f"❌ HTML 转换完成但未找到输出文件 {final_zh_html}")

    if args.dry_run or args.skip_upload:
        print("\nℹ️ 已按要求跳过上传步骤。")
        return

    run_step(
        [
            sys.executable,
            str(SCRIPTS_DIR / "upload_html_to_wordpress.py"),
            str(final_zh_html),
            "--status",
            args.status,
        ],
        f"上传到 WordPress（状态：{args.status}）",
    )
    print("\n🎉 全流程完成！")

    if not args.keep_output:
        cleanup_generated_files(slug)
    else:
        print("\nℹ️ 按参数要求保留 course_reports 下的生成文件。")


if __name__ == "__main__":
    main()
