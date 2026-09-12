from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from mvp import xhs_video


def test_video_fallback_requires_and_reuses_existing_xhs_browser(monkeypatch):
    config = SimpleNamespace(CDP_DEBUG_PORT=9222)
    monkeypatch.setattr(xhs_video, "find_platform_browser", lambda platform, port: 9227)

    assert xhs_video.configure_existing_xhs_browser(config) == 9227
    assert config.CDP_CONNECT_EXISTING is True
    assert config.CDP_DEBUG_PORT == 9227
    assert config.AUTO_CLOSE_BROWSER is False


def test_video_fallback_never_launches_a_replacement_browser(monkeypatch):
    config = SimpleNamespace(CDP_DEBUG_PORT=9222)
    monkeypatch.setattr(xhs_video, "find_platform_browser", lambda platform, port: None)

    with pytest.raises(RuntimeError, match="已确认登录的小红书窗口"):
        xhs_video.configure_existing_xhs_browser(config)

    assert not hasattr(config, "CDP_CONNECT_EXISTING")


def test_video_fallback_detaches_without_closing_login_browser(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(xhs_video.VENDOR))
    import config
    import playwright.async_api
    import tools.cdp_browser

    page = SimpleNamespace(closed=False)
    page.is_closed = lambda: page.closed

    async def close_page():
        page.closed = True

    page.close = close_page

    class FakeContext:
        async def cookies(self, urls):
            return [{"name": "web_session", "value": "present"}]

        async def new_page(self):
            return page

    context = FakeContext()
    managers = []

    class FakeManager:
        def __init__(self):
            self.browser_context = context
            self.browser = object()
            managers.append(self)

        async def launch_and_connect(self, playwright, headless=False):
            assert config.CDP_CONNECT_EXISTING is True
            assert config.CDP_DEBUG_PORT == 9222
            return context

        async def cleanup(self):
            raise AssertionError("existing login browser must not be closed")

    class FakePlaywright:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    monkeypatch.setattr(xhs_video, "find_platform_browser", lambda platform, port: 9222)
    monkeypatch.setattr(playwright.async_api, "async_playwright", FakePlaywright)
    monkeypatch.setattr(tools.cdp_browser, "CDPBrowserManager", FakeManager)

    assert asyncio.run(xhs_video._download([], tmp_path, lambda message: None)) == {}
    assert page.closed is True
    assert managers[0].browser_context is None
    assert managers[0].browser is None
