import asyncio
from datetime import datetime
import sys
from types import SimpleNamespace

from mvp.history import CollectionHistory
from mvp.rules import CollectionRequest
from mvp.xhs_worker import (
    FilteredXhsCrawlerMixin,
    extract_follower_count,
    is_access_restriction,
    normalise_card,
    parse_metric,
)


def test_metric_parser_distinguishes_missing_from_zero():
    assert parse_metric(None) is None
    assert parse_metric("") is None
    assert parse_metric("0") == 0
    assert parse_metric("2.8万") == 28_000
    assert parse_metric("1.2w") == 12_000
    assert parse_metric("3.5k") == 3_500


def test_search_card_exposes_filter_fields_without_detail_request():
    card = normalise_card({
        "id": "note-1",
        "xsec_token": "test-token",
        "xsec_source": "pc_search",
        "note_card": {
            "type": "video",
            "interact_info": {"liked_count": "680"},
            "user": {"user_id": "author-1", "nickname": "示例作者"},
        },
    })
    assert card["note_id"] == "note-1"
    assert card["type"] == "video"
    assert card["liked_count"] == 680
    assert card["user_id"] == "author-1"


def test_creator_card_shape_is_also_supported():
    card = normalise_card({
        "note_id": "note-2",
        "type": "video",
        "interact_info": {"liked_count": "1.1万"},
    })
    assert card["note_id"] == "note-2"
    assert card["liked_count"] == 11_000


def test_follower_count_requires_an_explicit_follower_field():
    profile = {
        "basicInfo": {"nickname": "测试"},
        "interactions": [
            {"type": "follows", "name": "关注", "count": "88"},
            {"type": "fans", "name": "粉丝", "count": "3.2万"},
        ],
    }
    assert extract_follower_count(profile) == 32_000
    assert extract_follower_count({"interactions": [{"type": "follows", "count": "88"}]}) is None


def test_rate_limit_hidden_by_retry_wrapper_is_still_recognised():
    wrapped = RuntimeError("XHS request blocked with HTTP 429")
    retry_error = SimpleNamespace(last_attempt=SimpleNamespace(exception=lambda: wrapped))
    assert is_access_restriction(retry_error)
    assert not is_access_restriction(RuntimeError("temporary DNS failure"))


def test_list_filter_avoids_detail_for_low_likes_and_history(tmp_path, monkeypatch):
    stored = []

    async def store_note(item):
        stored.append(item["note_id"])

    async def store_video(*args):
        return None

    xhs_store = SimpleNamespace(
        update_xhs_note=store_note,
        get_video_url_arr=lambda item: [],
        update_xhs_note_video=store_video,
    )
    monkeypatch.setitem(sys.modules, "store", SimpleNamespace(xhs=xhs_store))

    now = int(datetime.now().timestamp() * 1000)

    class Client:
        def __init__(self):
            self.detail_calls = []

        async def get_note_by_id(self, note_id, source, token):
            self.detail_calls.append(note_id)
            return {
                "note_id": note_id,
                "type": "video",
                "time": now,
                "interact_info": {"liked_count": "500"},
                "user": {"user_id": "author-1"},
            }

        async def get_note_media(self, url):
            raise AssertionError("no video URL was provided")

    crawler = FilteredXhsCrawlerMixin()
    crawler.collection_request = CollectionRequest(
        platform="xhs",
        trigger_type="keyword",
        keywords=["测试"],
        min_likes=350,
        max_items=1,
    )
    crawler.history = CollectionHistory(tmp_path / "history.sqlite3")
    crawler.history.record_many([{"platform": "xhs", "content_id": "old"}])
    crawler.seen_in_scan = set()
    crawler.selected = []
    crawler.author_followers = {}
    crawler.last_request_at = 0.0
    crawler.request_pause_min = crawler.request_pause_max = 0
    crawler.xhs_client = Client()
    crawler.stats = {
        "found": 0, "videos": 0, "history_skipped": 0, "duplicates_in_scan": 0,
        "likes_filtered": 0, "followers_filtered": 0, "details_requested": 0,
        "profile_requests": 0, "in_date_range": 0,
    }

    async def exercise():
        await crawler._consider({"id": "low", "note_card": {"type": "video", "interact_info": {"liked_count": "100"}}})
        await crawler._consider({"id": "old", "note_card": {"type": "video", "interact_info": {"liked_count": "900"}}})
        # A missing list counter is verified through detail data instead of being
        # silently treated as zero or left as a manual "pending" item.
        await crawler._consider({"id": "new", "note_card": {"type": "video", "interact_info": {}}})

    asyncio.run(exercise())
    assert crawler.xhs_client.detail_calls == ["new"]
    assert crawler.stats["likes_filtered"] == 1
    assert crawler.stats["history_skipped"] == 1
    assert crawler.selected[0]["note_id"] == "new"
    assert stored == ["new"]
