$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$AppRoot = Split-Path -Parent $PSScriptRoot
$VendorRoot = Join-Path $AppRoot "vendor\MediaCrawler"
$Python = Join-Path $VendorRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $VendorRoot -PathType Container)) {
    throw "缺少 vendor\MediaCrawler，请先按 README.md 放置兼容版本。"
}
if (-not (Test-Path -LiteralPath (Join-Path $VendorRoot "main.py") -PathType Leaf)) {
    throw "MediaCrawler 源码不完整：缺少 main.py。"
}
if (-not (Test-Path -LiteralPath (Join-Path $VendorRoot "LICENSE") -PathType Leaf)) {
    throw "MediaCrawler 源码不完整：缺少 LICENSE。"
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "缺少 Windows Python 环境，请先运行 scripts\install-windows.ps1。"
}

& $Python -c "import fastapi, openpyxl, faster_whisper, playwright; print('环境检查通过')"
if ($LASTEXITCODE -ne 0) {
    throw "Python 依赖检查失败。"
}

Write-Host "Windows 环境检查通过。" -ForegroundColor Green
