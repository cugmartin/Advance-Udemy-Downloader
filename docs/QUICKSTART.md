# Advance Udemy Downloader 快速上手指南

本指南汇总仓库的核心功能、依赖与典型工作流，帮助你在最短时间内完成环境配置、命令行下载、自动化内容生成以及 Web 控制台的部署。内容基于 `README.md`、`README_zh.md`、`docs/README.md` 与核心脚本实现整理而成。@README.md#1-177 @README_zh.md#1-107 @docs/README.md#1-28

## 1. 功能速览

1. **CLI 下载器（`main.py`）**：支持 DRM 课程、可配置画质/字幕/章节、可自动抓取浏览器 Cookie 与 Widevine Key 并输出至 `out_dir/`。@README.md#69-162 @constants.py#35-44
2. **脚本工作流（`scripts/`）**：提供抓取课程介绍、翻译、导语重写、Markdown→HTML、发布 WordPress 的一体化流水线，推荐入口 `run_course_pipeline.py`。@docs/README.md#1-27 @scripts/run_course_pipeline.py#1-152
3. **Web 控制台（`webapp/`）**：基于 FastAPI/Tasks 管理器的可视化面板，集成课程预检、任务调度、日志流和一键生成文章。@webapp/server.py#1-400

## 2. 环境准备

### 2.1 系统与依赖

- Windows 是主要开发平台，也兼容 Linux（macOS 未测试）。@README.md#48-57  
- 硬性依赖（需放入 PATH）：Python 3.9+、FFmpeg（推荐 yt-dlp 构建）、aria2/aria2c、shaka-packager、yt-dlp。@README.md#58-68  
- Python 依赖位于 `requirements.txt`，涵盖下载、字幕转换、FastAPI Web 控制台、Firecrawl 抓取与翻译适配。@README.md#93-96 @requirements.txt#1-24  
- 可选：项目自带 `Dockerfile`/`docker-compose.yml`，用于容器化运行主脚本。@Dockerfile#1-34 @docker-compose.yml#1-12

### 2.2 获取代码与安装

```bash
git clone <repo-url>
cd Advance-Udemy-Downloader
python -m venv .venv && .\.venv\Scripts\activate  # 可选
pip install -r requirements.txt
```

## 3. 准备认证信息

1. **Cookie**：使用 Cookies Editor 扩展导出 Udemy 登录 Cookie（Netscape 格式），粘贴/覆盖到根目录 `cookie.txt`。@README.md#73-81  
2. **Widevine Key**：在 Firefox 中安装 Widevine L3 Decrypter，播放目标课程获取 Key/KID，写入 `keyfile.json`。@README.md#82-92  
3. **环境变量**：
   - 复制 `.env.example` 为 `.env`。
   - 必填 `UDEMY_BEARER`（用于主脚本及 Web 控制台默认 token）。
   - 可选翻译：`DEEPL_API_KEY` 或自定义 `TRANSLATE_* / SUBTITLE_TRANSLATE_*`。@README_zh.md#44-58 @.env.example#1-23  
   - Web 控制台账号密码通过 `WEB_ADMIN_USERNAME/WEB_ADMIN_PASSWORD` 配置，默认 `admin/Lead123456@`。@webapp/config.py#8-23  
4. （可选）WordPress/Firecrawl Pipeline：在 `.env` 中补齐 `WORDPRESS_*` 与 Firecrawl、OpenAI/Google/DeepL 等 API Key，以供 `scripts/` 使用。详见各脚本参数。@docs/README.md#18-27 @scripts/run_course_pipeline.py#42-153

## 4. 命令行下载流程

### 4.1 最小化命令

```bash
python main.py -c https://www.udemy.com/course/<slug>
```

脚本会：

- 自动读取 `.env` 中的 `UDEMY_BEARER`（若 CLI 未显式传 `-b`）。
- 为每个课程在 `out_dir/<course-name>/` 里创建章节文件夹；日志按时间写入 `logs/<mm-dd_hh-mm-ss>.log`。@main.py#112-409 @constants.py#35-45

### 4.2 常用参数

| 目标 | 示例命令 |
| --- | --- |
| 指定 Bearer Token / 画质 | `python main.py -c <URL> -b <TOKEN> -q 720` |
| 下载素材/字幕/测验 | `--download-assets` / `--download-captions` / `--download-quizzes` |
| 仅下载字幕或素材 | `--skip-lectures --download-captions` / `--skip-lectures --download-assets` |
| 选择字幕语言或全部 | `--download-captions -l en|es|all` |
| 控制并发与章节 | `--concurrent-downloads 20`、`--chapter "1,3-5"` |
| 切换输出路径 & 连续编号 | `--out D:\Udemy --continue-lecture-numbers` |
| H.265 软编/硬编 | `--use-h265 [--h265-crf 20 --h265-preset faster --use-nvenc]` |
| 仅打印课程信息 | `--info` |
| 缓存/读取课程结构 | `--save-to-file` / `--load-from-file` |

完整参数说明参见 `README.md` Quick Start 列表。@README.md#98-162

### 4.3 字幕与翻译自动化

- 未指定 `--skip-lectures` 时，脚本会强制启用英文字幕下载。
- 若 `.env` 配置了翻译提供商（DeepL 或 `TRANSLATE_PROVIDER`），字幕会自动生成双语 `.srt`，失败会重试并打印日志。@main.py#360-381 @README_zh.md#60-74

## 5. 内容生成流水线

当你需要把课程介绍加工成中文文章并发布 WordPress，可使用 `scripts/`：

1. **推荐入口**：`python scripts/run_course_pipeline.py <course_url> --status draft [--skip-*]`  
   - 自动串联 Firecrawl 抓取 (`generate_course_summary.py`)、`translate_md_ng.py` 翻译、`rewrite_intro.py` 导语重写、`md_to_html_converter.py` 转 HTML、`upload_html_to_wordpress.py` 上传。@scripts/run_course_pipeline.py#1-152
2. **分步模式**：按 `docs/README.md` 建议，手动执行单个脚本以插入人工校对。@docs/README.md#18-24
3. **输入输出**：所有中间文件存放在 `course_reports/`，流水线可通过 `--keep-output` 保留。@scripts/run_course_pipeline.py#62-152

## 6. Web 控制台部署

1. **启动**：激活虚拟环境后运行
   ```bash
   uvicorn webapp.server:app --host 0.0.0.0 --port 8000
   ```
   FastAPI 应用会自动挂载静态资源与模板。@webapp/server.py#12-210
2. **登录**：访问 `/` 输入 `WEB_ADMIN_*` 凭据，成功后跳转 `/dashboard`。
3. **主要功能**：
   - **课程预检**：`/api/precheck` 校验 Bearer Token 与课程 DRM 状态。
   - **下载任务**：`/api/download` 触发后台任务，支持提交多个并发命令并流式查看日志。@webapp/server.py#281-319
   - **历史记录**：`HistoryStore` 将任务状态写入 `web_data/history.json`，保留最近 10 条。@webapp/server.py#220-279 @webapp/config.py#8-23
   - **文章生成**：对成功下载的任务可一键调用 `run_course_pipeline.py`，实时推送日志。@webapp/server.py#321-400

> 提示：Web 控制台默认复用根目录 `keyfile.json` 与 `out_dir/`，因此务必确保这些文件夹的读写权限。@webapp/config.py#20-23

## 7. Docker / Compose 运行（可选）

1. 构建镜像：`docker build -t udemy-downloader .`（镜像已预装 Python 3.12、FFmpeg、aria2、shaka-packager）。@Dockerfile#3-34  
2. 使用 Compose：
   ```bash
   COURSE_URL=https://www.udemy.com/course/<slug> docker compose up
   ```
   - 自动挂载 `./output` 到容器 `/app/out_dir`，并以只读模式注入 `keyfile.json`。  
   - `.env` 会被传入容器，确保其中包含 `UDEMY_BEARER`。@docker-compose.yml#1-12

## 8. 重要目录速查

| 目录 / 文件 | 说明 |
| --- | --- |
| `out_dir/` | 下载结果根目录，可用 `--out` 自定义。@main.py#352-357 |
| `logs/` | 每次运行生成一个时间戳日志文件。@constants.py#39-45 |
| `saved/` | 存放 `--save-to-file` 的课程缓存。@constants.py#35-38 |
| `course_reports/` | 内容流水线的中间/最终 Markdown & HTML。@scripts/run_course_pipeline.py#62-152 |
| `web_data/history.json` | Web 控制台任务历史与文章状态。@webapp/config.py#8-23 |
| `scripts/` | 课程摘要、翻译、发布工具集合（详见 `docs/README.md`）。@docs/README.md#1-27 |

---

完成上述步骤后，即可利用 CLI 下载器进行课程备份，或借助脚本/控制台搭建完整的「下载→翻译→发布」自动化流程。建议先在测试课程上演练，以熟悉日志与产物结构，再投入正式流程。@
