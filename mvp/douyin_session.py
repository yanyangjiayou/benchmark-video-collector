"""Share the user's real Douyin login between the login and collection workers."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[1]
SESSION_FILE = ROOT / "runtime" / "auth" / "douyin.json"
SESSION_NAMES = {"sessionid", "sessionid_ss", "sid_tt"}


def authenticated_cookies(cookies: list[dict]) -> bool:
    now = time.time()
    return any(cookie.get("name") in SESSION_NAMES and cookie.get("value")
               and str(cookie.get("domain", "")).lstrip(".") in {"douyin.com", "www.douyin.com"}
               and (cookie.get("expires", -1) == -1 or cookie.get("expires", 0) > now)
               for cookie in cookies)


async def logged_in(context) -> bool:
    # HasUserLogin / LOGIN_STATUS can survive logout and are not credentials.
    return authenticated_cookies(await context.cookies(["https://www.douyin.com"]))


async def save_session(context) -> None:
    cookies = await context.cookies(["https://www.douyin.com"])
    if not authenticated_cookies(cookies):
        raise RuntimeError("MVP_DOUYIN_LOGIN_REQUIRED: 抖音登录未完成，请在专用窗口扫码登录")
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = SESSION_FILE.with_suffix(".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump({"cookies": cookies}, stream)
    temporary.replace(SESSION_FILE)
    SESSION_FILE.chmod(0o600)


async def restore_session(context) -> bool:
    if await logged_in(context):
        return False
    try:
        cookies = json.loads(SESSION_FILE.read_text(encoding="utf-8")).get("cookies", [])
    except (OSError, ValueError, AttributeError):
        return False
    if not isinstance(cookies, list) or not authenticated_cookies(cookies):
        return False
    cookies = [cookie for cookie in cookies
               if cookie.get("expires", -1) == -1 or cookie.get("expires", 0) > time.time()]
    await context.add_cookies(cookies)
    return True


def configure_session(crawler, *, allow_login: bool) -> None:
    from media_platform.douyin.login import DouYinLogin

    original_create = crawler.create_douyin_client

    async def create_client(proxy):
        if await restore_session(crawler.browser_context):
            await crawler.context_page.reload(wait_until="domcontentloaded")
        client = await original_create(proxy)

        async def pong(browser_context):
            return await logged_in(browser_context)

        client.pong = pong
        return client

    async def manual_login(login):
        if not allow_login:
            raise RuntimeError("MVP_DOUYIN_LOGIN_REQUIRED: 抖音登录已失效，请重新确认登录")
        print("请在抖音窗口扫码并确认登录；如有验证码，请手动完成。", flush=True)
        page = login.context_page
        if not await page.locator("#login-panel-new").is_visible():
            try:
                await page.get_by_text("登录", exact=True).first.click(timeout=5000)
            except Exception:
                print("请点击抖音网页右上角的登录按钮。", flush=True)
        for _ in range(150):
            if await logged_in(login.browser_context):
                # Save while Playwright is connected, before the login window closes.
                await save_session(login.browser_context)
                print("登录成功，凭证已保存。窗口将保留 15 秒，便于确认“始终保持登录”等提示。", flush=True)
                await asyncio.sleep(15)
                await save_session(login.browser_context)
                return
            await asyncio.sleep(1)
        raise RuntimeError("登录超时，请在抖音窗口完成扫码或验证后重试")

    crawler.create_douyin_client = create_client
    DouYinLogin.begin = manual_login
