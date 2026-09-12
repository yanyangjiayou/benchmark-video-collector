$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$AppRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $AppRoot "vendor\MediaCrawler\.venv\Scripts\python.exe"
$AppUrl = "http://127.0.0.1:8000"
$InstanceUrl = "$AppUrl/api/instance"

$Existing = $null
try {
    $Existing = Invoke-RestMethod -Uri $InstanceUrl -Method Get -TimeoutSec 2
}
catch {
    if ($null -ne $_.Exception.Response) {
        throw "8000 端口正在运行另一套程序或历史版本。为防止数据交叉，正式版没有启动。"
    }
}

if ($null -ne $Existing) {
    if ($Existing.app_id -eq "benchmark-video-collector" -and $Existing.data_scope -eq "video") {
        Write-Host "正式版已经在运行：$AppUrl" -ForegroundColor Green
        exit 0
    }
    throw "8000 端口正在运行另一套程序。为防止数据交叉，正式版没有启动。"
}

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
