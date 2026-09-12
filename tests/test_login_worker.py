from __future__ import annotations

import io
import json

from mvp.login_worker import find_platform_browser


def _response(pages: list[dict]) -> io.BytesIO:
    return io.BytesIO(json.dumps(pages).encode("utf-8"))


def test_find_platform_browser_reuses_matching_xhs_window(monkeypatch):
    monkeypatch.setattr(
        "mvp.login_worker.urllib.request.urlopen",
        lambda url, timeout: _response([{"url": "https://www.xiaohongshu.com/explore"}]),
    )

    assert find_platform_browser("xhs", 9222, 1) == 9222


def test_find_platform_browser_does_not_reuse_another_platform(monkeypatch):
    monkeypatch.setattr(
        "mvp.login_worker.urllib.request.urlopen",
        lambda url, timeout: _response([{"url": "https://www.xiaohongshu.com/explore"}]),
    )

    assert find_platform_browser("dy", 9222, 1) is None
