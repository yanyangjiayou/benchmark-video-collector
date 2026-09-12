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


def preserve_launched_browser(manager: object) -> bool:
    """Detach a successfully logged-in Chrome from worker exit cleanup."""
    launcher = getattr(manager, "launcher", None)
    process = getattr(launcher, "browser_process", None)
    if launcher is None or process is None or process.poll() is not None:
        return False
    # CDPBrowserManager registered an atexit callback that otherwise terminates
    # this process even when AUTO_CLOSE_BROWSER is disabled. Chrome was launched
    # in its own process group, so dropping this one reference safely leaves it
    # available for the subsequent collection worker.
    launcher.browser_process = None
    return True

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
    # Keep the logged-in browser alive so the 采集 step can reuse it over CDP.
    # Closing it here would force 采集 to auto-launch a second Chrome with the same
    # profile, which exits almost immediately and breaks the run.
    config.AUTO_CLOSE_BROWSER = platform != "xhs"
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

            async def search(self) -> None:
                # Verification must happen while the playwright async context in
                # XiaoHongShuCrawler.start() is still active. Once start() returns,
                # the browser context is closed and any post-hoc check raises
                # TargetClosedError. The user scans the QR during login_obj.begin();
                # this method polls until the server confirms the session.
                for attempt in range(90):  # up to 180s, polling every 2s
                    if await self.xhs_client.pong():
                        break
                    print("等待小红书登录态校验通过，请在弹出窗口中扫码/登录...", flush=True)
                    await asyncio.sleep(2)
                else:
                    raise RuntimeError("小红书登录态未校验通过；请在弹出的窗口中完成扫码/登录")
                print("MVP_LOGIN_CONFIRMED", flush=True)

        crawler = SafeLoginXhsCrawler()
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
    login_completed = False
    try:
        # MediaCrawler's qrcode login extracts the QR from the page and also pops it as a
        # separate OS image window (PIL Image.show). The real, scannable QR already lives in
        # the headed browser window, so we silence the redundant popup to avoid the
        # "scan two codes" confusion. Patched here (after all imports settle) because
        # login_by_qrcode reads utils.show_qrcode at call time from the tools.utils module.
        import tools.utils as _utils

        _utils.show_qrcode = lambda *a, **k: None

        # Launch the browser first; this brings up the platform window (QR code, etc.).
        # 150s gives the user the full Xiaohongshu QR validity window (≈120s) to scan.
        # For xhs, SafeLoginXhsCrawler.search() performs the login verification and
        # prints MVP_LOGIN_CONFIRMED while the playwright context is still open.
        # For dy, confirm_session() persists the session and we confirm success here.
        await asyncio.wait_for(crawler.start(), timeout=150)
        login_completed = True

        if platform != "xhs":
            print("MVP_LOGIN_CONFIRMED", flush=True)
    except asyncio.TimeoutError as exc:
        raise RuntimeError("登录超时，请在平台窗口完成扫码或验证后重试") from exc
    finally:
        manager = getattr(crawler, "cdp_manager", None)
        if manager is not None and config.CDP_CONNECT_EXISTING:
            # We only attached to a window owned by another worker/user action.
            # Exiting Playwright disconnects from it; do not close its context.
            pass
        elif manager is not None and platform == "xhs" and login_completed:
            preserve_launched_browser(manager)
        elif manager is not None:
            await manager.cleanup(force=True)
        elif manager is None and getattr(crawler, "browser_context", None):
            await crawler.browser_context.close()

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
