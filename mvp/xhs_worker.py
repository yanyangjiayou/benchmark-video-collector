"""Run a bounded, list-first Xiaohongshu collection with no automatic re-login.

The vendor crawler is intentionally kept as the browser/session and signing layer.  This
module replaces only its collection strategy so that list metadata and persistent history
are applied before note details or media are requested.
"""
from __future__ import annotations

import asyncio
import json
import math
import random
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable


ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "MediaCrawler"
sys.path.insert(0, str(VENDOR))

from .login_worker import find_platform_browser

ACCESS_RESTRICTED = "MVP_XHS_ACCESS_RESTRICTED"
LOGIN_REQUIRED = "MVP_XHS_LOGIN_REQUIRED"
METRIC_UNAVAILABLE = "MVP_XHS_METRIC_UNAVAILABLE"


def parse_metric(value: object) -> int | None:
    """Parse counters such as ``2.8万`` without converting missing values to zero."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return max(0, int(value))
    text = str(value).strip().lower().replace(",", "").replace("+", "")
    if not text or text in {"-", "--", "none", "null"}:
        return None
    multiplier = 1
    for suffix, scale in (("亿", 100_000_000), ("万", 10_000), ("w", 10_000), ("k", 1_000)):
        if suffix in text:
            multiplier = scale
            text = text.replace(suffix, "")
            break
    try:
        return max(0, int(float(text) * multiplier))
    except ValueError:
        return None


def normalise_card(item: dict[str, Any]) -> dict[str, Any]:
    """Return the common fields exposed by search and creator list cards."""
    card = item.get("note_card") if isinstance(item.get("note_card"), dict) else item
    interaction = card.get("interact_info") if isinstance(card.get("interact_info"), dict) else {}
    user = card.get("user") if isinstance(card.get("user"), dict) else {}
    return {
        "note_id": str(item.get("id") or item.get("note_id") or card.get("note_id") or ""),
        "xsec_token": str(item.get("xsec_token") or card.get("xsec_token") or ""),
        "xsec_source": str(item.get("xsec_source") or card.get("xsec_source") or "pc_search"),
        "type": str(card.get("type") or item.get("type") or "").lower(),
        "liked_count": parse_metric(interaction.get("liked_count", card.get("liked_count"))),
        "user_id": str(user.get("user_id") or user.get("id") or item.get("user_id") or ""),
        "nickname": str(user.get("nickname") or item.get("nickname") or ""),
    }


def extract_follower_count(profile: object) -> int | None:
    """Extract a follower count from known and nested profile response shapes."""
    direct_keys = {
        "fans", "fans_count", "fansCount", "follower_count", "followerCount",
        "followers", "followers_count", "followersCount",
    }
    label_keys = ("type", "name", "label", "title")
    value_keys = ("count", "num", "value", "fans", "followers")

    def walk(value: object) -> int | None:
        if isinstance(value, dict):
            for key in direct_keys:
                if key in value:
                    result = parse_metric(value[key])
                    if result is not None:
                        return result
            label = " ".join(str(value.get(key, "")) for key in label_keys).strip().lower()
            if label in {"fans", "fan", "followers", "follower", "粉丝"} or "粉丝" in label:
                for key in value_keys:
                    result = parse_metric(value.get(key))
                    if result is not None:
                        return result
            for child in value.values():
                result = walk(child)
                if result is not None:
                    return result
        elif isinstance(value, list):
            for child in value:
                result = walk(child)
                if result is not None:
                    return result
        return None

    return walk(profile)


def is_access_restriction(exc: BaseException) -> bool:
    """Classify platform security/rate-limit failures, including tenacity wrappers."""
    last_attempt = getattr(exc, "last_attempt", None)
    if last_attempt is not None:
        wrapped = last_attempt.exception()
        if wrapped is not None and wrapped is not exc:
            return is_access_restriction(wrapped)
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    markers = (
        "platformaccess", "ipblock", "captcha", "verifytype", "300011",
        "http 401", "http 403", "http 429", "status code 401", "status code 403",
        "status code 429", "status_code=401", "status_code=403", "status_code=429",
        "操作频繁", "访问频繁", "安全限制", "账号异常",
    )
    return "platformaccess" in name or "ipblock" in name or any(marker in text for marker in markers)


async def strict_login_probe(client: Any) -> bool:
    """Check login without turning a network/security failure into a login prompt."""
    from tools.httpx_util import make_async_client

    uri = "/api/sns/web/v1/user/selfinfo"
    headers = await client._pre_headers(uri, params={})
    try:
        async with make_async_client(proxy=client.proxy) as http:
            response = await http.get(
                f"{client._host}{uri}", headers=headers, timeout=client.timeout
            )
        if response.status_code in {401, 403, 429, 461, 471}:
            raise RuntimeError(ACCESS_RESTRICTED)
        if response.status_code != 200:
            raise RuntimeError("MVP_XHS_LOGIN_CHECK_FAILED")
        data = response.json()
        return bool(data.get("data", {}).get("result", {}).get("success"))
    except Exception as exc:
        if is_access_restriction(exc) or ACCESS_RESTRICTED in str(exc):
            raise RuntimeError(ACCESS_RESTRICTED) from exc
        raise


class FilteredXhsCrawlerMixin:
    """Mixin applied to the vendor crawler inside :func:`main`."""

    request_pause_min = 1.6
    request_pause_max = 2.8

    def _prepare_job(self) -> None:
        import config
        from mvp.history import CollectionHistory
        from mvp.rules import CollectionRequest

        self.raw = Path(config.SAVE_DATA_PATH)
        settings = json.loads((self.raw.parent / "request.json").read_text(encoding="utf-8"))
        self.collection_request = CollectionRequest.model_validate(settings["request"])
        self.history = CollectionHistory(ROOT / "runtime" / "collection_history.sqlite3")
        self.scan_limit = min(50, max(20, self.collection_request.max_items * 4))
        self.seen_in_scan: set[str] = set()
        self.selected: list[dict[str, Any]] = []
        self.author_followers: dict[str, int] = {}
        self.last_missing_metric = ""
        self.consecutive_missing_metrics = 0
        self.last_request_at = 0.0
        self.stats: dict[str, Any] = {
            "strategy": "list_first",
            "scan_limit": self.scan_limit,
            "found": 0,
            "videos": 0,
            "history_skipped": 0,
            "duplicates_in_scan": 0,
            "likes_filtered": 0,
            "followers_filtered": 0,
            "likes_missing": 0,
            "time_missing": 0,
            "followers_missing": 0,
            "details_requested": 0,
            "profile_requests": 0,
            "list_requests": 0,
            "in_date_range": 0,
            "selected": 0,
        }

    async def _pause(self) -> None:
        target = random.uniform(self.request_pause_min, self.request_pause_max)
        elapsed = time.monotonic() - self.last_request_at
        if self.last_request_at and elapsed < target:
            await asyncio.sleep(target - elapsed)
        self.last_request_at = time.monotonic()

    async def _call(self, operation: Callable[..., Awaitable[Any]], *args: Any, **kwargs: Any) -> Any:
        await self._pause()
        try:
            return await operation(*args, **kwargs)
        except Exception as exc:
            if is_access_restriction(exc):
                raise RuntimeError(ACCESS_RESTRICTED) from exc
            raise

    def _write_stats(self) -> None:
        self.stats["selected"] = len(self.selected)
        path = self.raw.parent / "xhs_scan_summary.json"
        path.write_text(json.dumps(self.stats, ensure_ascii=False, indent=2), encoding="utf-8")

    def _reset_missing_metric_streak(self) -> None:
        self.last_missing_metric = ""
        self.consecutive_missing_metrics = 0

    def _skip_missing_metric(self, metric: str, label: str) -> None:
        """Skip one uncertain item, but stop if the same response defect repeats."""
        self.stats[f"{metric}_missing"] += 1
        if self.last_missing_metric == metric:
            self.consecutive_missing_metrics += 1
        else:
            self.last_missing_metric = metric
            self.consecutive_missing_metrics = 1
        print(
            f"指标缺失跳过：当前作品未返回可核验的{label}，不会导出；继续检查后续内容",
            flush=True,
        )
        if self.consecutive_missing_metrics >= 3:
            raise RuntimeError(
                f"{METRIC_UNAVAILABLE}: 连续 3 条候选内容缺少可核验的{label}，已停止后续请求"
            )

    async def _profile_followers(
        self, user_id: str, xsec_token: str = "", xsec_source: str = ""
    ) -> int | None:
        if not user_id:
            return None
        if user_id in self.author_followers:
            return self.author_followers[user_id]
        self.stats["profile_requests"] += 1
        profile = await self._call(
            self.xhs_client.get_creator_info,
            user_id=user_id,
            xsec_token=xsec_token,
            xsec_source=xsec_source,
        )
        followers = extract_follower_count(profile)
        if followers is None:
            return None
        self.author_followers[user_id] = followers
        return followers

    async def _detail(self, card: dict[str, Any]) -> dict[str, Any] | None:
        self.stats["details_requested"] += 1
        try:
            detail = await self._call(
                self.xhs_client.get_note_by_id,
                card["note_id"],
                card["xsec_source"],
                card["xsec_token"],
            )
        except Exception as exc:
            if type(exc).__name__ == "NoteNotFoundError" or "not found" in str(exc).lower():
                return None
            raise
        if not detail:
            return None
        detail.update({"xsec_token": card["xsec_token"], "xsec_source": card["xsec_source"]})
        return detail

    async def _download_selected_video(self, detail: dict[str, Any]) -> None:
        from store import xhs as xhs_store

        note_id = str(detail.get("note_id") or "")
        for url in xhs_store.get_video_url_arr(detail)[:2]:
            content = await self.xhs_client.get_note_media(url)
            if content and len(content) > 50_000 and b"ftyp" in content[:32]:
                await xhs_store.update_xhs_note_video(note_id, content, "0.mp4")
                return

    async def _consider(self, raw_item: dict[str, Any]) -> None:
        from store import xhs as xhs_store

        if len(self.selected) >= self.collection_request.max_items:
            return
        card = normalise_card(raw_item)
        note_id = card["note_id"]
        if not note_id:
            return
        if note_id in self.seen_in_scan:
            self.stats["duplicates_in_scan"] += 1
            return
        self.seen_in_scan.add(note_id)
        self.stats["found"] += 1

        if note_id in self.history.seen_content_ids("xhs", [note_id]):
            self.stats["history_skipped"] += 1
            return
        if card["type"] and card["type"] != "video":
            return
        if card["type"] == "video":
            self.stats["videos"] += 1
        if card["liked_count"] is not None and card["liked_count"] < self.collection_request.min_likes:
            self._reset_missing_metric_streak()
            self.stats["likes_filtered"] += 1
            return

        detail = await self._detail(card)
        if detail is None:
            return
        if str(detail.get("type") or "").lower() != "video":
            return
        if card["type"] != "video":
            self.stats["videos"] += 1
        interactions = detail.get("interact_info") if isinstance(detail.get("interact_info"), dict) else {}
        likes = parse_metric(interactions.get("liked_count"))
        if likes is None:
            # 详情接口偶发缺字段时，回退到列表阶段已核验的 liked_count
            # （预筛已用它验证 >= min_likes，是可信任的同一来源数据）
            likes = card.get("liked_count")
            if likes is None:
                self._skip_missing_metric("likes", "点赞数")
                return
        if likes < self.collection_request.min_likes:
            self._reset_missing_metric_streak()
            self.stats["likes_filtered"] += 1
            return
        stamp = parse_metric(detail.get("time"))
        if stamp is None:
            self._skip_missing_metric("time", "发布时间")
            return
        published = datetime.fromtimestamp(stamp / 1000 if stamp > 10_000_000_000 else stamp).date()
        if not (self.collection_request.start_date <= published <= self.collection_request.end_date):
            self._reset_missing_metric_streak()
            return
        self.stats["in_date_range"] += 1

        if self.collection_request.min_followers is not None:
            user = detail.get("user") if isinstance(detail.get("user"), dict) else {}
            user_id = str(user.get("user_id") or card["user_id"] or "")
            followers = await self._profile_followers(user_id, card["xsec_token"], card["xsec_source"])
            if followers is None:
                self._skip_missing_metric("followers", "粉丝数")
                return
            if followers < self.collection_request.min_followers:
                self._reset_missing_metric_streak()
                self.stats["followers_filtered"] += 1
                return

        self._reset_missing_metric_streak()
        await xhs_store.update_xhs_note(detail)
        await self._download_selected_video(detail)
        self.selected.append(detail)
        print(
            f"列表预筛选：已扫描 {self.stats['found']} 条，仅找到 {len(self.selected)}/{self.collection_request.max_items} 条合格新视频",
            flush=True,
        )

    async def search(self) -> None:
        import config
        from media_platform.xhs.field import SearchNoteType, SearchSortType
        from media_platform.xhs.help import get_search_id
        from var import source_keyword_var

        self._prepare_job()
        config.ENABLE_GET_MEIDAS = False
        try:
            keywords = [word.strip() for word in self.collection_request.keywords if word.strip()]
            max_pages = max(1, math.ceil(self.scan_limit / 20))
            page_by_keyword = {keyword: 1 for keyword in keywords}
            search_ids = {keyword: get_search_id() for keyword in keywords}
            active = list(keywords)
            while active and len(self.seen_in_scan) < self.scan_limit and len(self.selected) < self.collection_request.max_items:
                next_active: list[str] = []
                for keyword in active:
                    if len(self.seen_in_scan) >= self.scan_limit or len(self.selected) >= self.collection_request.max_items:
                        break
                    page = page_by_keyword[keyword]
                    if page > max_pages:
                        continue
                    source_keyword_var.set(keyword)
                    self.stats["list_requests"] += 1
                    response = await self._call(
                        self.xhs_client.get_note_by_keyword,
                        keyword=keyword,
                        search_id=search_ids[keyword],
                        page=page,
                        sort=(SearchSortType(config.SORT_TYPE) if config.SORT_TYPE else SearchSortType.GENERAL),
                        note_type=SearchNoteType.VIDEO,
                    )
                    items = response.get("items", []) if isinstance(response, dict) else []
                    for item in items:
                        if not isinstance(item, dict) or item.get("model_type") in {"rec_query", "hot_query"}:
                            continue
                        await self._consider(item)
                        if len(self.seen_in_scan) >= self.scan_limit or len(self.selected) >= self.collection_request.max_items:
                            break
                    page_by_keyword[keyword] += 1
                    if items and response.get("has_more", False) and page_by_keyword[keyword] <= max_pages:
                        next_active.append(keyword)
                active = next_active
        finally:
            self._write_stats()

    async def get_creators_and_notes(self) -> None:
        import config
        from media_platform.xhs.help import parse_creator_info_from_url
        from var import source_keyword_var

        self._prepare_job()
        # 前置登录态自检：在真正发起采集前确认浏览器连通且登录态有效。
        # 浏览器断连/登录失效会在这一步暴露，而不是走到详情阶段才因缺字段崩溃。
        probe = getattr(self.xhs_client, "pong", None)
        if callable(probe):
            try:
                if not await probe():
                    raise RuntimeError(LOGIN_REQUIRED)
            except RuntimeError as exc:
                if any(token in str(exc) for token in (ACCESS_RESTRICTED, LOGIN_REQUIRED, "LOGIN_CHECK_FAILED")):
                    raise
                raise RuntimeError(LOGIN_REQUIRED) from exc
        config.ENABLE_GET_MEIDAS = False
        source_keyword_var.set("")
        try:
            for creator_url in config.XHS_CREATOR_ID_LIST:
                creator = parse_creator_info_from_url(creator_url)
                if self.collection_request.min_followers is not None:
                    followers = await self._profile_followers(
                        creator.user_id, creator.xsec_token, creator.xsec_source
                    )
                    if followers is None:
                        self._skip_missing_metric("followers", "粉丝数")
                        break
                    if followers < self.collection_request.min_followers:
                        self._reset_missing_metric_streak()
                        self.stats["followers_filtered"] += 1
                        print("博主粉丝数未达到筛选条件，本次无需读取作品详情", flush=True)
                        break
                cursor = ""
                while len(self.seen_in_scan) < self.scan_limit and len(self.selected) < self.collection_request.max_items:
                    remaining = self.scan_limit - len(self.seen_in_scan)
                    self.stats["list_requests"] += 1
                    response = await self._call(
                        self.xhs_client.get_notes_by_creator,
                        creator.user_id,
                        cursor,
                        page_size=min(30, remaining),
                        xsec_token=creator.xsec_token,
                        xsec_source=creator.xsec_source or "pc_feed",
                    )
                    items = response.get("notes", []) if isinstance(response, dict) else []
                    for item in items:
                        if isinstance(item, dict):
                            await self._consider(item)
                        if len(self.seen_in_scan) >= self.scan_limit or len(self.selected) >= self.collection_request.max_items:
                            break
                    if not items or not response.get("has_more", False):
                        break
                    next_cursor = str(response.get("cursor") or "")
                    if not next_cursor or next_cursor == cursor:
                        break
                    cursor = next_cursor
                break
        finally:
            self._write_stats()


def main() -> None:
    import main as vendor_main
    import config
    from media_platform.xhs import XiaoHongShuCrawler
    from media_platform.xhs import core as xhs_core
    from tenacity import stop_after_attempt
    from tools.app_runner import run

    class NoAutomaticLogin:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def begin(self) -> None:
            raise RuntimeError(LOGIN_REQUIRED)

    class FilteredXhsCrawler(FilteredXhsCrawlerMixin, XiaoHongShuCrawler):
        async def create_xhs_client(self, httpx_proxy: str | None):
            client = await super().create_xhs_client(httpx_proxy)
            # Collection calls make one attempt.  Security/CAPTCHA failures must never be
            # amplified by the vendor's generic three-attempt retry wrapper.
            type(client).request.retry.stop = stop_after_attempt(1)

            async def strict_pong() -> bool:
                return await strict_login_probe(client)

            client.pong = strict_pong
            return client

    # Collection never launches or replaces a browser.  It only attaches to the exact
    # Xiaohongshu window that the explicit "确认登录" action left open.
    existing_port = find_platform_browser("xhs", config.CDP_DEBUG_PORT)
    if existing_port is None:
        raise RuntimeError(LOGIN_REQUIRED)
    config.CDP_CONNECT_EXISTING = True
    config.CDP_DEBUG_PORT = existing_port
    config.AUTO_CLOSE_BROWSER = False
    config.ENABLE_GET_MEIDAS = False
    config.ENABLE_GET_COMMENTS = False
    config.ENABLE_GET_SUB_COMMENTS = False
    config.MAX_CONCURRENCY_NUM = 1
    xhs_core.XiaoHongShuLogin = NoAutomaticLogin
    vendor_main.CrawlerFactory.CRAWLERS["xhs"] = FilteredXhsCrawler

    original_cleanup = vendor_main.async_cleanup

    async def detach_without_closing_login_browser() -> None:
        """Release Playwright references without closing the user-visible login window."""
        crawler = vendor_main.crawler
        manager = getattr(crawler, "cdp_manager", None) if crawler else None
        if manager is not None and config.CDP_CONNECT_EXISTING:
            manager.browser_context = None
            manager.browser = None
            crawler.browser_context = None
            crawler.context_page = None
        await original_cleanup()

    run(vendor_main.main, detach_without_closing_login_browser)


if __name__ == "__main__":
    main()
