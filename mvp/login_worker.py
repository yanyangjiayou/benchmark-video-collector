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
        crawler = XiaoHongShuCrawler()
        crawler.search = noop
        crawler.get_specified_notes = noop
        crawler.get_creators_and_notes = noop
    elif platform == "dy":
        from media_platform.douyin import DouYinCrawler
        crawler = DouYinCrawler()
        crawler.search = noop
        crawler.get_specified_awemes = noop
        crawler.get_creators_and_videos = noop
    else:
        raise ValueError("首版只支持小红书和抖音")
    await crawler.start()
    print("MVP_LOGIN_CONFIRMED")

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))

