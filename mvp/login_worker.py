from __future__ import annotations
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "MediaCrawler"
sys.path.insert(0, str(VENDOR))

async def noop(*args, **kwargs):
    return None

async def main(platform: str) -> None:
    import config
    config.PLATFORM = platform
    config.LOGIN_TYPE = "qrcode"
    config.ENABLE_IP_PROXY = False
    config.ENABLE_GET_COMMENTS = False
    config.CDP_CONNECT_EXISTING = False
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
        if manager:
            await manager.cleanup(force=True)

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
