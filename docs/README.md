# Scripts Directory Overview

下表汇总了 `scripts/` 目录中的主要工具、功能及常用命令，便于快速查阅与组合使用。

| 脚本 | 作用 | 常用命令 / 说明 |
| --- | --- | --- |
| `build_outline_from_outdir.py` | 根据已下载的课程目录 (`out_dir/<slug>/…`) 生成章节大纲 Markdown，可供其它脚本插入“Chapter Overview”。 | `python scripts/build_outline_from_outdir.py --course-dir out_dir/<slug>` |
| `download_course_info.py` | 通过 Firecrawl 抓取课程介绍页，输出原始 Markdown。通常由 `generate_course_summary.py` 间接调用。 | 一般不单独调用；如需测试：`python scripts/download_course_info.py <course_url> --output course_reports/demo.md` |
| `generate_course_summary.py` | 串联抓取、解析、注入本地大纲，最终生成 `<slug>_final.md`。 | `python scripts/generate_course_summary.py <course_url> [--full-page] [--course-dir out_dir/<slug>]` |
| `md_to_html_converter.py` | 将 Markdown 转为带内联样式的 HTML，内置自定义 CSS、H2 分隔线、FAQ/推荐块处理。 | `python scripts/md_to_html_converter.py course_reports/demo_final_zh.md` (默认输出同目录 `.html`，可追加自定义输出或 `--no-inline`)
| `parse_course_report.py` | 对抓取的 Markdown 做结构化解析，抽取 “What you’ll learn / Requirements …” 等板块，生成 `_summary.md`。 | 通常由 `generate_course_summary.py` 调用；可单独运行：`python scripts/parse_course_report.py course_reports/demo.md` |
| `publish_markdown_to_wordpress.py` | 旧版“一键发布”脚本：处理图片上传、Markdown→HTML、上传 WordPress。现在多由 `run_course_pipeline.py` 取代，但仍可用作细粒度控制。 | `python scripts/publish_markdown_to_wordpress.py docs/example.md --status draft [--skip-images] [--dry-run]` |
| `rewrite_intro.py` | 调用 LLM 将 Markdown 首段导语重写为“痛点 + 解决方案”风格。 | `python scripts/rewrite_intro.py course_reports/demo_final_zh.md [--model gpt-4o-mini]` |
| `run_course_pipeline.py` | **推荐**的总控脚本：从 Udemy URL 开始，依次抓取→翻译→导语重写→转 HTML→上传 WordPress，并可自动清理生成文件。 | `python scripts/run_course_pipeline.py <course_url> --status draft [--skip-download] [--skip-translate] [--skip-intro] [--dry-run] [--keep-output]` |
| `translate_md_ng.py` | “吴恩达三步” Markdown 翻译器，支持分段、重试、进度日志、阶段日志。 | `python scripts/translate_md_ng.py course_reports/demo_final.md --overwrite [--no-progress] [--no-stage-logs]` |
| `upload_html_to_wordpress.py` | 将 HTML 或 Markdown（会先转 HTML）上传为 WordPress 文章。 | `python scripts/upload_html_to_wordpress.py course_reports/demo_final_zh.md --status draft` |

## 使用建议

1. **完整流水线**：首选 `run_course_pipeline.py <course_url>`，可在一条命令内得到 WordPress 草稿。若只需中间成果，配合 `--dry-run` 或 `--skip-*` 参数。
2. **手动分步**：
   - `generate_course_summary.py → translate_md_ng.py → rewrite_intro.py → md_to_html_converter.py → upload_html_to_wordpress.py`
   - 适合需要在各阶段插入人工校对、审查或自定义处理的场景。
3. **WordPress 凭据**：确保 `.env` 中设置 `WORDPRESS_URL / WORDPRESS_USERNAME / WORDPRESS_APP_PASSWORD`，并根据 `translate_md_ng.py`、`rewrite_intro.py` 的需要补全 `TRANSLATE_*` 相关变量。
4. **清理产物**：`run_course_pipeline.py` 默认执行完会删除 `course_reports` 下的临时文件；若需保留，加 `--keep-output`。`main.py`（课程下载器）会自动清空 `temp/`。

如需新增脚本说明或示例，可在本文件继续补充。
