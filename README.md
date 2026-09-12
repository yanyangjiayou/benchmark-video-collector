# Video 采集助手

> 项目代号：`benchmark-video-collector`。用于小红书、抖音对标视频筛选、本地语音转写及 Excel 导出的本地 MVP。

## 一、版本定位（重要）

- 本仓库是 `benchmark-video-collector` 的正式开发与发布目录。
- 源码、测试和使用文档在 Git 中维护；采集结果与登录状态仅保存在运行电脑，不进入 GitHub。

## 二、功能

- 按博主链接或关键词发起采集，按日期、点赞数及数量筛选视频。
- 使用 faster-whisper 在本地转写，导出博主账号、标题、发布时间、视频转文字、点赞数、收藏数、原始链接。
- 使用“平台 + 内容 ID”持久化标记已完成内容，后续采集会自动跳过；同时通过视频 SHA-256 防止内容级重复。
- 每次任务都保留独立 Excel；历史列表显示采集时间、平台、博主账号和结果数，默认展示最近 3 个批次。
- 小红书先用列表中的视频类型、点赞数、发布日期和历史 ID 自动预筛，只为候选内容请求详情；日期无法可靠识别时才使用详情兜底。
- 最低粉丝数仅用于“关键词发现博主”，按博主核验并在任务内缓存；指定博主主页时不显示该条件。
- 小红书采集过程中不会自动重新登录；检测到操作频繁、安全验证或访问限制时立即停止并持久化暂停状态，用户在官方页面恢复后才能手动解除。
- 抖音采集复用已确认的登录状态，并从正常登录网页读取作品列表；登录失效时才要求重新确认。
- 默认最近 30 天、最低 200 赞、最多 10 条；单次硬上限 50 条。
- 本地服务监听 `127.0.0.1:8000`，扫码与验证码由用户手动完成。
- 启动器会核验服务身份；如果 8000 端口属于历史版本或其他程序，将停止启动而不会误开另一套页面。

## 三、目录结构

**源码（纳入版本控制）：**

- `mvp/`：界面、平台登录会话、采集流程、去重、转写及导出。
- `config/`：默认参数。
- `scripts/`：启动和环境检查。
- `tests/`：参数规则、登录会话、去重、平台采集及 Excel 历史测试。
- `agent/`：自动化操作约束。
- `docs/`：技术诊断和补充说明。

**运行时生成 / 本地提供（已被 `.gitignore` 忽略，不会上传，但物理上位于本目录内，是本目录“完整运行”的一部分）：**

- `output/`：每次采集的 Excel + JSON 结果。首次启动自动创建；历史采集 Excel 统一存放于此。
- `runtime/`：去重数据库 `collection_history.sqlite3`、登录日志、临时媒体、matplotlib / uv 缓存。首次启动自动创建。
- `browser_data/`：平台登录态（独立浏览器目录）。登录时自动创建。
- `vendor/MediaCrawler/`：第三方采集器源码，**不随本仓库提供**，需自行放置（见第四节）。该目录被 git 忽略。

> 说明：`output/`、`runtime/`、`browser_data/`、`vendor/` 都已加入 `.gitignore`，不会进入 GitHub，但会真实存在于你本机的 `video/` 目录中，使本目录成为一个可独立运行、结果自包含的完整文件夹。在 `video/` 中查找历史 Excel，请直接看 `video/output/`，而不是旧版 `对标视频采集助手/output/`。

## 四、运行环境

需要 64 位操作系统、Python 3.11+、Node.js（供第三方采集器执行 JavaScript）、uv，以及可用的浏览器环境。代码提供 macOS 和 64 位 Windows 10/11 启动方式；Windows 仍需在目标电脑完成平台登录与采集冒烟验证。Windows on ARM 尚未验证。

本仓库不包含 MediaCrawler 第三方源码及本机环境。先阅读 [MediaCrawler 项目](https://github.com/NanmiCoder/MediaCrawler) 的安装说明与许可证，自行取得兼容版本并放置在 `vendor/MediaCrawler/`，保留其许可证。该目录已加入 Git 忽略规则，不要随本项目上传。

### macOS

在本项目根目录执行：

```sh
cd vendor/MediaCrawler
uv sync
cd ../..
uv pip install --python vendor/MediaCrawler/.venv/bin/python -r requirements-mvp.txt
vendor/MediaCrawler/.venv/bin/python -m playwright install chromium
zsh scripts/healthcheck.sh
zsh scripts/start.sh
```

打开 http://127.0.0.1:8000 。环境安装完成后也可双击 `启动工具.command`。首次转写可能需要下载模型，输出保存在 `output/`。

> **小红书浏览器使用方式（重要）**：
> 1. 采集前点击网页中的「确认登录」，完成扫码后保持弹出的专用 Chrome 窗口开启。
> 2. 正式采集和视频补取会复用这个窗口，不会再次启动同一登录目录。
> 3. 如果窗口意外关闭，可双击 `启动小红书Chrome.command` 重新打开；确认登录后再采集。
> 4. 不要同时打开两个“小红书专用 Chrome”。程序检测不到可复用窗口时会停止并给出提示，避免登录状态互相挤占。
> 5. 正式版为小红书和抖音分别使用固定专用端口，不扫描或复用历史项目的登录窗口。

### Windows 10/11（x86-64）

建议将整个项目放在不含中文、层级较浅的路径，例如 `C:\video-collector`，以减少第三方工具的路径兼容问题。安装好 uv、Node.js 16+ 和 Chrome/Edge 后，在 PowerShell 中执行：

```powershell
cd C:\video-collector
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-windows.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1
```

也可以依次双击 `安装依赖-Windows.bat` 和 `启动工具-Windows.bat`。浏览器打开后访问 http://127.0.0.1:8000 。

当前转写固定使用 CPU `int8`，普通 Intel/AMD Windows 电脑不需要 NVIDIA 显卡或 CUDA。建议至少 8 GB 内存，16 GB 更合适。首次选择 `small` 或 `medium` 模型时需要联网下载模型；普通电脑优先使用默认的 `small`，它采用快速解码；`medium` 保留更慢的束搜索以换取准确度。`faster-whisper` 通过 PyAV 解码媒体，通常无需单独安装 FFmpeg。若导入 CTranslate2 时提示缺少运行库，请安装 Microsoft Visual C++ Redistributable。

已完成内容的去重记录保存在 `runtime/collection_history.sqlite3`，重启工具后仍有效。未取得视频或转写失败的内容不会写入历史，下次可自动重试。
每次采集的 Excel（包括 0 条新内容的批次）都会持久保存在 `output/`。网页底部的“历史采集 Excel”会显示采集时间、平台、博主账号、结果数和下载入口。

第三方采集器配置需要关闭评论、图片与代理、限制并发为 1，并使用独立浏览器目录；不要指向日常浏览器配置。发布包未携带原机的第三方配置。仅修改 `config/defaults.json` 不代表第三方所有配置都会同步生效。

小红书的目标数量不是无限扫描承诺。程序按目标数量动态设置列表预算（最低 20、最高 50），达到目标后立即停止；页面会分别显示列表扫描数、详情请求数和点赞预筛排除数。关键点赞、粉丝或发布时间无法核验时，程序不会把缺失值当 0，也不会导出无法确认是否合格的结果。

## 五、验证与限制

macOS：

```sh
vendor/MediaCrawler/.venv/bin/python -m pytest tests -q
```

Windows：

```powershell
.\vendor\MediaCrawler\.venv\Scripts\python.exe -m pytest tests -q
```

此发布版已在当前电脑完成抖音和小红书真实账号的采集、视频下载、转写、Excel 导出与去重验证；在全新电脑安装或更换 MediaCrawler 版本后仍需重新验证接口兼容性。实际采集结果取决于平台、账号、网络和依赖状态。

有关底层采集器的选型、许可与兼容风险，参见 [`docs/MediaCrawler-替换诊断.md`](docs/MediaCrawler-替换诊断.md)。该文档是阶段性技术诊断，不替代当前 README 和测试结果。

## 六、发布与许可

Git 跟踪内容不包含 Cookie、浏览器登录态、运行记录、导出表格、媒体文件或依赖环境。上传时只提交本仓库中已跟踪及明确新增的源码、测试和文档，不要上传项目父目录。

第三方 MediaCrawler 使用 NON-COMMERCIAL LEARNING LICENSE 1.1，原说明限定非商业学习用途，详见 `THIRD_PARTY_NOTICES.md`。本项目尚未指定自有源码的开源许可证；上传 GitHub 不等于授予任意使用许可。
