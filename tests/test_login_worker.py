from __future__ import annotations

import io
import json

from types import SimpleNamespace

from mvp.login_worker import find_platform_browser, preserve_launched_browser


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


def test_successful_login_detaches_launched_browser_from_exit_cleanup():
    process = SimpleNamespace(poll=lambda: None)
    launcher = SimpleNamespace(browser_process=process)
    manager = SimpleNamespace(launcher=launcher)

    assert preserve_launched_browser(manager)
    assert launcher.browser_process is None
