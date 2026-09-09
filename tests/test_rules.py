from datetime import date, timedelta

import pytest

from mvp.rules import CollectionRequest


def test_defaults_are_applied():
    request = CollectionRequest(
        platform="xhs",
        trigger_type="creator_url",
        creator_url="https://example.test/creator",
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
            creator_url="https://example.test/creator",
            max_items=51,
        )
