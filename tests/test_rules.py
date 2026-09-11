from datetime import date, timedelta

import pytest

from mvp.rules import CollectionRequest


def test_defaults_are_applied():
    request = CollectionRequest(
        platform="xhs",
        trigger_type="creator_url",
        creator_url="https://www.xiaohongshu.com/user/profile/abc",
    )
    assert request.min_likes == 200
    assert request.max_items == 10
    assert request.end_date == date.today()
    assert request.start_date == date.today() - timedelta(days=29)
    assert request.video_only is True
    assert request.transcribe_video is True


def test_keyword_requires_keywords():
    with pytest.raises(ValueError):
        CollectionRequest(platform="dy", trigger_type="keyword")


def test_limit_has_hard_cap():
    with pytest.raises(ValueError):
        CollectionRequest(
            platform="xhs",
            trigger_type="creator_url",
            creator_url="https://www.xiaohongshu.com/user/profile/abc",
            max_items=51,
        )


def test_platform_mismatch_is_rejected_before_collection():
    with pytest.raises(ValueError, match="当前平台是抖音"):
        CollectionRequest(platform="dy", trigger_type="creator_url", creator_url="https://xhslink.cn/o/example")


def test_douyin_share_text_extracts_homepage_url():
    request = CollectionRequest(platform="dy", trigger_type="creator_url",
                                creator_url="这是博主主页 https://www.douyin.com/user/MS4wLjABAAAAexample?from_tab_name=main 复制打开")
    assert request.creator_url == "https://www.douyin.com/user/MS4wLjABAAAAexample"


def test_douyin_mobile_profile_uses_sec_uid():
    request = CollectionRequest(platform="dy", trigger_type="creator_url",
                                creator_url="https://www.iesdouyin.com/share/user/123?sec_uid=MS4wLjABAAAAexample")
    assert request.creator_url == "https://www.douyin.com/user/MS4wLjABAAAAexample"


def test_video_link_cannot_be_used_as_creator():
    with pytest.raises(ValueError, match="视频链接"):
        CollectionRequest(platform="dy", trigger_type="creator_url", creator_url="https://www.douyin.com/video/123")


def test_douyin_short_link_is_preserved_for_resolution():
    request = CollectionRequest(platform="dy", trigger_type="creator_url", creator_url="去看看 https://v.douyin.com/abc/，复制打开")
    assert request.creator_url == "https://v.douyin.com/abc/"


def test_wrong_platform_after_short_link_resolution_is_rejected():
    from mvp.sources import normalize_creator_url
    with pytest.raises(ValueError, match="当前平台是抖音"):
        normalize_creator_url("https://www.xiaohongshu.com/user/profile/abc", "dy", allow_short=False)
