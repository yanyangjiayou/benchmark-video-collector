import asyncio
from datetime import date, datetime
import sys
from types import SimpleNamespace

import pytest

from mvp.history import CollectionHistory
from mvp.rules import CollectionRequest
from mvp.xhs_worker import (
    FilteredXhsCrawlerMixin,
    extract_follower_count,
    is_access_restriction,
    note_id_published_date,
    normalise_card,
    parse_metric,
    parse_published_date,
)


def test_metric_parser_distinguishes_missing_from_zero():
    assert parse_metric(None) is None
    assert parse_metric("") is None
    assert parse_metric("0") == 0
    assert parse_metric("2.8万") == 28_000
    assert parse_metric("1.2w") == 12_000
    assert parse_metric("3.5k") == 3_500


def test_list_date_parser_supports_explicit_relative_and_note_id_dates():
    reference = date(2026, 9, 12)
    assert parse_published_date("2026-08-23", reference) == date(2026, 8, 23)
    assert parse_published_date("08-23", reference) == date(2026, 8, 23)
    assert parse_published_date("昨天", reference) == date(2026, 9, 11)
    stamp = int(datetime(2026, 8, 23).timestamp())
    note_id = f"{stamp:08x}" + "0" * 16
    assert note_id_published_date(note_id, reference) == date(2026, 8, 23)


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


def test_creator_card_exposes_explicit_list_date():
    card = normalise_card({
        "note_id": "note-with-date",
        "type": "video",
        "publish_time": "2026-08-23",
        "interact_info": {"liked_count": "900"},
    })
    assert card["published_date"] == date(2026, 8, 23)
    assert card["published_date_source"] == "list"


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
    crawler.last_missing_metric = ""
    crawler.consecutive_missing_metrics = 0
    crawler.last_request_at = 0.0
    crawler.request_pause_min = crawler.request_pause_max = 0
    crawler.xhs_client = Client()
    crawler.stats = {
        "found": 0, "videos": 0, "non_video_filtered": 0, "history_skipped": 0, "duplicates_in_scan": 0,
        "likes_filtered": 0, "followers_filtered": 0, "details_requested": 0,
        "profile_requests": 0, "in_date_range": 0, "date_filtered": 0,
        "likes_missing": 0, "time_missing": 0, "followers_missing": 0,
    }

    async def exercise():
        await crawler._consider({"id": "image", "note_card": {"type": "normal", "interact_info": {"liked_count": "900"}}})
        await crawler._consider({"id": "low", "note_card": {"type": "video", "interact_info": {"liked_count": "100"}}})
        await crawler._consider({"id": "old", "note_card": {"type": "video", "interact_info": {"liked_count": "900"}}})
        # A missing list counter is verified through detail data instead of being
        # silently treated as zero or left as a manual "pending" item.
        await crawler._consider({"id": "new", "note_card": {"type": "video", "interact_info": {}}})

    asyncio.run(exercise())
    assert crawler.xhs_client.detail_calls == ["new"]
    assert crawler.stats["likes_filtered"] == 1
    assert crawler.stats["non_video_filtered"] == 1
    assert crawler.stats["history_skipped"] == 1
    assert crawler.selected[0]["note_id"] == "new"
    assert stored == ["new"]


def test_missing_detail_likes_falls_back_to_verified_list_value(tmp_path, monkeypatch):
    stored = []

    async def store_note(item):
        stored.append(item["note_id"])

    xhs_store = SimpleNamespace(
        update_xhs_note=store_note,
        get_video_url_arr=lambda item: [],
        update_xhs_note_video=lambda *args: None,
    )
    monkeypatch.setitem(sys.modules, "store", SimpleNamespace(xhs=xhs_store))
    now = int(datetime.now().timestamp() * 1000)

    class Client:
        async def get_note_by_id(self, note_id, source, token):
            return {
                "note_id": note_id,
                "type": "video",
                "time": now,
                "interact_info": {},
                "user": {"user_id": "author-1"},
            }

    crawler = FilteredXhsCrawlerMixin()
    crawler.collection_request = CollectionRequest(
        platform="xhs", trigger_type="keyword", keywords=["测试"], min_likes=350, max_items=2
    )
    crawler.history = CollectionHistory(tmp_path / "history.sqlite3")
    crawler.seen_in_scan = set()
    crawler.selected = []
    crawler.author_followers = {}
    crawler.last_missing_metric = ""
    crawler.consecutive_missing_metrics = 0
    crawler.last_request_at = 0.0
    crawler.request_pause_min = crawler.request_pause_max = 0
    crawler.xhs_client = Client()
    crawler.stats = {
        "found": 0, "videos": 0, "non_video_filtered": 0, "history_skipped": 0, "duplicates_in_scan": 0,
        "likes_filtered": 0, "followers_filtered": 0, "details_requested": 0,
        "profile_requests": 0, "in_date_range": 0, "date_filtered": 0,
        "likes_missing": 0, "time_missing": 0, "followers_missing": 0,
    }

    asyncio.run(crawler._consider({
        "id": "fallback",
        "note_card": {"type": "video", "interact_info": {"liked_count": "500"}},
    }))

    assert stored == ["fallback"]
    assert crawler.stats["likes_missing"] == 0


def test_list_date_prefilter_avoids_detail_request(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "store", SimpleNamespace(xhs=SimpleNamespace()))

    class Client:
        async def get_note_by_id(self, *args):
            raise AssertionError("日期范围外的卡片不应读取详情")

    crawler = FilteredXhsCrawlerMixin()
    crawler.collection_request = CollectionRequest(
        platform="xhs", trigger_type="keyword", keywords=["测试"],
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 12),
        min_likes=350, max_items=2,
    )
    crawler.history = CollectionHistory(tmp_path / "history.sqlite3")
    crawler.seen_in_scan = set()
    crawler.selected = []
    crawler.author_followers = {}
    crawler.rejected_authors = set()
    crawler.current_creator_id = ""
    crawler.last_missing_metric = ""
    crawler.consecutive_missing_metrics = 0
    crawler.last_request_at = 0.0
    crawler.request_pause_min = crawler.request_pause_max = 0
    crawler.xhs_client = Client()
    crawler.stats = {
        "found": 0, "videos": 0, "non_video_filtered": 0, "history_skipped": 0,
        "duplicates_in_scan": 0, "likes_filtered": 0, "followers_filtered": 0,
        "author_cards_filtered": 0, "details_requested": 0, "profile_requests": 0,
        "creators_checked": 0, "in_date_range": 0, "date_filtered": 0,
        "date_prefiltered": 0, "date_detail_filtered": 0,
        "likes_missing": 0, "time_missing": 0, "followers_missing": 0,
    }

    asyncio.run(crawler._consider({
        "id": "old-date", "note_card": {"type": "video", "publish_time": "2026-08-23",
        "interact_info": {"liked_count": "900"}},
    }))

    assert crawler.stats["date_prefiltered"] == 1
    assert crawler.stats["details_requested"] == 0


def test_keyword_follower_filter_runs_before_detail_and_is_cached(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "store", SimpleNamespace(xhs=SimpleNamespace()))

    class Client:
        def __init__(self):
            self.profile_calls = 0

        async def get_creator_info(self, **kwargs):
            self.profile_calls += 1
            return {"fans": "120"}

        async def get_note_by_id(self, *args):
            raise AssertionError("粉丝不足的博主不应读取作品详情")

    crawler = FilteredXhsCrawlerMixin()
    crawler.collection_request = CollectionRequest(
        platform="xhs", trigger_type="keyword", keywords=["测试"],
        min_followers=500, min_likes=0, max_items=2,
    )
    crawler.history = CollectionHistory(tmp_path / "history.sqlite3")
    crawler.seen_in_scan = set()
    crawler.selected = []
    crawler.author_followers = {}
    crawler.rejected_authors = set()
    crawler.current_creator_id = ""
    crawler.last_missing_metric = ""
    crawler.consecutive_missing_metrics = 0
    crawler.last_request_at = 0.0
    crawler.request_pause_min = crawler.request_pause_max = 0
    crawler.xhs_client = Client()
    crawler.stats = {
        "found": 0, "videos": 0, "non_video_filtered": 0, "history_skipped": 0,
        "duplicates_in_scan": 0, "likes_filtered": 0, "followers_filtered": 0,
        "author_cards_filtered": 0, "details_requested": 0, "profile_requests": 0,
        "creators_checked": 0, "in_date_range": 0, "date_filtered": 0,
        "date_prefiltered": 0, "date_detail_filtered": 0,
        "likes_missing": 0, "time_missing": 0, "followers_missing": 0,
    }

    card = {"note_card": {"type": "video", "user": {"user_id": "author-low"},
            "interact_info": {"liked_count": "900"}}}
    asyncio.run(crawler._consider({"id": "low-author-1", **card}))
    asyncio.run(crawler._consider({"id": "low-author-2", **card}))

    assert crawler.xhs_client.profile_calls == 1
    assert crawler.stats["creators_checked"] == 1
    assert crawler.stats["followers_filtered"] == 1
    assert crawler.stats["author_cards_filtered"] == 2
    assert crawler.stats["details_requested"] == 0


def test_one_missing_metric_is_skipped_but_three_consecutive_stop():
    crawler = FilteredXhsCrawlerMixin()
    crawler.stats = {"likes_missing": 0, "time_missing": 0, "followers_missing": 0}
    crawler.last_missing_metric = ""
    crawler.consecutive_missing_metrics = 0

    crawler._skip_missing_metric("likes", "点赞数")
    crawler._skip_missing_metric("likes", "点赞数")
    with pytest.raises(RuntimeError, match="连续 3 条"):
        crawler._skip_missing_metric("likes", "点赞数")
    assert crawler.stats["likes_missing"] == 3
