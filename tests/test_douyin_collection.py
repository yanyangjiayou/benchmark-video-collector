import asyncio
from datetime import datetime
import json
from types import SimpleNamespace
import sys

import pytest

from mvp import crawler_worker, douyin_session, douyin_page
from mvp.history import CollectionHistory


@pytest.mark.parametrize("collected,expected", [([], "2"), (["2"], "3")])
def test_only_new_videos_meeting_like_threshold_are_downloaded(tmp_path, monkeypatch, collected, expected):
    raw = tmp_path / "runtime/jobs/test/raw"
    raw.mkdir(parents=True)
    (raw.parent / "request.json").write_text(json.dumps({"request": {
        "platform": "dy", "trigger_type": "creator_url", "creator_url": "https://www.douyin.com/user/MS4wExample",
        "min_likes": 350, "max_items": 1,
    }}))
    history = CollectionHistory(tmp_path / "runtime/collection_history.sqlite3")
    history.record_many([{"platform": "dy", "content_id": item_id} for item_id in collected])
    downloaded = []
    stored = []
    posts = [{"aweme_id": str(index), "create_time": datetime.now().timestamp() - index,
              "statistics": {"digg_count": 348 + index}} for index in range(1, 4)]

    class Client:
        calls = 0

        async def get_user_aweme_posts(self, user, cursor):
            self.calls += 1
            assert self.calls == 1, "must stop once enough eligible new videos are found"
            return {"status_code": 0, "aweme_list": posts, "has_more": 1, "max_cursor": "next"}

    class PageSource:
        def __init__(self, *args):
            self.client = Client()

        async def start(self, url):
            pass

        async def next_page(self):
            return await self.client.get_user_aweme_posts("example", "")

        async def close(self):
            pass

    class Crawler:
        def __init__(self):
            self.dy_client = Client()
            self.context_page = None

        async def get_aweme_video(self, item):
            downloaded.append(item["aweme_id"])

    async def store(item):
        stored.append(item)

    factory = SimpleNamespace(CRAWLERS={})
    vendor_main = SimpleNamespace(CrawlerFactory=factory, main=None, async_cleanup=None)

    def run(*args):
        asyncio.run(factory.CRAWLERS["dy"]().get_creators_and_videos())

    monkeypatch.setattr(crawler_worker, "VENDOR", tmp_path / "vendor/MediaCrawler")
    monkeypatch.setattr(douyin_session, "configure_session", lambda *args, **kwargs: None)
    monkeypatch.setattr(douyin_page, "BrowserPostSource", PageSource)
    async def download(page, item, raw):
        downloaded.append(item["aweme_id"])
    monkeypatch.setattr(douyin_page, "download_video", download)
    modules = {
        "main": vendor_main,
        "media_platform.douyin": SimpleNamespace(DouYinCrawler=Crawler),
        "media_platform.douyin.help": SimpleNamespace(parse_creator_info_from_url=lambda url: SimpleNamespace(sec_user_id="example")),
        "tools.app_runner": SimpleNamespace(run=run),
        "config": SimpleNamespace(SAVE_DATA_PATH=str(raw), DY_CREATOR_ID_LIST=["example"]),
        "store": SimpleNamespace(douyin=SimpleNamespace(update_douyin_aweme=store, _extract_video_download_url=lambda item: "video.mp4")),
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    crawler_worker.main()
    assert downloaded == [expected]
    assert len(stored) == 3
