# Video 采集助手

> 项目代号：`benchmark-video-collector`。用于小红书、抖音对标视频筛选、本地语音转写及 Excel 导出的本地 MVP。

## 一、版本定位（重要）

- 本目录 `video/` 是**唯一正式版 / 开发目录（GitHub 发布版）**。所有新功能、文档、采集结果都在此维护。
- `对标视频采集助手/` 是**历史测试目录**，仅作归档，不再更新，也不要在其中产生新结果，避免两个版本数据交叉重叠。
- 本目录与“对标视频采集助手”工作目录相互独立。GitHub 仓库名建议 `benchmark-video-collector`，发布时只上传本目录。

## 二、功能

- 按博主链接或关键词发起采集，按日期、点赞数及数量筛选视频。
- 使用 faster-whisper 在本地转写，导出博主账号、标题、发布时间、视频转文字、点赞数、收藏数、原始链接。
- 使用“平台 + 内容 ID”持久化标记已完成内容，后续采集会自动跳过；同时通过视频 SHA-256 防止内容级重复。
- 每次任务都保留独立 Excel；历史列表显示采集时间、平台、博主账号和结果数，默认展示最近 3 个批次。
- 小红书先用列表中的视频类型、真实点赞数和历史 ID 自动预筛，只为候选内容请求详情；粉丝门槛按作者核验并在任务内缓存，不需要用户逐条勾选。
- 小红书采集过程中不会自动重新登录；检测到操作频繁、安全验证或访问限制时立即停止并持久化暂停状态，用户在官方页面恢复后才能手动解除。
- 抖音采集复用已确认的登录状态，并从正常登录网页读取作品列表；登录失效时才要求重新确认。
- 默认最近 30 天、最低 200 赞、最多 10 条；单次硬上限 50 条。
- 本地服务监听 `127.0.0.1:8000`，扫码与验证码由用户手动完成。

## 三、目录结构

**源码（纳入版本控制）：**

- `mvp/`：界面、平台登录会话、采集流程、去重、转写及导出。
- `config/`：默认参数。
- `scripts/`：启动和环境检查。
- `tests/`：参数规则、登录会话、去重、平台采集及 Excel 历史测试。
- `agent/`：自动化操作约束。

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

此发布版已在当前电脑完成抖音真实账号的采集、视频下载、转写、Excel 导出和二次去重验证；在全新电脑安装或更换 MediaCrawler 版本后仍需重新验证接口兼容性。抖音与小红书实际采集结果取决于平台和依赖状态。

## 六、发布与许可

此目录未包含 Cookie、浏览器登录态、运行记录、导出表格、媒体文件、依赖环境或原 Git 历史。上传时选择本目录，不要选择其父目录或旧版“对标视频采集助手”目录。

第三方 MediaCrawler 使用 NON-COMMERCIAL LEARNING LICENSE 1.1，原说明限定非商业学习用途，详见 `THIRD_PARTY_NOTICES.md`。本项目尚未指定自有源码的开源许可证；上传 GitHub 不等于授予任意使用许可。
