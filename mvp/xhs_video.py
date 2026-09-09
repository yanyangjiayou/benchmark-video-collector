from __future__ import annotations

import asyncio
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
                    await page.wait_for_timeout(5_000)
                    browser_urls = await page.evaluate("""() => {
                        const found = [];
                        document.querySelectorAll('video, video source').forEach(v => {
                            if (v.currentSrc) found.push(v.currentSrc);
                            if (v.src) found.push(v.src);
                        });
                        performance.getEntriesByType('resource').forEach(e => found.push(e.name));
                        const seen = new Set();
                        const walk = (x, depth=0) => {
                            if (depth > 12 || x == null) return;
                            if (typeof x === 'string') {
                                if (x.startsWith('http') && (x.includes('sns-video') || x.includes('.mp4'))) seen.add(x);
                                return;
                            }
                            if (Array.isArray(x)) return x.forEach(v => walk(v, depth+1));
                            if (typeof x === 'object') Object.values(x).forEach(v => walk(v, depth+1));
                        };
                        try { walk(window.__INITIAL_STATE__); } catch (_) {}
                        return [...found, ...seen];
                    }""")
                    candidates = []
                    for url in [*observed, *browser_urls]:
                        if isinstance(url, str) and _looks_like_video(url) and not url.startswith("blob:") and url not in candidates:
                            candidates.append(url)
                    log(f"详情页发现 {len(candidates)} 个候选视频地址")
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
    """Use the logged-in detail page as a fallback when MediaCrawler returns an empty video_url."""
    return asyncio.run(_download(items, raw, log))
