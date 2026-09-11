$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$AppRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $AppRoot "vendor\MediaCrawler\.venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "缺少依赖环境，请先运行 scripts\install-windows.ps1。"
}

$env:PYTHONPATH = $AppRoot
$env:MPLCONFIGDIR = Join-Path $AppRoot "runtime\matplotlib"
$env:UV_CACHE_DIR = Join-Path $AppRoot "runtime\uv-cache"

New-Item -ItemType Directory -Force -Path $env:MPLCONFIGDIR | Out-Null
New-Item -ItemType Directory -Force -Path $env:UV_CACHE_DIR | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $AppRoot "output") | Out-Null

Set-Location $AppRoot
& $Python -m uvicorn mvp.app:app --host 127.0.0.1 --port 8000
if ($LASTEXITCODE -ne 0) {
    throw "服务启动失败，退出代码：$LASTEXITCODE"
}
