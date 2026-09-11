from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "MediaCrawler"


def _looks_like_video(url: str) -> bool:
    value = url.lower()
    return url.startswith("http") and ("sns-video" in value or ".mp4" in value or "/stream/" in value)


async def _download(items: list[dict], raw: Path, log: Callable[[str], None]) -> dict[str, Path]:
    sys.path.insert(0, str(VENDOR))
    import config
    from playwright.async_api import async_playwright
    from tools.cdp_browser import CDPBrowserManager

    config.PLATFORM = "xhs"
    config.SAVE_LOGIN_STATE = True
    config.CDP_CONNECT_EXISTING = False
    manager = CDPBrowserManager()
    downloaded: dict[str, Path] = {}
    async with async_playwright() as playwright:
        context = await manager.launch_and_connect(playwright, headless=False)
        try:
            cookies = await context.cookies(["https://www.xiaohongshu.com"])
            if not any(cookie.get("name") == "web_session" and cookie.get("value") for cookie in cookies):
                raise RuntimeError("补取视频的浏览器未读取到小红书登录状态，请重新确认登录")
            page = await context.new_page()
            for index, item in enumerate(items, 1):
                note_id = str(item.get("note_id", ""))
                note_url = str(item.get("note_url", ""))
                if not note_id or not note_url:
                    continue
                log(f"正在补取视频文件 {index}/{len(items)}：{item.get('title', '')[:30]}")
                observed: list[str] = []

                def remember(response) -> None:
                    content_type = response.headers.get("content-type", "").lower()
                    if "video" in content_type or _looks_like_video(response.url):
                        observed.append(response.url)

                page.on("response", remember)
                try:
                    await page.goto(note_url, wait_until="domcontentloaded", timeout=45_000)
                    try:
                        await page.locator("video").first.wait_for(state="attached", timeout=8_000)
                    except Exception:
                        pass
                    await page.wait_for_timeout(1_000)
                    browser_urls = await page.evaluate("""noteId => {
                        const isVideoUrl = value => typeof value === 'string' && value.startsWith('http') &&
                            (value.includes('sns-video') || value.includes('.mp4') || value.includes('/stream/'));
                        const unique = values => [...new Set(values.filter(isVideoUrl))];
                        const collectUrls = (value, found, depth=0) => {
                            if (depth > 12 || value == null) return;
                            if (typeof value === 'string') { if (isVideoUrl(value)) found.push(value); return; }
                            if (Array.isArray(value)) { value.forEach(v => collectUrls(v, found, depth+1)); return; }
                            if (typeof value === 'object') Object.values(value).forEach(v => collectUrls(v, found, depth+1));
                        };
                        const matched = [];
                        const findNote = (value, depth=0) => {
                            if (depth > 12 || value == null || typeof value !== 'object') return;
                            if (!Array.isArray(value)) {
                                const ids = [value.note_id, value.noteId, value.id].map(String);
                                if (ids.includes(String(noteId))) { collectUrls(value, matched); return; }
                            }
                            Object.values(value).forEach(v => findNote(v, depth+1));
                        };
                        try { findNote(window.__INITIAL_STATE__); } catch (_) {}
                        const visibleVideos = [...document.querySelectorAll('video')]
                            .map(video => ({video, rect: video.getBoundingClientRect()}))
                            .filter(({rect}) => rect.width > 80 && rect.height > 80)
                            .sort((a, b) => b.rect.width * b.rect.height - a.rect.width * a.rect.height)
                            .flatMap(({video}) => [video.currentSrc, video.src, ...[...video.querySelectorAll('source')].map(s => s.src)]);
                        return {matched: unique(matched), visible: unique(visibleVideos)};
                    }""", note_id)
                    confident_urls = [*browser_urls.get("matched", []), *browser_urls.get("visible", [])]
                    observed_urls = list(dict.fromkeys(url for url in observed if _looks_like_video(url)))
                    if not confident_urls and len(observed_urls) == 1:
                        confident_urls = observed_urls
                    candidates = []
                    for url in confident_urls:
                        if isinstance(url, str) and _looks_like_video(url) and not url.startswith("blob:") and url not in candidates:
                            candidates.append(url)
                    log(f"详情页发现 {len(candidates)} 个与当前笔记匹配的视频地址")
                    for video_url in candidates:
                        response = await context.request.get(video_url, headers={"Referer": note_url}, timeout=60_000)
                        if response.ok:
                            body = await response.body()
                            content_type = response.headers.get("content-type", "").lower()
                            is_media = content_type.startswith("video/") or body[4:12] in {b"ftypisom", b"ftypmp42", b"ftypMSNV"}
                            if len(body) > 50_000 and is_media:
                                destination = raw / "xhs" / "videos" / note_id / "0.mp4"
                                destination.parent.mkdir(parents=True, exist_ok=True)
                                destination.write_bytes(body)
                                downloaded[note_id] = destination
                                log(f"视频文件已取得：{item.get('title', '')[:30]}")
                                break
                    if note_id not in downloaded:
                        log(f"未能从详情页取得视频：{item.get('title', '')[:30]}")
                except Exception as exc:
                    log(f"补取视频失败：{item.get('title', '')[:30]}（{exc}）")
                finally:
                    page.remove_listener("response", remember)
        finally:
            await manager.cleanup()
    return downloaded


def download_missing_videos(items: list[dict], raw: Path, log: Callable[[str], None]) -> dict[str, Path]:
    """Run fallback downloading from the vendor cwd so it reuses the crawler login profile."""
    request_path = raw.parent / ".xhs_video_request.json"
    request_path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(ROOT), str(VENDOR))),
        "MPLCONFIGDIR": str(ROOT / "runtime/matplotlib"),
    }
    command = [
        sys.executable,
        "-m",
        "mvp.xhs_video_worker",
        str(request_path),
        str(raw),
    ]
    try:
        process = subprocess.Popen(
            command,
            cwd=VENDOR,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if process.stdout:
            for line in iter(process.stdout.readline, ""):
                if line.strip():
                    log(line.strip())
        code = process.wait()
        if code:
            raise RuntimeError(f"补取视频程序退出，代码 {code}")
    finally:
        request_path.unlink(missing_ok=True)
    return {
        str(item.get("note_id")): path
        for item in items
        if (path := next((raw / "xhs" / "videos" / str(item.get("note_id"))).glob("*"), None)) is not None
    }
