"""Read the creator posts loaded by Douyin's normal logged-in webpage."""
from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import parse_qs, urlparse


class BrowserPostSource:
    def __init__(self, page, creator_id: str):
        self.page = page
        self.creator_id = creator_id
        self.queue = asyncio.Queue()
        self.tasks = set()
        self.seen = set()
        self.first_page = True

    async def capture(self, response):
        url = urlparse(response.url)
        if not (url.hostname or "").endswith(".douyin.com") or url.path != "/aweme/v1/web/aweme/post/":
            return
        if parse_qs(url.query).get("sec_user_id", [""])[0] != self.creator_id:
            return
        try:
            data = await response.json()
        except Exception:
            # The webpage can retry another endpoint itself; wait for its result.
            return
        if not isinstance(data, dict):
            return
        if data.get("status_code", 0) != 0 or "aweme_list" not in data:
            return
        posts = data.get("aweme_list") or []
        key = (str(data.get("max_cursor")), tuple(str(item.get("aweme_id")) for item in posts))
        if key not in self.seen:
            self.seen.add(key)
            await self.queue.put(data)

    def on_response(self, response):
        task = asyncio.create_task(self.capture(response))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def start(self, url):
        self.page.on("response", self.on_response)
        await self.page.goto(url, wait_until="domcontentloaded", timeout=45000)

    async def next_page(self):
        if self.first_page:
            self.first_page = False
            try:
                return await asyncio.wait_for(self.queue.get(), timeout=35)
            except asyncio.TimeoutError as exc:
                raise RuntimeError("抖音网页未能加载作品列表，请在抖音网页检查登录、验证或服务异常提示") from exc
        if not self.queue.empty():
            return await self.queue.get()
        for _ in range(4):
            links = self.page.locator('a[href*="/video/"]')
            if await links.count():
                await links.last.scroll_into_view_if_needed(timeout=5000)
            await self.page.mouse.wheel(0, 1200)
            try:
                return await asyncio.wait_for(self.queue.get(), timeout=4)
            except asyncio.TimeoutError:
                continue
        raise RuntimeError("抖音网页没有加载更多作品，请稍后重试；已保存本次运行记录")

    async def close(self):
        self.page.remove_listener("response", self.on_response)
        if self.tasks:
            await asyncio.gather(*list(self.tasks), return_exceptions=True)


async def download_video(page, item, raw: Path) -> bool:
    video = item.get("video") or {}
    urls = list(dict.fromkeys(url for key in ("play_addr", "play_addr_h264", "play_addr_256")
                            for url in (video.get(key) or {}).get("url_list", []) if url.startswith("https://")))
    item_id = str(item.get("aweme_id") or "")
    if not item_id or Path(item_id).name != item_id:
        return False
    headers = {"Referer": "https://www.douyin.com/", "User-Agent": await page.evaluate("() => navigator.userAgent")}
    for url in urls[:3]:
        response = None
        try:
            response = await page.context.request.get(url, headers=headers, timeout=60000)
            if response.status != 200:
                continue
            body = await response.body()
            if b"ftyp" not in body[:32]:
                continue
            destination = raw / "douyin" / "videos" / item_id / "video.mp4"
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(".part")
            temporary.write_bytes(body)
            temporary.replace(destination)
            return True
        except Exception as exc:
            print(f"视频下载暂未成功：{type(exc).__name__}", flush=True)
        finally:
            if response is not None:
                await response.dispose()
    print(f"未取得视频文件：{item_id}；本条不会标记为已采集", flush=True)
    return False
