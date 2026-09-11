"""Run MediaCrawler with the same Douyin session used by login confirmation."""
from __future__ import annotations

import sys
import asyncio
import json
from datetime import datetime
from pathlib import Path

VENDOR = Path(__file__).resolve().parents[1] / "vendor" / "MediaCrawler"
sys.path.insert(0, str(VENDOR))


def main():
    import main as vendor_main
    from media_platform.douyin import DouYinCrawler
    from tools.app_runner import run
    from .douyin_session import configure_session
    from .history import CollectionHistory
    from .rules import CollectionRequest
    from .douyin_page import BrowserPostSource, download_video

    class SessionDouYinCrawler(DouYinCrawler):
        def __init__(self):
            super().__init__()
            configure_session(self, allow_login=False)

        async def get_creators_and_videos(self):
            import config
            from media_platform.douyin.help import parse_creator_info_from_url
            from store import douyin as store

            raw = Path(config.SAVE_DATA_PATH)
            settings = json.loads((raw.parent / "request.json").read_text(encoding="utf-8"))
            request = CollectionRequest.model_validate(settings["request"])
            history = CollectionHistory(VENDOR.parents[1] / "runtime/collection_history.sqlite3")
            posts = {}
            for creator_url in config.DY_CREATOR_ID_LIST:
                user_id = parse_creator_info_from_url(creator_url).sec_user_id
                seen_cursors = set()
                selected = []
                source = BrowserPostSource(self.context_page, user_id)
                await source.start(creator_url)
                # Bound metadata pagination; download only the requested new videos.
                for _ in range(12):
                    result = await source.next_page()
                    if result.get("status_code", 0) != 0 or "aweme_list" not in result:
                        raise RuntimeError("抖音未返回作品列表，请在平台网页确认登录和访问状态")
                    page_posts = result.get("aweme_list") or []
                    for item in page_posts:
                        item_id = str(item.get("aweme_id") or "")
                        if item_id and item_id not in posts:
                            posts[item_id] = item
                            await store.update_douyin_aweme(item)
                    seen_ids = history.seen_content_ids("dy", posts)
                    selected = sorted((item for item_id, item in posts.items()
                        if item_id not in seen_ids and not item.get("images")
                        and store._extract_video_download_url(item)
                        and ((item.get("statistics") or {}).get("digg_count") or 0) >= request.min_likes
                        and request.start_date <= datetime.fromtimestamp(item.get("create_time") or 0).date() <= request.end_date),
                        key=lambda item: item.get("create_time", 0), reverse=True)[:request.max_items]
                    print(f"已读取 {len(posts)} 条作品，找到 {len(selected)} 条符合条件的新视频", flush=True)
                    if len(selected) >= request.max_items or not result.get("has_more") or not page_posts:
                        break
                    if all(datetime.fromtimestamp(item.get("create_time") or 0).date() < request.start_date for item in page_posts):
                        break
                    next_cursor = str(result.get("max_cursor") or "")
                    if not next_cursor or next_cursor in seen_cursors:
                        raise RuntimeError("抖音作品列表分页未前进，请稍后重试")
                    seen_cursors.add(next_cursor)
                    await asyncio.sleep(2)
                await source.close()
                for index, item in enumerate(selected, 1):
                    print(f"正在下载符合条件的视频 {index}/{len(selected)}", flush=True)
                    await download_video(self.context_page, item, raw)

    vendor_main.CrawlerFactory.CRAWLERS["dy"] = SessionDouYinCrawler
    run(vendor_main.main, vendor_main.async_cleanup)


if __name__ == "__main__":
    main()
