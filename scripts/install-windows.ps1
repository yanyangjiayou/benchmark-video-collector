$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$AppRoot = Split-Path -Parent $PSScriptRoot
$VendorRoot = Join-Path $AppRoot "vendor\MediaCrawler"
$Requirements = Join-Path $AppRoot "requirements-mvp.txt"
$Python = Join-Path $VendorRoot ".venv\Scripts\python.exe"

if (-not [Environment]::Is64BitOperatingSystem) {
    throw "当前依赖要求 64 位 Windows。"
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "未找到 uv，请先安装 uv 并重新打开终端。"
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw "未找到 Node.js，请先安装 Node.js 16 或更高版本。"
}
if (-not (Test-Path -LiteralPath (Join-Path $VendorRoot "main.py") -PathType Leaf)) {
    throw "缺少完整的 vendor\MediaCrawler。请先按 README.md 放置兼容版本。"
}
if (-not (Test-Path -LiteralPath (Join-Path $VendorRoot "LICENSE") -PathType Leaf)) {
    throw "MediaCrawler 源码缺少 LICENSE，已停止安装。"
}

Push-Location $VendorRoot
try {
    & uv sync
    if ($LASTEXITCODE -ne 0) {
        throw "MediaCrawler 依赖安装失败。"
    }
}
finally {
    Pop-Location
}

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "uv 未创建预期的 Windows 虚拟环境：$Python"
}

& uv pip install --python $Python -r $Requirements
if ($LASTEXITCODE -ne 0) {
    throw "本项目依赖安装失败。"
}

& $Python -m playwright install chromium
if ($LASTEXITCODE -ne 0) {
    throw "Playwright Chromium 安装失败。"
}

& (Join-Path $PSScriptRoot "healthcheck.ps1")
Write-Host "安装完成。首次转写时还会下载所选 Whisper 模型。" -ForegroundColor Green
