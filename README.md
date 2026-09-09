# 对标视频采集助手

用于小红书、抖音对标视频筛选、本地语音转写及 Excel 导出的本地 MVP。

此目录为 **GitHub 发布版**，与原“对标视频采集助手”工作目录独立。建议 GitHub 仓库名：`benchmark-video-collector`。

## 功能

- 按博主链接或关键词发起采集，按日期、点赞数及数量筛选视频。
- 使用 faster-whisper 在本地转写，导出账号、标题、发布时间、视频转文字、点赞数、收藏数、原始链接。
- 默认最近 30 天、最低 200 赞、最多 10 条；单次硬上限 50 条。
- 本地服务监听 `127.0.0.1:8000`，扫码与验证码由用户手动完成。

## 安装与运行（macOS）

需要 Python 3.11+、Node.js（供第三方采集器执行 JavaScript）、uv，以及可用的浏览器环境。启动脚本使用 zsh。

本仓库不包含 MediaCrawler 第三方源码及本机环境。先阅读 [MediaCrawler 项目](https://github.com/NanmiCoder/MediaCrawler) 的安装说明与许可证，自行取得兼容版本并放置在 `vendor/MediaCrawler/`，保留其许可证。该目录已加入 Git 忽略规则，不要随本项目上传。

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

第三方采集器配置需要关闭评论、图片与代理、限制并发为 1，并使用独立浏览器目录；不要指向日常浏览器配置。发布包未携带原机的第三方配置。仅修改 `config/defaults.json` 不代表第三方所有配置都会同步生效。

## 目录

- `mvp/`：界面、采集流程、转写及导出。
- `config/`：默认参数。
- `scripts/`：启动和环境检查。
- `tests/`：参数规则测试。
- `agent/`：自动化操作约束。

## 验证与限制

```sh
vendor/MediaCrawler/.venv/bin/python -m pytest tests -q
```

此发布版整理保留助手源码，未在全新电脑上完成安装及真实平台端到端验证。原目录的 MediaCrawler 不含 Git 提交信息，无法锁定原机所用上游版本；取得新版本后需验证接口兼容性。抖音与小红书实际采集结果取决于平台和依赖状态。

## 发布与许可

此目录未包含 Cookie、浏览器登录态、运行记录、导出表格、媒体文件、依赖环境或原 Git 历史。上传时选择本目录，不要选择其父目录或原工作目录。

第三方 MediaCrawler 使用 NON-COMMERCIAL LEARNING LICENSE 1.1，原说明限定非商业学习用途，详见 `THIRD_PARTY_NOTICES.md`。本项目尚未指定自有源码的开源许可证；上传 GitHub 不等于授予任意使用许可。
