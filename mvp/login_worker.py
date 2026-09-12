from __future__ import annotations
import asyncio
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "MediaCrawler"
sys.path.insert(0, str(VENDOR))

async def noop(*args, **kwargs):
    return None


PLATFORM_PAGE_MARKERS = {
    "xhs": ("xiaohongshu.com", "xhscdn.com"),
    "dy": ("douyin.com",),
}


def find_platform_browser(platform: str, start_port: int = 9222, port_count: int = 100) -> int | None:
    """Return a CDP port only when its open pages belong to the requested platform."""
    markers = PLATFORM_PAGE_MARKERS.get(platform, ())
    for port in range(start_port, start_port + port_count):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=0.08) as response:
                pages = json.load(response)
        except (OSError, ValueError):
            continue
        urls = "\n".join(str(page.get("url", "")).lower() for page in pages if isinstance(page, dict))
        if any(marker in urls for marker in markers):
            return port
    return None

async def main(platform: str) -> None:
    import config
    config.PLATFORM = platform
    config.LOGIN_TYPE = "qrcode"
    config.ENABLE_IP_PROXY = False
    config.ENABLE_GET_COMMENTS = False
    # Reuse the requested platform's browser after login. Starting a second Chrome
    # process with the same profile makes Chrome exit immediately.
    existing_port = find_platform_browser(platform, config.CDP_DEBUG_PORT)
    config.CDP_CONNECT_EXISTING = existing_port is not None
    if existing_port is not None:
        config.CDP_DEBUG_PORT = existing_port
    if platform == "xhs":
        from media_platform.xhs import XiaoHongShuCrawler
        from .xhs_worker import strict_login_probe

        class SafeLoginXhsCrawler(XiaoHongShuCrawler):
            async def create_xhs_client(self, httpx_proxy):
                client = await super().create_xhs_client(httpx_proxy)

                async def strict_pong() -> bool:
                    return await strict_login_probe(client)

                client.pong = strict_pong
                return client

        crawler = SafeLoginXhsCrawler()
        crawler.search = noop
        crawler.get_specified_notes = noop
        crawler.get_creators_and_notes = noop
    elif platform == "dy":
        from media_platform.douyin import DouYinCrawler
        from .douyin_session import configure_session, save_session
        crawler = DouYinCrawler()
        configure_session(crawler, allow_login=True)

        async def confirm_session(*args, **kwargs):
            await save_session(crawler.browser_context)

        crawler.search = confirm_session
        crawler.get_specified_awemes = confirm_session
        crawler.get_creators_and_videos = confirm_session
    else:
        raise ValueError("首版只支持小红书和抖音")
    try:
        # Bound the third-party login wait; the worker always releases its browser.
        await asyncio.wait_for(crawler.start(), timeout=180)
        print("MVP_LOGIN_CONFIRMED", flush=True)
    except asyncio.TimeoutError as exc:
        raise RuntimeError("登录超时，请在平台窗口完成扫码或验证后重试") from exc
    finally:
        manager = getattr(crawler, "cdp_manager", None)
        if manager is not None and not config.CDP_CONNECT_EXISTING:
            await manager.cleanup(force=True)
        elif manager is None and getattr(crawler, "browser_context", None):
            await crawler.browser_context.close()

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
