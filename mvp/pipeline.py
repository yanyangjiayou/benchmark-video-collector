from __future__ import annotations
import json, os, shutil, subprocess, uuid
from datetime import datetime
from pathlib import Path
from typing import Callable
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from .rules import CollectionRequest
from .transcriber import LocalTranscriber
from .xhs_video import download_missing_videos

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "MediaCrawler"

def resolve_creator_url(url: str) -> str:
    if "xhslink.cn" not in url and "v.douyin.com" not in url:
        return url
    from urllib.request import Request, urlopen
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=20) as response:
        return response.geturl()

def number(value: object) -> int:
    text = str(value or "0").strip().lower().replace(",", "")
    multiple = 10000 if ("万" in text or "w" in text) else 1
    try:
        return int(float(text.replace("万", "").replace("w", "")) * multiple)
    except ValueError:
        return 0

def published(item: dict, platform: str) -> datetime:
    stamp = float(item.get("time" if platform == "xhs" else "create_time") or 0)
    return datetime.fromtimestamp(stamp / 1000 if stamp > 10_000_000_000 else stamp)

def is_video(item: dict, platform: str) -> bool:
    return item.get("type") == "video" if platform == "xhs" else bool(item.get("video_download_url"))

def content_id(item: dict, platform: str) -> str:
    return str(item.get("note_id" if platform == "xhs" else "aweme_id"))

def find_media(raw: Path, platform: str, item_id: str) -> Path | None:
    folder = raw / platform / "videos" / item_id
    return next((p for p in folder.rglob("*") if p.is_file()), None) if folder.exists() else None

def read_rows(raw: Path, platform: str) -> list[dict]:
    files = sorted((raw / platform / "jsonl").glob("*_contents_*.jsonl"))
    if not files:
        return []
    return [json.loads(line) for line in files[-1].read_text(encoding="utf-8").splitlines() if line.strip()]

def export_excel(rows: list[dict], path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "视频结果"
    headers = ["账号", "标题", "发布时间", "视频转文字", "点赞数", "收藏数", "原始链接"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="315EFB")
    for record in rows:
        ws.append([record[h] for h in headers])
    ws.freeze_panes, ws.auto_filter.ref = "A2", ws.dimensions
    for index, width in enumerate([18, 38, 20, 80, 12, 12, 55], 1):
        ws.column_dimensions[chr(64 + index)].width = width
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
        row[-1].hyperlink, row[-1].style = row[-1].value, "Hyperlink"
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)

def run_job(request: CollectionRequest, account_label: str, log: Callable[[str], None],
            progress: Callable[[dict], None] | None = None,
            on_records: Callable[[list[dict]], None] | None = None,
            model_name: str = "small", glossary: str = "") -> tuple[Path, dict, list[dict]]:
    job_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    raw = ROOT / "runtime" / "jobs" / job_id / "raw"
    raw.mkdir(parents=True)
    cmd = [str(VENDOR / ".venv/bin/python"), "main.py", "--platform", request.platform, "--lt", "qrcode",
           "--save_data_option", "jsonl", "--save_data_path", str(raw), "--crawler_max_notes_count", "50",
           "--max_concurrency_num", "1", "--get_comment", "false", "--get_sub_comment", "false",
           "--enable_ip_proxy", "false"]
    if request.trigger_type == "creator_url":
        cmd += ["--type", "creator", "--creator_id", resolve_creator_url(request.creator_url)]
    else:
        cmd += ["--type", "search", "--keywords", ",".join(request.keywords)]
    log("正在启动独立浏览器，请在弹出页面中扫码。")
    env = {**os.environ, "MPLCONFIGDIR": str(ROOT / "runtime/matplotlib"), "UV_CACHE_DIR": str(ROOT / "runtime/uv-cache")}
    process = subprocess.Popen(cmd, cwd=VENDOR, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace")
    for line in iter(process.stdout.readline, ""):
        if line.strip():
            log(line.strip())
    code = process.wait()
    if code:
        raise RuntimeError(f"采集程序退出，代码 {code}")
    all_rows = read_rows(raw, request.platform)
    video_rows = [x for x in all_rows if is_video(x, request.platform)]
    date_rows = [x for x in video_rows if request.start_date <= published(x, request.platform).date() <= request.end_date]
    candidates = [x for x in date_rows if number(x.get("liked_count")) >= request.min_likes]
    candidates = sorted(candidates, key=lambda x: published(x, request.platform), reverse=True)[:request.max_items]
    summary = {"found": len(all_rows), "videos": len(video_rows), "in_date_range": len(date_rows),
               "eligible": len(candidates), "transcribed": 0, "media_missing": 0, "exported": 0,
               "stage": "筛选完成", "estimated_total_seconds": 90 + len(candidates) * (75 if model_name == "small" else 130)}
    if progress:
        progress(summary)
    log(f"筛选结果：发现 {len(all_rows)} 条，其中视频 {len(video_rows)} 条，日期范围内 {len(date_rows)} 条，点赞达到 {request.min_likes} 的 {len(candidates)} 条")
    if request.platform == "xhs" and candidates:
        missing = [item for item in candidates if find_media(raw, request.platform, content_id(item, request.platform)) is None]
        if missing:
            summary["stage"] = "正在取得视频文件"
            if progress:
                progress(summary)
            log(f"MediaCrawler 未取得 {len(missing)} 个视频文件，正在从详情页补取。")
            download_missing_videos(missing, raw, log)
    transcriber, results = LocalTranscriber(model_name), []
    for index, item in enumerate(candidates, 1):
        media = find_media(raw, request.platform, content_id(item, request.platform))
        log(f"正在转写 {index}/{len(candidates)}：{item.get('title', '')[:30]}")
        summary.update(stage=f"正在转写第 {index}/{len(candidates)} 条", current=index)
        if progress:
            progress(summary)
        if media:
            prompt = "，".join(x for x in [glossary.strip(), account_label.strip(), item.get("title", ""), item.get("desc", "")] if x)[:1000]
            transcript = transcriber.transcribe(media, initial_prompt=prompt)
            summary["transcribed"] += 1
        else:
            transcript = "未取得视频文件，无法转写"
            summary["media_missing"] += 1
        results.append({"账号": account_label or item.get("nickname", ""), "标题": item.get("title", ""),
                        "发布时间": published(item, request.platform).strftime("%Y-%m-%d %H:%M:%S"),
                        "视频转文字": transcript, "点赞数": number(item.get("liked_count")),
                        "收藏数": number(item.get("collected_count")),
                        "原始链接": item.get("note_url") or item.get("aweme_url") or ""})
        if on_records:
            on_records(results)
        if progress:
            progress(summary)
    destination = ROOT / "output" / f"{request.platform}_{job_id}.xlsx"
    export_excel(results, destination)
    summary["exported"] = len(results)
    summary["stage"] = "全部完成"
    if progress:
        progress(summary)
    shutil.rmtree(raw, ignore_errors=True)
    log(f"已完成：{destination}")
    return destination, summary, results
