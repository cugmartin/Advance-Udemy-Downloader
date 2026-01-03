# Udemy Downloader（支持 DRM）

这是一个面向个人学习者的 Python 自动化工具，可以将你在 Udemy 上购买的课程下载到本地，包含 DRM 加密的视频（前提是你拥有 Widevine 解密密钥）。脚本的开发平台为 Windows，但也尽力兼容 Linux。使用前务必了解并遵守 Udemy 的使用条款。

## 赞助作者

如果这个项目对你有帮助，欢迎通过下述任一方式进行支持，以促进未来更多免费工具的开发：

- **币安 ID 转账：**`150697028`
- **BNB（BEP20）地址：**`0xef6e84f601441439e809088fe0355ec63b9f0017`
- **USDT（BEP20）地址：**`0xef6e84f601441439e809088fe0355ec63b9f0017`

> 请勿发送 NFT；如需其它链（ERC20、TRC20）可通过邮箱或 GitHub 联系作者。

## 提示与免责声明

1. 本项目仅用于教育和个人备份目的，下载课程可能违反 Udemy 服务条款，使用者需自行承担风险。
2. DRM 视频必须提供 Widevine 密钥，否则无法播放或解密。
3. 项目代码仍处于持续维护状态，按原样提供，不承担使用过程中造成的任何后果。

## 环境依赖

以下工具不会包含在仓库中，请提前安装并确保它们在 PATH 中可用：

- [Python 3](https://python.org/)（建议 3.9 及以上）
- [ffmpeg](https://www.ffmpeg.org/)
  - 推荐使用 yt-dlp 团队提供的自定义编译版以规避兼容性问题：[FFmpeg-Builds](https://github.com/yt-dlp/FFmpeg-Builds/releases/tag/latest)
- [aria2（aria2c）](https://github.com/aria2/aria2/)
- [shaka-packager](https://github.com/shaka-project/shaka-packager/releases/latest)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp/)（可通过 `pip install yt-dlp` 安装）

## 快速上手

1. **准备 Udemy 登录 Cookie**
   - 安装浏览器扩展（如 Cookies Editor），Firefox 兼容性更好。
   - 登录 Udemy，打开扩展，将 cookies 以 Netscape 格式导出。
   - 把内容粘贴到仓库根目录的 `cookie.txt` 中（可覆盖）。

2. **准备 Widevine 密钥（用于 DRM 视频）**
   - 推荐使用 **Firefox** + ["Widevine L3 Decrypter"](https://addons.mozilla.org/en-US/firefox/addon/widevine-l3-decrypter/) 插件。
   - 在 Udemy 播放任意加密视频，并在播放过程中打开插件，点击 “Guess” 等待自动填充 Key 和 Key ID。
   - 将插件返回的 Key/Key ID 写入 `keyfile.json`（示例可参考仓库中的文件）。

3. **配置环境变量**
   - 复制 `.env.example` 为 `.env`
   - 填入你的 `UDEMY_BEARER` token
   - （可选）填入 `DEEPL_API_KEY` 以启用自动中英文字幕翻译

4. **安装 Python 依赖**
   ```bash
   pip install -r requirements.txt
   ```

5. **运行下载脚本**
   ```bash
   python main.py -c <课程网址>
   ```
   脚本会自动从 `.env` 读取 Bearer Token，并在下载视频时自动下载英文字幕。如果配置了 DeepL API Key，会自动生成中文翻译。

## 自动中英文字幕功能

**新功能：** 脚本现在支持自动下载英文字幕并翻译为中文！

- 下载视频时会自动下载英文字幕（无需手动指定 `--download-captions`）
- 如果在 `.env` 中配置了 `DEEPL_API_KEY`，会生成单一的 `LectureTitle_en_zh.srt` 文件（每条字幕显示英文+中文）
- 翻译支持缓存机制，避免重复翻译
- 翻译失败会自动重试 3 次，失败后会保留英文内容
- 日志会显示翻译进度

**如何获取 DeepL API Key：**
1. 访问 [DeepL API](https://www.deepl.com/pro-api) 注册账号
2. 免费版每月可翻译 50 万字符
3. 将 API Key 填入 `.env` 文件的 `DEEPL_API_KEY` 变量

## 常用命令示例

- 下载特定画质：`python main.py -c <Course URL> -q 720`
- 同时下载课程素材：`python main.py -c <Course URL> --download-assets`
- 仅下载字幕（不下载视频）：`python main.py -c <Course URL> --skip-lectures --download-captions`
- 保留 .vtt 文件：`python main.py -c <Course URL> --keep-vtt`
- 跳过解析 HLS（速度更快）：`python main.py -c <Course URL> --skip-hls`
- 打印课程信息：`python main.py -c <Course URL> --info`
- 指定并行下载线程：`python main.py -c <Course URL> -cd 20`
- 使用课程 ID 作为输出目录名：`python main.py -c <Course URL> --id-as-course-name`
- 使用 H.265 编码：`python main.py -c <Course URL> --use-h265`
- 指定 H.265 的 CRF：`python main.py -c <Course URL> --use-h265 -h265-crf 20`
- 用 NVIDIA 硬件编码：`python main.py -c <Course URL> --use-h265 --use-nvenc`
- 下载指定章节：`python main.py -c <Course URL> --chapter "1,3-5"`
- 缓存课程信息：`python main.py -c <Course URL> --save-to-file`
- 读取缓存：`python main.py -c <Course URL> --load-from-file`
- 设置日志等级：`--log-level DEBUG|INFO|WARNING|CRITICAL`

## 作者与联系方式

开发者：**Sheikh Bilal**（Java 爱好者兼自动化狂热者）

- GitHub：https://github.com/sheikh-bilal65
- LinkedIn：https://www.linkedin.com/in/bilal-ahmad2
- 邮箱：bilalahmadallbd@gmail.com
- Instagram：https://www.instagram.com/sheikhh.bilal/

如遇问题可以通过以上渠道联系作者，或在项目 issue 中留言。

## 法律与使用说明

本工具仅供学习和研究，请勿用于违反 Udemy 服务条款或其他法律法规的场景。使用过程中产生的任何风险与后果均由使用者自行承担。
