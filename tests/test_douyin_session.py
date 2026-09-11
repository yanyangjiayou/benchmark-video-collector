import asyncio
import stat
import time

import pytest

from mvp import douyin_session


class BrowserContext:
    def __init__(self, cookies):
        self.values = cookies

    async def cookies(self, urls):
        return self.values

    async def add_cookies(self, cookies):
        self.values.extend(cookies)


def cookie(name="sessionid", expires=-1):
    return {"name": name, "value": "test-only", "domain": ".douyin.com", "path": "/", "expires": expires}


def test_login_hint_alone_is_not_authenticated():
    assert not douyin_session.authenticated_cookies([cookie("LOGIN_STATUS")])
    assert douyin_session.authenticated_cookies([cookie()])
    assert not douyin_session.authenticated_cookies([cookie(expires=time.time() - 1)])
    assert not douyin_session.authenticated_cookies([{**cookie(), "domain": "unrelated.example"}])


def test_login_survives_a_new_browser_context(tmp_path, monkeypatch):
    destination = tmp_path / "auth/douyin.json"
    monkeypatch.setattr(douyin_session, "SESSION_FILE", destination)
    asyncio.run(douyin_session.save_session(BrowserContext([cookie()])))
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    new_context = BrowserContext([])
    assert asyncio.run(douyin_session.restore_session(new_context))
    assert asyncio.run(douyin_session.logged_in(new_context))


def test_failed_login_is_not_saved(tmp_path, monkeypatch):
    destination = tmp_path / "auth/douyin.json"
    monkeypatch.setattr(douyin_session, "SESSION_FILE", destination)
    with pytest.raises(RuntimeError, match="登录未完成"):
        asyncio.run(douyin_session.save_session(BrowserContext([cookie("LOGIN_STATUS")])))
    assert not destination.exists()
