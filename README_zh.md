# 支持 DRM 的 Udemy 下载器

使用这个强大的 Python 脚本，将你的 Udemy 课程解锁为离线可用！它可以无缝下载课程内容（包括 DRM 保护的内容），并通过提取 Cookie 与 Widevine Key 来完成解密与合并。该工具仅用于学习与研究目的，用于演示自动化技术的个人用途。快速上手，随时随地离线学习。

本脚本可帮助你将 Udemy 课程下载到本地离线播放（包括带 DRM 的课程）。它会引导你提取所需的 Cookie 与 Widevine 解密密钥，从而访问你已购买的内容。非常适合希望在无网络环境下学习的用户。

**让自动化为你赋能！**

如果这个工具对你有帮助，欢迎支持项目持续开发。你的支持（无论多少）都能推动更多免费、强大且功能丰富的工具诞生。

<a href="https://buymeacoffee.com/bilalsheikh" target="_blank"> <img src="https://img.shields.io/badge/Buy%20Me%20A%20Coffee-FFDD00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black" alt="Buy Me A Coffee"> </a>

### 💸 加密货币捐赠

如果你希望支持该项目，也可以通过加密货币捐赠。

#### **方式 1：Binance ID（适用于 Binance 用户的站内转账）**

- **Binance ID：** `150697028`
  - （可在 Binance 的“通过 Binance ID 转账”中使用，账户间秒到账）

#### **方式 2：钱包地址（BNB Smart Chain / BEP20）**

**BNB（Binance Coin，BEP20）：**

- **网络：** BNB Smart Chain（BEP20）
- **钱包地址：**
  `0xef6e84f601441439e809088fe0355ec63b9f0017`

![BNB Wallet QR code](BNB.jpg)

---

**USDT（Tether USD，BEP20）：**

- **网络：** BNB Smart Chain（BEP20）
- **钱包地址：**
  `0xef6e84f601441439e809088fe0355ec63b9f0017`

![USDT Wallet QR code](USDT.jpg)

---

> **注意：**
> 请勿向该地址发送 NFT。
> 如需其它币种，或需要 ERC20/TRC20 地址，请通过邮件或 GitHub 联系作者。

---

用于下载 Udemy 课程的工具脚本，支持 DRM 视频，但出于合规原因需要用户自行获取解密 Key（法律原因）。<br>
Windows 是主要开发系统，同时也尽量兼容 Linux（macOS 未测试）。

> [!IMPORTANT]
> 若未提供解密 Key，本工具无法下载/合并加密课程内容。
>
> 下载课程可能违反 Udemy 的服务条款（Terms of Service）。因使用本程序导致账号被封禁等后果，作者不承担任何责任。
>
> 本程序仍在开发中（WIP），代码按“原样”提供。作者不对使用本工具可能产生的任何法律问题负责。

### 运行依赖（Requirements）

运行脚本需要以下第三方工具。它们 **不包含在仓库中**，需要你自行下载安装，并确保在系统 `PATH` 可被访问。

- [Python 3](https://python.org/)
- [ffmpeg](https://www.ffmpeg.org/) - Linux 也可通过包管理器安装
  - 说明：推荐使用 yt-dlp 团队提供的自定义构建版本，包含与 yt-dlp 配合使用时的一些补丁；但不是必须。最新构建可在这里获取：
    <https://github.com/yt-dlp/FFmpeg-Builds/releases/tag/latest>
- [aria2/aria2c](https://github.com/aria2/aria2/) - Linux 也可通过包管理器安装
- [shaka-packager](https://github.com/shaka-project/shaka-packager/releases/latest)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp/) - Linux 也可通过包管理器安装，也可选择 pip 安装（`pip install yt-dlp`）

### 快速开始（Quick Start）

如果需要下载 DRM 课程，你必须先提取 Cookie 与 Widevine 解密 Key。按以下步骤操作：

1) **提取 Cookie（用于 Udemy 登录态）**：

- 为浏览器安装 “Cookies Editor” 扩展。推荐使用 Mozilla Firefox，以获得更好的 Widevine L3 Decrypter 兼容性。
  - **Google Chrome**：<https://cookie-editor.com/>
  - **Mozilla Firefox**：<https://cookie-editor.com/>
- 在浏览器中登录你的 Udemy 账号。
- 打开 Cookies Editor 扩展。
- 以 “Netscape” 格式复制 Cookie。
- 将复制的内容粘贴到项目目录下的 `cookie.txt` 文件中。

2) **提取 Widevine DRM Key（用于加密视频）**：

- **重要：**目前 “Widevine L3 Decrypter” 在 Google Chrome 上无法完整支持 Key 提取，强烈建议使用 **Mozilla Firefox**。
- 在 Mozilla Firefox 安装扩展：
  - **Mozilla Firefox**：<https://addons.mozilla.org/en-US/firefox/addon/widevine-l3-decrypter/>
- 如果你在第 1 步从 Chrome 复制了 Cookie，请确保你在 Firefox 中也处于已登录状态。
- 打开要下载的 Udemy 课程页面，并播放任意一节视频。
- 视频播放时打开 “Widevine L3 Decrypter” 扩展。
- 使用默认设置，点击 “Guess”，等待扩展处理并展示解密信息。
- 复制扩展提供的 “Key” 与 “Key ID”。
- 将这些 Key 写入项目目录下的 `keyfile.json`。这样脚本才能解密下载的加密文件并绕过 DRM。

3) **安装 Python 依赖**（推荐 Python 3.9+）：

```bash
pip install -r requirements.txt
```

### Web 控制台（FastAPI）

启动 Web 控制台：

```bash
python -m uvicorn webapp.server:app --host 127.0.0.1 --port 8000
```

如果你希望在开发时启用热重载（auto-reload），请确保 reload **只监控 `webapp` 目录**（否则下载任务写入 `out_dir/` 时会触发 reload，可能中断正在运行的下载任务）：

```bash
python -m uvicorn webapp.server:app --host 127.0.0.1 --port 8000 --reload --reload-dir webapp
```

2) **运行主下载脚本**：

使用 `main.py` 并通过命令行参数指定课程 URL 与下载选项。

**示例用法：**

- 传入 Bearer Token 与课程 URL
  - `python main.py -c <课程 URL> -b <Bearer Token>`
  - `python main.py -c https://www.udemy.com/courses/myawesomecourse -b <Bearer Token>`

- 下载指定清晰度
  - `python main.py -c <课程 URL> -q 720`

- 下载视频的同时下载素材
  - `python main.py -c <课程 URL> --download-assets`

- 下载素材并指定清晰度
  - `python main.py -c <课程 URL> -q 360 --download-assets`

- 下载字幕（默认英文）
  - `python main.py -c <课程 URL> --download-captions`

- 下载指定语言字幕
  - `python main.py -c <课程 URL> --download-captions -l en` - 英文
  - `python main.py -c <课程 URL> --download-captions -l es` - 西班牙语
  - `python main.py -c <课程 URL> --download-captions -l it` - 意大利语
  - `python main.py -c <课程 URL> --download-captions -l pl` - 波兰语
  - `python main.py -c <课程 URL> --download-captions -l all` - 下载全部字幕
  - 等等

- 跳过下载视频（只下载字幕/素材）
  - `python main.py -c <课程 URL> --skip-lectures --download-captions` - 仅下载字幕
  - `python main.py -c <课程 URL> --skip-lectures --download-assets` - 仅下载素材

- 保留 .VTT 字幕文件
  - `python main.py -c <课程 URL> --download-captions --keep-vtt`

- 跳过解析 HLS 流（非 DRM 视频通常 HLS 里包含 1080p）
  - `python main.py -c <课程 URL> --skip-hls`

- 仅打印课程信息
  - `python main.py -c <课程 URL> --info`

- 指定最大并发下载数
  - `python main.py -c <课程 URL> --concurrent-downloads 20`
  - `python main.py -c <课程 URL> -cd 20`

- 缓存课程信息
  - `python main.py -c <课程 URL> --save-to-file`

- 读取课程缓存
  - `python main.py -c <课程 URL> --load-from-file`

- 修改日志级别
  - `python main.py -c <课程 URL> --log-level DEBUG`
  - `python main.py -c <课程 URL> --log-level WARNING`
  - `python main.py -c <课程 URL> --log-level INFO`
  - `python main.py -c <课程 URL> --log-level CRITICAL`

- 使用课程 ID 作为课程目录名
  - `python main.py -c <课程 URL> --id-as-course-name`

- H.265 编码
  - `python main.py -c <课程 URL> --use-h265`

- H.265 编码并指定 CRF
  - `python main.py -c <课程 URL> --use-h265 -h265-crf 20`

- H.265 编码并指定 preset
  - `python main.py -c <课程 URL> --use-h265 --h265-preset faster`

- 使用 NVIDIA 硬件编码（NVENC）
  - `python main.py -c <课程 URL> --use-h265 --use-nvenc`

- 连续编号（每章不从 1 重新开始）
  - `python main.py -c <课程 URL> --continue-lecture-numbers`
  - `python main.py -c <课程 URL> -n`

- 下载指定章节
  - `python main.py -c <课程 URL> --chapter "1,3,5"` - 下载第 1、3、5 章
  - `python main.py -c <课程 URL> --chapter "1-5"` - 下载第 1~5 章
  - `python main.py -c <课程 URL> --chapter "1,3-5,7,9-11"` - 下载第 1 章、第 3~5 章、第 7 章、第 9~11 章

- 下载指定章节并指定清晰度
  - `python main.py -c <课程 URL> --chapter "1-3" -q 720`

- 下载指定章节并下载字幕
  - `python main.py -c <课程 URL> --chapter "1,3" --download-captions`

### 关于作者（About the Creator）

你好！我叫 **Sheikh Bilal**，是一名热爱编码与自动化的 Java 开发者。这个工具是我兴趣与热情的体现，旨在帮助你学习与探索 Udemy 自动化。

联系作者：

- **GitHub**：<https://github.com/sheikh-bilal65>
- **LinkedIn**：<https://www.linkedin.com/in/bilal-ahmad2>
- **Gmail**：<mailto:bilalahmadallbd@gmail.com>
- **Instagram**：<https://www.instagram.com/sheikhh.bilal/>

遇到问题？欢迎通过 Instagram 或邮件联系我！

本工具仅用于 **教育用途**。它演示自动化技术，不应被用于违反 Udemy 服务条款或任何适用法律。作者 Sheikh Bilal 不对任何滥用该工具或由此产生的后果负责。用户需自行确保遵守 Udemy 政策与当地法规。
